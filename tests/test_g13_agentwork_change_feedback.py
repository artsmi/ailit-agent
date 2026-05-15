"""G13.3: AgentWork `memory.change_feedback` и mechanical remap без LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_memory.storage.sqlite_pag import SqlitePagStore
from ailit_base.providers.mock_provider import MockProvider
from ailit_runtime.models import (
    CONTRACT_VERSION,
    RuntimeRequestEnvelope,
)
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)
from agent_work.session.loop import SessionRunner, SessionSettings
from agent_work.tool_runtime.executor import ToolInvocation, ToolRunResult


def _make_req(
    *,
    payload: dict[str, Any],
    chat_id: str = "c1",
) -> RuntimeRequestEnvelope:
    return RuntimeRequestEnvelope(
        contract_version=CONTRACT_VERSION,
        runtime_id="rt1",
        chat_id=chat_id,
        broker_id="br1",
        trace_id="tr1",
        message_id="m1",
        parent_message_id="p1",
        goal_id="g1",
        namespace="ns",
        from_agent="test",
        to_agent="AgentMemory:global",
        created_at="2020-01-01T00:00:00Z",
        type="service.request",
        payload=payload,
    )


def test_successful_write_sends_change_feedback() -> None:
    """После успешного write_file notifier вызывается с written_items."""
    calls: list[dict[str, Any]] = []

    def notifier(info: dict[str, Any]) -> None:
        calls.append(dict(info))

    runner = SessionRunner(
        MagicMock(),
        MagicMock(),
        file_changed_notifier=notifier,
    )
    settings = SessionSettings()
    invs = [
        ToolInvocation(
            call_id="call-w",
            tool_name="write_file",
            arguments_json="{}",
        ),
    ]
    results = [
        ToolRunResult(
            call_id="call-w",
            tool_name="write_file",
            content="ok",
            error=None,
            extras={"relative_path": "pkg/x.py"},
        ),
    ]
    runner._append_tool_results(  # noqa: SLF001
        [],
        invs,
        results,
        settings,
        [],
        None,
        None,
    )
    assert len(calls) == 1
    assert calls[0].get("written_paths")
    items = calls[0].get("written_items")
    assert isinstance(items, list) and len(items) == 1
    assert items[0].get("path") == "pkg/x.py"
    assert items[0].get("call_id") == "call-w"


def test_failed_or_rejected_tool_sends_no_feedback() -> None:
    """Ошибка write_file — notifier не вызывается."""
    calls: list[dict[str, Any]] = []

    def notifier(info: dict[str, Any]) -> None:
        calls.append(dict(info))

    runner = SessionRunner(
        MagicMock(),
        MagicMock(),
        file_changed_notifier=notifier,
    )
    settings = SessionSettings()
    invs = [
        ToolInvocation(
            call_id="call-f",
            tool_name="write_file",
            arguments_json="{}",
        ),
    ]
    results = [
        ToolRunResult(
            call_id="call-f",
            tool_name="write_file",
            content="",
            error="write failed",
            extras={"relative_path": "b.py"},
        ),
    ]
    runner._append_tool_results(  # noqa: SLF001
        [],
        invs,
        results,
        settings,
        [],
        None,
        None,
    )
    assert calls == []


def test_mechanical_remap_does_not_call_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mechanical C remap не дергает MockProvider.stream."""
    db = tmp_path / "p.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    root = tmp_path / "repo"
    root.mkdir()
    pyf = root / "mod.py"
    src = "def foo():\n    return 1\n"
    pyf.write_text(src, encoding="utf-8")
    store = SqlitePagStore(db)
    w = PagGraphWriteService(store)
    w.upsert_node(
        namespace="ns",
        node_id="A:ns",
        level="A",
        kind="project",
        path=".",
        title="p",
        summary="p",
        attrs={},
        fingerprint="fa",
    )
    w.upsert_node(
        namespace="ns",
        node_id="B:mod.py",
        level="B",
        kind="file",
        path="mod.py",
        title="mod.py",
        summary="f",
        attrs={},
        fingerprint="fb0",
    )
    w.upsert_node(
        namespace="ns",
        node_id="C:mod.py#foo",
        level="C",
        kind="function",
        path="mod.py",
        title="foo",
        summary="s",
        attrs={
            "name": "foo",
            "kind": "function",
            "stable_key": "py:function:foo",
            "line_hint": {"start": 1, "end": 2},
        },
        fingerprint="c0",
        staleness_state="fresh",
    )
    pyf.write_text(
        "# comment\n" + src,
        encoding="utf-8",
    )
    pl: dict[str, Any] = {
        "service": "memory.change_feedback",
        "request_id": "r1",
        "chat_id": "chat",
        "turn_id": "t1",
        "namespace": "ns",
        "project_root": str(root),
        "source": "AgentWork",
        "change_batch_id": "cb-unique-1",
        "user_intent_summary": "u",
        "goal": "g",
        "changed_files": [
            {
                "path": "mod.py",
                "operation": "modify",
                "tool_call_id": "tc1",
                "message_id": "m1",
                "content_after_fingerprint": "sha256:aa",
            },
        ],
    }
    prov = MockProvider()
    stream_mock = MagicMock(wraps=prov.stream)
    prov.stream = stream_mock  # type: ignore[assignment, method-assign]
    worker = AgentMemoryWorker(
        MemoryAgentConfig(chat_id="x", broker_id="b", namespace="ns"),
    )
    worker._provider = prov  # type: ignore[assignment, misc]
    req = _make_req(payload=pl)
    out = worker.handle(req)
    assert out.get("ok") is True
    stream_mock.assert_not_called()
    pl2 = dict(pl)
    pl2["change_batch_id"] = "cb-2"
    out2 = worker.handle(_make_req(payload=pl2))
    assert out2.get("ok") is True
    stream_mock.assert_not_called()
