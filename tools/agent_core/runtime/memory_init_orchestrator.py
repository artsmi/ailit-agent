"""Оркестратор ``memory init``.

PREPARE → EXECUTE → worker → VERIFY journal → COMMIT или ABORT.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Final

from agent_core.runtime.agent_memory_chat_log import (
    COMPACT_LOG_FILE_NAME,
    create_unique_cli_session_dir,
)
from agent_core.runtime.compact_observability_sink import (
    CompactObservabilitySink,
)
from agent_core.runtime.errors import RuntimeProtocolError
from agent_core.runtime.memory_init_transaction import (
    MemoryInitPaths,
    MemoryInitTransaction,
    resolve_memory_init_paths,
)
from agent_core.runtime.models import (
    RuntimeIdentity,
    RuntimeNow,
    make_request_envelope,
)
from agent_core.runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)

_DEFAULT_TAIL_BYTES: Final[int] = 8 * 1024 * 1024
_EXIT_VERIFY_FAIL: Final[int] = 1
_EXIT_INTERRUPT: Final[int] = 130
_EXIT_RUNTIME: Final[int] = 2


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


def _pick_relative_query_path(root: Path) -> str:
    for pat in ("*.py", "*.md", "*.txt"):
        for f in sorted(root.rglob(pat)):
            if f.is_file():
                try:
                    return str(f.relative_to(root)).replace("\\", "/")
                except ValueError:
                    continue
    return ""


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
    """PREPARE / EXECUTE / AgentMemoryWorker / VERIFY / COMMIT|ABORT."""

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
        chat_id: str | None = None,
    ) -> int:
        """
        Returns:
            0 при COMMIT; 1 при VERIFY fail; 2 при прочих ошибках;
            130 при interrupt.
        """
        root = normalize_memory_init_root(project_root)
        ns = str(pag_namespace_key).strip()
        if not ns:
            return _EXIT_RUNTIME
        init_session_id = str(uuid.uuid4())
        cid = (
            str(chat_id).strip()
            if chat_id
            else f"memory-init-{init_session_id[:8]}"
        )
        started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cli_dir = create_unique_cli_session_dir()
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
            try:
                tx.phase_abort()
            except RuntimeProtocolError:
                pass
            return _EXIT_RUNTIME
        shadow = tx.shadow_journal_path
        if shadow is None:
            try:
                tx.phase_abort()
            except RuntimeProtocolError:
                pass
            return _EXIT_RUNTIME
        guard.install()
        try:
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "execute"},
            )
            tx.phase_execute_destructive_namespace_clear()
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "execute_worker"},
            )
            cfg = MemoryAgentConfig(
                chat_id=cid,
                broker_id=f"memory-init-{init_session_id[:8]}",
                namespace=ns,
                session_log_mode="cli_init",
                cli_session_dir=cli_dir,
                memory_journal_path=shadow,
                compact_init_session_id=init_session_id,
            )
            worker = AgentMemoryWorker(cfg)
            rel = _pick_relative_query_path(root)
            identity = RuntimeIdentity(
                runtime_id=f"rt-{init_session_id[:8]}",
                chat_id=cid,
                broker_id=cfg.broker_id,
                trace_id=f"tr-{init_session_id[:8]}",
                goal_id="memory_init",
                namespace=ns,
            )
            req = make_request_envelope(
                identity=identity,
                message_id=f"msg-init-{init_session_id[:8]}",
                parent_message_id=None,
                from_agent=f"AgentWork:{cid}",
                to_agent="AgentMemory:global",
                msg_type="service.request",
                payload={
                    "service": "memory.query_context",
                    "request_id": f"req-init-{init_session_id[:8]}",
                    "path": rel,
                    "goal": "inspect path",
                    "project_root": str(root),
                    "workspace_projects": [
                        {"project_id": "memory_init", "namespace": ns},
                    ],
                },
                now=RuntimeNow(),
            )
            try:
                out = worker.handle(req)
            except KeyboardInterrupt:
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
                self._print_summary(compact_path)
                return _EXIT_INTERRUPT
            if guard.cancelled:
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
                self._print_summary(compact_path)
                return _EXIT_INTERRUPT
            if not isinstance(out, dict) or out.get("ok") is not True:
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
                self._print_summary(compact_path)
                return _EXIT_VERIFY_FAIL
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
                self._print_summary(compact_path)
                return _EXIT_VERIFY_FAIL
            try:
                tx.phase_commit()
            except Exception:
                self._emit_orch(
                    orch_sink,
                    session,
                    "orch_memory_init_phase",
                    {"phase": "abort"},
                )
                self._print_summary(compact_path)
                return _EXIT_RUNTIME
            self._emit_orch(
                orch_sink,
                session,
                "orch_memory_init_phase",
                {"phase": "commit"},
            )
            self._print_summary(compact_path)
            return 0
        except Exception:
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
            self._print_summary(compact_path)
            return _EXIT_RUNTIME
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

    def _print_summary(self, compact_path: Path) -> None:
        a, b, c = count_compact_d4_summary_lines(compact_path)
        sys.stderr.write(f"{a} {b} {c}\n")
        sys.stderr.flush()
