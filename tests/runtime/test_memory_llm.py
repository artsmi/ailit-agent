from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ailit_base.capabilities import Capability
from ailit_base.models import (
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
    StreamDone,
    StreamEvent,
)
from agent_memory.memory_journal import MemoryJournalStore
from agent_memory.memory_llm import (
    AgentMemoryLLMLoop,
    MemoryLLMConfig,
    parse_memory_llm_decision,
)


class _Provider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[object] = []

    @property
    def provider_id(self) -> str:
        return "memory-test"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT})

    def complete(self, request: object) -> NormalizedChatResponse:
        self.requests.append(request)
        text = self._responses.pop(0)
        return NormalizedChatResponse(
            text_parts=(text,),
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            usage=NormalizedUsage(1, 1, 2, usage_missing=False),
            provider_metadata={},
        )

    def stream(self, request: object) -> Iterator[StreamEvent]:
        yield StreamDone(response=self.complete(request))


def _json_decision(level: str, node: str, *, partial: bool = False) -> str:
    return (
        "{"
        f'"selected_nodes":["{node}"],'
        f'"candidate_nodes":["{node}"],'
        f'"next_action":"explore.{level}",'
        f'"decision_summary":"selected {node}",'
        f'"partial":{str(partial).lower()},'
        f'"recommended_next_step":"continue {level}"'
        "}"
    )


def test_parse_memory_llm_decision() -> None:
    d = parse_memory_llm_decision(
        _json_decision("A", "A:ns"),
        pass_level="A",
    )

    assert d.selected_nodes == ("A:ns",)
    assert d.next_action == "explore.A"
    assert d.partial is False


def test_memory_llm_loop_runs_a_b_c_and_writes_journal(tmp_path: Path) -> None:
    journal = MemoryJournalStore(tmp_path / "memory-journal.jsonl")
    provider = _Provider(
        [
            _json_decision("A", "A:ns"),
            _json_decision("B", "B:tools/app.py"),
            _json_decision("C", "C:tools/app.py:1-20"),
        ],
    )
    loop = AgentMemoryLLMLoop(
        provider=provider,
        config=MemoryLLMConfig(model="mock", max_memory_turns=3),
        journal=journal,
    )

    decision = loop.run(
        chat_id="chat-a",
        request_id="req-1",
        namespace="ns",
        goal="inspect app",
    )

    assert len(provider.requests) == 3
    assert decision.pass_level == "C"
    assert decision.selected_nodes == ("C:tools/app.py:1-20",)
    rows = list(journal.filter_rows(chat_id="chat-a"))
    assert [row.event_name for row in rows] == [
        "memory.explore.A.started",
        "memory.explore.A.finished",
        "memory.explore.B.started",
        "memory.explore.B.finished",
        "memory.explore.C.started",
        "memory.explore.C.finished",
    ]
    assert all(
        "chain_of_thought" not in row.to_dict()["payload"]
        for row in rows
    )


def test_memory_llm_loop_stops_at_max_memory_turns(tmp_path: Path) -> None:
    journal = MemoryJournalStore(tmp_path / "memory-journal.jsonl")
    provider = _Provider(
        [
            _json_decision("A", "A:ns"),
            _json_decision("B", "B:tools/app.py"),
            _json_decision("C", "C:tools/app.py:1-20"),
        ],
    )
    loop = AgentMemoryLLMLoop(
        provider=provider,
        config=MemoryLLMConfig(model="mock", max_memory_turns=2),
        journal=journal,
    )

    decision = loop.run(
        chat_id="chat-a",
        request_id="req-1",
        namespace="ns",
        goal="inspect app",
    )

    assert len(provider.requests) == 2
    assert decision.pass_level == "B"


def test_memory_llm_loop_returns_partial_on_bad_json(tmp_path: Path) -> None:
    journal = MemoryJournalStore(tmp_path / "memory-journal.jsonl")
    loop = AgentMemoryLLMLoop(
        provider=_Provider(["not json"]),
        config=MemoryLLMConfig(model="mock", max_memory_turns=3),
        journal=journal,
    )

    decision = loop.run(
        chat_id="chat-a",
        request_id="req-1",
        namespace="ns",
        goal="inspect app",
    )

    assert decision.partial is True
    assert decision.next_action == "partial"
    rows = list(journal.filter_rows(chat_id="chat-a"))
    assert rows[-1].event_name == "memory.partial"
