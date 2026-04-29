"""AgentMemoryQueryPipeline: memory.query_context (G13.2, D13.2)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING, Mapping, Sequence

from agent_core.models import ChatMessage, ChatRequest, MessageRole
from agent_core.providers.protocol import ChatProvider
from agent_core.runtime.agent_memory_runtime_contract import (
    AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
    AgentMemoryCommandName,
    W14CommandParseError,
    parse_memory_query_pipeline_llm_text,
)
from agent_core.runtime.agent_memory_result_assembly import (
    FinishDecisionResultAssembler,
)
from agent_core.runtime.agent_memory_chat_log import (
    MEMORY_AUDIT_A1_POLICY_LLM_OFF,
    MEMORY_AUDIT_A2_MECHANICAL_SLICE,
    MEMORY_AUDIT_A3_NO_PROJECT_ROOT,
    MEMORY_AUDIT_A4_PLANNER_JSON_INVALID,
    MEMORY_AUDIT_A5_LLM_PLANNER,
    MEMORY_AUDIT_A6_W14_COMMAND_REJECTED,
)
from agent_core.runtime.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)
from agent_core.runtime.models import RuntimeRequestEnvelope
from agent_core.memory.pag_runtime import PagRuntimeConfig
from agent_core.memory.sqlite_pag import SqlitePagStore

if TYPE_CHECKING:
    from agent_core.runtime.subprocess_agents.memory_agent import (
        AgentMemoryWorker,
    )

# G14R.6: C/B LLM — `agent_core.runtime.agent_memory_summary_service` (D14R.4);
# не `agent_core.legacy` C extraction.

# G14R.11: первый LLM-раунд — plan_traversal (C14R.5). G13 planner снят.
W14_PLAN_TRAVERSAL_SYSTEM: str = (
    "Ты выполняешь команду AgentMemory plan_traversal. "
    "Для user_subgoal из входного JSON (goal, namespace, explicit_paths) "
    "верни только JSON agent_memory_command_output.v1, "
    "command=plan_traversal. "
    "Поля: schema_version, command, command_id, status, payload "
    "(actions, is_final, final_answer_basis), decision_summary, violations. "
    "actions[].action: list_children|get_b_summary|get_c_content|"
    "decompose_b_to_c|summarize_b|finish; пути — POSIX relpath. "
    "Не выдумывай пути; не проси сырой B content. "
    "См. plan/14-agent-memory-runtime.md C14R.5 для полной схемы."
)


def _json_dumps(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


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
    am_v1_explicit_results: list[dict[str, Any]] | None = None
    am_v1_status: str | None = None


class AgentMemoryQueryPipeline:
    """W14: plan_traversal / finish_decision → PAG (no G13 c_upserts)."""

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
            self._w.log_memory_why_llm(  # noqa: SLF001
                req,
                request_id=request_id,
                reason_id=MEMORY_AUDIT_A1_POLICY_LLM_OFF,
                checklist={"memory_llm_optimization_enabled": False},
            )
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
            ms = mech.memory_slice
            self._w.log_memory_why_llm(  # noqa: SLF001
                req,
                request_id=request_id,
                reason_id=MEMORY_AUDIT_A2_MECHANICAL_SLICE,
                checklist={
                    "mechanical_slice_eligible": bool(
                        explicit_paths and str(goal or "").strip(),
                    ),
                },
                extra={
                    "slice_reason": str(ms.get("reason", "") or ""),
                    "staleness": str(ms.get("staleness", "") or ""),
                },
            )
            self._nj(
                req=req,
                event_name="memory.explore.cache_hit",
                summary="mechanical pag slice, no provider",
                request_id=request_id,
            )
            return mech
        if not str(project_root or "").strip():
            self._w.log_memory_why_llm(  # noqa: SLF001
                req,
                request_id=request_id,
                reason_id=MEMORY_AUDIT_A3_NO_PROJECT_ROOT,
                checklist={"project_root": ""},
            )
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
        self._w.log_memory_why_llm(  # noqa: SLF001
            req,
            request_id=request_id,
            reason_id=MEMORY_AUDIT_A5_LLM_PLANNER,
            checklist={
                "llm_optimization_enabled": True,
                "mechanical_slice_eligible": bool(
                    explicit_paths and str(goal or "").strip(),
                ),
                "mechanical_slice_hit": False,
                "project_root_non_empty": bool(
                    str(project_root or "").strip(),
                ),
            },
            extra={"planner_user_json": pl_user},
        )
        c_req = self._policy.apply_chat_request(
            ChatRequest(
                messages=(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=W14_PLAN_TRAVERSAL_SYSTEM,
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
        pl_prompt_id: str = str(uuid.uuid4())
        pl_command_trace: str = str(uuid.uuid4())
        qid_log = str(
            (req.payload.get("query_id", "") or "") or f"mem-{request_id}",
        ).strip() or f"mem-{request_id}"
        w14_seq: list[int] = [0]

        def _w14_next_step_id() -> str:
            w14_seq[0] += 1
            return f"{qid_log}:s{w14_seq[0]}"

        user_pl_chars = len(_json_dumps(pl_user))
        self._w.log_memory_w14_command_requested(  # noqa: SLF001
            req,
            request_id,
            prompt_id=pl_prompt_id,
            command_id=pl_command_trace,
            query_id=qid_log,
            input_message_count=len(c_req.messages),
            input_user_payload_chars=user_pl_chars,
            model=str(c_req.model or "mock-memory"),
        )
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=_w14_next_step_id(),
            state="start",
            next_state="llm_await",
            action_kind="planner_round",
            query_id=qid_log,
            counters={"runtime_transitions": 1},
        )
        try:
            resp = self._prov.complete(c_req)
        except Exception as exc:  # noqa: BLE001
            self._w.log_memory_llm_verbose(  # noqa: SLF001
                req,
                request_id,
                "planner",
                c_req,
                None,
                exc,
            )
            raise
        self._w.log_memory_llm_verbose(  # noqa: SLF001
            req,
            request_id,
            "planner",
            c_req,
            resp,
            None,
        )
        raw_txt = "".join(resp.text_parts).strip()
        try:
            plan_obj = parse_memory_query_pipeline_llm_text(raw_txt)
        except W14CommandParseError as exc:
            return self._w14_command_output_rejected_partial(
                req=req,
                request_id=request_id,
                qid_log=qid_log,
                w14_next_step_id=_w14_next_step_id,
                project_root=project_root,
                explicit_paths=explicit_paths,
                goal=goal,
                query_kind=query_kind,
                level=level,
                nspace=nspace,
                reason=str(exc),
                prompt_id=pl_prompt_id,
                command_id=pl_command_trace,
            )
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
        if (
            str(plan_obj.get("schema_version", "") or "").strip()
            == AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA
        ):
            pld0: Any = plan_obj.get("payload", {})
            pld_ct = 0
            if isinstance(pld0, dict):
                ar0 = pld0.get("actions")
                if isinstance(ar0, list):
                    pld_ct = len(ar0)
                elif isinstance(pld0.get("selected_results"), list):
                    pld_ct = len(pld0.get("selected_results", []))
            self._w.log_memory_w14_command_compact(  # noqa: SLF001
                req,
                request_id,
                command=str(plan_obj.get("command", "") or ""),
                command_id=str(plan_obj.get("command_id", "") or ""),
                status=str(plan_obj.get("status", "") or ""),
                prompt_id=pl_prompt_id,
                schema_version=str(plan_obj.get("schema_version", "") or ""),
                result_counts={"payload_items": pld_ct} if pld_ct else None,
            )
            w14_cmd: str = str(
                plan_obj.get("command", "") or "unknown",
            ).strip() or "unknown"
            self._w.log_memory_w14_runtime_step(  # noqa: SLF001
                req,
                request_id,
                step_id=_w14_next_step_id(),
                state="llm_await",
                next_state="w14_command_parsed",
                action_kind=w14_cmd,
                query_id=qid_log,
                counters={"w14_command_ok": 1},
            )
            if str(plan_obj.get("command", "") or "").strip() == (
                AgentMemoryCommandName.FINISH_DECISION.value
            ):
                return self._finish_decision_result(
                    req=req,
                    plan_obj=plan_obj,
                    request_id=request_id,
                    qid_log=qid_log,
                    w14_next_step_id=_w14_next_step_id,
                    project_root=project_root,
                    goal=goal,
                    query_kind=query_kind,
                    level=level,
                    nspace=nspace,
                    partial_plan=partial_plan,
                )
            return self._w14_intermediate_command_result(
                req=req,
                request_id=request_id,
                qid_log=qid_log,
                w14_next_step_id=_w14_next_step_id,
                plan_obj=plan_obj,
                project_root=project_root,
                goal=goal,
                query_kind=query_kind,
                level=level,
                nspace=nspace,
                explicit_paths=explicit_paths,
            )
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

    def _finish_decision_result(
        self,
        *,
        req: RuntimeRequestEnvelope,
        plan_obj: dict[str, Any],
        request_id: str,
        qid_log: str,
        w14_next_step_id: Callable[[], str],
        project_root: str,
        goal: str,
        query_kind: str,
        level: str,
        nspace: str,
        partial_plan: bool,
    ) -> AgentMemoryQueryPipelineResult:
        """
        G14R.7: ``finish_decision`` -> ``agent_memory_result`` (§1.3).
        """
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="w14_command_parsed",
            next_state="finish_assembly",
            action_kind=AgentMemoryCommandName.FINISH_DECISION.value,
            query_id=qid_log,
            counters={"finish_decision_enter": 1},
        )
        pld: Any = plan_obj.get("payload", {})
        if not isinstance(pld, dict):
            pld = {}
        selected: Any = pld.get("selected_results", [])
        if not isinstance(selected, list):
            selected = []
        store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
        root = Path(str(project_root or "").strip()).expanduser().resolve()
        asm = FinishDecisionResultAssembler(
            project_root=root,
            namespace=nspace,
            store=store,
        )
        results, path_rejects = asm.assemble_finish_decision_results(
            selected,
        )
        pr_flags = bool(partial_plan) or bool(path_rejects)
        inner = str(pld.get("status", "complete") or "complete")
        if inner not in ("complete", "partial", "blocked"):
            inner = "complete"
        if path_rejects and not results:
            inner = "blocked"
        elif path_rejects and results:
            if inner == "complete":
                inner = "partial"
        elif not results and not selected:
            inner = "blocked"
        dsum = str(plan_obj.get("decision_summary", "") or "")[:1_200]
        rns = str(
            pld.get("recommended_next_step", "")
            or plan_obj.get("recommended_next_step", "")
            or "",
        )[:500]
        if not dsum.strip():
            dsum = "finish_decision"
        node_ids: list[str] = []
        for row in results:
            cid = row.get("c_node_id")
            if cid:
                node_ids.append(str(cid))
        tfp = sorted(
            {str(r.get("path", "") or "") for r in results if r.get("path")},
        )
        part_flag = pr_flags or (inner in ("partial", "blocked"))
        stl = "w14_finish_assembly" if results else "w14_finish_empty"
        rsn = "w14_finish_decision" if results else "w14_finish_no_evidence"
        mem_sl: dict[str, Any] = {
            "kind": "memory_slice",
            "schema": "memory.slice.v1",
            "level": level,
            "node_ids": node_ids,
            "edge_ids": [],
            "injected_text": "",
            "estimated_tokens": 0,
            "staleness": stl,
            "reason": rsn,
            "target_file_paths": tfp,
            "partial": part_flag,
        }
        if str(goal or "").strip():
            mem_sl["query_subgoal"] = str(goal)[:200]
        if str(query_kind or "").strip():
            mem_sl["query_kind"] = str(query_kind)[:120]
        return AgentMemoryQueryPipelineResult(
            memory_slice=mem_sl,
            partial=bool(mem_sl.get("partial", False)),
            decision_summary=dsum,
            recommended_next_step=rns
            or ("refine subgoal" if inner == "blocked" else ""),
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
            am_v1_explicit_results=results,
            am_v1_status=inner,
        )

    def _w14_intermediate_command_result(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        qid_log: str,
        w14_next_step_id: Callable[[], str],
        plan_obj: dict[str, Any],
        project_root: str,
        goal: str,
        query_kind: str,
        level: str,
        nspace: str,
        explicit_paths: list[str],
    ) -> AgentMemoryQueryPipelineResult:
        """
        G14R.11: W14 envelope, command != finish_decision.

        Один run() — partial slice + PAG grow по explicit_paths; без c_upserts.
        """
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="w14_command_parsed",
            next_state="w14_intermediate_slice",
            action_kind=str(plan_obj.get("command", "") or "w14_intermediate"),
            query_id=qid_log,
            counters={"w14_intermediate": 1},
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
        ms2: dict[str, Any] = dict(
            ms0
            or {
                "kind": "memory_slice",
                "schema": "memory.slice.v1",
                "level": level,
                "node_ids": [],
                "edge_ids": [],
                "injected_text": (goal[:400] + "\n") if goal else "\n",
                "estimated_tokens": 0,
                "staleness": "w14_intermediate",
                "reason": "w14_intermediate_no_runtime_loop",
            },
        )
        ms2["partial"] = True
        dsum = str(
            plan_obj.get("decision_summary", "")
            or "W14: промежуточная команда; нужны следующие runtime-шаги",
        )[:1_200]
        rns = str(
            plan_obj.get("recommended_next_step", "")
            or "Повторите memory query после расширения PAG",
        )[:500]
        return AgentMemoryQueryPipelineResult(
            memory_slice=ms2,
            partial=True,
            decision_summary=dsum,
            recommended_next_step=rns,
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
        )

    def _w14_command_output_rejected_partial(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        qid_log: str,
        w14_next_step_id: Callable[[], str],
        project_root: str,
        explicit_paths: list[str],
        goal: str,
        query_kind: str,
        level: str,
        nspace: str,
        reason: str,
        prompt_id: str,
        command_id: str,
    ) -> AgentMemoryQueryPipelineResult:
        self._w.log_memory_why_llm(  # noqa: SLF001
            req,
            request_id=request_id,
            reason_id=MEMORY_AUDIT_A6_W14_COMMAND_REJECTED,
        )
        self._w.log_memory_w14_command_rejected(  # noqa: SLF001
            req,
            request_id,
            error_code="w14_command_parse",
            detail=reason,
            command_id=command_id,
            prompt_id=prompt_id,
        )
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="llm_await",
            next_state="w14_command_rejected",
            action_kind="w14_parse_rejected",
            query_id=qid_log,
            counters={"w14_command_reject": 1},
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
            decision_summary="w14 command output invalid",
            recommended_next_step="retry",
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
        )

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
        self._w.log_memory_why_llm(  # noqa: SLF001
            req,
            request_id=request_id,
            reason_id=MEMORY_AUDIT_A4_PLANNER_JSON_INVALID,
        )
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
