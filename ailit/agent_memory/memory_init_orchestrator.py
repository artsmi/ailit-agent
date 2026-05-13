"""Оркестратор ``memory init``.

PREPARE → EXECUTE → broker RPC (``memory.query_context``) → VERIFY journal
→ COMMIT или ABORT.
"""

from __future__ import annotations

import json
import os
import signal
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from agent_memory.agent_memory_chat_log import (
    COMPACT_LOG_FILE_NAME,
    create_unique_cli_session_dir,
)
from agent_memory.agent_memory_config import (
    load_or_create_agent_memory_config,
)
from agent_memory.compact_observability_sink import (
    CompactObservabilitySink,
)
from agent_memory.memory_init_summary import (
    emit_memory_init_user_summary,
)
from ailit_runtime.errors import RuntimeProtocolError
from agent_memory.memory_init_cli_outcome import (
    MemoryInitTerminalStatus,
    agent_memory_v1_status_from_envelope,
    memory_init_exit_code,
    terminal_status_worker_not_ok,
)
from agent_memory.memory_journal import (
    MemoryJournalRow,
    MemoryJournalStore,
)
from agent_memory.memory_init_transaction import (
    MemoryInitPaths,
    MemoryInitTransaction,
    resolve_memory_init_paths,
)
from agent_memory.agent_memory_result_v1 import FIX_MEMORY_LLM_JSON_STEP
from ailit_runtime.broker_json_client import (
    BrokerResponseError,
    BrokerTransportError,
)
from ailit_runtime.models import (
    RuntimeIdentity,
    RuntimeNow,
    make_request_envelope,
)

_DEFAULT_TAIL_BYTES: Final[int] = 8 * 1024 * 1024
# Имя ожидается тестами; = ``memory_init_exit_code`` при SIGINT.
_EXIT_INTERRUPT: Final[int] = 130

# UC-06: compact W14 tokens in ``abort_reason=`` (no raw LLM / full envelope).
_W14_REASON_UNKNOWN_LEGACY: Final[str] = "unknown_legacy_w14_status"
_W14_REASON_CMD_INVALID: Final[str] = "w14_command_output_invalid"

BrokerInvoke = Callable[[Mapping[str, Any]], dict[str, Any]]


def _w14_reason_short_from_worker_ok_envelope(
    out: Mapping[str, Any],
) -> str | None:
    """
    If the last successful worker response indicates W14 as primary cause,
    return a one-line machine id for summary; else None.
    """
    if out.get("ok") is not True:
        return None
    pl = out.get("payload")
    if not isinstance(pl, dict):
        return None
    ds = str(pl.get("decision_summary") or "")
    ms = pl.get("memory_slice")
    ms_dict = ms if isinstance(ms, dict) else None
    if _W14_REASON_UNKNOWN_LEGACY in ds or (
        ms_dict is not None
        and _W14_REASON_UNKNOWN_LEGACY in str(ms_dict.get("reason") or "")
    ):
        return _W14_REASON_UNKNOWN_LEGACY
    if ms_dict is None:
        return None
    ms_reason = str(ms_dict.get("reason") or "")
    w14_cf = bool(ms_dict.get("w14_contract_failure"))
    if w14_cf or ms_reason == _W14_REASON_CMD_INVALID:
        return _W14_REASON_CMD_INVALID
    return None


def _w14_reason_short_from_worker_failure_envelope(
    out: Mapping[str, Any],
) -> str | None:
    """W14 id from ``ok: false`` error message (compact substrings)."""
    if out.get("ok") is not False:
        return None
    err = out.get("error")
    if not isinstance(err, dict):
        return None
    msg = str(err.get("message", "") or "")
    if _W14_REASON_UNKNOWN_LEGACY in msg:
        return _W14_REASON_UNKNOWN_LEGACY
    if _W14_REASON_CMD_INVALID in msg:
        return _W14_REASON_CMD_INVALID
    return None


def _w14_reason_short_from_worker_envelope(
    out: Mapping[str, Any],
) -> str | None:
    """Union of ok/failure W14 extractors for partial ``handle`` outcomes."""
    rs = _w14_reason_short_from_worker_ok_envelope(out)
    if rs is not None:
        return rs
    return _w14_reason_short_from_worker_failure_envelope(out)


# D1: max ``handle`` invocations — ключ ``memory.init.max_continuation_rounds``
# в ``~/.ailit/agent-memory/config.yaml`` (``MemoryInitSubConfig``).

