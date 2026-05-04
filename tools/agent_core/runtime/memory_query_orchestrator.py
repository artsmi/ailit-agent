"""Оркестратор CLI ``ailit memory query`` (один или несколько W14-раундов)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Final, Mapping

from agent_core.memory.pag_runtime import PagRuntimeConfig
from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.agent_memory_chat_log import (
    COMPACT_LOG_FILE_NAME,
    create_unique_cli_session_dir,
)
from agent_core.runtime.agent_memory_config import (
    load_or_create_agent_memory_config,
)
from agent_core.runtime.compact_observability_sink import (
    CompactObservabilitySink,
)
from agent_core.runtime.memory_init_cli_outcome import (
    MemoryInitTerminalStatus,
    memory_init_exit_code,
    terminal_status_worker_not_ok,
)
from agent_core.runtime.memory_init_orchestrator import (
    MemoryInitSigintGuard,
    count_compact_d4_summary_lines,
    normalize_memory_init_root,
)
from agent_core.runtime.memory_init_summary import emit_memory_cli_user_summary
from agent_core.runtime.models import (
    RuntimeIdentity,
    RuntimeNow,
    make_request_envelope,
)
from agent_core.runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)
from agent_core.session.repo_context import (
    detect_repo_context,
    namespace_for_repo,
)

_RESUME_MAX_NODES: Final[int] = 20
_RESUME_SUMMARY_CAP: Final[int] = 140


def build_memory_query_resume_lines(
    *,
    namespace: str,
    db_path: Path,
    memory_slice: Mapping[str, Any],
    max_nodes: int = _RESUME_MAX_NODES,
    summary_max_chars: int = _RESUME_SUMMARY_CAP,
) -> list[str]:
    """Краткие строки RESUME: node_id, path, усечённый summary из PAG."""
    ns = str(namespace or "").strip()
    raw_ids = memory_slice.get("node_ids")
    if not isinstance(raw_ids, list):
        return ["  (no node_ids in memory_slice)"]
    nids = [str(x).strip() for x in raw_ids if str(x).strip()]
    if not nids:
        return ["  (empty node_ids)"]
    store = SqlitePagStore(db_path.resolve())
    lines: list[str] = []
    shown = nids[: max(1, int(max_nodes))]
    rest = max(0, len(nids) - len(shown))
    for i, nid in enumerate(shown, start=1):
        node = store.fetch_node(namespace=ns, node_id=nid) if ns else None
        if node is None:
            summary = "(not found in PAG)"
            path_s = ""
        else:
            path_s = str(node.path or "").strip()
            sm = str(node.summary or "").replace("\n", " ").strip()
            if len(sm) > int(summary_max_chars):
                sm = sm[: int(summary_max_chars) - 1] + "…"
            summary = sm or "(no summary)"
        path_part = f" path={path_s}" if path_s else ""
        lines.append(f"  [{i}] {nid}{path_part}")
        lines.append(f"      {summary}")
    if rest:
        lines.append(f"  … and {rest} more node(s) omitted")
    return lines


def _terminal_from_last_ok(out: Mapping[str, Any]) -> MemoryInitTerminalStatus:
    pl = out.get("payload")
    if not isinstance(pl, dict):
        return "partial"
    amr_raw = pl.get("agent_memory_result")
    amr = amr_raw if isinstance(amr_raw, dict) else {}
    st = str(amr.get("status") or "").strip().lower()
    partial = bool(pl.get("partial", False))
    if st == "blocked":
        return "blocked"
    if st == "complete" and not partial:
        return "complete"
    return "partial"


def _amr_continuation_true(out: Mapping[str, Any]) -> bool:
    pl = out.get("payload")
    if not isinstance(pl, dict):
        return False
    amr_raw = pl.get("agent_memory_result")
    amr = amr_raw if isinstance(amr_raw, dict) else None
    return amr is not None and amr.get("memory_continuation_required") is True


class MemoryQueryOrchestrator:
    """Запуск ``memory.query_context`` с continuation; без destructive init."""

    def run(
        self,
        project_root: str | Path,
        query_text: str,
        *,
        chat_id: str | None = None,
    ) -> int:
        """
        Returns:
            Как у ``memory init``: 0 complete; 1 partial/blocked; 130 SIGINT.
        """
        root = normalize_memory_init_root(project_root)
        goal = str(query_text or "").strip()
        if not goal:
            return memory_init_exit_code(
                "blocked",
                abort_class="infrastructure",
            )

        rctx = detect_repo_context(root)
        ns = namespace_for_repo(
            repo_uri=rctx.repo_uri,
            repo_path=rctx.repo_path,
            branch=rctx.branch,
        )
        if not str(ns).strip():
            return memory_init_exit_code(
                "blocked",
                abort_class="infrastructure",
            )

        session_id = str(uuid.uuid4())
        if chat_id and str(chat_id).strip():
            cid = str(chat_id).strip()
        else:
            cid = f"memory-query-{session_id[:8]}"
        cli_dir = create_unique_cli_session_dir()
        compact_path = cli_dir / COMPACT_LOG_FILE_NAME
        journal_path = cli_dir / "memory_query_journal.jsonl"

        orch_sink = CompactObservabilitySink(
            compact_file=compact_path,
            init_session_id=session_id,
            tee_stderr=True,
        )
        orch_sink.emit(
            req=None,
            chat_id=cid,
            event="orch_memory_query_started",
            fields={
                "namespace": str(ns)[:200],
                "project_root": str(root)[:240],
            },
        )

        cfg = MemoryAgentConfig(
            chat_id=cid,
            broker_id=f"memory-query-{session_id[:8]}",
            namespace=str(ns),
            session_log_mode="cli_init",
            cli_session_dir=cli_dir,
            memory_journal_path=journal_path,
            compact_init_session_id=session_id,
            broker_trace_stdout=False,
        )
        worker = AgentMemoryWorker(cfg)
        am_file_cfg = load_or_create_agent_memory_config()
        max_rounds = int(am_file_cfg.memory.init.max_continuation_rounds)

        identity = RuntimeIdentity(
            runtime_id=f"rt-{session_id[:8]}",
            chat_id=cid,
            broker_id=cfg.broker_id,
            trace_id=f"tr-{session_id[:8]}",
            goal_id="memory_query",
            namespace=str(ns),
        )

        guard = MemoryInitSigintGuard()
        guard.install()
        round_idx = 0
        last_ok: dict[str, Any] | None = None
        hit_round_cap = False
        try:
            orch_sink.emit(
                req=None,
                chat_id=cid,
                event="orch_memory_query_phase",
                fields={"phase": "execute_worker"},
            )
            while True:
                if round_idx >= max_rounds:
                    hit_round_cap = True
                    break
                rid_suffix = uuid.uuid4().hex[:10]
                rq_base = f"req-memq-{session_id}-{round_idx:04d}"
                request_id = f"{rq_base}-{rid_suffix}"
                msg_base = f"msg-memq-{session_id}-{round_idx:04d}"
                message_id = f"{msg_base}-{rid_suffix}"
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
                        "goal": goal,
                        "project_root": str(root),
                        "workspace_projects": [
                            {
                                "project_id": "memory_query",
                                "namespace": str(ns),
                            },
                        ],
                    },
                    now=RuntimeNow(),
                )
                try:
                    out = worker.handle(req)
                except KeyboardInterrupt:
                    self._finish_summary(
                        compact_path,
                        "partial",
                        reason_short="keyboard_interrupt",
                        last_ok=None,
                        namespace=str(ns),
                    )
                    return memory_init_exit_code(
                        "partial",
                        abort_class="interrupt",
                    )
                if guard.cancelled:
                    self._finish_summary(
                        compact_path,
                        "partial",
                        reason_short="sigint",
                        last_ok=None,
                        namespace=str(ns),
                    )
                    return memory_init_exit_code(
                        "partial",
                        abort_class="interrupt",
                    )
                if not isinstance(out, dict) or out.get("ok") is not True:
                    wfail = terminal_status_worker_not_ok(
                        out if isinstance(out, dict) else None,
                    )
                    self._finish_summary(
                        compact_path,
                        wfail,
                        reason_short="worker_not_ok",
                        last_ok=None,
                        namespace=str(ns),
                    )
                    return memory_init_exit_code(wfail)
                last_ok = out
                pl_raw = out.get("payload")
                pl = pl_raw if isinstance(pl_raw, dict) else None
                amr_raw = pl.get("agent_memory_result") if pl else None
                amr = amr_raw if isinstance(amr_raw, dict) else None
                cont = (
                    amr is not None
                    and amr.get("memory_continuation_required") is True
                )
                if not cont:
                    break
                round_idx += 1

            if last_ok is None:
                self._finish_summary(
                    compact_path,
                    "partial",
                    reason_short="no_response",
                    last_ok=None,
                    namespace=str(ns),
                )
                return memory_init_exit_code("partial")

            base_status = _terminal_from_last_ok(last_ok)
            if hit_round_cap and _amr_continuation_true(last_ok):
                term: MemoryInitTerminalStatus = "partial"
                reason = "max_continuation_rounds"
            else:
                term = base_status
                reason = None
                if hit_round_cap:
                    reason = "max_continuation_rounds"

            self._finish_summary(
                compact_path,
                term,
                reason_short=reason,
                last_ok=last_ok,
                namespace=str(ns),
            )
            return memory_init_exit_code(term)
        finally:
            if guard.active:
                guard.restore()

    def _finish_summary(
        self,
        compact_path: Path,
        term: MemoryInitTerminalStatus,
        *,
        reason_short: str | None,
        last_ok: Mapping[str, Any] | None,
        namespace: str,
    ) -> None:
        d4 = count_compact_d4_summary_lines(compact_path)
        resume: list[str] | None = None
        if last_ok is not None:
            pl = last_ok.get("payload")
            if isinstance(pl, dict):
                ms = pl.get("memory_slice")
                if isinstance(ms, dict):
                    db_path = PagRuntimeConfig.from_env().db_path
                    resume = build_memory_query_resume_lines(
                        namespace=namespace,
                        db_path=db_path,
                        memory_slice=ms,
                    )
        emit_memory_cli_user_summary(
            compact_path,
            term,
            d4,
            reason_short=reason_short,
            summary_header="=== memory query summary ===",
            resume_lines=resume,
        )
