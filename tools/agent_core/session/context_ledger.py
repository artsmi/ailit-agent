"""Context Ledger event payload builders for Workflow 10."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agent_core.models import ChatMessage, NormalizedUsage, ToolDefinition

_DEFAULT_MODEL_CONTEXT_LIMIT = 200_000
_DEFAULT_RESERVED_OUTPUT_TOKENS = 20_000
_WARNING_PCT = 75.0
_COMPACT_RECOMMENDED_PCT = 90.0


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
class ModelContextLimits:
    """Model context metadata used for effective window calculations."""

    context_window: int
    max_output_tokens: int


class ModelLimitResolver:
    """Resolve model context limits without provider-specific tokenizers."""

    def __init__(
        self,
        overrides: Mapping[str, ModelContextLimits] | None = None,
    ) -> None:
        self._overrides = dict(overrides or {})

    def resolve(self, model: str) -> ModelContextLimits:
        """Return best-known context limits for a provider/model string."""
        key = str(model or "").strip().lower()
        if key in self._overrides:
            return self._overrides[key]
        if "moonshot-v1-8k" in key:
            return ModelContextLimits(
                context_window=8_192,
                max_output_tokens=4_096,
            )
        if "moonshot-v1-32k" in key:
            return ModelContextLimits(
                context_window=32_768,
                max_output_tokens=8_192,
            )
        if "moonshot-v1-128k" in key or "kimi" in key:
            return ModelContextLimits(
                context_window=128_000,
                max_output_tokens=16_000,
            )
        if "deepseek" in key:
            return ModelContextLimits(
                context_window=64_000,
                max_output_tokens=8_000,
            )
        return ModelContextLimits(
            context_window=_DEFAULT_MODEL_CONTEXT_LIMIT,
            max_output_tokens=_DEFAULT_RESERVED_OUTPUT_TOKENS,
        )


def _reserve_output_tokens(limits: ModelContextLimits) -> int:
    reserve = min(
        _DEFAULT_RESERVED_OUTPUT_TOKENS,
        max(1, int(limits.max_output_tokens)),
    )
    return min(reserve, max(1, int(limits.context_window) - 1))


def _warning_state(*, estimated: int, effective_limit: int) -> str:
    if estimated >= effective_limit:
        return "overflow_risk"
    pct = (float(estimated) / float(max(1, effective_limit))) * 100.0
    if pct >= _COMPACT_RECOMMENDED_PCT:
        return "compact_recommended"
    if pct >= _WARNING_PCT:
        return "warning"
    return "normal"


def _usage_percent(*, estimated: int, effective_limit: int) -> float:
    pct = (float(estimated) / float(max(1, effective_limit))) * 100.0
    return round(min(999.0, pct), 2)


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Estimated prompt window state emitted before provider request."""

    turn_id: str
    model: str
    model_context_limit: int
    effective_context_limit: int
    reserved_output_tokens: int
    estimated_context_tokens: int
    context_usage_percent: float
    warning_state: str
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
            "context_usage_percent": self.context_usage_percent,
            "warning_state": self.warning_state,
            "usage_state": self.usage_state,
            "breakdown": dict(self.breakdown),
        }


class ContextSnapshotBuilder:
    """Build Context Ledger snapshots from prepared model inputs."""

    def __init__(self, resolver: ModelLimitResolver | None = None) -> None:
        self._resolver = resolver or ModelLimitResolver()

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
        limits = self._resolver.resolve(model)
        model_limit = max(1, int(limits.context_window))
        reserved = _reserve_output_tokens(limits)
        effective = max(1, model_limit - reserved)
        free = max(0, effective - estimated)
        return ContextSnapshot(
            turn_id=turn_id,
            model=model,
            model_context_limit=model_limit,
            effective_context_limit=effective,
            reserved_output_tokens=reserved,
            estimated_context_tokens=estimated,
            context_usage_percent=_usage_percent(
                estimated=estimated,
                effective_limit=effective,
            ),
            warning_state=_warning_state(
                estimated=estimated,
                effective_limit=effective,
            ),
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
    confirmed_context_tokens = 0
    for value in (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
    ):
        if value is not None:
            confirmed_context_tokens += int(value)
    return {
        "schema": "context.provider_usage_confirmed.v1",
        "turn_id": turn_id,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "confirmed_context_tokens": confirmed_context_tokens,
        "usage_state": "confirmed",
    }


@dataclass(frozen=True, slots=True)
class ContextProjectRef:
    """Namespace-aware memory reference for Context Ledger v2."""

    project_id: str
    namespace: str
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-ready project ref payload."""
        return {
            "project_id": self.project_id,
            "namespace": self.namespace,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
        }


def memory_injected_v2_payload(
    *,
    chat_id: str,
    turn_id: str,
    source_agent: str,
    project_refs: Sequence[ContextProjectRef],
    estimated_tokens: int,
    prompt_section: str,
    decision_summary: str,
    recommended_next_step: str,
) -> dict[str, Any]:
    """Return a namespace-aware ``context.memory_injected.v2`` payload."""
    node_ids: list[str] = []
    edge_ids: list[str] = []
    for ref in project_refs:
        node_ids.extend(ref.node_ids)
        edge_ids.extend(ref.edge_ids)
    return {
        "schema": "context.memory_injected.v2",
        "chat_id": chat_id,
        "turn_id": turn_id,
        "source_agent": source_agent,
        "usage_state": "estimated",
        "project_refs": [ref.to_payload() for ref in project_refs],
        "node_ids": node_ids,
        "edge_ids": edge_ids,
        "estimated_tokens": int(estimated_tokens),
        "prompt_section": prompt_section,
        "decision_summary": decision_summary,
        "recommended_next_step": recommended_next_step,
    }