# D2 / UC-01: canonical English goal (no driver ``path``; ``memory_init`` SoT).
MEMORY_INIT_CANONICAL_GOAL: Final[str] = (
    "Build knowledge base and agent memory for the entire project at the "
    "configured project_root; traverse the relevant tree excluding caches, "
    "generated artifacts, and vendor paths; finish only when project memory "
    "is sufficient for further AgentWork and Desktop work."
)


@dataclass(frozen=True, slots=True)
class MemoryInitSession:
    """Сессия CLI init: корреляция логов и journal."""

    init_session_id: str
    chat_id: str
    normalized_project_root: Path
    pag_namespace_key: str
    started_at_utc_iso: str
    cli_session_dir: Path


def normalize_memory_init_root(raw: str | Path) -> Path:
    """Абсолютный корень; существование и доступность каталога (UC-02 A1)."""
    p = Path(str(raw)).expanduser().resolve()
    if not p.exists():
        raise RuntimeProtocolError(
            code="memory_init_root_missing",
            message=f"project root does not exist: {p}",
        )
    if not p.is_dir():
        raise RuntimeProtocolError(
            code="memory_init_root_not_dir",
            message=f"project root is not a directory: {p}",
        )
    if not os.access(p, os.R_OK | os.X_OK):
        raise RuntimeProtocolError(
            code="memory_init_root_inaccessible",
            message=f"project root not readable/executable: {p}",
        )
    return p


def verify_memory_init_journal_complete_marker(
    journal_path: Path,
    chat_id: str,
    *,
    max_tail_bytes: int = _DEFAULT_TAIL_BYTES,
) -> bool:
    """
    Последняя по ``created_at`` строка ``memory.result.returned`` для
    ``chat_id`` с ``payload.status == complete`` (§4.1). Bounded tail read.
    """
    cid = str(chat_id).strip()
    if not cid:
        return False
    p = journal_path.resolve()
    if not p.exists():
        return False
    try:
        size = p.stat().st_size
    except OSError:
        return False
    if size <= max_tail_bytes:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return False
    else:
        try:
            with p.open("rb") as fh:
                fh.seek(max(0, size - max_tail_bytes))
                raw = fh.read()
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            return False
    best_ts: str = ""
    found: bool = False
    for line in text.splitlines():
        s = line.strip()
        if not s or cid not in s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("chat_id", "")) != cid:
            continue
        if str(obj.get("event_name", "")) != "memory.result.returned":
            continue
        pl = obj.get("payload")
        if not isinstance(pl, dict):
            continue
        if str(pl.get("status", "")) != "complete":
            continue
        ts = str(obj.get("created_at", ""))
        if ts >= best_ts:
            best_ts = ts
            found = True
    return found


def count_compact_d4_summary_lines(compact_path: Path) -> tuple[int, int, int]:
    """
    D4: (1) ``event=memory.why_llm``;
    (2) ``event=memory.pag_graph`` и ``op=node`` в одной строке;
    (3) канонический ``event=memory.w14_graph_highlight``.
    """
    p = compact_path.resolve()
    if not p.exists():
        return (0, 0, 0)
    try:
        body = p.read_text(encoding="utf-8")
    except OSError:
        return (0, 0, 0)
    n_why = 0
    n_pg_node = 0
    n_w14 = 0
    for line in body.splitlines():
        if "event=memory.why_llm" in line:
            n_why += 1
        if "event=memory.pag_graph" in line and "op=node" in line:
            n_pg_node += 1
        if "event=memory.w14_graph_highlight" in line:
            n_w14 += 1
    return (n_why, n_pg_node, n_w14)


class MemoryInitSigintGuard:
    """SIGINT до VERIFY: только флаг (без ``phase_abort`` в обработчике)."""

    def __init__(self) -> None:
        self._cancelled: bool = False
        self._previous: Callable[..., None] | int | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def _handler(self, signum: int, frame: object | None) -> None:
        _ = signum
        _ = frame
        self._cancelled = True

    def install(self) -> None:
        self._previous = signal.signal(signal.SIGINT, self._handler)

    def restore(self) -> None:
        prev = self._previous
        if prev is not None:
            signal.signal(signal.SIGINT, prev)
            self._previous = None

    @property
    def active(self) -> bool:
        return self._previous is not None


