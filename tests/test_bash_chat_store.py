"""Тесты bash_chat_store (этап D.2)."""

from __future__ import annotations

from ailit.bash_chat_store import (
    append_execution,
    runs_list,
    set_view_tail_lines,
    view_tail_lines,
)


def test_append_and_list_roundtrip() -> None:
    store: dict[str, object] = {}
    append_execution(
        store,
        {
            "call_id": "id1",
            "command": "echo x",
            "combined_output": "exit_code: 0\n\n--- stdout ---\nx\n",
            "ok": True,
            "error": None,
            "started_at": "2026-04-01T10:00:00+00:00",
            "finished_at": "2026-04-01T10:00:01+00:00",
            "exit_code": 0,
            "truncated": False,
            "timed_out": False,
        },
    )
    runs = runs_list(store)
    assert len(runs) == 1
    assert runs[0]["call_id"] == "id1"
    assert runs[0]["exit_code"] == 0


def test_view_tail_lines_default_and_set() -> None:
    store: dict[str, object] = {}
    assert view_tail_lines(store) == 200
    set_view_tail_lines(store, 42)
    assert view_tail_lines(store) == 42
