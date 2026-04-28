"""AgentMemory subprocess worker (G8.4.2, memory slice adapter).

The worker owns the Desktop actor contract for ``memory.query_context``:
it returns both legacy ``MemoryGrant`` objects and a prompt-ready
``memory_slice`` with PAG node ids for Context Ledger / Memory 3D.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from agent_core.runtime.agent_memory_config import (
    SourceBoundaryFilter,
    build_compact_query_journal,
    load_or_create_agent_memory_config,
)
from agent_core.runtime.memory_journal import (
    MemoryJournalRow,
    MemoryJournalStore,
)
from agent_core.memory.pag_runtime import PagRuntimeConfig
from agent_core.runtime.memory_growth import QueryDrivenPagGrowth
from agent_core.runtime.models import (
    CONTRACT_VERSION,
    MemoryGrant,
    MemoryGrantRange,
    RuntimeRequestEnvelope,
    make_response_envelope,
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
        self._boundary = SourceBoundaryFilter(self._am_file.memory.artifacts)
        self._growth = QueryDrivenPagGrowth(
            db_path=PagRuntimeConfig.from_env().db_path,
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

    @staticmethod
    def _graph_trace_hook(
        req: RuntimeRequestEnvelope,
    ) -> Callable[[str, str, int, dict[str, Any]], None]:
        """Колбек для SqlitePagStore.graph_trace: G12.1 дельты в trace."""

        def _cb(
            op: str,
            namespace: str,
            rev: int,
            data: dict[str, Any],
        ) -> None:
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

        return _cb

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

    def _grow_pag_for_query(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        project_root: str,
        goal: str,
        explicit_paths: list[str],
    ) -> None:
        if not project_root.strip():
            return
        try:
            res = self._growth.grow(
                project_root=Path(project_root).expanduser().resolve(),
                goal=goal,
                explicit_paths=explicit_paths,
                namespace=req.namespace or self._cfg.namespace,
                graph_trace_hook=self._graph_trace_hook(req),
            )
        except Exception as exc:  # noqa: BLE001
            self._append_journal(
                req=req,
                event_name="memory.index.partial",
                summary="query-driven PAG growth failed",
                request_id=request_id,
                payload={"error": f"{type(exc).__name__}:{exc}"},
            )
            return
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
            return
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
        if req.type != "service.request":
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={"code": "unsupported", "message": req.type},
            ).to_dict()
        service = str(req.payload.get("service", "") or "")
        if service and service != "memory.query_context":
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={"code": "unknown_service", "message": service},
            ).to_dict()
        request_id = str(req.payload.get("request_id", "") or req.message_id)
        goal = str(req.payload.get("goal", "") or "")
        if not goal.strip():
            goal = str(req.payload.get("need", "") or "")
        query_kind = str(req.payload.get("query_kind", "") or "task")
        level = str(req.payload.get("level", "") or "B").strip() or "B"
        project_root = str(req.payload.get("project_root", "") or "")
        want_path = str(req.payload.get("path", "") or "")
        if not want_path:
            want_path = str(req.payload.get("hint_path", "") or "")
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
            explicit_paths = []
        self._grow_pag_for_query(
            req=req,
            request_id=request_id,
            project_root=project_root,
            goal=goal,
            explicit_paths=explicit_paths,
        )
        memory_slice = self._slice_from_pag(
            project_root=project_root,
            namespace=req.namespace or self._cfg.namespace,
            goal=goal,
            query_kind=query_kind,
            level=level,
        )
        if memory_slice is None:
            memory_slice = self._fallback_slice(
                namespace=req.namespace or self._cfg.namespace,
                path=want_path,
                goal=goal,
                query_kind=query_kind,
                level=level,
            )
        elif not str(memory_slice.get("injected_text") or "").strip():
            memory_slice = self._fallback_slice(
                namespace=req.namespace or self._cfg.namespace,
                path=want_path,
                goal=goal,
                query_kind=query_kind,
                level=level,
            )
        if not want_path:
            targets = memory_slice.get("target_file_paths")
            if isinstance(targets, list) and targets:
                want_path = str(targets[0] or "")
        grants = []
        if want_path:
            grant = self._issue_grant(
                want_path,
                chat_id=req.chat_id,
                start_line=1,
                end_line=200,
            )
            grants.append(grant.to_dict())
        if not want_path and not memory_slice.get("injected_text"):
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "memory_unavailable",
                    "message": "no PAG slice or path hint available",
                },
            ).to_dict()
        node_ids = list(memory_slice.get("node_ids") or [])
        edge_ids = list(memory_slice.get("edge_ids") or [])
        project_refs = [
            {
                "project_id": "",
                "namespace": req.namespace or self._cfg.namespace,
                "node_ids": node_ids,
                "edge_ids": edge_ids,
            },
        ]
        decision_summary = str(memory_slice.get("reason") or "memory slice")
        recommended_next_step = (
            "read selected context"
            if node_ids
            else "provide more specific memory goal"
        )
        cj = build_compact_query_journal(
            event_name="memory.slice.returned",
            request_id=request_id,
            task_summary=goal,
            decision_summary=decision_summary,
            node_ids=node_ids,
        )
        self._append_journal(
            req=req,
            event_name="memory.slice.returned",
            summary=decision_summary,
            request_id=request_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            payload={
                "partial": False,
                "recommended_next_step": recommended_next_step,
                "estimated_tokens": memory_slice.get("estimated_tokens"),
                "compact": cj.to_payload(),
            },
        )
        return make_response_envelope(
            request=req,
            ok=True,
            payload={
                "memory_slice": memory_slice,
                "grants": grants,
                "project_refs": project_refs,
                "partial": False,
                "recommended_next_step": recommended_next_step,
                "decision_summary": decision_summary,
            },
            error=None,
        ).to_dict()


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
