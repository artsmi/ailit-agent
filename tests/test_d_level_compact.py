from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.models import (
    ChatMessage,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
)
from agent_core.session.d_level_compact import DLevelCompactService
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.state import SessionState
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.registry import default_builtin_registry


class _CapturingProvider:
    """Single-response provider that records the prompt context."""

    def __init__(self, response: NormalizedChatResponse) -> None:
        self._response = response
        self.last_request: object | None = None

    @property
    def provider_id(self) -> str:
        return "capture"

    def capabilities(self) -> frozenset[object]:
        return frozenset()

    def complete(self, request: object) -> NormalizedChatResponse:
        self.last_request = request
        return self._response


def _response() -> NormalizedChatResponse:
    return NormalizedChatResponse(
        text_parts=("ok",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(10, 5, 15, usage_missing=False),
        provider_metadata={},
    )


def test_d_level_compact_service_writes_node_and_edges(tmp_path: Path) -> None:
    store = SqlitePagStore(tmp_path / "pag.sqlite3")
    service = DLevelCompactService(store)

    res = service.compact(
        namespace="ns",
        removed_messages=[
            ChatMessage(role=MessageRole.USER, content="old question"),
            ChatMessage(role=MessageRole.ASSISTANT, content="old answer"),
        ],
        kept_messages=[ChatMessage(role=MessageRole.USER, content="tail")],
        linked_node_ids=("A:ns", "B:tools/app.py"),
        trigger="manual",
    )

    node = store.fetch_node(namespace="ns", node_id=res.d_node_id)
    assert node is not None
    assert node.level == "D"
    assert node.kind == "compact_summary"
    assert node.attrs["boundary_id"] == res.boundary_id
    assert node.attrs["linked_node_ids"] == ["A:ns", "B:tools/app.py"]
    edges = store.list_edges_touching(
        namespace="ns",
        node_ids=[res.d_node_id],
    )
    assert {e.to_node_id for e in edges} == {"A:ns", "B:tools/app.py"}
    assert res.message.name == "agent_memory_d"


def test_session_compaction_creates_d_node_and_context_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "pag.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db_path))
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    provider = _CapturingProvider(_response())
    runner = SessionRunner(provider, default_builtin_registry())
    messages = [
        ChatMessage(role=MessageRole.USER, content=f"old message {i}")
        for i in range(5)
    ]

    out = runner.run(
        messages,
        ApprovalSession(),
        SessionSettings(
            model="mock",
            compaction_tail_messages=2,
            compact_to_memory_enabled=True,
            pag_runtime_enabled=False,
        ),
    )

    assert out.state is SessionState.FINISHED
    compact_events = [
        e for e in out.events if e.get("event_type") == "context.compacted"
    ]
    assert compact_events
    linked = compact_events[0]["linked_node_ids"]
    assert isinstance(linked, list)
    namespace = str(linked[0]).removeprefix("A:")
    d_node_id = str(compact_events[0]["d_node_id"])
    store = SqlitePagStore(db_path)
    node = store.fetch_node(namespace=namespace, node_id=d_node_id)
    assert node is not None
    req = provider.last_request
    assert req is not None
    ctx = getattr(req, "messages", ())
    assert any(getattr(m, "name", None) == "agent_memory_d" for m in ctx)
    snapshot = next(
        e for e in out.events if e.get("event_type") == "context.snapshot"
    )
    assert snapshot["breakdown"]["memory_d"] > 0
