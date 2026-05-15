"""
Обработка `memory.change_feedback` → PAG (mechanical/LLM matrix, G13.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_memory.storage.sqlite_pag import SqlitePagStore
from ailit_base.providers.protocol import ChatProvider
from agent_memory.config.agent_memory_config import SourceBoundaryFilter
from agent_memory.services.agent_work_change_feedback import (
    AgentWorkChangeFeedback,
    ChangedFileFeedback,
    MemoryChangeDecision,
)
from agent_memory.services.memory_c_remap import (
    CRemapBatchResult,
    SemanticCRemapService,
)
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService

_JOURNAL_CB = Callable[..., None]


@dataclass(frozen=True, slots=True)
class ChangeFeedbackApplyResult:
    """Результат `MemoryChangeUpdateService.apply`."""

    ok: bool
    decisions: tuple[MemoryChangeDecision, ...]
    idempotent: bool
    previous_summary: str | None
    error: str | None = None


class ChangeFeedbackIdempotencyStore:
    """In-memory idempotency по `change_batch_id` + fingerprint входа."""

    def __init__(self) -> None:
        self._rows: dict[
            str,
            tuple[str, tuple[MemoryChangeDecision, ...]],
        ] = {}

    def get(
        self,
        batch_id: str,
        fp: str,
    ) -> tuple[MemoryChangeDecision, ...] | None:
        row = self._rows.get(batch_id)
        if row is None:
            return None
        prev_fp, decisions = row
        if prev_fp != fp:
            return None
        return decisions

    def put(
        self,
        batch_id: str,
        fp: str,
        decisions: tuple[MemoryChangeDecision, ...],
    ) -> None:
        self._rows[batch_id] = (fp, decisions)

    @staticmethod
    def summary_text(decisions: tuple[MemoryChangeDecision, ...]) -> str:
        parts: list[str] = []
        for d in decisions:
            u, lm = d.c_updated, d.c_needs_llm_remap
            parts.append(f"{d.path}:{d.mode}(u={u},llm={lm})")
        return "; ".join(parts)


class MemoryChangeUpdateService:
    """
    Feedback: boundary → mechanical C remap через PagGraphWriteService.

    `SemanticCRemapService` не зовёт LLM; при `needs_llm_remap` — journal;
    сырой `ChatProvider` не трогаем (LLM path — G13.2/4, policy).
    """

    def __init__(
        self,
        *,
        boundary: SourceBoundaryFilter,
        db_path: Path,
        idempotency: ChangeFeedbackIdempotencyStore,
        journal_append: _JOURNAL_CB,
        llm_provider: ChatProvider | None = None,
    ) -> None:
        self._boundary = boundary
        self._db_path = db_path
        self._idempotency = idempotency
        self._journal_append = journal_append
        self._llm_provider = llm_provider

    def apply(
        self,
        feedback: AgentWorkChangeFeedback,
        *,
        graph_trace_hook: Any,
        chat_id: str,
        request_id: str,
    ) -> ChangeFeedbackApplyResult:
        _ = chat_id
        fp = feedback.idempotency_fingerprint()
        cached = self._idempotency.get(feedback.change_batch_id, fp)
        if cached is not None:
            return ChangeFeedbackApplyResult(
                ok=True,
                decisions=cached,
                idempotent=True,
                previous_summary=ChangeFeedbackIdempotencyStore.summary_text(
                    cached,
                ),
                error=None,
            )
        self._journal_append(
            event_name="memory.change.received",
            summary="AgentWork change feedback batch",
            request_id=request_id,
            payload={
                "change_batch_id": feedback.change_batch_id,
                "files": [c.path for c in feedback.changed_files],
            },
        )
        store = SqlitePagStore(self._db_path)
        write = PagGraphWriteService(store)
        remap = SemanticCRemapService(write)
        decisions: list[MemoryChangeDecision] = []
        pr = Path(feedback.project_root).expanduser().resolve()
        try:
            for cf in feedback.changed_files:
                d = self._process_one_file(
                    feedback=feedback,
                    project_root=pr,
                    cf=cf,
                    remap=remap,
                    graph_trace_hook=graph_trace_hook,
                    request_id=request_id,
                )
                decisions.append(d)
        except Exception as exc:  # noqa: BLE001
            self._journal_append(
                event_name="memory.change.error",
                summary="change feedback apply failed",
                request_id=request_id,
                payload={"error": f"{type(exc).__name__}:{exc}"},
            )
            return ChangeFeedbackApplyResult(
                ok=False,
                decisions=tuple(decisions),
                idempotent=False,
                previous_summary=None,
                error=f"{type(exc).__name__}:{exc}",
            )
        tup = tuple(decisions)
        self._idempotency.put(feedback.change_batch_id, fp, tup)
        return ChangeFeedbackApplyResult(
            ok=True,
            decisions=tup,
            idempotent=False,
            previous_summary=None,
            error=None,
        )

    def _had_c_nodes(self, *, namespace: str, rel: str) -> bool:
        store = SqlitePagStore(self._db_path)
        nodes = store.list_nodes_for_path(
            namespace=namespace,
            path=rel,
            level="C",
            limit=1,
        )
        return bool(nodes)

    @staticmethod
    def _decide_mode(
        res: CRemapBatchResult | None,
        *,
        had_c_before: bool,
    ) -> tuple[str, str]:
        if res is None:
            return "llm_extract_new", "remap_no_result"
        need = int(res.needs_llm_remap)
        upd = int(res.updated)
        if need > 0:
            return "llm_remap", "needs_llm_remap_after_mechanical"
        if upd > 0:
            return "mechanical_remap", "remap_ok"
        if not had_c_before:
            return "llm_extract_new", "no_c_nodes"
        return "mechanical_remap", "c_nodes_unchanged"

    def _process_one_file(
        self,
        *,
        feedback: AgentWorkChangeFeedback,
        project_root: Path,
        cf: ChangedFileFeedback,
        remap: SemanticCRemapService,
        graph_trace_hook: Any,
        request_id: str,
    ) -> MemoryChangeDecision:
        if self._boundary.is_forbidden_source_path(cf.path):
            self._journal_append(
                event_name="memory.change.skipped",
                summary="forbidden or artifact path",
                request_id=request_id,
                payload={"path": cf.path},
            )
            return MemoryChangeDecision(
                path=cf.path,
                mode="skip_artifact",
                reason="forbidden_source_boundary",
                b_fingerprint="",
                c_updated=0,
                c_needs_llm_remap=0,
            )
        rel = str(cf.path or "").replace("\\", "/").strip().lstrip("./")
        abs_f = (project_root / rel).resolve()
        if not abs_f.is_file():
            self._journal_append(
                event_name="memory.change.file_decided",
                summary="delete_or_stale: missing file on disk",
                request_id=request_id,
                payload={"path": cf.path, "mode": "delete_or_stale"},
            )
            return MemoryChangeDecision(
                path=cf.path,
                mode="delete_or_stale",
                reason="file_missing",
                b_fingerprint="",
                c_updated=0,
                c_needs_llm_remap=0,
            )
        had_c = self._had_c_nodes(
            namespace=feedback.namespace,
            rel=rel,
        )
        batch = remap.process_changes(
            namespace=feedback.namespace,
            project_root=project_root,
            relative_paths=(rel,),
            graph_trace_hook=graph_trace_hook,
        )
        r: CRemapBatchResult | None = batch[0] if batch else None
        b_fp = r.b_fingerprint if r is not None else ""
        upd = int(r.updated) if r is not None else 0
        need = int(r.needs_llm_remap) if r is not None else 0
        mode, reason = self._decide_mode(r, had_c_before=had_c)
        self._journal_append(
            event_name="memory.change.file_decided",
            summary=f"decided {mode} for {cf.path}",
            request_id=request_id,
            payload={
                "path": cf.path,
                "mode": mode,
                "reason": reason,
            },
        )
        if mode == "mechanical_remap" and need == 0 and upd > 0:
            self._journal_append(
                event_name="memory.change.mechanical_remap.finished",
                summary="mechanical C remap",
                request_id=request_id,
                payload={"path": cf.path, "updated": upd},
            )
        elif need > 0:
            self._journal_append(
                event_name="memory.change.llm_remap.started",
                summary="needs_llm_remap after mechanical",
                request_id=request_id,
                payload={"path": cf.path, "needs_llm_remap": need},
            )
            self._maybe_remap_placeholder(
                path=cf.path,
                request_id=request_id,
            )
            self._journal_append(
                event_name="memory.change.llm_remap.finished",
                summary="llm remap stage (no raw provider in G13.3 service)",
                request_id=request_id,
                payload={"path": cf.path},
            )
        return MemoryChangeDecision(
            path=cf.path,
            mode=mode,
            reason=reason,
            b_fingerprint=b_fp,
            c_updated=upd,
            c_needs_llm_remap=need,
        )

    def _maybe_remap_placeholder(self, *, path: str, request_id: str) -> None:
        """G13.3: без сырого prompt; LLM path — policy-bound (G13.2/4)."""
        if self._llm_provider is None:
            return
        _ = (path, request_id, self._llm_provider)
