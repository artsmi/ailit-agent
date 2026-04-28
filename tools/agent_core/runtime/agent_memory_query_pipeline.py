"""AgentMemoryQueryPipeline: memory.query_context (G13.2, D13.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING, Mapping, Sequence

from agent_core.models import ChatMessage, ChatRequest, MessageRole
from agent_core.providers.protocol import ChatProvider
from agent_core.runtime.agent_memory_config import (
    parse_memory_json_with_retry,
)
from agent_core.runtime.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)
from agent_core.runtime.models import RuntimeRequestEnvelope
from agent_core.memory.pag_runtime import PagRuntimeConfig
from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.link_claim_resolver import LinkClaimResolver
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService

if TYPE_CHECKING:
    from agent_core.runtime.subprocess_agents.memory_agent import (
        AgentMemoryWorker,
    )

PLANNER_SYSTEM: str = """You are AgentMemory planner. Return ONLY JSON.
No markdown, no chain-of-thought. Fields:
selected_projects: string[]
selected_b_nodes: string[]
requested_reads: {path: string, reason: string}[]
extraction_targets: {path: string, kind: string, name: string}[]
c_upserts: {node_id: string, level: string, kind: string, path: string,
  title: string, summary: string, fingerprint: string}[]
link_claims: optional; each item: from_node_id, to_node_id (or to_stable_key),
  relation_type (enum), confidence (0..1)
