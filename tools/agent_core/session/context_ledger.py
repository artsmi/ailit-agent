"""Context Ledger event payload builders for Workflow 10."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agent_core.models import ChatMessage, NormalizedUsage, ToolDefinition

_DEFAULT_MODEL_CONTEXT_LIMIT = 200_000
_DEFAULT_RESERVED_OUTPUT_TOKENS = 20_000


def estimate_text_tokens(text: str) -> int:
    """Estimate tokens using the donor-style chars/4 heuristic."""
    body = str(text or "")
    if not body:
        return 0
    return max(1, (len(body) + 3) // 4)


def _estimate_messages_tokens(messages: Sequence[ChatMessage]) -> int:
    total = 0
    for msg in messages:
        total += estimate_text_tokens(msg.content)
        if msg.tool_calls:
            for call in msg.tool_calls:
                total += estimate_text_tokens(call.tool_name)
                total += estimate_text_tokens(call.arguments_json)
    return total


def _estimate_tools_tokens(tools_defs: Sequence[ToolDefinition]) -> int:
    total = 0
    for tool in tools_defs:
        total += estimate_text_tokens(tool.name)
        total += estimate_text_tokens(tool.description)
        total += estimate_text_tokens(str(dict(tool.parameters)))
    return total


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Estimated prompt window state emitted before provider request."""

    turn_id: str
    model: str
    model_context_limit: int
    effective_context_limit: int
    reserved_output_tokens: int
    estimated_context_tokens: int
    breakdown: Mapping[str, int]
    usage_state: str = "estimated"

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-ready ``context.snapshot.v1`` payload."""
        return {
            "schema": "context.snapshot.v1",
            "turn_id": self.turn_id,
            "model": self.model,
            "model_context_limit": self.model_context_limit,
            "effective_context_limit": self.effective_context_limit,
            "reserved_output_tokens": self.reserved_output_tokens,
            "estimated_context_tokens": self.estimated_context_tokens,
            "usage_state": self.usage_state,
            "breakdown": dict(self.breakdown),
        }


class ContextSnapshotBuilder:
    """Build Context Ledger snapshots from prepared model inputs."""

    def build(
        self,
        *,
        context: Sequence[ChatMessage],
        model: str,
        turn_id: str,
        tools_defs: Sequence[ToolDefinition],
    ) -> ContextSnapshot:
        """Build an estimated prompt snapshot for the next request."""
        tools_tokens = _estimate_tools_tokens(tools_defs)
        system_tokens = 0
        message_tokens = 0
        memory_abc_tokens = 0
        memory_d_tokens = 0
        tool_results_tokens = 0
        for msg in context:
            tokens = _estimate_messages_tokens((msg,))
            if msg.name == "agent_memory_slice":
                memory_abc_tokens += tokens
            elif msg.name == "agent_memory_d":
                memory_d_tokens += tokens
            elif msg.role.value == "system":
                system_tokens += tokens
            elif msg.role.value == "tool":
                tool_results_tokens += tokens
            else:
                message_tokens += tokens
        estimated = (
            system_tokens
            + tools_tokens
            + message_tokens
            + memory_abc_tokens
            + memory_d_tokens
            + tool_results_tokens
        )
        model_limit = _DEFAULT_MODEL_CONTEXT_LIMIT
        reserved = _DEFAULT_RESERVED_OUTPUT_TOKENS
        effective = max(1, model_limit - reserved)
        free = max(0, effective - estimated)
        return ContextSnapshot(
            turn_id=turn_id,
            model=model,
            model_context_limit=model_limit,
            effective_context_limit=effective,
            reserved_output_tokens=reserved,
            estimated_context_tokens=estimated,
            breakdown={
                "system": system_tokens,
                "tools": tools_tokens,
                "messages": message_tokens,
                "memory_abc": memory_abc_tokens,
                "memory_d": memory_d_tokens,
                "tool_results": tool_results_tokens,
                "free": free,
            },
        )


def provider_usage_confirmed_payload(
    *,
    usage: NormalizedUsage,
    turn_id: str,
) -> dict[str, Any]:
    """Return a JSON-ready ``context.provider_usage_confirmed.v1`` payload."""
    return {
        "schema": "context.provider_usage_confirmed.v1",
        "turn_id": turn_id,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "usage_state": "confirmed",
    }
