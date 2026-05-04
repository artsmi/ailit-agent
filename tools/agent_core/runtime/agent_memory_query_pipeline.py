"""AgentMemoryQueryPipeline: memory.query_context (G13.2, D13.2)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING, Mapping, Sequence

from agent_core.memory.pag_indexer import PagIndexer
from agent_core.models import ChatMessage, ChatRequest, MessageRole
from agent_core.providers.protocol import ChatProvider
from agent_core.runtime.agent_memory_runtime_contract import (
    AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
    AgentMemoryCommandName,
    W14CommandParseResult,
    W14CommandParseError,
    parse_memory_query_pipeline_llm_text_result,
)
from agent_core.runtime.agent_memory_link_candidate_validator import (
    AgentMemoryLinkCandidateValidator,
)
from agent_core.runtime.agent_memory_result_assembly import (
    FinishDecisionResultAssembler,
)
from agent_core.runtime.agent_memory_terminal_outcomes import (
    REASON_LINK_REJECTED,
    REASON_W14_PARSE_FAILED,
    or013_reasons_from_assembly_reject_codes,
    w14_intermediate_runtime_partial_reasons,
)
from agent_core.runtime.agent_memory_w14_observability import (
    build_link_candidates_external_event,
    build_links_updated_external_event,
)
from agent_core.runtime.agent_memory_summary_service import (
    AgentMemorySummaryService,
    SummarizeCNodeInputV1,
    SummarizeCLocator,
    W14CommandLimits,
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
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService
from agent_core.runtime.w14_graph_highlight_path import (
    W14GraphHighlightPathBuilder,
)

if TYPE_CHECKING:
    from agent_core.runtime.subprocess_agents.memory_agent import (
        AgentMemoryWorker,
    )

_memory_pipeline_cancel_tls = threading.local()


class MemoryQueryCancelledError(Exception):
    """Сигнал cooperative cancel для ``memory.query_context`` pipeline."""


def _memory_pipeline_begin_cancel(
    cancel_event: threading.Event | None,
) -> None:
    """Привязать cancel-event к текущему потоку (``memory.query_context``)."""
    setattr(_memory_pipeline_cancel_tls, "cancel_event", cancel_event)


def _memory_pipeline_end_cancel() -> None:
    """Снять привязку cancel-event после ``pl.run``."""
    if hasattr(_memory_pipeline_cancel_tls, "cancel_event"):
        delattr(_memory_pipeline_cancel_tls, "cancel_event")


def _memory_pipeline_coop_check() -> None:
    ev = getattr(_memory_pipeline_cancel_tls, "cancel_event", None)
    if isinstance(ev, threading.Event) and ev.is_set():
        raise MemoryQueryCancelledError()


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
    "Top-level поле status только \"ok\", \"partial\" или \"refuse\"; "
    "не используй \"in_progress\" и иные lifecycle-метки на верхнем уровне "
    "envelope — ход плана только через payload.is_final и payload.actions. "
    "Top-level command не должен быть summarize_c/summarize_b "
    "(это внутренние runtime-фазы, не envelope планера). "
    "Не используй command=repair_invalid_response (repair — фаза журнала "
    "planner_repair, не имя envelope). "
    "actions[].action: list_children|get_b_summary|get_c_content|"
    "decompose_b_to_c|summarize_b|finish; пути — POSIX relpath. "
    "Не выдумывай пути; не проси сырой B content. "
    "См. plan/14-agent-memory-runtime.md C14R.5 для полной схемы."
)


def _w14_repair_error_targets_in_progress_legacy_status(
    validation_error: str,
) -> bool:
    """UC-03: repair-контекст для unknown_legacy_w14_status + in_progress."""
    low = str(validation_error or "").lower()
    return "unknown_legacy_w14_status" in low and "in_progress" in low


def _w14_repair_system_message(validation_error: str) -> str:
    """Текст system-сообщения для repair W14 (C4 при legacy in_progress)."""
    base = (
        "Исправь JSON ответа AgentMemory. Верни только "
        "валидный agent_memory_command_output.v1 JSON. "
        "Не меняй смысл команды без необходимости."
    )
    if not _w14_repair_error_targets_in_progress_legacy_status(
        validation_error,
    ):
        return base
    return (
        f"{base} "
        "UC-03 (plan_traversal, C4): если validation_error про недопустимый "
        "legacy top-level status `in_progress`, команда plan_traversal, "
        "payload валиден по контракту, payload.is_final=false и "
        "payload.actions непустой — установи top-level status в "
        "\"ok\" (или \"partial\"/\"refuse\" по смыслу ответа), не сохраняй "
        "\"in_progress\" на верхнем уровне из‑за общей фразы "
        "«не меняй смысл»: прогресс плана выражается через is_final и "
        "actions, это не меняет смысл шага."
    )


def _w14_repair_user_instruction(validation_error: str) -> str:
    """Structured instruction для repair_user (тот же UC-03 / C4)."""
    base = (
        "Return only a JSON object that validates as "
        "agent_memory_command_output.v1. Do not add prose."
    )
    if not _w14_repair_error_targets_in_progress_legacy_status(
        validation_error,
    ):
        return base
    return (
        f"{base} "
        "If command is plan_traversal, payload is valid, is_final is false, "
        "and actions is a non-empty array: top-level status must be one of "
        "ok|partial|refuse; set status to ok instead of in_progress."
    )


def _json_dumps(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _norm_rel_path(raw: str) -> str:
    return str(raw or "").replace("\\", "/").strip().lstrip("./")


def _b_node_id(rel: str) -> str:
    return f"B:{_norm_rel_path(rel)}"


def _edge_id(edge_class: str, edge_type: str, from_id: str, to_id: str) -> str:
    raw = f"{edge_class}:{edge_type}:{from_id}->{to_id}"
    h = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"e:{h}"


def _looks_like_full_repo_goal(goal: str) -> bool:
    g = str(goal or "").lower()
    return any(
        token in g
        for token in (
            "кажд",
            "все файл",
            "всех файл",
            "all files",
            "whole repo",
            "full repo",
        )
    )


@dataclass(frozen=True, slots=True)
class W14RuntimeLimits:
    max_turns: int
    max_selected_b: int
    max_c_per_b: int
    max_total_c: int
    max_reads_per_turn: int
    max_summary_chars: int
    max_reason_chars: int
    max_decision_chars: int
    min_child_summary_coverage: float


@dataclass(frozen=True, slots=True)
class W14DeferredGraphHighlight:
    """Отложенный emit graph_highlight после PAG (включая D-digest)."""

    request_id: str
    namespace: str
    query_id: str
    w14_command: str
    w14_command_id: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    reason: str


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
    w14_graph_highlight_deferred: W14DeferredGraphHighlight | None = None
    runtime_partial_reasons: tuple[str, ...] = ()


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
        memory_init: bool = False,
    ) -> AgentMemoryQueryPipelineResult:
        nspace = str(req.namespace or self._w._cfg.namespace)  # noqa: SLF001
        hold_raw = os.environ.get(
            "AILIT_TEST_MEMORY_PIPELINE_HOLD_S",
            "",
        ).strip()
        if hold_raw:
            time.sleep(float(hold_raw))
        _memory_pipeline_coop_check()
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
            _memory_pipeline_coop_check()
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
            plan_result = parse_memory_query_pipeline_llm_text_result(
                raw_txt,
                runtime_command_id=pl_command_trace,
            )
        except W14CommandParseError as exc:
            repaired = self._repair_w14_command_output(
                req=req,
                request_id=request_id,
                original_text=raw_txt,
                validation_error=str(exc),
                base_request=c_req,
                runtime_command_id=pl_command_trace,
            )
            if repaired is not None:
                plan_result = repaired
            else:
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
                qid_log=qid_log,
                w14_next_step_id=_w14_next_step_id,
            )
        else:
            if plan_result.normalized:
                self._nj(
                    req=req,
                    event_name="memory.command.normalized",
                    summary="w14 command envelope canonicalized",
                    request_id=request_id,
                    payload={
                        "from_schema_version": plan_result.from_schema_version,
                        "to_schema_version": (
                            AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA
                        ),
                        "from_status": plan_result.legacy_status_from,
                        "command_id_restored": plan_result.command_id_restored,
                        "command": str(
                            plan_result.obj.get("command", "") or "",
                        )[:200],
                        "command_id": str(
                            plan_result.obj.get("command_id", "") or "",
                        )[:200],
                    },
                )
            if plan_result.command_id_restored:
                self._nj(
                    req=req,
                    event_name="memory.w14.command_id_restored",
                    summary="w14 command_id restored from runtime trace id",
                    request_id=request_id,
                    payload={
                        "command_id": str(
                            plan_result.obj.get("command_id", "") or "",
                        )[:200],
                    },
                )
        plan_obj = plan_result.obj
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
            if str(plan_obj.get("command", "") or "").strip() == (
                AgentMemoryCommandName.PROPOSE_LINKS.value
            ):
                return self._w14_propose_links_wire_result(
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
                memory_init=memory_init,
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
            qid_log=qid_log,
            w14_next_step_id=_w14_next_step_id,
        )

    def _repair_w14_command_output(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        original_text: str,
        validation_error: str,
        base_request: ChatRequest,
        runtime_command_id: str,
    ) -> W14CommandParseResult | None:
        if not self._should_repair_w14_error(validation_error):
            return None
        repair_user = {
            "validation_error": str(validation_error)[:1_000],
            "previous_response": str(original_text or "")[:4_000],
            "required_schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
            "instruction": _w14_repair_user_instruction(validation_error),
        }
        repair_req = self._policy.apply_chat_request(
            ChatRequest(
                messages=(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=_w14_repair_system_message(validation_error),
                    ),
                    ChatMessage(
                        role=MessageRole.USER,
                        content=_json_dumps(repair_user),
                    ),
                ),
                model=base_request.model,
                temperature=0.0,
                max_tokens=base_request.max_tokens,
                stream=False,
            ),
            phase="planner",
            model_override=self._policy.model or base_request.model,
        )
        try:
            _memory_pipeline_coop_check()
            resp = self._prov.complete(repair_req)
        except Exception as exc:  # noqa: BLE001
            self._w.log_memory_llm_verbose(  # noqa: SLF001
                req,
                request_id,
                "planner_repair",
                repair_req,
                None,
                exc,
            )
            return None
        self._w.log_memory_llm_verbose(  # noqa: SLF001
            req,
            request_id,
            "planner_repair",
            repair_req,
            resp,
            None,
        )
        raw = "".join(resp.text_parts).strip()
        try:
            return parse_memory_query_pipeline_llm_text_result(
                raw,
                runtime_command_id=runtime_command_id,
            )
        except (W14CommandParseError, ValueError):
            return None

    @staticmethod
    def _should_repair_w14_error(reason: str) -> bool:
        low = str(reason or "").lower()
        if "must be only json" in low:
            return False
        if "invalid json" in low:
            return False
        return True

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

    @staticmethod
    def _wire_link_candidates_from_propose_payload(
        payload: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """S1: извлечь candidates после wire-валидации propose_links."""
        if "candidates" in payload:
            cand = payload.get("candidates")
            if isinstance(cand, list):
                return [
                    dict(x) for x in cand if isinstance(x, dict)
                ][:128]
            return []
        lb = payload.get("link_batch")
        if isinstance(lb, dict):
            cand2 = lb.get("candidates")
            if isinstance(cand2, list):
                return [
                    dict(x) for x in cand2 if isinstance(x, dict)
                ][:128]
        return []

    def _w14_propose_links_wire_result(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        qid_log: str,
        w14_next_step_id: Callable[[], str],
        plan_obj: dict[str, Any],
        _project_root: str,
        goal: str,
        query_kind: str,
        level: str,
        nspace: str,
    ) -> AgentMemoryQueryPipelineResult:
        """
        S1/S3: ``propose_links`` — внешние события S2 и запись PAG через S3.

        Рёбра из LLM JSON не пишутся в ``SqlitePagStore`` минуя
        ``AgentMemoryLinkCandidateValidator`` + ``PagGraphWriteService``.
        """
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="w14_command_parsed",
            next_state="w14_propose_links_wire",
            action_kind=AgentMemoryCommandName.PROPOSE_LINKS.value,
            query_id=qid_log,
            counters={"w14_propose_links_wire": 1},
        )
        pld: Any = plan_obj.get("payload", {})
        if not isinstance(pld, dict):
            pld = {}
        cands = self._wire_link_candidates_from_propose_payload(pld)
        self._w.log_memory_external_event_v1(  # noqa: SLF001
            req,
            request_id,
            envelope=build_link_candidates_external_event(
                query_id=qid_log,
                candidates=cands,
            ),
        )
        store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
        write = PagGraphWriteService(store)
        validator = AgentMemoryLinkCandidateValidator()
        with store.graph_trace(
            self._w._graph_trace_hook(  # noqa: SLF001
                req,
                request_id=request_id,
                service="memory.query_context",
            ),
        ):
            batch_result = validator.process_batch(
                store=store,
                write=write,
                namespace=nspace,
                candidates=cands,
            )
        applied_report: list[dict[str, str]] = [
            {"link_id": x["link_id"], "edge_id": x["edge_id"]}
            for x in batch_result.applied_edges
        ]
        applied_report.extend(
            {
                "link_id": x["link_id"],
                "pending_id": x["pending_id"],
                "state": "pending",
            }
            for x in batch_result.applied_pending
        )
        self._w.log_memory_external_event_v1(  # noqa: SLF001
            req,
            request_id,
            envelope=build_links_updated_external_event(
                query_id=qid_log,
                applied=applied_report,
                rejected=batch_result.rejected,
            ),
        )
        for rj in batch_result.rejected:
            lid = str(rj.get("link_id") or "").strip() or "?"
            rsn = str(rj.get("reason") or "").strip()[:300]
            self._w._append_journal(  # noqa: SLF001
                req=req,
                event_name="memory.link_rejected",
                summary=f"link_rejected:{lid}",
                request_id=request_id,
                payload={"link_id": lid, "reason": rsn},
            )
        dsum = str(plan_obj.get("decision_summary", "") or "").strip() or (
            "w14 propose_links validated (S3)"
        )
        new_edge_ids = [x["edge_id"] for x in batch_result.applied_edges]
        mem_sl: dict[str, Any] = {
            "kind": "memory_slice",
            "schema": "memory.slice.v1",
            "level": level,
            "node_ids": [],
            "edge_ids": list(new_edge_ids),
            "injected_text": "",
            "estimated_tokens": 0,
            "staleness": "w14_propose_links_wire",
            "reason": "w14_propose_links_validated",
            "partial": True,
            "w14_link_candidates": cands,
            "w14_link_candidate_count": len(cands),
            "w14_links_applied_edge_count": len(batch_result.applied_edges),
            "w14_links_pending_count": len(batch_result.applied_pending),
            "w14_links_rejected_count": len(batch_result.rejected),
        }
        if str(goal or "").strip():
            mem_sl["query_subgoal"] = str(goal)[:200]
        if str(query_kind or "").strip():
            mem_sl["query_kind"] = str(query_kind)[:120]
        pl_reasons: tuple[str, ...] = (
            (REASON_LINK_REJECTED,) if batch_result.rejected else ()
        )
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="w14_propose_links_wire",
            next_state="terminal",
            action_kind=AgentMemoryCommandName.PROPOSE_LINKS.value,
            query_id=qid_log,
            counters={"w14_propose_links_terminal": 1},
        )
        return AgentMemoryQueryPipelineResult(
            memory_slice=mem_sl,
            partial=True,
            decision_summary=dsum[:1_200],
            recommended_next_step=(
                "continue AgentMemory query or resolve pending links"
            ),
            created_node_ids=[],
            created_edge_ids=list(new_edge_ids),
            used_llm=True,
            llm_disabled_fallback=False,
            am_v1_explicit_results=None,
            am_v1_status="partial",
            w14_graph_highlight_deferred=None,
            runtime_partial_reasons=pl_reasons,
        )

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
        fr_trace = or013_reasons_from_assembly_reject_codes(
            [x.code for x in path_rejects],
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
        _cmd_id = str(plan_obj.get("command_id", "") or "").strip() or (
            f"{qid_log}:finish_decision"
        )
        _fnids = mem_sl.get("node_ids", [])
        _w14_hl = W14GraphHighlightPathBuilder.union_to_ends(
            store,
            nspace,
            [str(x) for x in _fnids if str(x).strip()],
        )
        _gh_def: W14DeferredGraphHighlight | None = None
        if _w14_hl.node_ids or _w14_hl.edge_ids:
            _gh_def = W14DeferredGraphHighlight(
                request_id=request_id,
                namespace=nspace,
                query_id=qid_log,
                w14_command=AgentMemoryCommandName.FINISH_DECISION.value,
                w14_command_id=_cmd_id,
                node_ids=tuple(_w14_hl.node_ids),
                edge_ids=tuple(_w14_hl.edge_ids),
                reason=str(dsum)[:256],
            )
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="finish_assembly",
            next_state="terminal",
            action_kind=AgentMemoryCommandName.FINISH_DECISION.value,
            query_id=qid_log,
            counters={"w14_finish_terminal": 1},
        )
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
            w14_graph_highlight_deferred=_gh_def,
            runtime_partial_reasons=fr_trace,
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
        memory_init: bool,
    ) -> AgentMemoryQueryPipelineResult:
        """
        W14 action runtime: execute plan_traversal actions deterministically.
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
        return self._run_w14_action_runtime(
            req=req,
            request_id=request_id,
            qid_log=qid_log,
            w14_next_step_id=w14_next_step_id,
            plan_obj=plan_obj,
            project_root=project_root,
            goal=goal,
            query_kind=query_kind,
            level=level,
            nspace=nspace,
            explicit_paths=explicit_paths,
            memory_init=memory_init,
        )

    def _runtime_limits(self) -> W14RuntimeLimits:
        cfg = self._w._am_file.memory.runtime  # noqa: SLF001
        return W14RuntimeLimits(
            max_turns=int(cfg.max_turns),
            max_selected_b=int(cfg.max_selected_b),
            max_c_per_b=int(cfg.max_c_per_b),
            max_total_c=int(cfg.max_total_c),
            max_reads_per_turn=int(cfg.max_reads_per_turn),
            max_summary_chars=int(cfg.max_summary_chars),
            max_reason_chars=int(cfg.max_reason_chars),
            max_decision_chars=int(cfg.max_decision_chars),
            min_child_summary_coverage=float(cfg.min_child_summary_coverage),
        )

    def _run_w14_action_runtime(
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
        memory_init: bool,
    ) -> AgentMemoryQueryPipelineResult:
        limits = self._runtime_limits()
        root = Path(str(project_root or "")).expanduser().resolve()
        store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
        selected_b = self._select_b_paths_for_w14(
            root=root,
            goal=goal,
            plan_obj=plan_obj,
            explicit_paths=explicit_paths,
            limits=limits,
            memory_init=memory_init,
        )
        with store.graph_trace(
            self._w._graph_trace_hook(  # noqa: SLF001
                req,
                request_id=request_id,
                service="memory.query_context",
            ),
        ):
            self._materialize_b_paths(
                store=store,
                namespace=nspace,
                root=root,
                rel_paths=selected_b,
            )
            PagIndexer(store).sync_changes(
                namespace=nspace,
                project_root=root,
                changed_paths=selected_b,
            )
            for rel in selected_b:
                b_nid = _b_node_id(str(rel))
                self._w._append_journal(  # noqa: SLF001
                    req=req,
                    event_name="memory.index.node_updated",
                    summary="query-driven PAG node updated",
                    request_id=request_id,
                    node_ids=[b_nid],
                    payload={
                        "namespace": nspace,
                        "selected_paths": [str(rel)],
                        "reason": "w14_materialize_b",
                    },
                )
            c_nodes = self._c_nodes_for_b_paths(
                store=store,
                namespace=nspace,
                paths=selected_b,
                limits=limits,
            )
            svc = AgentMemorySummaryService(PagGraphWriteService(store))
            summarized_c = self._summarize_c_nodes(
                req=req,
                request_id=request_id,
                qid_log=qid_log,
                svc=svc,
                namespace=nspace,
                root=root,
                c_nodes=c_nodes,
                goal=goal,
                limits=limits,
            )
            summarized_b = self._summarize_b_nodes(
                req=req,
                request_id=request_id,
                qid_log=qid_log,
                svc=svc,
                namespace=nspace,
                paths=selected_b,
                goal=goal,
                limits=limits,
            )
        candidates = self._candidate_results_from_c_nodes(summarized_c)
        cap_hit = (
            len(selected_b) >= limits.max_selected_b
            or len(c_nodes) >= limits.max_total_c
        )
        r_trace = w14_intermediate_runtime_partial_reasons(
            candidate_count=len(candidates),
            c_node_count=len(c_nodes),
            cap_exhausted=cap_hit,
        )
        status, explicit_results = self._finish_from_candidates(
            req=req,
            request_id=request_id,
            qid_log=qid_log,
            project_root=root,
            namespace=nspace,
            goal=goal,
            candidates=candidates,
            exhausted=cap_hit,
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
        ms2["partial"] = status != "complete"
        ms2["w14_runtime"] = {
            "selected_b": len(selected_b),
            "c_total": len(c_nodes),
            "c_summarized": len(summarized_c),
            "b_summarized": len(summarized_b),
            "candidate_results": len(candidates),
            "max_turns": limits.max_turns,
            "max_selected_b": limits.max_selected_b,
            "max_c_per_b": limits.max_c_per_b,
            "max_total_c": limits.max_total_c,
        }
        dsum = str(
            plan_obj.get("decision_summary", "")
            or "W14: промежуточная команда; нужны следующие runtime-шаги",
        )[: limits.max_decision_chars]
        rns = str(
            plan_obj.get("recommended_next_step", "")
            or (
                "Продолжить AgentMemory query со следующей партией файлов"
                if status != "complete"
                else ""
            ),
        )[: limits.max_decision_chars]
        _pt_cmd = str(plan_obj.get("command", "") or "").strip() or (
            AgentMemoryCommandName.PLAN_TRAVERSAL.value
        )
        _pt_cid = str(plan_obj.get("command_id", "") or "").strip() or (
            f"{qid_log}:plan_traversal"
        )
        _slice_n = [
            str(x) for x in (ms2.get("node_ids") or []) if str(x).strip()
        ]
        _end_from_results = [
            str(r.get("node_id", "") or "")
            for r in explicit_results
            if r.get("node_id")
        ]
        _hl_ends = _end_from_results or _slice_n
        _w14_hl = W14GraphHighlightPathBuilder.union_to_ends(
            store, nspace, _hl_ends
        )
        _gh_def2: W14DeferredGraphHighlight | None = None
        if _w14_hl.node_ids or _w14_hl.edge_ids:
            _gh_def2 = W14DeferredGraphHighlight(
                request_id=request_id,
                namespace=nspace,
                query_id=qid_log,
                w14_command=_pt_cmd,
                w14_command_id=_pt_cid,
                node_ids=tuple(_w14_hl.node_ids),
                edge_ids=tuple(_w14_hl.edge_ids),
                reason=str(dsum)[:256],
            )
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="w14_intermediate_slice",
            next_state="terminal",
            action_kind=_pt_cmd,
            query_id=qid_log,
            counters={"w14_intermediate_terminal": 1},
        )
        return AgentMemoryQueryPipelineResult(
            memory_slice=ms2,
            partial=status != "complete",
            decision_summary=dsum,
            recommended_next_step=rns,
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
            am_v1_explicit_results=explicit_results,
            am_v1_status=status,
            w14_graph_highlight_deferred=_gh_def2,
            runtime_partial_reasons=r_trace,
        )

    def _select_b_paths_for_w14(
        self,
        *,
        root: Path,
        goal: str,
        plan_obj: Mapping[str, Any],
        explicit_paths: Sequence[str],
        limits: W14RuntimeLimits,
        memory_init: bool,
    ) -> list[str]:
        selected: list[str] = []
        for raw in explicit_paths:
            rel = _norm_rel_path(str(raw))
            if rel and (root / rel).resolve().is_file():
                selected.append(rel)
        payload = plan_obj.get("payload")
        actions = (
            payload.get("actions", []) if isinstance(payload, dict) else []
        )
        if isinstance(actions, list):
            for item in actions:
                if not isinstance(item, dict):
                    continue
                rel = _norm_rel_path(str(item.get("path", "") or ""))
                if rel and rel != "." and (root / rel).resolve().is_file():
                    selected.append(rel)
        if not selected:
            use_walk = memory_init or _looks_like_full_repo_goal(goal)
            if use_walk:
                max_b = limits.max_selected_b
                selected.extend(
                    self._walk_project_files(root, limit=max_b),
                )
            else:
                selected.extend(self._first_level_files(root))
        out: list[str] = []
        for rel in selected:
            if rel and rel not in out:
                out.append(rel)
            if len(out) >= limits.max_selected_b:
                break
        return out

    @staticmethod
    def _walk_project_files(root: Path, *, limit: int) -> list[str]:
        ignore = {
            ".git",
            ".hg",
            ".svn",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "dist",
            "build",
            ".pytest_cache",
            ".mypy_cache",
        }
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignore]
            rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
            if rel_dir == ".":
                rel_dir = ""
            for filename in sorted(filenames):
                if filename.startswith(".") and filename != ".gitignore":
                    continue
                rel = f"{rel_dir}/{filename}" if rel_dir else filename
                out.append(rel)
                if len(out) >= limit:
                    return out
        return out

    @staticmethod
    def _first_level_files(root: Path) -> list[str]:
        out: list[str] = []
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name)
        except OSError:
            return out
        for p in entries:
            if p.is_file() and not p.name.startswith("."):
                out.append(p.name)
        return out

    def _materialize_b_paths(
        self,
        *,
        store: SqlitePagStore,
        namespace: str,
        root: Path,
        rel_paths: Sequence[str],
    ) -> None:
        write = PagGraphWriteService(store)
        a_id = f"A:{namespace}"
        write.upsert_node(
            namespace=namespace,
            node_id=a_id,
            level="A",
            kind="project",
            path=".",
            title=root.name,
            summary="",
            attrs={"namespace": namespace, "repo_path": str(root)},
            fingerprint=str(root),
            staleness_state="fresh",
        )
        dirs: set[str] = set()
        for rel in rel_paths:
            parent = Path(rel).parent.as_posix()
            while parent and parent != ".":
                dirs.add(parent)
                parent = Path(parent).parent.as_posix()
        for d in sorted(dirs):
            b_id = _b_node_id(d)
            write.upsert_node(
                namespace=namespace,
                node_id=b_id,
                level="B",
                kind="dir",
                path=d,
                title=Path(d).name,
                summary="Directory",
                attrs={"child_count": 0},
                fingerprint="dir",
                staleness_state="fresh",
            )
            parent = Path(d).parent.as_posix()
            from_id = a_id if parent == "." else _b_node_id(parent)
            write.upsert_edge(
                namespace=namespace,
                edge_id=_edge_id("containment", "contains", from_id, b_id),
                edge_class="containment",
                edge_type="contains",
                from_node_id=from_id,
                to_node_id=b_id,
            )
        for rel in rel_paths:
            b_id = _b_node_id(rel)
            parent = Path(rel).parent.as_posix()
            from_id = a_id if parent == "." else _b_node_id(parent)
            write.upsert_edge(
                namespace=namespace,
                edge_id=_edge_id("containment", "contains", from_id, b_id),
                edge_class="containment",
                edge_type="contains",
                from_node_id=from_id,
                to_node_id=b_id,
            )

    @staticmethod
    def _c_nodes_for_b_paths(
        *,
        store: SqlitePagStore,
        namespace: str,
        paths: Sequence[str],
        limits: W14RuntimeLimits,
    ) -> list[Any]:
        out: list[Any] = []
        for rel in paths:
            nodes = store.list_nodes_for_path(
                namespace=namespace,
                path=rel,
                level="C",
                limit=limits.max_c_per_b,
            )
            out.extend(nodes[: limits.max_c_per_b])
            if len(out) >= limits.max_total_c:
                return out[: limits.max_total_c]
        return out

    def _complete_w14_subcommand(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        phase: str,
        raw_input: str,
    ) -> str:
        c_req = self._policy.apply_chat_request(
            ChatRequest(
                messages=(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=(
                            "Ты выполняешь команду AgentMemory. Верни только "
                            "JSON agent_memory_command_output.v1 без markdown."
                        ),
                    ),
                    ChatMessage(role=MessageRole.USER, content=raw_input),
                ),
                model="mock-memory",
                temperature=0.0,
                max_tokens=self._policy.extractor_max_output_tokens,
                stream=False,
            ),
            phase="extractor",
            model_override=self._policy.model or "mock-memory",
        )
        _memory_pipeline_coop_check()
        resp = self._prov.complete(c_req)
        self._w.log_memory_llm_verbose(  # noqa: SLF001
            req,
            request_id,
            phase,
            c_req,
            resp,
            None,
        )
        return "".join(resp.text_parts).strip()

    def _summarize_c_nodes(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        qid_log: str,
        svc: AgentMemorySummaryService,
        namespace: str,
        root: Path,
        c_nodes: Sequence[Any],
        goal: str,
        limits: W14RuntimeLimits,
    ) -> list[Any]:
        out: list[Any] = []
        lim = W14CommandLimits(
            max_summary_chars=limits.max_summary_chars,
            max_claims=4,
        )
        for node in c_nodes:
            attrs = node.attrs if isinstance(node.attrs, dict) else {}
            if str(attrs.get("summary_fingerprint", "") or "").strip():
                out.append(node)
                continue
            span = self._span_from_c_attrs(attrs)
            if span is None:
                continue
            text = self._read_lines(root / node.path, span[0], span[1])
            c_input = SummarizeCNodeInputV1(
                c_node_id=node.node_id,
                path=node.path,
                semantic_kind=str(attrs.get("semantic_kind") or node.kind),
                text=text[:12_000],
                locator=SummarizeCLocator(
                    start_line=span[0],
                    end_line=span[1],
                    symbol=str(attrs.get("symbol_key") or node.title),
                ),
            )
            _sc_cid = f"{qid_log}:summarize_c:{len(out) + 1}"
            try:
                svc.summarize_c_call_llm(
                    namespace=namespace,
                    c_input=c_input,
                    user_subgoal=goal,
                    limits=lim,
                    command_id=_sc_cid,
                    query_id=qid_log,
                    complete=lambda raw, phase="summarize_c": (
                        self._complete_w14_subcommand(
                            req=req,
                            request_id=request_id,
                            phase=phase,
                            raw_input=raw,
                        )
                    ),
                )
            except Exception:  # noqa: BLE001
                pass
            refreshed = svc.store.fetch_node(
                namespace=namespace,
                node_id=node.node_id,
            )
            if refreshed is not None:
                out.append(refreshed)
        return out

    def _summarize_b_nodes(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        qid_log: str,
        svc: AgentMemorySummaryService,
        namespace: str,
        paths: Sequence[str],
        goal: str,
        limits: W14RuntimeLimits,
    ) -> list[Any]:
        out: list[Any] = []
        lim = W14CommandLimits(
            max_summary_chars=limits.max_summary_chars,
            max_claims=4,
            max_children=limits.max_c_per_b,
        )
        for rel in paths:
            b_id = _b_node_id(rel)
            b_node = svc.store.fetch_node(namespace=namespace, node_id=b_id)
            if b_node is None:
                continue
            children = svc.store.list_nodes_for_path(
                namespace=namespace,
                path=rel,
                level="C",
                limit=limits.max_c_per_b,
            )
            if not children:
                continue
            fresh = [
                n
                for n in children
                if str((n.attrs or {}).get("summary_fingerprint", "")).strip()
            ]
            coverage = len(fresh) / max(1, len(children))
            if coverage < limits.min_child_summary_coverage:
                continue
            _sb_cid = f"{qid_log}:summarize_b:{len(out) + 1}"
            try:
                svc.summarize_b_call_llm(
                    namespace=namespace,
                    b_node_id=b_id,
                    path=rel,
                    kind=b_node.kind,
                    child_nodes=fresh,
                    user_subgoal=goal,
                    limits=lim,
                    command_id=_sb_cid,
                    query_id=qid_log,
                    complete=lambda raw, phase="summarize_b": (
                        self._complete_w14_subcommand(
                            req=req,
                            request_id=request_id,
                            phase=phase,
                            raw_input=raw,
                        )
                    ),
                )
            except Exception:  # noqa: BLE001
                pass
            refreshed = svc.store.fetch_node(namespace=namespace, node_id=b_id)
            if refreshed is not None:
                out.append(refreshed)
        return out

    @staticmethod
    def _candidate_results_from_c_nodes(
        nodes: Sequence[Any],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in nodes:
            attrs = n.attrs if isinstance(n.attrs, dict) else {}
            if not str(attrs.get("summary_fingerprint", "") or "").strip():
                continue
            out.append(
                {
                    "kind": "c_summary",
                    "path": n.path,
                    "node_id": n.node_id,
                    "summary": n.summary,
                    "read_lines": [],
                    "reason": "w14_runtime_candidate",
                },
            )
        return out

    def _finish_from_candidates(
        self,
        *,
        req: RuntimeRequestEnvelope,
        request_id: str,
        qid_log: str,
        project_root: Path,
        namespace: str,
        goal: str,
        candidates: list[dict[str, Any]],
        exhausted: bool,
    ) -> tuple[str, list[dict[str, Any]]]:
        selected = candidates[:]
        if candidates:
            payload = {
                "finish": True,
                "status": "partial" if exhausted else "complete",
                "selected_results": [
                    {
                        "kind": c["kind"],
                        "path": c["path"],
                        "node_id": c["node_id"],
                        "reason": c["reason"],
                    }
                    for c in candidates
                ],
                "decision_summary": "w14 runtime collected evidence",
                "recommended_next_step": (
                    "continue with next file batch" if exhausted else ""
                ),
            }
            env = {
                "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
                "command": AgentMemoryCommandName.FINISH_DECISION.value,
                "command_id": f"{qid_log}:finish_decision",
                "status": "ok",
                "payload": payload,
                "decision_summary": "finish",
                "violations": [],
            }
            try:
                raw = self._complete_w14_subcommand(
                    req=req,
                    request_id=request_id,
                    phase="finish_decision",
                    raw_input=_json_dumps(env),
                )
                parsed = parse_memory_query_pipeline_llm_text_result(raw).obj
                pld = parsed.get("payload", {})
                if isinstance(pld, dict):
                    raw_sel = pld.get("selected_results", [])
                    if isinstance(raw_sel, list):
                        selected = [x for x in raw_sel if isinstance(x, dict)]
                    st = str(pld.get("status", "") or "")
                    status = (
                        st if st in ("complete", "partial", "blocked") else ""
                    )
                    if status:
                        assembled_status, assembled = self._assemble_selected(
                            project_root=project_root,
                            namespace=namespace,
                            selected=selected,
                        )
                        return assembled_status or status, assembled
            except Exception:  # noqa: BLE001
                pass
        status = "partial" if exhausted or not selected else "complete"
        _, assembled = self._assemble_selected(
            project_root=project_root,
            namespace=namespace,
            selected=selected,
        )
        return status, assembled

    @staticmethod
    def _assemble_selected(
        *,
        project_root: Path,
        namespace: str,
        selected: Sequence[Mapping[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        store = SqlitePagStore(PagRuntimeConfig.from_env().db_path)
        asm = FinishDecisionResultAssembler(
            project_root=project_root,
            namespace=namespace,
            store=store,
        )
        results, rejects = asm.assemble_finish_decision_results(selected)
        status = "partial" if rejects else "complete"
        if not results:
            status = "partial"
        return status, results

    @staticmethod
    def _span_from_c_attrs(attrs: Mapping[str, Any]) -> tuple[int, int] | None:
        try:
            sl = int(attrs.get("start_line", 0) or 0)
            el = int(attrs.get("end_line", 0) or 0)
        except (TypeError, ValueError):
            return None
        if sl < 1 or el < sl:
            return None
        return sl, el

    @staticmethod
    def _read_lines(path: Path, start_line: int, end_line: int) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
        except OSError:
            return ""
        lo = max(0, start_line - 1)
        hi = min(len(lines), end_line)
        return "\n".join(lines[lo:hi])

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
        self._w.log_memory_w14_runtime_step(  # noqa: SLF001
            req,
            request_id,
            step_id=w14_next_step_id(),
            state="w14_command_rejected",
            next_state="terminal",
            action_kind="w14_parse_rejected",
            query_id=qid_log,
            counters={"w14_rejected_terminal": 1},
        )
        return AgentMemoryQueryPipelineResult(
            memory_slice={
                "kind": "memory_slice",
                "schema": "memory.slice.v1",
                "level": level,
                "node_ids": [],
                "edge_ids": [],
                "injected_text": "",
                "estimated_tokens": 0,
                "staleness": "w14_command_rejected",
                "reason": "w14_command_output_invalid",
                "partial": True,
                "w14_contract_failure": True,
            },
            partial=True,
            decision_summary=f"w14 command output invalid: {reason}"[:1_200],
            recommended_next_step="fix_memory_llm_json",
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
            runtime_partial_reasons=(REASON_W14_PARSE_FAILED,),
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
        qid_log: str = "",
        w14_next_step_id: Callable[[], str] | None = None,
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
        if w14_next_step_id is not None and str(qid_log or "").strip():
            self._w.log_memory_w14_runtime_step(  # noqa: SLF001
                req,
                request_id,
                step_id=w14_next_step_id(),
                state="llm_await",
                next_state="terminal",
                action_kind="w14_invalid_json",
                query_id=qid_log,
                counters={"w14_invalid_json_terminal": 1},
            )
        return AgentMemoryQueryPipelineResult(
            memory_slice={
                "kind": "memory_slice",
                "schema": "memory.slice.v1",
                "level": level,
                "node_ids": [],
                "edge_ids": [],
                "injected_text": "",
                "estimated_tokens": 0,
                "staleness": "w14_invalid_json",
                "reason": "w14_invalid_json",
                "partial": True,
                "w14_contract_failure": True,
            },
            partial=True,
            decision_summary="invalid json",
            recommended_next_step="fix_memory_llm_json",
            created_node_ids=[],
            created_edge_ids=[],
            used_llm=True,
            llm_disabled_fallback=False,
            runtime_partial_reasons=(REASON_W14_PARSE_FAILED,),
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
