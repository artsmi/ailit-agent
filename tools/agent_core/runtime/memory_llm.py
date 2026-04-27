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
) -> MemoryLLMDecision:
    """Parse strict JSON LLM output into a memory decision."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid memory decision json: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("memory decision must be object")
    return MemoryLLMDecision(
        selected_nodes=_str_list(raw.get("selected_nodes")),
        candidate_nodes=_str_list(raw.get("candidate_nodes")),
        next_action=str(raw.get("next_action") or ""),
        decision_summary=str(raw.get("decision_summary") or ""),
        partial=bool(raw.get("partial", False)),
        recommended_next_step=str(raw.get("recommended_next_step") or ""),
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
    ) -> None:
        self._provider = provider
        self._config = config
        self._journal = journal

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
            "goal": goal,
            "known_selected_nodes": list(selected_nodes),
        }
        req = ChatRequest(
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
        resp = self._provider.complete(req)
        text = "".join(resp.text_parts).strip()
        decision = parse_memory_llm_decision(text, pass_level=level)
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
