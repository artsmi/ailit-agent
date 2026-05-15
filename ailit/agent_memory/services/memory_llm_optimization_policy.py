"""MemoryLlmOptimizationPolicy: caps, thinking off, JSON-only."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, MutableMapping

from ailit_base.models import ChatRequest

MemoryLlmPhase = Literal["planner", "extractor", "remap", "synth"]


def _f(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _i(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _b(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


@dataclass(frozen=True, slots=True)
class MemoryLlmOptimizationPolicy:
    """
    Дефолты — план G13.2 / YAML ``memory.llm`` (agent-memory config).
    Все вызовы AgentMemory к LLM проходят через :meth:`apply_chat_request`.
    """

    enabled: bool
    model: str
    temperature: float
    max_memory_turns: int
    thinking_enabled: bool
    thinking_allow_for_remap: bool
    thinking_effort: str
    planner_max_input_chars: int
    planner_max_output_tokens: int
    planner_max_candidates: int
    extractor_max_excerpt_chars: int
    extractor_max_output_tokens: int
    extractor_max_candidates: int
    remap_max_excerpt_chars: int
    remap_max_output_tokens: int
    remap_max_candidates: int
    threshold_mechanical_accept: float
    threshold_ambiguous_min: float
    cache_enabled: bool
    strict_json: bool = True

    @staticmethod
    def default() -> MemoryLlmOptimizationPolicy:
        return MemoryLlmOptimizationPolicy(
            enabled=True,
            model="",
            temperature=0.0,
            max_memory_turns=4,
            thinking_enabled=False,
            thinking_allow_for_remap=False,
            thinking_effort="none",
            planner_max_input_chars=12_000,
            planner_max_output_tokens=512,
            planner_max_candidates=24,
            extractor_max_excerpt_chars=24_000,
            extractor_max_output_tokens=1200,
            extractor_max_candidates=12,
            remap_max_excerpt_chars=32_000,
            remap_max_output_tokens=1200,
            remap_max_candidates=8,
            threshold_mechanical_accept=0.85,
            threshold_ambiguous_min=0.5,
            cache_enabled=True,
            strict_json=True,
        )

    @classmethod
    def from_memory_llm_mapping(
        cls,
        raw: Mapping[str, Any],
    ) -> MemoryLlmOptimizationPolicy:
        d = dict(raw)
        th: MutableMapping[str, Any] = (
            dict(d["thresholds"])
            if isinstance(d.get("thresholds"), Mapping)
            else {}
        )
        th_mech = th.get("mechanical_accept", 0.85)
        th_amb = th.get("ambiguous_min", 0.5)
        think: MutableMapping[str, Any] = (
            dict(d["thinking"])
            if isinstance(d.get("thinking"), Mapping)
            else {}
        )
        pl: MutableMapping[str, Any] = (
            dict(d["planner"]) if isinstance(d.get("planner"), Mapping) else {}
        )
        ex: MutableMapping[str, Any] = (
            dict(d["extractor"])
            if isinstance(d.get("extractor"), Mapping)
            else {}
        )
        rm: MutableMapping[str, Any] = (
            dict(d["remap"]) if isinstance(d.get("remap"), Mapping) else {}
        )
        cache: MutableMapping[str, Any] = (
            dict(d["cache"]) if isinstance(d.get("cache"), Mapping) else {}
        )
        return cls(
            enabled=_b(d.get("enabled"), True),
            model=str(d.get("model", "") or ""),
            temperature=_f(d.get("temperature"), 0.0),
            max_memory_turns=max(1, _i(d.get("max_memory_turns"), 4)),
            thinking_enabled=_b(think.get("enabled"), False),
            thinking_allow_for_remap=_b(think.get("allow_for_remap"), False),
            thinking_effort=str(think.get("effort", "none") or "none"),
            planner_max_input_chars=max(
                400,
                _i(pl.get("max_input_chars"), 12_000),
            ),
            planner_max_output_tokens=max(
                32,
                _i(pl.get("max_output_tokens"), 512),
            ),
            planner_max_candidates=max(1, _i(pl.get("max_candidates"), 24)),
            extractor_max_excerpt_chars=max(
                400,
                _i(ex.get("max_excerpt_chars"), 24_000),
            ),
            extractor_max_output_tokens=max(
                32,
                _i(ex.get("max_output_tokens"), 1200),
            ),
            extractor_max_candidates=max(1, _i(ex.get("max_candidates"), 12)),
            remap_max_excerpt_chars=max(
                400,
                _i(rm.get("max_excerpt_chars"), 32_000),
            ),
            remap_max_output_tokens=max(
                32,
                _i(rm.get("max_output_tokens"), 1200),
            ),
            remap_max_candidates=max(1, _i(rm.get("max_candidates"), 8)),
            threshold_mechanical_accept=_f(th_mech, 0.85),
            threshold_ambiguous_min=_f(th_amb, 0.5),
            cache_enabled=_b(cache.get("enabled"), True),
            strict_json=True,
        )

    def max_output_tokens_for_phase(self, phase: MemoryLlmPhase) -> int:
        if phase == "planner":
            return int(self.planner_max_output_tokens)
        if phase == "extractor":
            return int(self.extractor_max_output_tokens)
        if phase == "remap":
            return int(self.remap_max_output_tokens)
        return int(self.planner_max_output_tokens)

    def apply_chat_request(
        self,
        request: ChatRequest,
        *,
        phase: MemoryLlmPhase,
        model_override: str | None = None,
    ) -> ChatRequest:
        """Apply token caps, policy temperature and no-thinking defaults."""
        m = model_override if model_override is not None else self.model
        model = str(m or "").strip() or request.model
        max_tok = self.max_output_tokens_for_phase(phase)
        ex: dict[str, Any] = dict(request.extra or {})
        ex["memory_llm"] = {
            "phase": phase,
            "thinking": {
                "enabled": self.thinking_enabled
                and (phase == "remap" and self.thinking_allow_for_remap),
                "effort": self.thinking_effort,
            },
            "response_format": "json_schema" if self.strict_json else "json",
        }
        if self.strict_json:
            ex["response_format"] = {"type": "json_object"}
        return replace(
            request,
            model=model,
            temperature=float(self.temperature),
            max_tokens=max_tok,
            extra=ex,
        )

    def clamp_utf8(self, text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[: max_chars] + "…"