decision_summary: string
partial: boolean
recommended_next_step: string
"""


def _json_dumps(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _c_level(raw: str) -> str:
    s = (raw or "C").strip().upper()
    if len(s) == 1 and s in "ABCD":
        return s
    return "C"


@dataclass(frozen=True, slots=True)
class AgentMemoryQueryPipelineResult:
    """Результат pipeline (ответ memory.query_context)."""

    memory_slice: dict[str, Any]
    partial: bool
    decision_summary: str
    recommended_next_step: str
    created_node_ids: list[str]
    created_edge_ids: list[str]
    used_llm: bool
    llm_disabled_fallback: bool


class AgentMemoryQueryPipeline:
    """LLM plan → PAG grow по requested_reads → c_upserts → slice."""

    def __init__(
        self,
        worker: AgentMemoryWorker,
        policy: MemoryLlmOptimizationPolicy,
        provider: ChatProvider,
    ) -> None:
        self._w = worker
        self._policy = policy
        self._prov = provider

    def _nj(
        self,
        req: RuntimeRequestEnvelope,
        *,
        event_name: str,
        summary: str,
        request_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._w._append_journal(  # noqa: SLF001
            req=req,
            event_name=event_name,
            summary=summary,
            request_id=request_id,
            payload=dict(payload or {}),
        )

    def run(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        goal: str,
        project_root: str,
        explicit_paths: list[str],
        query_kind: str,
        level: str,
    ) -> AgentMemoryQueryPipelineResult:
        nspace = str(req.namespace or self._w._cfg.namespace)  # noqa: SLF001
        if not self._policy.enabled:
            return self._fallback_without_llm(
                req=req,
                request_id=request_id,
                goal=goal,
                project_root=project_root,
                explicit_paths=explicit_paths,
                query_kind=query_kind,
                level=level,
                nspace=nspace,
            )
        mech = self._try_mechanical_slice(
            goal=goal,
            project_root=project_root,
            namespace=nspace,
            query_kind=query_kind,
            level=level,
            explicit_paths=explicit_paths,
        )
        if mech is not None:
            self._nj(
                req=req,
                event_name="memory.explore.cache_hit",
                summary="mechanical pag slice, no provider",
                request_id=request_id,
            )
            return mech
        if not str(project_root or "").strip():
            return self._fallback_without_llm(
                req=req,
                request_id=request_id,
                goal=goal,
                project_root=project_root,
                explicit_paths=explicit_paths,
                query_kind=query_kind,
                level=level,
                nspace=nspace,
            )
        pl_user = {
            "goal": self._policy.clamp_utf8(
                str(goal or ""),
                self._policy.planner_max_input_chars,
            ),
            "namespace": nspace,
            "explicit_paths": explicit_paths,
        }
        c_req = self._policy.apply_chat_request(
            ChatRequest(
                messages=(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=PLANNER_SYSTEM,
                    ),
                    ChatMessage(
                        role=MessageRole.USER,
                        content=_json_dumps(pl_user),
                    ),
                ),
                model="mock-memory",
                temperature=0.0,
                max_tokens=self._policy.planner_max_output_tokens,
                stream=False,
            ),
            phase="planner",
            model_override=self._policy.model or "mock-memory",
        )
        resp = self._prov.complete(c_req)
        raw_txt = "".join(resp.text_parts).strip()
        try:
            plan_obj = parse_memory_json_with_retry(raw_txt)
        except ValueError:
            return self._partial_json_fallback(
                req=req,
                request_id=request_id,
                project_root=project_root,
                explicit_paths=explicit_paths,
                goal=goal,
                query_kind=query_kind,
                level=level,
                nspace=nspace,
            )
        partial_plan = bool(plan_obj.get("partial", False))
        c_ups: Any = plan_obj.get("c_upserts", [])
        if not isinstance(c_ups, list):
            c_ups = []
        link_claims_list: Any = plan_obj.get("link_claims", [])
        if not isinstance(link_claims_list, list):
            link_claims_list = []
        req_reads: Any = plan_obj.get("requested_reads", [])
        rels: list[str] = [
            str(x.get("path", "")).strip()
            for x in (req_reads if isinstance(req_reads, list) else [])
            if isinstance(x, dict)
        ]
        rels = [p for p in rels if p] or list(explicit_paths)
        if rels:
            self._w._grow_pag_for_query(  # noqa: SLF001
                req=req,
                request_id=request_id,
                project_root=project_root,
                goal=goal,
                explicit_paths=rels,
            )
        created: list[str] = []
        if c_ups or link_claims_list:
            store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
            write = PagGraphWriteService(store)
            hook = self._w._graph_trace_hook(req)  # noqa: SLF001
            with store.graph_trace(hook):
                for c in c_ups:
                    if not isinstance(c, dict):
                        continue
                    node_id = str(c.get("node_id", "") or "").strip()
                    if not node_id:
                        continue
                    path_v = str(
                        c.get("path", rels[0] if rels else "") or "",
                    )[:2_000]
                    write.upsert_node(
                        namespace=nspace,
                        node_id=node_id,
                        level=_c_level(str(c.get("level", "C") or "C")),
                        kind=str(c.get("kind", "chunk") or "chunk")[:200],
                        path=path_v,
                        title=str(
                            c.get("title", node_id) or node_id,
                        )[:2_000],
                        summary=str(c.get("summary", "") or "")[:4_000],
                        attrs={},
                        fingerprint=str(
                            c.get("fingerprint", "")
                            or f"llm:{node_id[:80]}",
                        )[:200],
                        staleness_state="fresh",
                    )
                    created.append(node_id)
                vclaims: list[dict[str, Any]] = [
                    x
                    for x in link_claims_list
                    if isinstance(x, dict)
                ]
                if vclaims:
                    resolver = LinkClaimResolver()
                    _ = resolver.apply_link_claims(
                        write,
                        namespace=nspace,
                        claims=vclaims,
                    )
        memory_slice = self._w._slice_from_pag(  # noqa: SLF001
            project_root=project_root,
            namespace=nspace,
            goal=goal,
            query_kind=query_kind,
            level=level,
        )
        if not memory_slice:
            memory_slice = {
                "kind": "memory_slice",
                "schema": "memory.slice.v1",
                "level": level,
                "node_ids": list(created),
                "edge_ids": [],
                "injected_text": (goal[:400] + "\n") if goal else "\n",
                "estimated_tokens": 0,
                "staleness": "synthetic" if created else "fallback",
                "reason": "planner_upsert_slice" if created else "empty_slice",
            }
        ms = dict(memory_slice)
        nids = list(ms.get("node_ids") or [])
        for cid in created:
            if cid not in nids:
                nids.append(cid)
        ms["node_ids"] = nids
        ms["partial"] = bool(ms.get("partial", False) or partial_plan)
        dsum = str(
            plan_obj.get("decision_summary", "") or "planner ok",
        )[:1_200]
        rns = str(plan_obj.get("recommended_next_step", "") or "")[:500]
        return AgentMemoryQueryPipelineResult(
            memory_slice=ms,
            partial=bool(ms.get("partial", False)),
            decision_summary=dsum,
            recommended_next_step=rns,
            created_node_ids=created,
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
        )

    def _try_mechanical_slice(
        self,
        *,
        goal: str,
        project_root: str,
        namespace: str,
        query_kind: str,
        level: str,
        explicit_paths: Sequence[str],
    ) -> AgentMemoryQueryPipelineResult | None:
        if not explicit_paths or not str(goal or "").strip():
            return None
        sl = self._w._slice_from_pag(  # noqa: SLF001
            project_root=project_root,
            namespace=namespace,
            goal=goal,
            query_kind=query_kind,
            level=level,
        )
        if (
            sl
            and str(sl.get("reason", "") or "") == "pag_runtime_slice"
            and str(sl.get("staleness", "") or "") == "fresh"
        ):
            return AgentMemoryQueryPipelineResult(
                memory_slice=dict(sl),
                partial=bool(sl.get("partial", False)),
                decision_summary="cache: pag runtime slice",
                recommended_next_step="n/a",
                created_node_ids=[],
                created_edge_ids=[],
                used_llm=False,
                llm_disabled_fallback=False,
            )
        return None

    def _partial_json_fallback(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        project_root: str,
        explicit_paths: list[str],
        goal: str,
        query_kind: str,
        level: str,
        nspace: str,
    ) -> AgentMemoryQueryPipelineResult:
        self._nj(
            req=req,
            event_name="memory.partial",
            summary="invalid planner json, partial",
            request_id=request_id,
        )
        self._w._grow_pag_for_query(  # noqa: SLF001
            req=req,
            request_id=request_id,
            project_root=project_root,
            goal=goal,
            explicit_paths=explicit_paths,
        )
        ms0 = self._w._slice_from_pag(  # noqa: SLF001
            project_root=project_root,
            namespace=nspace,
            goal=goal,
            query_kind=query_kind,
            level=level,
        )
        ms2 = dict(ms0 or {"kind": "memory_slice", "node_ids": []})
        if not ms0:
            ms2["partial"] = True
        elif (
            str(ms2.get("reason", "") or "") == "pag_runtime_slice"
            and str(ms2.get("staleness", "") or "") == "fresh"
        ):
            ms2["partial"] = False
        else:
            ms2["partial"] = True
        pflag = bool(ms2.get("partial", True))
        return AgentMemoryQueryPipelineResult(
            memory_slice=ms2,
            partial=pflag,
            decision_summary="invalid json",
            recommended_next_step="retry",
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
        )

    def _fallback_without_llm(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        goal: str,
        project_root: str,
        explicit_paths: list[str],
        query_kind: str,
        level: str,
        nspace: str,
    ) -> AgentMemoryQueryPipelineResult:
        self._nj(
            req=req,
            event_name="memory.fallback",
            summary="llm disabled, heuristic PAG",
            request_id=request_id,
            payload={"reason": "llm_disabled"},
        )
        self._w._grow_pag_for_query(  # noqa: SLF001
            req=req,
            request_id=request_id,
            project_root=project_root,
            goal=goal,
            explicit_paths=explicit_paths,
        )
        sl = self._w._slice_from_pag(  # noqa: SLF001
            project_root=project_root,
            namespace=nspace,
            goal=goal,
            query_kind=query_kind,
            level=level,
        )
        if not sl:
            sl = self._w._fallback_slice(  # noqa: SLF001
                namespace=nspace,
                path=explicit_paths[0] if explicit_paths else "",
                goal=goal,
                query_kind=query_kind,
                level=level,
            )
        s2 = dict(sl)
        s2["partial"] = True
        s2.setdefault("staleness", "heuristic")
        s2["reason"] = "memory.fallback"
        s2["c_semantic_validated"] = False
        return AgentMemoryQueryPipelineResult(
            memory_slice=s2,
            partial=True,
            decision_summary="heuristic",
            recommended_next_step="enable memory.llm in agent-memory config",
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=False,
            llm_disabled_fallback=True,
        )
