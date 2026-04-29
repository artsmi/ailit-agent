"""AgentMemory subprocess worker (G8.4.2, memory slice adapter).

The worker owns the Desktop actor contract for ``memory.query_context``:
it returns ``MemoryGrant`` objects, a ``memory_slice`` (compatibility
projection) and W14 ``agent_memory_result`` (``agent_memory_result.v1``)
as the source of truth in the response payload.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from agent_core.models import ChatRequest, NormalizedChatResponse
from agent_core.runtime.agent_memory_config import (
    SourceBoundaryFilter,
    build_compact_query_journal,
    load_or_create_agent_memory_config,
)
from agent_core.runtime.agent_memory_ailit_config import (
    build_chat_provider_for_agent_memory,
    load_merged_ailit_config_for_memory,
    resolve_memory_llm_optimization,
)
from agent_core.runtime.agent_memory_chat_log import (
    AgentMemoryChatDebugLog,
    MEMORY_AUDIT_WHY,
    audit_jsonable,
)
from agent_core.runtime.d_creation_policy import (
    DCreationPolicy,
    am_result_digest_goal_text,
    enrich_memory_slice_tiered,
    linked_abc_from_am_explicit_results,
    merge_d_into_node_ids,
)
from agent_core.runtime.memory_journal import (
    MemoryJournalRow,
    MemoryJournalStore,
)
from agent_core.memory.pag_runtime import PagRuntimeConfig
from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.agent_memory_query_pipeline import (
    AgentMemoryQueryPipeline,
)
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService
from agent_core.runtime.memory_growth import (
    PATH_SEL_ENTRYPOINT,
    PATH_SEL_GOAL_TERMS,
    QueryDrivenGrowthResult,
    QueryDrivenPagGrowth,
)
from agent_core.runtime.memory_change_update_service import (
    ChangeFeedbackIdempotencyStore,
    MemoryChangeUpdateService,
)
from agent_core.runtime.agent_work_change_feedback import (
    AgentWorkChangeFeedback,
)
from agent_core.runtime.agent_memory_result_v1 import (
    build_agent_memory_result_v1,
)
from agent_core.runtime.errors import RuntimeProtocolError
from agent_core.runtime.models import (
    CONTRACT_VERSION,
    AgentWorkMemoryQueryV1,
    MemoryGrant,
    MemoryGrantRange,
    RuntimeRequestEnvelope,
    is_agent_work_memory_query_v1_payload,
    make_response_envelope,
    parse_agent_work_memory_query_v1,
)
from agent_core.runtime.w14_clean_replacement import (
    W14_CLEAN_REPLACEMENT_REQUESTED_READS_IN_CLIENT_PAYLOAD_REJECTED,
)
from agent_core.runtime.memory_c_remap import (
    CRemapBatchResult,
    SemanticCRemapService,
)
from agent_core.runtime.pag_graph_trace import emit_pag_graph_trace_row


@dataclass(frozen=True, slots=True)
class MemoryAgentConfig:
    """Конфиг AgentMemory."""

    chat_id: str
    broker_id: str
    namespace: str


class AgentMemoryWorker:
    """Реализация memory.query_context -> memory_slice + MemoryGrant."""

    def __init__(self, cfg: MemoryAgentConfig) -> None:
        self._cfg = cfg
        self._journal = MemoryJournalStore()
        self._am_file = load_or_create_agent_memory_config()
        self._ailit_merged: dict[str, Any] = (
            load_merged_ailit_config_for_memory()
        )
        self._memory_llm_policy = resolve_memory_llm_optimization(
            self._ailit_merged,
            self._am_file.memory.llm_optimization,
        )
        self._chat_debug = AgentMemoryChatDebugLog(self._am_file)
        self._boundary = SourceBoundaryFilter(self._am_file.memory.artifacts)
        self._change_idempotency = ChangeFeedbackIdempotencyStore()
        self._growth = QueryDrivenPagGrowth(
            db_path=PagRuntimeConfig.from_env().db_path,
        )
        self._provider = build_chat_provider_for_agent_memory(
            self._ailit_merged,
        )

    def _issue_grant(
        self,
        path: str,
        *,
        chat_id: str,
        start_line: int,
        end_line: int,
    ) -> MemoryGrant:
        return MemoryGrant(
            grant_id=str(uuid.uuid4()),
            issued_by="AgentMemory:global",
            issued_to=f"AgentWork:{chat_id}",
            namespace=self._cfg.namespace,
            path=path,
            ranges=(
                MemoryGrantRange(
                    start_line=start_line,
                    end_line=end_line,
                ),
            ),
            whole_file=False,
            reason="query_context",
            expires_at="2099-01-01T00:00:00Z",
        )

    def _grants_for_am_read_lines(
        self,
        req: RuntimeRequestEnvelope,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        G14R.7: гранты по read_lines-диапазонам, не full-file (A14R.8).
        """
        out: list[dict[str, Any]] = []
        for r in results:
            if str(r.get("kind", "") or "") != "read_lines":
                continue
            rpath = str(r.get("path", "") or "").strip()
            if not rpath:
                continue
            segs = r.get("read_lines")
            if not isinstance(segs, list):
                continue
            for seg in segs:
                if not isinstance(seg, dict):
                    continue
                try:
                    sl = int(seg.get("start_line", 0) or 0)
                    el = int(seg.get("end_line", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if sl < 1 or el < sl:
                    continue
                out.append(
                    self._issue_grant(
                        rpath,
                        chat_id=req.chat_id,
                        start_line=sl,
                        end_line=el,
                    ).to_dict(),
                )
        return out

    def _graph_trace_hook(
        self,
        req: RuntimeRequestEnvelope,
        *,
        request_id: str,
        service: str,
        change_batch_id: str | None = None,
    ) -> Callable[[str, str, int, dict[str, Any]], None]:
        """graph_trace: desktop trace + chat_logs (verbose)."""
        w = self

        def _cb(
            op: str,
            namespace: str,
            rev: int,
            data: dict[str, Any],
        ) -> None:
            if w._chat_debug.enabled:
                w._chat_debug.log_audit(
                    raw_chat_id=req.chat_id,
                    event="memory.pag_graph",
                    request_id=request_id,
                    topic=f"graph_{op}",
                    service=service,
                    change_batch_id=change_batch_id,
                    body={
                        "op": op,
                        "namespace": namespace,
                        "rev": rev,
                        "data": audit_jsonable(data),
                    },
                )
            if op == "node":
                emit_pag_graph_trace_row(
                    req=req,
                    event_name="pag.node.upsert",
                    inner_payload={
                        "kind": "pag.node.upsert",
                        "namespace": namespace,
                        "rev": rev,
                        "node": data,
                    },
                )
            elif op == "edge":
                emit_pag_graph_trace_row(
                    req=req,
                    event_name="pag.edge.upsert",
                    inner_payload={
                        "kind": "pag.edge.upsert",
                        "namespace": namespace,
                        "rev": rev,
                        "edges": [data],
                    },
                )
            elif op == "edge_batch":
                if isinstance(data, dict):
                    edge_list = data.get("edges")
                else:
                    edge_list = None
                if not isinstance(edge_list, list):
                    edge_list = []
                emit_pag_graph_trace_row(
                    req=req,
                    event_name="pag.edge.upsert",
                    inner_payload={
                        "kind": "pag.edge.upsert",
                        "namespace": namespace,
                        "rev": rev,
                        "edges": edge_list,
                    },
                )

        return _cb

    def _log_handle_error(
        self,
        req: RuntimeRequestEnvelope,
        *,
        request_id: str,
        service: str,
        out: Mapping[str, Any],
        change_batch_id: str | None = None,
    ) -> None:
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.error",
            request_id=request_id,
            topic="handler_reject",
            service=service,
            change_batch_id=change_batch_id,
            body={"response": dict(out)},
        )

    def _append_journal(
        self,
        *,
        req: RuntimeRequestEnvelope,
        event_name: str,
        summary: str,
        request_id: str,
        node_ids: list[str] | None = None,
        edge_ids: list[str] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            self._journal.append(
                MemoryJournalRow(
                    chat_id=req.chat_id,
                    request_id=request_id,
                    namespace=req.namespace or self._cfg.namespace,
                    event_name=event_name,
                    summary=summary,
                    node_ids=tuple(node_ids or ()),
                    edge_ids=tuple(edge_ids or ()),
                    payload=dict(payload or {}),
                ),
            )
        except Exception:
            return

    def log_memory_llm_verbose(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        phase: str,
        c_req: ChatRequest,
        resp: NormalizedChatResponse | None,
        exc: BaseException | None = None,
        *,
        service: str = "memory.query_context",
        change_batch_id: str | None = None,
    ) -> None:
        """`memory.debug.verbose=1` — полные LLM-запрос/ответ в chat_logs."""
        err: str | None = None
        if exc is not None:
            err = f"{type(exc).__name__}:{exc}"
        self._chat_debug.log_llm(
            raw_chat_id=req.chat_id,
            request_id=request_id,
            phase=phase,
            request=c_req,
            response=resp,
            error=err,
            service=service,
            change_batch_id=change_batch_id,
        )

    def log_memory_why_llm(
        self,
        req: RuntimeRequestEnvelope,
        *,
        request_id: str,
        reason_id: str,
        checklist: Mapping[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
        service: str = "memory.query_context",
        change_batch_id: str | None = None,
    ) -> None:
        """Аудит: стабильный reason_id (whitelist) + опциональный чеклист."""
        if not self._chat_debug.enabled:
            return
        body: dict[str, Any] = {
            "reason_id": reason_id,
            "explanation": MEMORY_AUDIT_WHY.get(
                reason_id,
                "(unknown reason_id)",
            ),
        }
        if checklist is not None:
            body["checklist"] = dict(checklist)
        if extra is not None:
            body["details"] = dict(extra)
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.why_llm",
            request_id=request_id,
            topic="llm_decision",
            service=service,
            change_batch_id=change_batch_id,
            body=body,
        )

    def log_memory_planner_parsed(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        plan: Mapping[str, Any],
        paths_for_grow: list[str],
        grow_will_run: bool,
        service: str = "memory.query_context",
        change_batch_id: str | None = None,
    ) -> None:
        """Сырой план панера + пути для query-driven grow."""
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.runtime_decision",
            request_id=request_id,
            topic="planner_parsed",
            service=service,
            change_batch_id=change_batch_id,
            body={
                "plan": dict(plan),
                "paths_for_grow": list(paths_for_grow),
                "grow_will_run": grow_will_run,
            },
        )

    def log_memory_w14_command_requested(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        prompt_id: str,
        command_id: str,
        query_id: str,
        input_message_count: int,
        input_user_payload_chars: int,
        model: str,
        phase: str = "planner",
        service: str = "memory.query_context",
        change_batch_id: str | None = None,
    ) -> None:
        """
        C14R.11 / G14R.9: ``memory.command.requested`` + chat debug,
        без raw prompt.
        """
        pld: dict[str, Any] = {
            "command": phase,
            "command_id": str(command_id)[:200],
            "query_id": str(query_id)[:200],
            "prompt_id": str(prompt_id)[:200],
            "input_message_count": int(input_message_count),
            "input_user_payload_chars": int(input_user_payload_chars),
            "model": str(model)[:200],
        }
        self._append_journal(
            req=req,
            event_name="memory.command.requested",
            summary="llm command round: requested",
            request_id=request_id,
            payload=pld,
        )
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.chat_debug.command",
            request_id=request_id,
            topic="memory.command.requested",
            service=service,
            change_batch_id=change_batch_id,
            body={**pld, "redaction": "compact_no_raw_prompt"},
        )

    def log_memory_w14_command_compact(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        command: str,
        command_id: str,
        status: str,
        prompt_id: str = "",
        schema_version: str = "",
        result_counts: Mapping[str, int] | None = None,
        service: str = "memory.query_context",
        change_batch_id: str | None = None,
    ) -> None:
        """
        C14R.11: ``memory.command.parsed`` + chat ``memory.chat_debug.command``
        (без raw prompt), тот же ``command_id`` что в JSON от LLM.
        """
        pld: dict[str, Any] = {
            "command": str(command)[:200],
            "command_id": str(command_id)[:200],
            "status": str(status)[:64],
        }
        if str(prompt_id or "").strip():
            pld["prompt_id"] = str(prompt_id)[:200]
        if str(schema_version or "").strip():
            pld["schema_version"] = str(schema_version)[:80]
        if result_counts is not None:
            pld["result_counts"] = {
                str(k): int(v) for k, v in result_counts.items()
            }
        self._append_journal(
            req=req,
            event_name="memory.command.parsed",
            summary="w14 command output parsed",
            request_id=request_id,
            payload=dict(pld),
        )
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.chat_debug.command",
            request_id=request_id,
            topic="memory.command.parsed",
            service=service,
            change_batch_id=change_batch_id,
            body={**pld, "redaction": "compact_no_raw_prompt"},
        )

    def log_memory_w14_command_rejected(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        error_code: str,
        detail: str = "",
        command_id: str = "",
        prompt_id: str = "",
        service: str = "memory.query_context",
        change_batch_id: str | None = None,
    ) -> None:
        """
        C14R.11 / G14R.9: ``memory.command.rejected`` + chat
        (без сырого ответа LLM); тот же ``command_id`` в journal и chat_logs.
        """
        pld: dict[str, Any] = {
            "error_code": str(error_code)[:200],
            "command_id": str(command_id)[:200],
        }
        if str(prompt_id or "").strip():
            pld["prompt_id"] = str(prompt_id)[:200]
        if str(detail or "").strip():
            pld["detail"] = str(detail)[:500]
        self._append_journal(
            req=req,
            event_name="memory.command.rejected",
            summary="w14 command output rejected",
            request_id=request_id,
            payload=pld,
        )
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.chat_debug.command",
            request_id=request_id,
            topic="memory.command.rejected",
            service=service,
            change_batch_id=change_batch_id,
            body={**pld, "redaction": "compact_no_raw_prompt"},
        )

    def log_memory_graph_write(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        created_node_ids: list[str],
        link_claims_count: int,
        service: str = "memory.query_context",
        change_batch_id: str | None = None,
    ) -> None:
        """Результат upsert C-нод и link claims от планера."""
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.runtime_decision",
            request_id=request_id,
            topic="c_upserts_and_links",
            service=service,
            change_batch_id=change_batch_id,
            body={
                "created_node_ids": list(created_node_ids),
                "link_claims_submitted": int(link_claims_count),
            },
        )

    def _log_query_context_incoming(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        goal: str,
        query_kind: str,
        level: str,
        project_root: str,
        explicit_paths: list[str],
    ) -> None:
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.request",
            request_id=request_id,
            topic="query_context",
            service="memory.query_context",
            body={
                "envelope": req.to_dict(),
                "derived": {
                    "goal": goal,
                    "query_kind": query_kind,
                    "level": level,
                    "project_root": project_root,
                    "explicit_paths": list(explicit_paths),
                },
            },
        )

    def _log_query_context_outgoing(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        out: Mapping[str, Any],
    ) -> None:
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.response",
            request_id=request_id,
            topic="to_agent_work",
            service="memory.query_context",
            body={"response": dict(out)},
        )

    def _log_path_boundary(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        path: str,
    ) -> None:
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.runtime_decision",
            request_id=request_id,
            topic="path_boundary",
            service="memory.query_context",
            body={
                "excluded_path": path,
                "reason": "forbidden_artifact_or_cache",
            },
        )

    def _log_pipeline_slice(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        after_pipeline: dict[str, Any],
        used_fallback: bool,
    ) -> None:
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.runtime_decision",
            request_id=request_id,
            topic="query_slice_after_pipeline",
            service="memory.query_context",
            body={
                "memory_slice": audit_jsonable(after_pipeline),
                "used_path_fallback": used_fallback,
            },
        )

    def _log_d_policy(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        gate: str,
        reason: str,
        d_fingerprint: str,
        d_node_id: str | None,
    ) -> None:
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.runtime_decision",
            request_id=request_id,
            topic="d_policy",
            service="memory.query_context",
            body={
                "d_gate": gate,
                "d_reason": reason,
                "d_fingerprint": d_fingerprint,
                "d_node_id": d_node_id,
            },
        )

    def _log_enriched_slice(
        self,
        req: RuntimeRequestEnvelope,
        request_id: str,
        *,
        memory_slice: dict[str, Any],
    ) -> None:
        if not self._chat_debug.enabled:
            return
        self._chat_debug.log_audit(
            raw_chat_id=req.chat_id,
            event="memory.runtime_decision",
            request_id=request_id,
            topic="slice_tiered_enrich",
            service="memory.query_context",
            body={"memory_slice": audit_jsonable(dict(memory_slice))},
        )

    def _grow_pag_for_query(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        project_root: str,
        goal: str,
        explicit_paths: list[str],
    ) -> QueryDrivenGrowthResult | None:
        if not project_root.strip():
            return None
        try:
            res = self._growth.grow(
                project_root=Path(project_root).expanduser().resolve(),
                goal=goal,
                explicit_paths=explicit_paths,
                namespace=req.namespace or self._cfg.namespace,
                graph_trace_hook=self._graph_trace_hook(
                    req,
                    request_id=request_id,
                    service="memory.query_context",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._append_journal(
                req=req,
                event_name="memory.index.partial",
                summary="query-driven PAG growth failed",
                request_id=request_id,
                payload={"error": f"{type(exc).__name__}:{exc}"},
            )
            if self._chat_debug.enabled:
                self._chat_debug.log_audit(
                    raw_chat_id=req.chat_id,
                    event="memory.runtime_decision",
                    request_id=request_id,
                    topic="query_driven_pag_growth",
                    service="memory.query_context",
                    body={
                        "input_explicit_paths": list(explicit_paths),
                        "error": f"{type(exc).__name__}:{exc}",
                    },
                )
            return None
        if self._chat_debug.enabled:
            self._chat_debug.log_audit(
                raw_chat_id=req.chat_id,
                event="memory.runtime_decision",
                request_id=request_id,
                topic="query_driven_pag_growth",
                service="memory.query_context",
                body={
                    "input_explicit_paths": list(explicit_paths),
                    "result": {
                        "namespace": res.namespace,
                        "selected_paths": list(res.selected_paths),
                        "node_ids": list(res.node_ids),
                        "partial": res.partial,
                        "reason": res.reason,
                        "path_selection_source": res.path_selection_source,
                        "non_matching_explicit_paths": list(
                            res.non_matching_explicit_paths,
                        ),
                    },
                },
            )
        heur = (PATH_SEL_GOAL_TERMS, PATH_SEL_ENTRYPOINT)
        if res.path_selection_source in heur and self._chat_debug.enabled:
            self._chat_debug.log_audit(
                raw_chat_id=req.chat_id,
                event="memory.runtime_decision",
                request_id=request_id,
                topic="planner_path_heuristic_fallback",
                service="memory.query_context",
                body={
                    "explanation": (
                        "Heuristic file shortlist: no valid explicit relpath "
                        "remained, or the list was empty. Selection used goal "
                        "token match or entrypoint seed (e.g. README), not "
                        "only requested_reads that resolve to files."
                    ),
                    "input_explicit_paths": list(explicit_paths),
                    "path_selection_source": res.path_selection_source,
                    "non_matching_explicit_paths": list(
                        res.non_matching_explicit_paths,
                    ),
                    "selected_paths": list(res.selected_paths),
                },
            )
        if res.partial:
            self._append_journal(
                req=req,
                event_name="memory.index.partial",
                summary=res.reason,
                request_id=request_id,
                payload={
                    "namespace": res.namespace,
                    "selected_paths": list(res.selected_paths),
                },
            )
            return res
        for node_id in res.node_ids:
            self._append_journal(
                req=req,
                event_name="memory.index.node_updated",
                summary="query-driven PAG node updated",
                request_id=request_id,
                node_ids=[node_id],
                payload={
                    "namespace": res.namespace,
                    "selected_paths": list(res.selected_paths),
                    "reason": res.reason,
                },
            )
        return res

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough donor-style token estimate for pre-provider payloads."""
        return max(1, (len(text or "") + 3) // 4)

    @staticmethod
    def _path_node_ids(path: str, *, namespace: str) -> list[str]:
        """Build stable fallback A/B/C ids when PAG is missing or stale."""
        rel = str(path or "").strip().lstrip("./")
        if not rel:
            return [f"A:{namespace}"]
        return [f"A:{namespace}", f"B:{rel}", f"C:{rel}:1-200"]

    def _slice_from_pag(
        self,
        *,
        project_root: str,
        namespace: str,
        goal: str,
        query_kind: str,
        level: str,
    ) -> dict[str, Any] | None:
        """Build a real PAG slice when the local PAG store is available."""
        if not project_root.strip():
            return None
        try:
            from agent_core.memory.pag_runtime import (  # noqa: WPS433
                PagRuntimeAgentMemory,
                PagRuntimeConfig,
            )

            cfg = PagRuntimeConfig.from_env()
            if not cfg.enabled:
                return None
            mem = PagRuntimeAgentMemory(cfg)
            res = mem.build_slice_for_goal(
                project_root=Path(project_root).expanduser().resolve(),
                namespace=namespace,
                goal=goal,
                query_kind=query_kind,
            )
        except Exception:  # noqa: BLE001
            return None
        if not res.used or not res.injected_text:
            return {
                "kind": "memory_slice",
                "schema": "memory.slice.v1",
                "level": level,
                "node_ids": [],
                "edge_ids": [],
                "injected_text": "",
                "estimated_tokens": 0,
                "staleness": str(res.staleness_state),
                "reason": str(res.fallback_reason or "pag_unavailable"),
                "target_file_paths": list(res.target_file_paths),
            }
        node_ids = [n.node_id for n in res.nodes]
        edge_ids = [e.edge_id for e in res.edges]
        return {
            "kind": "memory_slice",
            "schema": "memory.slice.v1",
            "level": level,
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "injected_text": res.injected_text,
            "estimated_tokens": self._estimate_tokens(res.injected_text),
            "staleness": str(res.staleness_state),
            "reason": "pag_runtime_slice",
            "target_file_paths": list(res.target_file_paths),
        }

    def _handle_file_changed(
        self,
        req: RuntimeRequestEnvelope,
        *,
        request_id: str,
    ) -> Mapping[str, Any]:
        """`memory.file_changed` — B fingerprint + semantic C remap (G12.7)."""
        if self._chat_debug.enabled:
            self._chat_debug.log_audit(
                raw_chat_id=req.chat_id,
                event="memory.request",
                request_id=request_id,
                topic="file_changed",
                service="memory.file_changed",
                body={"envelope": req.to_dict()},
            )
        pl: Mapping[str, Any] = req.payload
        project_root = str(pl.get("project_root", "") or "").strip()
        if not project_root:
            out = make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "bad_request",
                    "message": "project_root required",
                },
            ).to_dict()
            self._log_handle_error(
                req,
                request_id=request_id,
                service="memory.file_changed",
                out=out,
            )
            return out
        raw_ch: Any = pl.get("changes", [])
        rels: list[str] = []
        if isinstance(raw_ch, list):
            for it in raw_ch:
                if isinstance(it, dict):
                    rp = str(it.get("path", "") or "").strip()
                    if rp:
                        rels.append(rp)
        if not rels:
            ok0 = make_response_envelope(
                request=req,
                ok=True,
                payload={"remapped": []},
            ).to_dict()
            if self._chat_debug.enabled:
                self._chat_debug.log_audit(
                    raw_chat_id=req.chat_id,
                    event="memory.response",
                    request_id=request_id,
                    topic="to_agent_work",
                    service="memory.file_changed",
                    body={"response": dict(ok0)},
                )
            return ok0
        self._append_journal(
            req=req,
            event_name="memory.file_changed.received",
            summary="file change batch for C remap",
            request_id=request_id,
            payload={"paths": list(rels)},
        )
        store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
        svc = SemanticCRemapService(PagGraphWriteService(store))
        ns = str(
            pl.get("namespace", "") or req.namespace or self._cfg.namespace,
        ).strip() or self._cfg.namespace
        res: list[CRemapBatchResult] = svc.process_changes(
            namespace=ns,
            project_root=Path(project_root).expanduser().resolve(),
            relative_paths=tuple(rels),
            graph_trace_hook=self._graph_trace_hook(
                req,
                request_id=request_id,
                service="memory.file_changed",
            ),
        )
        out_pl = {
            "remapped": [r.path for r in res],
            "summary": [
                {
                    "path": r.path,
                    "updated": r.updated,
                    "needs_llm_remap": r.needs_llm_remap,
                }
                for r in res
            ],
        }
        self._append_journal(
            req=req,
            event_name="memory.file_changed.finished",
            summary="C remap pass completed",
            request_id=request_id,
            payload=out_pl,
        )
        ok_out = make_response_envelope(
            request=req,
            ok=True,
            payload=out_pl,
            error=None,
        ).to_dict()
        if self._chat_debug.enabled:
            self._chat_debug.log_audit(
                raw_chat_id=req.chat_id,
                event="memory.response",
                request_id=request_id,
                topic="to_agent_work",
                service="memory.file_changed",
                body={"response": dict(ok_out)},
            )
        return ok_out

    def _handle_change_feedback(
        self,
        req: RuntimeRequestEnvelope,
        *,
        request_id: str,
    ) -> Mapping[str, Any]:
        """`memory.change_feedback` — AgentWork post-change (G13.3, D13.3)."""
        pl: Mapping[str, Any] = req.payload
        cb_in: str | None = str(
            pl.get("change_batch_id", "")
            or pl.get("changeBatchId", "")
            or "",
        ).strip() or None
        if self._chat_debug.enabled:
            self._chat_debug.log_audit(
                raw_chat_id=req.chat_id,
                event="memory.request",
                request_id=request_id,
                topic="change_feedback",
                service="memory.change_feedback",
                change_batch_id=cb_in,
                body={"envelope": req.to_dict()},
            )
        try:
            fb = AgentWorkChangeFeedback.from_payload(dict(pl))
        except ValueError as exc:
            out = make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "bad_request",
                    "message": str(exc),
                },
            ).to_dict()
            bad_cb = str(
                pl.get("change_batch_id", "")
                or pl.get("changeBatchId", "")
                or "",
            ).strip() or None
            self._log_handle_error(
                req,
                request_id=request_id,
                service="memory.change_feedback",
                out=out,
                change_batch_id=bad_cb,
            )
            return out

        batch_key = str(fb.change_batch_id or "").strip() or None

        def jappend(
            event_name: str,
            summary: str,
            request_id: str,
            payload: Mapping[str, Any] | None = None,
        ) -> None:
            self._append_journal(
                req=req,
                event_name=event_name,
                summary=summary,
                request_id=request_id,
                payload=dict(payload or {}),
            )
            if self._chat_debug.enabled:
                self._chat_debug.log_audit(
                    raw_chat_id=req.chat_id,
                    event="memory.journal_mirror",
                    request_id=request_id,
                    topic=event_name,
                    service="memory.change_feedback",
                    change_batch_id=batch_key,
                    body={
                        "summary": summary,
                        "payload": audit_jsonable(dict(payload or {})),
                    },
                )

        svc = MemoryChangeUpdateService(
            boundary=self._boundary,
            db_path=PagRuntimeConfig.from_env().db_path,
            idempotency=self._change_idempotency,
            journal_append=jappend,
            llm_provider=self._provider,
        )
        res = svc.apply(
            fb,
            graph_trace_hook=self._graph_trace_hook(
                req,
                request_id=request_id,
                service="memory.change_feedback",
                change_batch_id=batch_key,
            ),
            chat_id=req.chat_id,
            request_id=request_id,
        )
        if res.idempotent and self._chat_debug.enabled:
            self._chat_debug.log_audit(
                raw_chat_id=req.chat_id,
                event="memory.runtime_decision",
                request_id=request_id,
                topic="change_feedback_idempotent",
                service="memory.change_feedback",
                change_batch_id=batch_key,
                body={
                    "previous_summary": res.previous_summary,
                },
            )
        if not res.ok:
            out = make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "change_feedback_failed",
                    "message": res.error or "error",
                },
            ).to_dict()
            self._log_handle_error(
                req,
                request_id=request_id,
                service="memory.change_feedback",
                out=out,
                change_batch_id=batch_key,
            )
            return out
        dec_pl: list[dict[str, Any]] = [
            {
                "path": d.path,
                "mode": d.mode,
                "reason": d.reason,
                "b_fingerprint": d.b_fingerprint,
                "c_updated": d.c_updated,
                "c_needs_llm_remap": d.c_needs_llm_remap,
            }
            for d in res.decisions
        ]
        ok_out = make_response_envelope(
            request=req,
            ok=True,
            payload={
                "decisions": dec_pl,
                "idempotent": res.idempotent,
                "previous_summary": res.previous_summary,
            },
            error=None,
        ).to_dict()
        if self._chat_debug.enabled:
            self._chat_debug.log_audit(
                raw_chat_id=req.chat_id,
                event="memory.response",
                request_id=request_id,
                topic="to_agent_work",
                service="memory.change_feedback",
                change_batch_id=batch_key,
                body={"response": dict(ok_out)},
            )
        return ok_out

    def _fallback_slice(
        self,
        *,
        namespace: str,
        path: str,
        goal: str,
        query_kind: str,
        level: str,
    ) -> dict[str, Any]:
        """Return a structured degradation payload suitable for Desktop."""
        node_ids = self._path_node_ids(path, namespace=namespace)
        lines = [
            "PAG slice (AgentMemory -> AgentWork)",
            f"namespace={namespace}",
            f"query_kind={query_kind}",
        ]
        if goal.strip():
            lines.append(f"goal={goal.strip()}")
        if path.strip():
            lines.extend(["", "Shortlist files (top):", f"- {path.strip()}"])
        injected = "\n".join(lines).strip() + "\n"
        return {
            "kind": "memory_slice",
            "schema": "memory.slice.v1",
            "level": level,
            "node_ids": node_ids,
            "edge_ids": [],
            "injected_text": injected,
            "estimated_tokens": self._estimate_tokens(injected),
            "staleness": "fallback",
            "reason": "path_hint_fallback" if path.strip() else "no_pag_slice",
            "target_file_paths": [path.strip()] if path.strip() else [],
        }

    def handle(self, req: RuntimeRequestEnvelope) -> Mapping[str, Any]:
        rid0 = str(req.message_id or "")
        if req.type != "service.request":
            out = make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={"code": "unsupported", "message": req.type},
            ).to_dict()
            self._log_handle_error(
                req,
                request_id=rid0,
                service="dispatch",
                out=out,
            )
            return out
        service = str(req.payload.get("service", "") or "")
        if service == "memory.file_changed":
            rfc = str(req.payload.get("request_id", "") or "") or str(
                req.message_id,
            )
            return self._handle_file_changed(req, request_id=rfc)
        if service == "memory.change_feedback":
            rfc2 = str(req.payload.get("request_id", "") or "") or str(
                req.message_id,
            )
            return self._handle_change_feedback(req, request_id=rfc2)
        if service and service != "memory.query_context":
            out = make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={"code": "unknown_service", "message": service},
            ).to_dict()
            self._log_handle_error(
                req,
                request_id=str(
                    req.payload.get("request_id", "") or req.message_id,
                ),
                service=service,
                out=out,
            )
            return out
        request_id = str(req.payload.get("request_id", "") or req.message_id)
        if W14_CLEAN_REPLACEMENT_REQUESTED_READS_IN_CLIENT_PAYLOAD_REJECTED:
            raw_rr: Any = req.payload.get("requested_reads")
            if isinstance(raw_rr, list) and len(raw_rr) > 0:
                out = make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={
                        "code": "legacy_contract_rejected",
                        "message": (
                            "W14 clean replacement: client field "
                            "requested_reads is not supported"
                        ),
                    },
                ).to_dict()
                self._log_handle_error(
                    req,
                    request_id=request_id,
                    service="memory.query_context",
                    out=out,
                )
                return out
        v1q: AgentWorkMemoryQueryV1 | None = None
        if is_agent_work_memory_query_v1_payload(req.payload):
            try:
                v1q = parse_agent_work_memory_query_v1(req.payload)
            except RuntimeProtocolError as e:
                err_pl = make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={
                        "code": "invalid_memory_query_envelope",
                        "message": str(e.message),
                    },
                ).to_dict()
                self._log_handle_error(
                    req,
                    request_id=request_id,
                    service="memory.query_context",
                    out=err_pl,
                )
                return err_pl
            goal = v1q.subgoal
        else:
            goal = str(req.payload.get("goal", "") or "")
            if not goal.strip():
                goal = str(req.payload.get("need", "") or "")
        query_kind = str(req.payload.get("query_kind", "") or "task")
        level = str(req.payload.get("level", "") or "B").strip() or "B"
        project_root = str(req.payload.get("project_root", "") or "")
        if v1q is not None:
            project_root = v1q.project_root
        want_path = str(req.payload.get("path", "") or "")
        if not want_path:
            want_path = str(req.payload.get("hint_path", "") or "")
        if v1q is not None and not str(want_path or "").strip():
            if v1q.known_paths:
                want_path = str(v1q.known_paths[0])
        workspace_projects = req.payload.get("workspace_projects")
        self._append_journal(
            req=req,
            event_name="memory.request.received",
            summary="memory query received",
            request_id=request_id,
            payload={
                "goal_len": len(goal),
                "query_kind": query_kind,
                "level": level,
                "workspace_projects_count": (
                    len(workspace_projects)
                    if isinstance(workspace_projects, list)
                    else 0
                ),
            },
        )
        explicit_paths: list[str] = [want_path] if want_path else []
        if want_path and self._boundary.is_forbidden_source_path(want_path):
            self._append_journal(
                req=req,
                event_name="memory.path.excluded",
                summary="path matched source-boundary forbidden rule",
                request_id=request_id,
                payload={
                    "path": want_path,
                    "reason": "forbidden_artifact_or_cache_path",
                },
            )
            self._log_path_boundary(req, request_id, path=want_path)
            explicit_paths = []
        self._log_query_context_incoming(
            req,
            request_id,
            goal=goal,
            query_kind=query_kind,
            level=level,
            project_root=project_root,
            explicit_paths=explicit_paths,
        )
        pl = AgentMemoryQueryPipeline(
            self,
            self._memory_llm_policy,
            self._provider,
        )
        pr = pl.run(
            req=req,
            request_id=request_id,
            goal=goal,
            project_root=project_root,
            explicit_paths=explicit_paths,
            query_kind=query_kind,
            level=level,
        )
        w14_finish: bool = pr.am_v1_explicit_results is not None
        memory_slice = pr.memory_slice
        pipeline_partial = pr.partial
        if w14_finish and (pr.am_v1_status in ("partial", "blocked")):
            pipeline_partial = True
        pipeline_decision = pr.decision_summary
        pipeline_next = pr.recommended_next_step
        qid_payload = str(req.payload.get("query_id", "") or "").strip()
        am_query_id: str = (
            v1q.query_id
            if v1q is not None
            else (qid_payload or f"mem-{request_id}")
        )
        used_fb = False
        if memory_slice is None:
            memory_slice = self._fallback_slice(
                namespace=req.namespace or self._cfg.namespace,
                path=want_path,
                goal=goal,
                query_kind=query_kind,
                level=level,
            )
            used_fb = True
        elif (
            not str(memory_slice.get("injected_text") or "").strip()
            and not w14_finish
        ):
            memory_slice = self._fallback_slice(
                namespace=req.namespace or self._cfg.namespace,
                path=want_path,
                goal=goal,
                query_kind=query_kind,
                level=level,
            )
            used_fb = True
        self._log_pipeline_slice(
            req,
            request_id,
            after_pipeline=dict(memory_slice),
            used_fallback=used_fb,
        )
        if not want_path:
            targets = memory_slice.get("target_file_paths")
            if isinstance(targets, list) and targets:
                want_path = str(targets[0] or "")
        grants: list[dict[str, Any]] = []
        if w14_finish:
            grants = self._grants_for_am_read_lines(
                req,
                list(pr.am_v1_explicit_results or ()),
            )
        elif want_path:
            grant = self._issue_grant(
                want_path,
                chat_id=req.chat_id,
                start_line=1,
                end_line=200,
            )
            grants.append(grant.to_dict())
        if (
            not want_path
            and not str(memory_slice.get("injected_text") or "").strip()
            and not w14_finish
        ):
            err_out = make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "memory_unavailable",
                    "message": "no PAG slice or path hint available",
                },
            ).to_dict()
            self._log_query_context_outgoing(req, request_id, err_out)
            return err_out
        d_gate: str = ""
        d_rsn: str = ""
        if w14_finish:
            p_ns = str(req.namespace or self._cfg.namespace)
            p_store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
            d_pol = DCreationPolicy(self._am_file.memory.d_policy)
            explicit = list(pr.am_v1_explicit_results or [])
            linked_for_d = linked_abc_from_am_explicit_results(explicit)
            digest_goal = am_result_digest_goal_text(
                subgoal=goal,
                decision_summary=str(pipeline_decision or "")[:1_200],
                query_id=am_query_id,
            )
            d_out = d_pol.maybe_upsert_query_digest(
                PagGraphWriteService(p_store),
                namespace=p_ns,
                goal=digest_goal,
                node_ids=linked_for_d,
                graph_trace_hook=self._graph_trace_hook(
                    req,
                    request_id=request_id,
                    service="memory.query_context",
                ),
            )
            d_gate = str(d_out.gate)
            d_rsn = str(d_out.reason)
            if d_out.d_node_id:
                memory_slice["node_ids"] = merge_d_into_node_ids(
                    [str(x) for x in (memory_slice.get("node_ids") or [])],
                    d_out.d_node_id,
                )
            memory_slice["d_creation"] = {
                "gate": d_gate,
                "reason": d_rsn,
                "d_fingerprint": d_out.d_fingerprint,
            }
            self._log_d_policy(
                req,
                request_id,
                gate=d_gate,
                reason=d_rsn,
                d_fingerprint=str(d_out.d_fingerprint or ""),
                d_node_id=d_out.d_node_id,
            )
        enrich_memory_slice_tiered(
            memory_slice,
            namespace=str(req.namespace or self._cfg.namespace),
        )
        self._log_enriched_slice(
            req,
            request_id,
            memory_slice=dict(memory_slice),
        )
        memory_slice["partial"] = bool(
            memory_slice.get("partial", False) or pipeline_partial,
        )
        node_ids = list(memory_slice.get("node_ids") or [])
        edge_ids = list(memory_slice.get("edge_ids") or [])
        decision_summary = str(pipeline_decision or "").strip() or str(
            memory_slice.get("reason") or "memory slice",
        )
        recommended_next_step = str(pipeline_next or "").strip() or (
            "read selected context"
            if node_ids
            else "provide more specific memory goal"
        )
        final_partial: bool = bool(
            pipeline_partial or memory_slice.get("partial", False),
        )
        project_refs = [
            {
                "project_id": "",
                "namespace": req.namespace or self._cfg.namespace,
                "node_ids": node_ids,
                "edge_ids": edge_ids,
            },
        ]
        cj = build_compact_query_journal(
            event_name="memory.slice.returned",
            request_id=request_id,
            task_summary=goal,
            decision_summary=decision_summary,
            node_ids=node_ids,
            d_creation_gate=d_gate,
            d_creation_reason=d_rsn,
        )
        self._append_journal(
            req=req,
            event_name="memory.slice.returned",
            summary=decision_summary,
            request_id=request_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            payload={
                "partial": final_partial,
                "recommended_next_step": recommended_next_step,
                "estimated_tokens": memory_slice.get("estimated_tokens"),
                "compact": cj.to_payload(),
            },
        )
        agent_mem_res = build_agent_memory_result_v1(
            query_id=am_query_id,
            status=("partial" if final_partial else "complete"),
            memory_slice=dict(memory_slice),
            partial=final_partial,
            decision_summary=decision_summary,
            recommended_next_step=recommended_next_step,
            explicit_results=pr.am_v1_explicit_results,
            explicit_status=pr.am_v1_status,
        )
        ok_out = make_response_envelope(
            request=req,
            ok=True,
            payload={
                "memory_slice": memory_slice,
                "agent_memory_result": agent_mem_res,
                "grants": grants,
                "project_refs": project_refs,
                "partial": final_partial,
                "recommended_next_step": recommended_next_step,
                "decision_summary": decision_summary,
            },
            error=None,
        ).to_dict()
        self._log_query_context_outgoing(req, request_id, ok_out)
        return ok_out


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent-memory")
    p.add_argument("--chat-id", type=str, required=True)
    p.add_argument("--broker-id", type=str, required=True)
    p.add_argument("--namespace", type=str, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    cfg = MemoryAgentConfig(
        chat_id=str(args.chat_id),
        broker_id=str(args.broker_id),
        namespace=str(args.namespace),
    )
    worker = AgentMemoryWorker(cfg)
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            req = RuntimeRequestEnvelope.from_json_line(raw)
        except Exception:
            continue
        if req.contract_version != CONTRACT_VERSION:
            continue
        out = worker.handle(req)
        sys.stdout.write(json_dumps_single_line(out))
        sys.stdout.flush()
    return 0


def json_dumps_single_line(obj: Mapping[str, Any]) -> str:
    import json

    return (
        json.dumps(dict(obj), ensure_ascii=False, separators=(",", ":"))
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
