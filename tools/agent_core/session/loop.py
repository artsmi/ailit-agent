"""Явный session loop: провайдер → tool round → бюджет/compaction/shortlist."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event
from typing import Any, Sequence

from agent_core.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    StreamDone,
    StreamTextDelta,
    ToolChoice,
    ToolDefinition,
)
from agent_core.providers.protocol import ChatProvider
from agent_core.session.budget import BudgetGovernance
from agent_core.session.compaction import compact_messages
from agent_core.session.context_pager import (
    READ_CONTEXT_PAGE_NAME,
    ContextPageStore,
    ContextPagerConfig,
    StoredPage,
    build_context_pager_read_registry,
    build_preview,
    build_tool_message_for_page,
    context_pager_config_from_env,
    locator_from_invocation,
    stable_page_id,
    tool_to_source_key,
)
from agent_core.session.post_compact_restore import RecentFileReadStore
from agent_core.session.shortlist import apply_keyword_shortlist
from agent_core.session.tool_output_budget import (
    ToolOutputBudgetConfig,
    apply_tool_output_batch_budget,
    tool_output_budget_config_from_env,
)
from agent_core.session.tool_output_prune import (
    ToolOutputPruneConfig,
    apply_tool_output_prune,
    tool_output_prune_config_from_env,
)
from agent_core.session.state import SessionState
from agent_core.session.tool_exposure import tool_definitions_for_settings
from agent_core.session.tool_choice_policy import (
    default_tool_choice_policy,
    last_batch_had_successful_write_file,
)
from agent_core.session.bash_tool_events import emit_bash_shell_telemetry
from agent_core.session.event_contract import SessionEvent, SessionEventSink
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.executor import (
    ApprovalPending,
    ToolExecutor,
    ToolInvocation,
    ToolRejected,
    ToolRunResult,
)
from agent_core.tool_runtime.permission import PermissionEngine
from agent_core.normalization.usage_fields import usage_to_diag_dict
from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.transport.errors import TransportHttpError


def _default_suppress_tools_after_write_file() -> bool:
    """Legacy: один запрос без tools после write_file (вкл. через env)."""
    raw = (
        os.environ.get("AILIT_SUPPRESS_TOOLS_AFTER_WRITE", "")
        .strip()
        .lower()
    )
    return raw in ("1", "true", "yes", "on")


def _tool_call_finished_payload(
    inv: ToolInvocation,
    res: ToolRunResult,
) -> dict[str, Any]:
    """Полезная нагрузка для UI/логов по завершении инструмента."""
    pl: dict[str, Any] = {
        "tool": inv.tool_name,
        "call_id": inv.call_id,
        "ok": res.error is None,
    }
    ext = res.extras
    if ext:
        for key in ("relative_path", "file_change_kind"):
            if key in ext:
                pl[key] = ext[key]
    return pl


def _incomplete_tool_followup(messages: Sequence[ChatMessage]) -> bool:
    """True если последний assistant с tool_calls ещё без всех TOOL ответов."""
    last_ast: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.role is MessageRole.ASSISTANT and m.tool_calls:
            last_ast = i
            break
    if last_ast is None:
        return False
    ast = messages[last_ast]
    assert ast.tool_calls is not None
    needed = {tc.call_id for tc in ast.tool_calls}
    got: set[str] = set()
    for j in range(last_ast + 1, len(messages)):
        tm = messages[j]
        if tm.role is MessageRole.TOOL and tm.tool_call_id:
            got.add(tm.tool_call_id)
    return not needed <= got


@dataclass(frozen=True, slots=True)
class SessionSettings:
    """Параметры одного прогона session loop."""

    model: str = "mock"
    temperature: float = 0.0
    max_tokens: int | None = None
    max_turns: int = 10_000
    max_context_units: int | None = None
    max_total_tokens: int | None = None
    compaction_tail_messages: int = 40
    compaction_max_tool_chars: int = 2000
    post_compact_restore_enabled: bool = True
    post_compact_restore_max_files: int = 5
    post_compact_restore_max_chars_per_file: int = 2500
    post_compact_restore_max_total_chars: int = 9000
    tool_exposure: str = "full"
    shortlist_keywords: frozenset[str] | None = None
    use_stream: bool = False
    suppress_tools_after_write_file: bool = field(
        default_factory=_default_suppress_tools_after_write_file,
    )
    context_pager: ContextPagerConfig = field(
        default_factory=context_pager_config_from_env,
    )
    tool_output_budget: ToolOutputBudgetConfig = field(
        default_factory=tool_output_budget_config_from_env,
    )
    tool_output_prune: ToolOutputPruneConfig = field(
        default_factory=tool_output_prune_config_from_env,
    )


def _effective_max_turns(settings: SessionSettings) -> int:
    """Минимум из настроек и опционального AILIT_AGENT_HARD_CAP."""
    raw = os.environ.get("AILIT_AGENT_HARD_CAP", "1000000")
    try:
        hard = int(raw)
    except ValueError:
        hard = 1_000_000
    hard = max(1, hard)
    configured = max(1, settings.max_turns)
    return min(configured, hard)


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """Результат прогона или пауза на approval."""

    state: SessionState
    messages: tuple[ChatMessage, ...]
    events: tuple[dict[str, Any], ...]
    reason: str | None = None


class SessionRunner:
    """Готовит запросы к провайдеру, исполняет tools, ведёт бюджет."""

    def __init__(
        self,
        provider: ChatProvider,
        registry: ToolRegistry,
        *,
        permission_engine: PermissionEngine | None = None,
    ) -> None:
        """Связать провайдер и реестр инструментов."""
        self._provider = provider
        self._base_registry = registry
        self._context_page_store = ContextPageStore()
        self._recent_reads = RecentFileReadStore()
        perm = permission_engine or PermissionEngine()
        self._perm = perm

    def _tool_registry_for_run(
        self,
        settings: SessionSettings,
    ) -> ToolRegistry:
        """Реестр на прогон: базовый + read_context_page если pager вкл."""
        reg = self._base_registry
        if (
            settings.context_pager.enabled
            or settings.tool_output_budget.enabled
        ):
            return reg.merge(
                build_context_pager_read_registry(self._context_page_store),
            )
        return reg

    def _emit(
        self,
        events: list[dict[str, Any]],
        event_type: str,
        payload: dict[str, Any],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        row = {"event_type": event_type, **payload}
        events.append(row)
        if event_sink is not None:
            event_sink(SessionEvent(type=event_type, payload=dict(payload)))
        if diag_sink is not None:
            enriched: dict[str, Any] = {
                "contract": "ailit_session_diag_v1",
                "event_type": event_type,
                "ts": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                **payload,
            }
            diag_sink(enriched)

    def _safe_arguments_json(
        self,
        *,
        tool_name: str,
        arguments_json: str,
    ) -> str:
        """Redact potentially sensitive tool arguments for diagnostics."""
        name = str(tool_name or "")
        if name.startswith("kb_"):
            return "<redacted>"
        return arguments_json

    def _emit_memory_access(
        self,
        *,
        tool_name: str,
        call_id: str,
        arguments_json: str,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """Emit a safe, non-content memory access event (H4.2)."""
        name = str(tool_name or "")
        if not name.startswith("kb_"):
            return
        try:
            raw = json.loads(arguments_json) if arguments_json.strip() else {}
        except json.JSONDecodeError:
            raw = {}
        data: dict[str, Any] = {}
        if isinstance(raw, dict):
            for k in ("scope", "namespace", "top_k", "id"):
                v = raw.get(k)
                if v is None:
                    continue
                if isinstance(v, (str, int)):
                    data[k] = v
            q = raw.get("query")
            if isinstance(q, str):
                data["query_len"] = len(q)
            body = raw.get("body")
            if isinstance(body, str):
                data["body_len"] = len(body)
        self._emit(
            events,
            "memory.access",
            {
                "tool": name,
                "call_id": str(call_id),
                **data,
            },
            diag_sink,
            event_sink,
        )

    def _prepare_context(
        self,
        messages: list[ChatMessage],
        settings: SessionSettings,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> list[ChatMessage]:
        compacted = compact_messages(
            messages,
            tail_max=settings.compaction_tail_messages,
            max_tool_chars=settings.compaction_max_tool_chars,
        )
        if (
            settings.post_compact_restore_enabled
            and len(messages) > settings.compaction_tail_messages
        ):
            already = "\n".join(m.content for m in compacted[-8:]).strip()
            restore_msg, plan = self._recent_reads.build_restore_message(
                already_in_context=already,
                max_files=settings.post_compact_restore_max_files,
                max_chars_per_file=(
                    settings.post_compact_restore_max_chars_per_file
                ),
                max_total_chars=settings.post_compact_restore_max_total_chars,
            )
            if restore_msg is not None and plan.restored:
                compacted.append(restore_msg)
                self._emit(
                    events,
                    "compaction.restore_files",
                    {
                        "restored_files": len(plan.restored),
                        "injected_chars": plan.injected_chars,
                    },
                    diag_sink,
                    event_sink,
                )
        if settings.shortlist_keywords:
            return apply_keyword_shortlist(
                compacted,
                settings.shortlist_keywords,
            )
        return compacted

    def _invoke_model_request(
        self,
        *,
        context: list[ChatMessage],
        settings: SessionSettings,
        tool_choice: ToolChoice | None,
        tools_defs: tuple[ToolDefinition, ...],
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
        request_meta: dict[str, Any],
        cancel: Event | None,
    ) -> NormalizedChatResponse:
        """Вызов провайдера: stream или complete; эмит событий диагностики."""
        self._emit(
            events,
            "model.request",
            {
                "context_messages": len(context),
                "tools_count": len(tools_defs),
                **request_meta,
            },
            diag_sink,
            event_sink,
        )
        req = ChatRequest(
            messages=context,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            tools=tools_defs,
            tool_choice=tool_choice,
            stream=settings.use_stream,
        )
        if settings.use_stream:
            text_parts: list[str] = []
            stream_events = self._provider.stream(req)
            for ev in stream_events:
                if cancel is not None and cancel.is_set():
                    self._emit(
                        events,
                        "session.cancelled",
                        {"phase": "model_stream"},
                        diag_sink,
                        event_sink,
                    )
                    raise RuntimeError("cancelled")
                if isinstance(ev, StreamTextDelta):
                    text_parts.append(ev.text)
                    self._emit(
                        events,
                        "assistant.delta",
                        {"text": ev.text},
                        diag_sink,
                        event_sink,
                    )
                if isinstance(ev, StreamDone):
                    return ev.response
            msg = "stream ended without StreamDone"
            raise ValueError(msg)
        if cancel is not None and cancel.is_set():
            self._emit(
                events,
                "session.cancelled",
                {"phase": "model_complete"},
                diag_sink,
                event_sink,
            )
            raise RuntimeError("cancelled")
        return self._provider.complete(req)

    def _finalize_after_turn_cap(
        self,
        messages: list[ChatMessage],
        settings: SessionSettings,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
        bud: BudgetGovernance,
    ) -> SessionOutcome:
        """После исчерпания лимита ходов — один text-only запрос без tools."""
        self._emit(
            events,
            "session.cap_hit",
            {"policy": "finalize_text_only"},
            diag_sink,
            event_sink,
        )
        ctx_base = self._prepare_context(
            messages,
            settings,
            events,
            diag_sink,
            event_sink,
        )
        cap_msg = (
            "The maximum number of agent steps for this session was reached. "
            "Reply in natural language only: brief summary of progress, "
            "what is still pending if anything, and how the user may "
            "continue. Do not use tools."
        )
        finalize_prompt = ChatMessage(
            role=MessageRole.SYSTEM,
            content=cap_msg,
        )
        ctx_final = list(ctx_base) + [finalize_prompt]
        tools_empty: tuple[ToolDefinition, ...] = ()
        try:
            resp = self._invoke_model_request(
                context=ctx_final,
                settings=settings,
                tool_choice=None,
                tools_defs=tools_empty,
                events=events,
                diag_sink=diag_sink,
                event_sink=event_sink,
                request_meta={
                    "tool_choice_mode": "none_finalize",
                    "policy_reason": "session_turn_cap",
                },
                cancel=None,
            )
        except Exception as exc:  # noqa: BLE001
            err_reason = f"{type(exc).__name__}:{exc}"
            self._emit(
                events,
                "model.error",
                {"reason": err_reason, "phase": "cap_finalize"},
                diag_sink,
                event_sink,
            )
            messages.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=(
                        "Достигнут лимит шагов агента в этой сессии; "
                        "не удалось получить итоговое резюме от модели. "
                        "Продолжите новым сообщением или проверьте "
                        "настройки провайдера."
                    ),
                )
            )
            return SessionOutcome(
                state=SessionState.FINISHED,
                messages=tuple(messages),
                events=tuple(events),
                reason="cap_finalize_failed",
            )

        bud.record_usage(resp.usage)
        fin = resp.finish_reason.value
        resp_tool_names = [tc.tool_name for tc in resp.tool_calls]
        self._emit(
            events,
            "model.response",
            {
                "finish": fin,
                "tool_calls_count": len(resp.tool_calls),
                "tool_names": resp_tool_names,
                "usage": usage_to_diag_dict(resp.usage),
                "usage_session_totals": bud.diag_totals_dict(),
                "phase": "cap_finalize",
            },
            diag_sink,
            event_sink,
        )
        over = bud.check_exceeded(messages)
        if over is not None:
            self._emit(
                events,
                "session.budget",
                {"reason": over},
                diag_sink,
                event_sink,
            )
            return SessionOutcome(
                state=SessionState.BUDGET_EXCEEDED,
                messages=tuple(messages),
                events=tuple(events),
                reason=over,
            )

        text = "".join(resp.text_parts)
        if resp.tool_calls:
            fallback = (
                "Итог: после лимита шагов модель снова запросила инструменты; "
                "их выполнение отключено. Кратко опишите пользователю "
                "состояние задачи текстом."
            )
            text = text or fallback
        messages.append(ChatMessage(role=MessageRole.ASSISTANT, content=text))
        return SessionOutcome(
            state=SessionState.FINISHED,
            messages=tuple(messages),
            events=tuple(events),
            reason=None,
        )

    def _emit_context_pager_page_used(
        self,
        inv: ToolInvocation,
        res: ToolRunResult,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """Событие context.pager.page_used после read_context_page."""
        if res.error is not None:
            return
        if inv.tool_name != READ_CONTEXT_PAGE_NAME:
            return
        try:
            args = (
                json.loads(inv.arguments_json)
                if (inv.arguments_json and inv.arguments_json.strip())
                else {}
            )
        except json.JSONDecodeError:
            return
        if not isinstance(args, dict):
            return
        page_id = str(args.get("page_id", "") or "").strip()
        if not page_id:
            return
        try:
            off = int(args.get("offset_lines", 0) or 0)
        except (TypeError, ValueError):
            off = 0
        try:
            mlines = int(args.get("max_lines", 200) or 200)
        except (TypeError, ValueError):
            mlines = 200
        content = res.content or ""
        returned_lines = len(content.splitlines()) if content else 0
        self._emit(
            events,
            "context.pager.page_used",
            {
                "page_id": page_id,
                "reason": "read_context_page",
                "offset_lines": off,
                "max_lines": mlines,
                "returned_lines": returned_lines,
            },
            diag_sink,
            event_sink,
        )

    def _append_tool_results(
        self,
        messages: list[ChatMessage],
        invs: list[ToolInvocation],
        results: list[ToolRunResult],
        settings: SessionSettings,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """Добавить TOOL: pager → char budget (батч) → сообщения."""
        pcfg = settings.context_pager
        rows: list[tuple[ToolInvocation, ToolRunResult, str]] = []
        for inv, tr in zip(invs, results, strict=True):
            body = tr.content if tr.error is None else f"error:{tr.error}"
            if tr.error is None and inv.tool_name == "read_file":
                self._recent_reads.observe_read_file(
                    arguments_json=inv.arguments_json,
                    tool_output=tr.content or "",
                )
            # Не пагинировать вывод read_context_page: иначе каждый чанк
            # становится новой «страницей» → модель снова вызывает
            # read_context_page(offset=0) → бесконечная цепочка page_id.
            if (
                pcfg.enabled
                and tr.error is None
                and inv.tool_name != READ_CONTEXT_PAGE_NAME
                and len(body) >= pcfg.min_body_chars
            ):
                page_id = stable_page_id(
                    content=body,
                    call_id=inv.call_id,
                    tool_name=inv.tool_name,
                )
                source = tool_to_source_key(inv.tool_name)
                loc = locator_from_invocation(
                    inv.tool_name,
                    inv.arguments_json,
                )
                preview = build_preview(
                    body,
                    max_lines=pcfg.preview_max_lines,
                    max_chars=pcfg.preview_max_chars,
                )
                self._context_page_store.put(
                    page_id,
                    StoredPage(
                        full_text=body,
                        source=source,
                        tool_name=inv.tool_name,
                        locator=loc,
                    ),
                )
                b_total = len(body.encode("utf-8"))
                b_prev = len(preview.encode("utf-8"))
                preview_line_count = len(preview.splitlines())
                self._emit(
                    events,
                    "context.pager.page_created",
                    {
                        "page_id": page_id,
                        "source": source,
                        "tool_name": inv.tool_name,
                        "locator": loc,
                        "bytes_total": b_total,
                        "bytes_preview": b_prev,
                        "preview_lines": preview_line_count,
                    },
                    diag_sink,
                    event_sink,
                )
                body = build_tool_message_for_page(
                    page_id=page_id,
                    source=source,
                    locator=loc,
                    full_text=tr.content,
                    preview=preview,
                    config=pcfg,
                )
            rows.append((inv, tr, body))

        bcfg = settings.tool_output_budget
        bodies, t0, t1, nrep, extra_pager = apply_tool_output_batch_budget(
            rows,
            budget=bcfg,
            page_store=self._context_page_store,
        )
        for pev in extra_pager:
            self._emit(
                events,
                "context.pager.page_created",
                pev,
                diag_sink,
                event_sink,
            )
        if bcfg.enabled and nrep > 0:
            page_ids = [
                e.get("page_id")
                for e in extra_pager
                if e.get("page_id")
            ]
            self._emit(
                events,
                "tool.output_budget.enforced",
                {
                    "limit": bcfg.max_total_chars,
                    "total_before": t0,
                    "total_after": t1,
                    "replaced_count": nrep,
                    "page_id": [x for x in page_ids if isinstance(x, str)],
                },
                diag_sink,
                event_sink,
            )
        for inv, body in zip(
            (r[0] for r in rows), bodies, strict=True,
        ):
            messages.append(
                ChatMessage(
                    role=MessageRole.TOOL,
                    content=body,
                    tool_call_id=inv.call_id,
                ),
            )

    def _maybe_set_suppress_after_write_file(
        self,
        invs: list[ToolInvocation],
        results: list[ToolRunResult],
        settings: SessionSettings,
        suppress_next: list[bool],
    ) -> None:
        """Выставить флаг подавления tools после успешного write_file."""
        if not settings.suppress_tools_after_write_file:
            return
        if last_batch_had_successful_write_file(invs, results):
            suppress_next[0] = True

    def run(
        self,
        messages: list[ChatMessage],
        approvals: ApprovalSession,
        settings: SessionSettings,
        *,
        budget: BudgetGovernance | None = None,
        diag_sink: Callable[[dict[str, Any]], None] | None = None,
        event_sink: SessionEventSink | None = None,
        cancel: Event | None = None,
    ) -> SessionOutcome:
        """Цикл до FINISHED, бюджета, ошибки или паузы на approval."""
        events: list[dict[str, Any]] = []
        if (
            settings.context_pager.enabled
            or settings.tool_output_budget.enabled
        ):
            self._context_page_store.clear()
        active_reg = self._tool_registry_for_run(settings)
        executor = ToolExecutor(active_reg, self._perm)
        bud = budget or BudgetGovernance(
            max_total_tokens=settings.max_total_tokens,
            max_context_units=settings.max_context_units,
        )
        suppress_next: list[bool] = [False]

        for turn in range(_effective_max_turns(settings)):
            if cancel is not None and cancel.is_set():
                self._emit(
                    events,
                    "session.cancelled",
                    {"phase": "turn_loop"},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.ERROR,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason="cancelled",
                )
            self._emit(
                events,
                "session.turn",
                {"index": turn},
                diag_sink,
                event_sink,
            )
            if settings.tool_output_prune.enabled:
                pr = apply_tool_output_prune(
                    messages,
                    settings.tool_output_prune,
                )
                pcount = int(pr.get("pruned_tools_count", 0) or 0)
                if pcount > 0:
                    self._emit(
                        events,
                        "tool.output_prune.applied",
                        {
                            "pruned_tools_count": pcount,
                            "pruned_bytes_estimate": int(
                                pr.get("pruned_bytes_estimate", 0) or 0,
                            ),
                            "protected_tools": pr.get("protected_skipped", []),
                        },
                        diag_sink,
                        event_sink,
                    )
            exc = bud.check_exceeded(messages)
            if exc is not None:
                self._emit(
                    events,
                    "session.budget",
                    {"reason": exc},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.BUDGET_EXCEEDED,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason=exc,
                )

            if _incomplete_tool_followup(messages):
                ast_idx = next(
                    i
                    for i in range(len(messages) - 1, -1, -1)
                    if messages[i].role is MessageRole.ASSISTANT
                    and messages[i].tool_calls
                )
                ast = messages[ast_idx]
                assert ast.tool_calls is not None
                invs = [
                    ToolInvocation(tc.call_id, tc.tool_name, tc.arguments_json)
                    for tc in ast.tool_calls
                ]
                tool_names = [inv.tool_name for inv in invs]
                self._emit(
                    events,
                    "tool.batch",
                    {"count": len(invs), "tool_names": tool_names},
                    diag_sink,
                    event_sink,
                )
                try:
                    for inv in invs:
                        self._emit(
                            events,
                            "tool.call_started",
                            {
                                "tool": inv.tool_name,
                                "call_id": inv.call_id,
                                "arguments_json": self._safe_arguments_json(
                                    tool_name=inv.tool_name,
                                    arguments_json=inv.arguments_json,
                                ),
                            },
                            diag_sink,
                            event_sink,
                        )
                        self._emit_memory_access(
                            tool_name=inv.tool_name,
                            call_id=inv.call_id,
                            arguments_json=inv.arguments_json,
                            events=events,
                            diag_sink=diag_sink,
                            event_sink=event_sink,
                        )
                    results = executor.execute_serial(
                        invs,
                        approvals,
                        cancel=cancel,
                    )
                except ApprovalPending as exc:
                    self._emit(
                        events,
                        "session.waiting_approval",
                        {"call_id": exc.call_id, "tool": exc.tool_name},
                        diag_sink,
                        event_sink,
                    )
                    return SessionOutcome(
                        state=SessionState.WAITING_APPROVAL,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason="approval_pending",
                    )
                except ToolRejected as exc:
                    return SessionOutcome(
                        state=SessionState.ERROR,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason=f"rejected:{exc.tool_name}",
                    )
                for inv, res in zip(invs, results, strict=True):

                    def _emit_bash_et(et: str, pl: dict[str, Any]) -> None:
                        self._emit(events, et, pl, diag_sink, event_sink)

                    emit_bash_shell_telemetry(_emit_bash_et, inv, res)
                    self._emit(
                        events,
                        "tool.call_finished",
                        _tool_call_finished_payload(inv, res),
                        diag_sink,
                        event_sink,
                    )
                    self._emit_context_pager_page_used(
                        inv, res, events, diag_sink, event_sink
                    )
                self._maybe_set_suppress_after_write_file(
                    invs,
                    results,
                    settings,
                    suppress_next,
                )
                self._append_tool_results(
                    messages,
                    invs,
                    results,
                    settings,
                    events,
                    diag_sink,
                    event_sink,
                )
                continue

            ctx = self._prepare_context(
                messages,
                settings,
                events,
                diag_sink,
                event_sink,
            )
            tools_defs, tex = tool_definitions_for_settings(
                active_reg,
                settings.tool_exposure,
            )
            self._emit(
                events,
                "tool.exposure.applied",
                {
                    "mode": tex.mode,
                    "tools_total": tex.tools_total,
                    "tools_exposed": tex.tools_exposed,
                    "schema_chars": tex.schema_chars,
                },
                diag_sink,
                event_sink,
            )
            st_sup = settings.suppress_tools_after_write_file
            should_use_suppress = suppress_next[0] and st_sup
            if suppress_next[0]:
                suppress_next[0] = False
            decision = default_tool_choice_policy.choose(
                tools_available=bool(tools_defs),
                suppress_next_request=should_use_suppress,
                policy_enabled=settings.suppress_tools_after_write_file,
            )
            try:
                meta = {
                    "tool_choice_mode": decision.tool_choice_mode_effective,
                    "policy_reason": decision.policy_reason,
                }
                resp = self._invoke_model_request(
                    context=ctx,
                    settings=settings,
                    tool_choice=decision.tool_choice,
                    tools_defs=tools_defs,
                    events=events,
                    diag_sink=diag_sink,
                    event_sink=event_sink,
                    request_meta=meta,
                    cancel=cancel,
                )
            except Exception as exc:  # noqa: BLE001
                err_reason = f"{type(exc).__name__}:{exc}"
                extra: dict[str, object] = {}
                if isinstance(exc, TransportHttpError):
                    if exc.status_code is not None:
                        extra["status_code"] = exc.status_code
                    if exc.body_snippet:
                        extra["body_snippet"] = exc.body_snippet
                self._emit(
                    events,
                    "model.error",
                    {"reason": err_reason, **extra},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.ERROR,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason=err_reason,
                )

            bud.record_usage(resp.usage)
            resp_tool_names = [tc.tool_name for tc in resp.tool_calls]
            fin = resp.finish_reason.value
            self._emit(
                events,
                "model.response",
                {
                    "finish": fin,
                    "tool_calls_count": len(resp.tool_calls),
                    "tool_names": resp_tool_names,
                    "usage": usage_to_diag_dict(resp.usage),
                    "usage_session_totals": bud.diag_totals_dict(),
                },
                diag_sink,
                event_sink,
            )
            over = bud.check_exceeded(messages)
            if over is not None:
                self._emit(
                    events,
                    "session.budget",
                    {"reason": over},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.BUDGET_EXCEEDED,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason=over,
                )

            text = "".join(resp.text_parts)
            if resp.tool_calls:
                messages.append(
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=text,
                        tool_calls=tuple(resp.tool_calls),
                    )
                )
                invs = [
                    ToolInvocation(tc.call_id, tc.tool_name, tc.arguments_json)
                    for tc in resp.tool_calls
                ]
                tool_names = [inv.tool_name for inv in invs]
                self._emit(
                    events,
                    "tool.batch",
                    {"count": len(invs), "tool_names": tool_names},
                    diag_sink,
                    event_sink,
                )
                try:
                    for inv in invs:
                        self._emit(
                            events,
                            "tool.call_started",
                            {
                                "tool": inv.tool_name,
                                "call_id": inv.call_id,
                                "arguments_json": self._safe_arguments_json(
                                    tool_name=inv.tool_name,
                                    arguments_json=inv.arguments_json,
                                ),
                            },
                            diag_sink,
                            event_sink,
                        )
                        self._emit_memory_access(
                            tool_name=inv.tool_name,
                            call_id=inv.call_id,
                            arguments_json=inv.arguments_json,
                            events=events,
                            diag_sink=diag_sink,
                            event_sink=event_sink,
                        )
                    results = executor.execute_serial(
                        invs,
                        approvals,
                        cancel=cancel,
                    )
                except ApprovalPending as exc:
                    self._emit(
                        events,
                        "session.waiting_approval",
                        {"call_id": exc.call_id, "tool": exc.tool_name},
                        diag_sink,
                        event_sink,
                    )
                    return SessionOutcome(
                        state=SessionState.WAITING_APPROVAL,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason="approval_pending",
                    )
                except ToolRejected as exc:
                    return SessionOutcome(
                        state=SessionState.ERROR,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason=f"rejected:{exc.tool_name}",
                    )
                for inv, res in zip(invs, results, strict=True):

                    def _emit_bash_et2(et: str, pl: dict[str, Any]) -> None:
                        self._emit(events, et, pl, diag_sink, event_sink)

                    emit_bash_shell_telemetry(_emit_bash_et2, inv, res)
                    self._emit(
                        events,
                        "tool.call_finished",
                        _tool_call_finished_payload(inv, res),
                        diag_sink,
                        event_sink,
                    )
                    self._emit_context_pager_page_used(
                        inv, res, events, diag_sink, event_sink
                    )
                self._maybe_set_suppress_after_write_file(
                    invs,
                    results,
                    settings,
                    suppress_next,
                )
                self._append_tool_results(
                    messages,
                    invs,
                    results,
                    settings,
                    events,
                    diag_sink,
                    event_sink,
                )
                if resp.finish_reason is not FinishReason.TOOL_CALLS:
                    pass
                continue

            messages.append(
                ChatMessage(role=MessageRole.ASSISTANT, content=text),
            )
            return SessionOutcome(
                state=SessionState.FINISHED,
                messages=tuple(messages),
                events=tuple(events),
                reason=None,
            )

        return self._finalize_after_turn_cap(
            messages,
            settings,
            events,
            diag_sink,
            event_sink,
            bud,
        )
