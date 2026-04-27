from __future__ import annotations

from agent_core.models import (
    ChatMessage,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
)
from agent_core.session.context_ledger import (
    ContextSnapshotBuilder,
    ModelContextLimits,
    ModelLimitResolver,
)
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.state import SessionState
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.registry import default_builtin_registry


class _SingleResponseProvider:
    """Minimal provider for Context Ledger event tests."""

    def __init__(self, response: NormalizedChatResponse) -> None:
        self._response = response

    @property
    def provider_id(self) -> str:
        return "single"

    def capabilities(self) -> frozenset[object]:
        return frozenset()

    def complete(self, request: object) -> NormalizedChatResponse:
        return self._response


def test_context_snapshot_builder_counts_memory_slice_separately() -> None:
    builder = ContextSnapshotBuilder()

    snapshot = builder.build(
        context=[
            ChatMessage(role=MessageRole.SYSTEM, content="system prompt"),
            ChatMessage(
                role=MessageRole.SYSTEM,
                name="agent_memory_slice",
                content="memory abc slice",
            ),
            ChatMessage(role=MessageRole.USER, content="hello"),
        ],
        model="mock",
        turn_id="turn-0",
        tools_defs=(),
    )

    payload = snapshot.to_payload()
    assert payload["schema"] == "context.snapshot.v1"
    assert payload["usage_state"] == "estimated"
    assert payload["turn_id"] == "turn-0"
    assert payload["warning_state"] == "normal"
    assert payload["context_usage_percent"] > 0
    breakdown = payload["breakdown"]
    assert breakdown["memory_abc"] > 0
    assert breakdown["messages"] > 0
    assert payload["estimated_context_tokens"] >= breakdown["memory_abc"]


def test_snapshot_builder_effective_window_and_warning() -> None:
    builder = ContextSnapshotBuilder(
        resolver=ModelLimitResolver(
            overrides={
                "mock": ModelContextLimits(
                    context_window=100,
                    max_output_tokens=20,
                ),
            },
        ),
    )

    snapshot = builder.build(
        context=[
            ChatMessage(role=MessageRole.USER, content="x" * 300),
        ],
        model="mock",
        turn_id="turn-warn",
        tools_defs=(),
    )

    payload = snapshot.to_payload()
    assert payload["model_context_limit"] == 100
    assert payload["reserved_output_tokens"] == 20
    assert payload["effective_context_limit"] == 80
    assert payload["estimated_context_tokens"] == 75
    assert payload["warning_state"] == "compact_recommended"
    assert payload["context_usage_percent"] == 93.75


def test_snapshot_builder_marks_overflow_risk() -> None:
    builder = ContextSnapshotBuilder(
        resolver=ModelLimitResolver(
            overrides={
                "mock": ModelContextLimits(
                    context_window=100,
                    max_output_tokens=20,
                ),
            },
        ),
    )

    snapshot = builder.build(
        context=[
            ChatMessage(role=MessageRole.USER, content="x" * 400),
        ],
        model="mock",
        turn_id="turn-overflow",
        tools_defs=(),
    )

    payload = snapshot.to_payload()
    assert payload["estimated_context_tokens"] == 100
    assert payload["warning_state"] == "overflow_risk"
    assert payload["breakdown"]["free"] == 0


def test_session_emits_context_snapshot_and_usage() -> None:
    response = NormalizedChatResponse(
        text_parts=("ok",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cache_read_tokens=2,
            cache_write_tokens=1,
            usage_missing=False,
        ),
        provider_metadata={},
    )
    runner = SessionRunner(
        _SingleResponseProvider(response),
        default_builtin_registry(),
    )

    out = runner.run(
        [ChatMessage(role=MessageRole.USER, content="hi")],
        ApprovalSession(),
        SessionSettings(model="mock", pag_runtime_enabled=False),
    )

    assert out.state is SessionState.FINISHED
    event_types = [e.get("event_type") for e in out.events]
    snapshot_i = event_types.index("context.snapshot")
    request_i = event_types.index("model.request")
    usage_i = event_types.index("context.provider_usage_confirmed")
    response_i = event_types.index("model.response")
    assert snapshot_i < request_i
    assert request_i < usage_i < response_i
    snapshot = out.events[snapshot_i]
    assert snapshot["schema"] == "context.snapshot.v1"
    assert snapshot["turn_id"] == "turn-0"
    assert snapshot["usage_state"] == "estimated"
    usage = out.events[usage_i]
    assert usage["schema"] == "context.provider_usage_confirmed.v1"
    assert usage["turn_id"] == "turn-0"
    assert usage["usage_state"] == "confirmed"
    assert usage["input_tokens"] == 10
    assert usage["cache_read_tokens"] == 2
    assert usage["confirmed_context_tokens"] == 18
