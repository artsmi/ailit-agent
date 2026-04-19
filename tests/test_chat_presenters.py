"""Golden-тесты human-readable презентеров событий чата."""

from __future__ import annotations

import json

from ailit.chat_presenters import (
    format_event_for_user,
    format_jsonl_line_for_user,
    summarize_workflow_jsonl_for_user,
)


def test_golden_workflow_loaded() -> None:
    """workflow.loaded."""
    row = {
        "v": 1,
        "contract": "workflow_run_events_v1",
        "event_type": "workflow.loaded",
        "workflow_id": "demo_smoke",
    }
    assert format_event_for_user(row) == "Загружен workflow **`demo_smoke`**."


def test_golden_task_skipped_dry_run() -> None:
    """task.skipped_dry_run."""
    row = {
        "event_type": "task.skipped_dry_run",
        "workflow_id": "w",
        "task_id": "greet",
    }
    assert format_event_for_user(row) == (
        "Задача **`greet`** пропущена (dry-run, без вызова модели)."
    )


def test_golden_task_finished() -> None:
    """task.finished с причиной."""
    row = {
        "event_type": "task.finished",
        "task_id": "t1",
        "session_state": "finished",
        "reason": None,
    }
    out = format_event_for_user(row)
    assert "Задача **`t1`** завершена" in out
    assert "finished" in out


def test_golden_workflow_finished() -> None:
    """workflow.finished."""
    row = {"event_type": "workflow.finished", "workflow_id": "x"}
    assert format_event_for_user(row) == "Workflow **`x`** завершён."


def test_format_jsonl_line_roundtrip() -> None:
    """Строка JSONL → та же семантика, что и dict."""
    row = {"event_type": "stage.entered", "stage_id": "main", "workflow_id": "w"}
    line = json.dumps(row, ensure_ascii=False)
    assert "Стадия **`main`**" in format_jsonl_line_for_user(line)


def test_summarize_multi_line() -> None:
    """Несколько событий в summary."""
    lines = [
        json.dumps({"event_type": "workflow.loaded", "workflow_id": "a"}),
        json.dumps({"event_type": "workflow.finished", "workflow_id": "a"}),
    ]
    text = "\n".join(lines)
    summary = summarize_workflow_jsonl_for_user(text)
    assert "Загружен workflow" in summary
    assert "завершён" in summary


def test_unknown_event_type_fallback() -> None:
    """Неизвестный тип — fallback без полного JSON."""
    row = {"event_type": "custom.vendor.event", "payload": {"x": 1}}
    out = format_event_for_user(row)
    assert "custom.vendor.event" in out
    assert "диагностика" in out
