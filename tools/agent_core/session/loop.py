"""Явный session loop: провайдер → tool round → бюджет/compaction/shortlist."""

from __future__ import annotations

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
from agent_core.session.shortlist import apply_keyword_shortlist
from agent_core.session.state import SessionState
from agent_core.session.tool_bridge import tool_definitions_from_registry
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
    shortlist_keywords: frozenset[str] | None = None
    use_stream: bool = False
    suppress_tools_after_write_file: bool = field(
        default_factory=_default_suppress_tools_after_write_file,
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
        self._registry = registry
        perm = permission_engine or PermissionEngine()
        self._executor = ToolExecutor(registry, perm)

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

    def _prepare_context(
        self,
        messages: list[ChatMessage],
        settings: SessionSettings,
    ) -> list[ChatMessage]:
        compacted = compact_messages(
            messages,
            tail_max=settings.compaction_tail_messages,
            max_tool_chars=settings.compaction_max_tool_chars,
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
        ctx_base = self._prepare_context(messages, settings)
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

    def _append_tool_results(
        self,
        messages: list[ChatMessage],
        tool_calls: Sequence[Any],
        results: Sequence[Any],
    ) -> None:
        for tc, tr in zip(tool_calls, results, strict=True):
            body = tr.content if tr.error is None else f"error:{tr.error}"
            messages.append(
                ChatMessage(
                    role=MessageRole.TOOL,
                    content=body,
                    tool_call_id=tc.call_id,
                )
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
                                "arguments_json": inv.arguments_json,
                            },
                            diag_sink,
                            event_sink,
                        )
                    results = self._executor.execute_serial(
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
                self._maybe_set_suppress_after_write_file(
                    invs,
                    results,
                    settings,
                    suppress_next,
                )
                self._append_tool_results(messages, ast.tool_calls, results)
                continue

            ctx = self._prepare_context(messages, settings)
            tools_defs = tool_definitions_from_registry(self._registry)
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
                                "arguments_json": inv.arguments_json,
                            },
                            diag_sink,
                            event_sink,
                        )
                    results = self._executor.execute_serial(
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
                self._maybe_set_suppress_after_write_file(
                    invs,
                    results,
                    settings,
                    suppress_next,
                )
                self._append_tool_results(messages, resp.tool_calls, results)
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
