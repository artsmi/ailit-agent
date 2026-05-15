from __future__ import annotations

import json
from pathlib import Path

import pytest

from ailit_runtime.errors import RuntimeProtocolError
from agent_memory.storage.memory_journal import (
    JOURNAL_SCHEMA,
    MemoryJournalRow,
    MemoryJournalStore,
    default_memory_journal_path,
    redact_journal_value,
)


def test_memory_journal_append_read_and_filter(tmp_path: Path) -> None:
    store = MemoryJournalStore(tmp_path / "memory-journal.jsonl")

    store.append(
        MemoryJournalRow(
            chat_id="chat-a",
            request_id="req-1",
            namespace="ns-a",
            project_id="proj-a",
            event_name="memory.request.received",
            summary="accepted request",
            node_ids=("A:ns-a",),
            edge_ids=("edge-1",),
            payload={"next_action": "explore.B"},
        ),
    )
    store.append(
        MemoryJournalRow(
            chat_id="chat-b",
            request_id="req-2",
            namespace="ns-b",
            project_id="proj-b",
            event_name="memory.slice.returned",
            summary="returned slice",
        ),
    )

    rows = list(store.iter_rows())
    assert len(rows) == 2
    assert rows[0].schema == JOURNAL_SCHEMA
    assert rows[0].node_ids == ("A:ns-a",)
    assert rows[0].edge_ids == ("edge-1",)

    by_chat = list(store.filter_rows(chat_id="chat-a"))
    assert len(by_chat) == 1
    assert by_chat[0].request_id == "req-1"

    by_event = list(store.filter_rows(event_name="memory.slice.returned"))
    assert len(by_event) == 1
    assert by_event[0].chat_id == "chat-b"


def test_memory_journal_redacts_sensitive_fields(tmp_path: Path) -> None:
    store = MemoryJournalStore(tmp_path / "memory-journal.jsonl")
    store.append(
        MemoryJournalRow(
            chat_id="chat-a",
            event_name="memory.llm.turn.started",
            summary="llm turn",
            payload={
                "raw_prompt": "secret prompt",
                "chain_of_thought": "hidden reasoning",
                "nested": {
                    "api_key": "key",
                    "safe": "visible",
                    "token": "tok",
                },
            },
        ),
    )

    raw = store.path.read_text(encoding="utf-8").strip()
    data = json.loads(raw)
    payload = data["payload"]
    assert payload["raw_prompt"] == "[redacted]"
    assert payload["chain_of_thought"] == "[redacted]"
    assert payload["nested"]["api_key"] == "[redacted]"
    assert payload["nested"]["token"] == "[redacted]"
    assert payload["nested"]["safe"] == "visible"


def test_memory_journal_requires_required_fields(tmp_path: Path) -> None:
    store = MemoryJournalStore(tmp_path / "memory-journal.jsonl")

    with pytest.raises(RuntimeProtocolError):
        store.append(MemoryJournalRow(chat_id="", event_name="memory.error"))

    with pytest.raises(RuntimeProtocolError):
        store.append(MemoryJournalRow(chat_id="chat-a", event_name=""))


def test_memory_journal_default_path_uses_home_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("AILIT_MEMORY_JOURNAL_PATH", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_memory_journal_path() == (
        tmp_path / ".ailit" / "runtime" / "memory-journal.jsonl"
    ).resolve()


def test_redact_journal_value_handles_lists() -> None:
    redacted = redact_journal_value(
        [{"prompt": "hide"}, {"safe": "keep"}],
    )
    assert redacted == [{"prompt": "[redacted]"}, {"safe": "keep"}]