class MemoryInitOrchestrator:
    """PREPARE / EXECUTE / broker RPC → AgentMemory / VERIFY / COMMIT|ABORT."""

    def __init__(
        self,
        *,
        paths: MemoryInitPaths | None = None,
    ) -> None:
        self._paths: MemoryInitPaths = paths or resolve_memory_init_paths()

    def run(
        self,
        project_root: str | Path,
        pag_namespace_key: str,
        *,
        broker_invoke: BrokerInvoke,
        broker_chat_id: str,
        cli_session_dir: Path | None = None,
    ) -> int:
        """
        Returns:
            0 при ``complete``; 1 при ``partial``/``blocked``; 2 при infra;
            130 при SIGINT/KeyboardInterrupt.
        """
        root = normalize_memory_init_root(project_root)
        ns = str(pag_namespace_key).strip()
        if not ns:
            return memory_init_exit_code(
                "blocked",
                abort_class="infrastructure",
            )
        bcid = str(broker_chat_id or "").strip()
        if not bcid:
            return memory_init_exit_code(
                "blocked",
                abort_class="infrastructure",
            )
        cid = bcid
        init_session_id = str(uuid.uuid4())
        started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cli_dir = (
            cli_session_dir
            if cli_session_dir is not None
            else create_unique_cli_session_dir()
        )
        session = MemoryInitSession(
            init_session_id=init_session_id,
            chat_id=cid,
            normalized_project_root=root,
            pag_namespace_key=ns,
            started_at_utc_iso=started,
            cli_session_dir=cli_dir,
        )
        compact_path = cli_dir / COMPACT_LOG_FILE_NAME
        orch_sink = CompactObservabilitySink(
            compact_file=compact_path,
            init_session_id=init_session_id,
            tee_stderr=True,
        )
        self._emit_orch(orch_sink, session, "orch_memory_init_started", {})
        self._emit_orch(
            orch_sink,
            session,
            "orch_memory_init_phase",
            {"phase": "prepare"},
        )
        tx = MemoryInitTransaction(
            init_session_id=init_session_id,
            chat_id=cid,
            pag_namespace_key=ns,
            paths=self._paths,
        )
        guard = MemoryInitSigintGuard()
        try:
            tx.phase_prepare()
        except BaseException:
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "abort"},
            )
            prep_rid = f"req-meminit-{init_session_id}-prepare"
            orch_sink.emit_memory_result_returned_marker(
                req=None,
                chat_id=cid,
                request_id=prep_rid,
                status="blocked",
            )
            try:
                tx.phase_abort()
            except RuntimeProtocolError:
                pass
            self._emit_memory_init_user_summary(
                compact_path,
                "blocked",
                reason_short="prepare_failed",
            )
            return memory_init_exit_code(
                "blocked",
                abort_class="infrastructure",
            )
        shadow = tx.shadow_journal_path
        if shadow is None:
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "abort"},
            )
            miss_rid = f"req-meminit-{init_session_id}-no_shadow"
            orch_sink.emit_memory_result_returned_marker(
                req=None,
                chat_id=cid,
                request_id=miss_rid,
                status="blocked",
            )
            try:
                tx.phase_abort()
            except RuntimeProtocolError:
                pass
            self._emit_memory_init_user_summary(
                compact_path,
                "blocked",
                reason_short="journal_shadow_missing",
            )
            return memory_init_exit_code(
                "blocked",
                abort_class="infrastructure",
            )
        guard.install()
        last_request_id: str = f"req-meminit-{init_session_id}-0000-init"
        try:
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "execute_incremental"},
            )
            tx.phase_execute_destructive_namespace_clear()
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "execute_worker"},
            )
            am_file_cfg = load_or_create_agent_memory_config()
            max_continuation_rounds = (
                am_file_cfg.memory.init.max_continuation_rounds
            )
            identity = RuntimeIdentity(
                runtime_id=f"rt-{init_session_id[:8]}",
                chat_id=cid,
                broker_id=f"broker-{cid}",
                trace_id=f"tr-{init_session_id[:8]}",
                goal_id="memory_init",
                namespace=ns,
            )
            round_idx = 0
            last_ok_worker_envelope: dict[str, Any] | None = None
            while True:
                if round_idx >= max_continuation_rounds:
                    break
                rid_suffix = uuid.uuid4().hex[:10]
                request_id = (
                    f"req-meminit-{init_session_id}-"
                    f"{round_idx:04d}-{rid_suffix}"
                )
                message_id = (
                    f"msg-meminit-{init_session_id}-"
                    f"{round_idx:04d}-{rid_suffix}"
                )
                req = make_request_envelope(
                    identity=identity,
                    message_id=message_id,
                    parent_message_id=None,
                    from_agent=f"AgentWork:{cid}",
                    to_agent="AgentMemory:global",
                    msg_type="service.request",
                    payload={
                        "service": "memory.query_context",
                        "request_id": request_id,
                        "goal": MEMORY_INIT_CANONICAL_GOAL,
                        "project_root": str(root),
                        "workspace_projects": [
                            {"project_id": "memory_init", "namespace": ns},
                        ],
                        "memory_init": True,
                        "memory_init_round": int(round_idx),
                        "memory_init_shadow_journal_path": str(
                            shadow.resolve(),
                        ),
                    },
                    now=RuntimeNow(),
                )
                last_request_id = request_id
                try:
                    out = broker_invoke(req.to_dict())
                    if isinstance(out, dict) and out.get("ok") is True:
                        last_ok_worker_envelope = out
                except (BrokerTransportError, BrokerResponseError) as exc:
                    self._emit_orch(
                        orch_sink,
                        session,
                        "orch_memory_init_broker_error",
                        {"error": str(exc)[:400]},
                    )
                    self._emit_orchestrator_terminal_marker(
                        tx=tx,
                        orch_sink=orch_sink,
                        session=session,
                        status="partial",
                        request_id=last_request_id,
                    )
                    try:
                        tx.phase_abort()
                    except RuntimeProtocolError:
                        pass
                    self._emit_orch(
                        orch_sink,
                        session,
                        "orch_memory_init_phase",
                        {"phase": "abort"},
                    )
                    self._emit_memory_init_user_summary(
                        compact_path,
                        "partial",
                        reason_short="broker_rpc_failed",
                    )
                    return memory_init_exit_code(
                        "partial",
                        abort_class="infrastructure",
                    )
                except KeyboardInterrupt:
                    self._emit_orchestrator_terminal_marker(
                        tx=tx,
                        orch_sink=orch_sink,
                        session=session,
                        status="partial",
                        request_id=last_request_id,
                    )
                    try:
                        tx.phase_abort()
                    except RuntimeProtocolError:
                        pass
                    self._emit_orch(
                        orch_sink,
                        session,
                        "orch_memory_init_phase",
                        {"phase": "abort"},
                    )
                    self._emit_memory_init_user_summary(
                        compact_path,
                        "partial",
                        reason_short="keyboard_interrupt",
                    )
                    return memory_init_exit_code(
                        "partial",
                        abort_class="interrupt",
                    )
                if guard.cancelled:
                    self._emit_orchestrator_terminal_marker(
                        tx=tx,
                        orch_sink=orch_sink,
                        session=session,
                        status="partial",
                        request_id=last_request_id,
                    )
                    try:
                        tx.phase_abort()
                    except RuntimeProtocolError:
                        pass
                    self._emit_orch(
                        orch_sink,
                        session,
                        "orch_memory_init_phase",
                        {"phase": "abort"},
                    )
                    self._emit_memory_init_user_summary(
                        compact_path,
                        "partial",
                        reason_short="sigint",
                    )
                    return memory_init_exit_code(
                        "partial",
                        abort_class="interrupt",
                    )
                if not isinstance(out, dict) or out.get("ok") is not True:
                    wfail = terminal_status_worker_not_ok(
                        out if isinstance(out, dict) else None,
                    )
                    self._emit_orchestrator_terminal_marker(
                        tx=tx,
                        orch_sink=orch_sink,
                        session=session,
                        status=wfail,
                        request_id=last_request_id,
                    )
                    try:
                        tx.phase_abort()
                    except RuntimeProtocolError:
                        pass
                    self._emit_orch(
                        orch_sink,
                        session,
                        "orch_memory_init_phase",
                        {"phase": "abort"},
                    )
                    self._emit_memory_init_user_summary(
                        compact_path,
                        wfail,
                        reason_short=(
                            _w14_reason_short_from_worker_envelope(out)
                            if isinstance(out, dict)
                            else None
                        ),
                    )
                    return memory_init_exit_code(wfail)
                if verify_memory_init_journal_complete_marker(shadow, cid):
                    break
                pl_raw = out.get("payload")
                pl = pl_raw if isinstance(pl_raw, dict) else None
                amr_raw = pl.get("agent_memory_result") if pl else None
                amr = amr_raw if isinstance(amr_raw, dict) else None
                cont = (
                    amr is not None
                    and amr.get("memory_continuation_required") is True
                )
                # Init soak: ``memory_continuation_required`` бывает только при
                # узком UC-04 (partial + w14_finish + …). Для больших деревьев
                # частый путь — ``partial`` без continuation; без доп. раундов
                # журнал не получает ``memory.result.returned``/``complete`` и
                # VERIFY падает. Продолжаем RPC, пока есть бюджет раундов и
                # worker не ``blocked``/``complete``.
                if not cont:
                    st_am = str((amr or {}).get("status", "")).strip().lower()
                    rns = str(
                        (pl or {}).get("recommended_next_step", ""),
                    ).strip()
                    if (
                        st_am not in ("blocked", "complete")
                        and rns != FIX_MEMORY_LLM_JSON_STEP
                        and round_idx + 1 < max_continuation_rounds
                    ):
                        cont = True
                if not cont:
                    break
                round_idx += 1
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "verify"},
            )
            ok = verify_memory_init_journal_complete_marker(shadow, cid)
            tx.phase_verify(ok)
            if not ok:
                try:
                    tx.phase_abort()
                except RuntimeProtocolError:
                    pass
                self._emit_orch(
                    orch_sink,
                    session,
                    "orch_memory_init_phase",
                    {"phase": "abort"},
                )
                rs_verify: str | None = None
                if last_ok_worker_envelope is not None:
                    rs_verify = _w14_reason_short_from_worker_ok_envelope(
                        last_ok_worker_envelope,
                    )
                vstat: MemoryInitTerminalStatus = "partial"
                if (
                    agent_memory_v1_status_from_envelope(
                        last_ok_worker_envelope,
                    )
                    == "blocked"
                ):
                    vstat = "blocked"
                self._emit_memory_init_user_summary(
                    compact_path,
                    vstat,
                    reason_short=rs_verify,
                )
                return memory_init_exit_code(vstat)
            try:
                tx.phase_commit()
            except Exception:
                self._emit_orchestrator_terminal_marker(
                    tx=tx,
                    orch_sink=orch_sink,
                    session=session,
                    status="blocked",
                    request_id=last_request_id,
                )
                try:
                    tx.phase_abort()
                except RuntimeProtocolError:
                    pass
                self._emit_orch(
                    orch_sink,
                    session,
                    "orch_memory_init_phase",
                    {"phase": "abort"},
                )
                self._emit_memory_init_user_summary(
                    compact_path,
                    "blocked",
                    reason_short="commit_failed",
                )
                return memory_init_exit_code(
                    "blocked",
                    abort_class="infrastructure",
                )
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "commit"},
            )
            self._emit_memory_init_user_summary(compact_path, "complete")
            return memory_init_exit_code("complete")
        except Exception:
            self._emit_orchestrator_terminal_marker(
                tx=tx,
                orch_sink=orch_sink,
                session=session,
                status="blocked",
                request_id=last_request_id,
            )
            try:
                tx.phase_abort()
            except RuntimeProtocolError:
                pass
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "abort"},
            )
            self._emit_memory_init_user_summary(
                compact_path,
                "blocked",
                reason_short="runtime_error",
            )
            return memory_init_exit_code(
                "blocked",
                abort_class="infrastructure",
            )
        finally:
            if guard.active:
                guard.restore()

    def _emit_orch(
        self,
        sink: CompactObservabilitySink,
        session: MemoryInitSession,
        event: str,
        fields: dict[str, str],
    ) -> None:
        sink.emit(
            req=None,
            chat_id=session.chat_id,
            event=event,
            fields={"kind": "orchestrator", **fields},
        )

    def _emit_orchestrator_terminal_marker(
        self,
        *,
        tx: MemoryInitTransaction,
        orch_sink: CompactObservabilitySink,
        session: MemoryInitSession,
        status: MemoryInitTerminalStatus,
        request_id: str,
    ) -> None:
        """Shadow journal + compact/stderr: ``memory.result.returned`` (S4)."""
        sj = tx.shadow_journal_path
        rid = str(request_id or "").strip()
        if sj is not None and sj.exists():
            MemoryJournalStore(sj).append(
                MemoryJournalRow(
                    chat_id=session.chat_id,
                    event_name="memory.result.returned",
                    request_id=rid[:220],
                    namespace=session.pag_namespace_key,
                    project_id="memory_init",
                    summary="memory_init_cli_terminal",
                    payload={"status": status},
                ),
            )
        orch_sink.emit_memory_result_returned_marker(
            req=None,
            chat_id=session.chat_id,
            request_id=rid,
            status=status,
        )

    def _emit_memory_init_user_summary(
        self,
        compact_path: Path,
        terminal_status: MemoryInitTerminalStatus,
        *,
        reason_short: str | None = None,
    ) -> None:
        """
        UC-02 финальный блок summary. Каноническая тройка (S4):

        - ``complete`` — COMMIT и VERIFY с ``payload.status=complete``.
        - ``partial`` — неполный успех, прерывание пользователем (код 130),
          ответ worker не ``ok`` без признаков LLM-block.
        - ``blocked`` — VERIFY без complete при blocked в
          ``agent_memory_result``, ошибка COMMIT/рантайма,
          LLM/provider gate на ``ok: false``.
        """
        d4 = count_compact_d4_summary_lines(compact_path)
        emit_memory_init_user_summary(
            compact_path,
            terminal_status,
            d4,
            reason_short=reason_short,
        )
