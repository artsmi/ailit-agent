"""AgentMemory LLM-guided A/B/C exploration loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agent_core.models import (
    ChatMessage,
    ChatRequest,
    MessageRole,
)
from agent_core.providers.protocol import ChatProvider
from agent_core.runtime.agent_memory_config import (
    MemoryLlmSubConfig,
    ResultOnlyClamp,
    load_or_create_agent_memory_config,
    parse_memory_json_with_retry,
)
from agent_core.runtime.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)
from agent_core.runtime.memory_journal import (
    MemoryJournalRow,
    MemoryJournalStore,
)

MEMORY_LLM_SYSTEM_PROMPT: str = """\
You are AgentMemory. Explore project memory with minimal tokens.
Return ONLY compact JSON. Do not reveal chain-of-thought.
Use these fields:
selected_nodes: string[]
candidate_nodes: string[]
next_action: string
decision_summary: short string
partial: boolean
recommended_next_step: short string
Never request full-repo indexing. Pick only query-relevant A/B/C nodes.
"""

_PASSES: tuple[str, ...] = ("A", "B", "C")


@dataclass(frozen=True, slots=True)
class MemoryLLMConfig:
    """Runtime settings for AgentMemory LLM exploration."""

    model: str
    max_memory_turns: int = 3
    max_tokens: int = 512
    temperature: float = 0.0


@dataclass(frozen=True, slots=True)
class MemoryLLMDecision:
    """Structured decision returned by AgentMemory LLM."""

    selected_nodes: tuple[str, ...]
    candidate_nodes: tuple[str, ...]
    next_action: str
    decision_summary: str
    partial: bool
    recommended_next_step: str
    pass_level: str

    def to_payload(self) -> dict[str, Any]:
        """Return JSON-ready decision payload."""
        return {
            "selected_nodes": list(self.selected_nodes),
            "candidate_nodes": list(self.candidate_nodes),
            "next_action": self.next_action,
            "decision_summary": self.decision_summary,
            "partial": self.partial,
            "recommended_next_step": self.recommended_next_step,
            "pass_level": self.pass_level,
        }


def _str_list(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(str(x).strip() for x in raw if str(x).strip())


def parse_memory_llm_decision(
    text: str,
    *,
    pass_level: str,
    limits: MemoryLlmSubConfig | None = None,
) -> MemoryLLMDecision:
    """Parse strict JSON LLM output; retry/обрезка — G12.5."""
    lim: MemoryLlmSubConfig = limits or MemoryLlmSubConfig()
    try:
        raw0 = parse_memory_json_with_retry(text)
    except ValueError as exc:
        raise ValueError(f"invalid memory decision json: {exc}") from exc
    d: dict[str, object] = {str(k): v for k, v in raw0.items()}
    ResultOnlyClamp().apply_to_memory_decision(
        d,  # type: ignore[arg-type]
        max_summary=lim.max_summary_chars,
        max_reason=lim.max_reason_chars,
        max_decision=lim.max_decision_chars,
    )
    next_act: str = str(d.get("next_action", "") or "")
    if len(next_act) > lim.max_reason_chars:
        next_act = next_act[: lim.max_reason_chars] + "…"
    summ: str = str(d.get("decision_summary", "") or "")
    if len(summ) > lim.max_summary_chars:
        summ = summ[: lim.max_summary_chars] + "…"
    rns: str = str(d.get("recommended_next_step", "") or "")
    if len(rns) > lim.max_decision_chars:
        rns = rns[: lim.max_decision_chars] + "…"
    sel: tuple[str, ...] = _str_list(d.get("selected_nodes"))[: max(0, lim.max_selected_b)]
    return MemoryLLMDecision(
        selected_nodes=sel,
        candidate_nodes=_str_list(d.get("candidate_nodes")),
        next_action=next_act,
        decision_summary=summ,
        partial=bool(d.get("partial", False)),
        recommended_next_step=rns,
        pass_level=pass_level,
    )


class AgentMemoryLLMLoop:
    """Run bounded AgentMemory A/B/C LLM exploration."""

    def __init__(
        self,
        *,
        provider: ChatProvider,
        config: MemoryLLMConfig,
        journal: MemoryJournalStore,
        am_yaml_limits: MemoryLlmSubConfig | None = None,
        optimization: MemoryLlmOptimizationPolicy | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._journal = journal
        if am_yaml_limits is not None:
            self._am_limits: MemoryLlmSubConfig = am_yaml_limits
        else:
            self._am_limits: MemoryLlmSubConfig = (
                load_or_create_agent_memory_config().memory.llm
            )
        self._opt = optimization or MemoryLlmOptimizationPolicy.default()

    def run(
        self,
        *,
        chat_id: str,
        request_id: str,
        namespace: str,
        goal: str,
        known_nodes: Sequence[str] = (),
    ) -> MemoryLLMDecision:
        """Run up to max_memory_turns and return the latest decision."""
        max_turns = max(
            1,
            min(int(self._config.max_memory_turns), len(_PASSES)),
        )
        latest: MemoryLLMDecision | None = None
        selected: tuple[str, ...] = tuple(known_nodes)
        for level in _PASSES[:max_turns]:
            self._append(
                chat_id=chat_id,
                request_id=request_id,
                namespace=namespace,
                event_name=f"memory.explore.{level}.started",
                summary=f"start {level} exploration",
                payload={"known_nodes_count": len(selected)},
            )
            try:
                decision = self._invoke_pass(
                    level=level,
                    goal=goal,
                    selected_nodes=selected,
                )
            except Exception as exc:  # noqa: BLE001
                decision = MemoryLLMDecision(
                    selected_nodes=selected,
                    candidate_nodes=(),
                    next_action="partial",
                    decision_summary="memory decision parse failed",
                    partial=True,
                    recommended_next_step=str(exc),
                    pass_level=level,
                )
                self._append(
                    chat_id=chat_id,
                    request_id=request_id,
                    namespace=namespace,
                    event_name="memory.partial",
                    summary=decision.decision_summary,
                    node_ids=list(decision.selected_nodes),
                    payload=decision.to_payload(),
                )
                return decision
            selected = decision.selected_nodes or selected
            latest = decision
            self._append(
                chat_id=chat_id,
                request_id=request_id,
                namespace=namespace,
                event_name=f"memory.explore.{level}.finished",
                summary=decision.decision_summary,
                node_ids=list(decision.selected_nodes),
                payload=decision.to_payload(),
            )
            if decision.partial:
                return decision
        if latest is None:
            return MemoryLLMDecision(
                selected_nodes=selected,
                candidate_nodes=(),
                next_action="none",
                decision_summary="no memory decision",
                partial=True,
                recommended_next_step="retry memory query",
                pass_level="A",
            )
        return latest

    def _invoke_pass(
        self,
        *,
        level: str,
        goal: str,
        selected_nodes: Sequence[str],
    ) -> MemoryLLMDecision:
        user = {
            "pass_level": level,
            "goal": self._opt.clamp_utf8(
                str(goal or ""),
                self._opt.planner_max_input_chars,
            ),
            "known_selected_nodes": list(selected_nodes),
        }
        req0 = ChatRequest(
            messages=(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=MEMORY_LLM_SYSTEM_PROMPT,
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=json.dumps(
                        user,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            ),
            model=self._config.model,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            tools=(),
            stream=False,
        )
        req = self._opt.apply_chat_request(
            req0,
            phase="planner",
            model_override=self._config.model,
        )
        resp = self._provider.complete(req)
        text = "".join(resp.text_parts).strip()
        decision = parse_memory_llm_decision(
            text,
            pass_level=level,
            limits=self._am_limits,
        )
        return decision

    def _append(
        self,
        *,
        chat_id: str,
        request_id: str,
        namespace: str,
        event_name: str,
        summary: str,
        node_ids: Sequence[str] = (),
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._journal.append(
            MemoryJournalRow(
                chat_id=chat_id,
                request_id=request_id,
                namespace=namespace,
                event_name=event_name,
                summary=summary,
                node_ids=tuple(node_ids),
                payload=dict(payload or {}),
            ),
        )
