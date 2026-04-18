"""Session loop: scripted provider, approval resume, budget."""

from __future__ import annotations

from collections.abc import Iterator

from agent_core.capabilities import Capability
from agent_core.models import (
    ChatMessage,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
    StreamDone,
    StreamEvent,
    ToolCallNormalized,
)
from agent_core.providers.protocol import ChatProvider
from agent_core.session.budget import BudgetGovernance
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.state import SessionState
from agent_core.session.stream_reducer import StreamReducer
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.registry import default_builtin_registry


class ScriptedProvider:
    """Провайдер с заранее заданной очередью ответов."""

    def __init__(self, responses: list[NormalizedChatResponse], *, stream: bool = False) -> None:
        self._responses = list(responses)
        self._stream = stream

    @property
    def provider_id(self) -> str:
        return "scripted"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT, Capability.TOOLS})

    def complete(self, request: object) -> NormalizedChatResponse:
        if not self._responses:
            msg = "scripted provider queue empty"
            raise RuntimeError(msg)
        return self._responses.pop(0)

    def stream(self, request: object) -> Iterator[StreamEvent]:
        if not self._stream:
            yield StreamDone(response=self.complete(request))
            return
        r = self.complete(request)
        yield StreamDone(response=r)


def test_loop_tool_then_text(tmp_path: object, monkeypatch: object) -> None:
    """Один tool round (echo) затем финальный текст."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc = ToolCallNormalized(
        call_id="t1",
        tool_name="echo",
        arguments_json='{"message":"hi"}',
        stream_index=0,
        provider_name="scripted",
    )
    r1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r2 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(ScriptedProvider([r1, r2]), reg)
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert messages[-1].role is MessageRole.ASSISTANT
    assert "done" in messages[-1].content


def test_loop_waiting_approval_resume(tmp_path: object, monkeypatch: object) -> None:
    """WRITE tool → approval → продолжение."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc = ToolCallNormalized(
        call_id="w1",
        tool_name="write_file",
        arguments_json='{"path":"a.txt","content":"z"}',
        stream_index=0,
        provider_name="scripted",
    )
    r1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r2 = NormalizedChatResponse(
        text_parts=("ok",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    prov = ScriptedProvider([r1, r2])
    runner = SessionRunner(prov, reg)
    messages = [ChatMessage(role=MessageRole.USER, content="write")]
    approvals = ApprovalSession()
    out1 = runner.run(messages, approvals, SessionSettings(model="m"))
    assert out1.state is SessionState.WAITING_APPROVAL
    approvals.approve("w1")
    out2 = runner.run(messages, approvals, SessionSettings(model="m"))
    assert out2.state is SessionState.FINISHED


def test_budget_stops_run() -> None:
    """Бюджет обрывает цикл до бесконечных ходов."""
    reg = default_builtin_registry()
    heavy = NormalizedChatResponse(
        text_parts=("x",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1000, 1000, 2000, usage_missing=False),
        provider_metadata={},
    )
    prov = ScriptedProvider([heavy])
    runner = SessionRunner(prov, reg)
    messages = [ChatMessage(role=MessageRole.USER, content="u")]
    bud = BudgetGovernance(max_total_tokens=50)
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"), budget=bud)
    assert out.state is SessionState.BUDGET_EXCEEDED


def test_stream_reducer_with_scripted_stream() -> None:
    """StreamReducer на stream провайдера."""
    reg = default_builtin_registry()
    r = NormalizedChatResponse(
        text_parts=("z",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    prov = ScriptedProvider([r], stream=True)
    from agent_core.models import ChatRequest

    req = ChatRequest(messages=[], model="m")
    out = StreamReducer.consume(iter(prov.stream(req)))
    assert out.text_parts == ("z",)
