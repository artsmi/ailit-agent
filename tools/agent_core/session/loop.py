"""Явный session loop: провайдер → tool round → бюджет/compaction/shortlist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from agent_core.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    ToolChoice,
)
from agent_core.providers.protocol import ChatProvider
from agent_core.session.budget import BudgetGovernance
from agent_core.session.compaction import compact_messages
from agent_core.session.shortlist import apply_keyword_shortlist
from agent_core.session.state import SessionState
from agent_core.session.stream_reducer import StreamReducer
from agent_core.session.tool_bridge import tool_definitions_from_registry
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.executor import (
    ApprovalPending,
    ToolExecutor,
    ToolInvocation,
    ToolRejected,
)
from agent_core.tool_runtime.permission import PermissionEngine
from agent_core.tool_runtime.registry import ToolRegistry


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
    max_turns: int = 8
    max_context_units: int | None = None
    max_total_tokens: int | None = None
    compaction_tail_messages: int = 40
    compaction_max_tool_chars: int = 2000
    shortlist_keywords: frozenset[str] | None = None
    use_stream: bool = False


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """Результат прогона или пауза на approval."""

    state: SessionState
    messages: tuple[ChatMessage, ...]
    events: tuple[dict[str, Any], ...]
    reason: str | None = None


class SessionRunner:
    """Отделён от провайдера: готовит запросы, исполняет tools, ведёт бюджет."""

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
        self._executor = ToolExecutor(registry, permission_engine or PermissionEngine())

    def _emit(self, events: list[dict[str, Any]], event_type: str, payload: dict[str, Any]) -> None:
        row = {"event_type": event_type, **payload}
        events.append(row)

    def _prepare_context(self, messages: list[ChatMessage], settings: SessionSettings) -> list[ChatMessage]:
        compacted = compact_messages(
            messages,
            tail_max=settings.compaction_tail_messages,
            max_tool_chars=settings.compaction_max_tool_chars,
        )
        if settings.shortlist_keywords:
            return apply_keyword_shortlist(compacted, settings.shortlist_keywords)
        return compacted

    def _call_model(
        self,
        context: list[ChatMessage],
        settings: SessionSettings,
    ) -> NormalizedChatResponse:
        tools = tool_definitions_from_registry(self._registry)
        req = ChatRequest(
            messages=context,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            tools=tools,
            tool_choice=ToolChoice(mode="auto") if tools else None,
            stream=settings.use_stream,
        )
        if settings.use_stream:
            return StreamReducer.consume(iter(self._provider.stream(req)))
        return self._provider.complete(req)

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

    def run(
        self,
        messages: list[ChatMessage],
        approvals: ApprovalSession,
        settings: SessionSettings,
        *,
        budget: BudgetGovernance | None = None,
    ) -> SessionOutcome:
        """Исполнить цикл до завершения, бюджета, ошибки или ожидания approval."""
        events: list[dict[str, Any]] = []
        bud = budget or BudgetGovernance(
            max_total_tokens=settings.max_total_tokens,
            max_context_units=settings.max_context_units,
        )

        for turn in range(settings.max_turns):
            self._emit(events, "session.turn", {"index": turn})
            exc = bud.check_exceeded(messages)
            if exc is not None:
                self._emit(events, "session.budget", {"reason": exc})
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
                    if messages[i].role is MessageRole.ASSISTANT and messages[i].tool_calls
                )
                ast = messages[ast_idx]
                assert ast.tool_calls is not None
                invs = [
                    ToolInvocation(tc.call_id, tc.tool_name, tc.arguments_json) for tc in ast.tool_calls
                ]
                self._emit(events, "tool.batch", {"count": len(invs)})
                try:
                    results = self._executor.execute_serial(invs, approvals)
                except ApprovalPending as exc:
                    self._emit(
                        events,
                        "session.waiting_approval",
                        {"call_id": exc.call_id, "tool": exc.tool_name},
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
                self._append_tool_results(messages, ast.tool_calls, results)
                continue

            ctx = self._prepare_context(messages, settings)
            self._emit(events, "model.request", {"context_messages": len(ctx)})
            try:
                resp = self._call_model(ctx, settings)
            except Exception as exc:  # noqa: BLE001
                return SessionOutcome(
                    state=SessionState.ERROR,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason=f"{type(exc).__name__}:{exc}",
                )

            bud.record_usage(resp.usage)
            self._emit(events, "model.response", {"finish": resp.finish_reason.value})
            over = bud.check_exceeded(messages)
            if over is not None:
                self._emit(events, "session.budget", {"reason": over})
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
                try:
                    results = self._executor.execute_serial(invs, approvals)
                except ApprovalPending as exc:
                    self._emit(
                        events,
                        "session.waiting_approval",
                        {"call_id": exc.call_id, "tool": exc.tool_name},
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
                self._append_tool_results(messages, resp.tool_calls, results)
                if resp.finish_reason is not FinishReason.TOOL_CALLS:
                    pass
                continue

            messages.append(ChatMessage(role=MessageRole.ASSISTANT, content=text))
            return SessionOutcome(
                state=SessionState.FINISHED,
                messages=tuple(messages),
                events=tuple(events),
                reason=None,
            )

        return SessionOutcome(
            state=SessionState.ERROR,
            messages=tuple(messages),
            events=tuple(events),
            reason="max_turns_exceeded",
        )
