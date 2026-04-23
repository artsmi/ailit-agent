"""Session log summary + resume signals (M3)."""

from __future__ import annotations

from typing import Any

from ailit.token_economy_aggregates import (
    SESSION_SUMMARY_CONTRACT,
    build_session_summary,
)


def test_resume_ready_true_when_clean_tail() -> None:
    rows: list[dict[str, Any]] = [
        {
            "event_type": "model.response",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    ]
    s = build_session_summary(rows)
    assert s.get("contract") == SESSION_SUMMARY_CONTRACT
    assert "subsystems" in s
    assert "m3_eval_signals" in s
    assert s["m3_eval_signals"].get("kind") == "m3_eval_proxy_v1"
    assert s["resume"]["resume_ready"] is True
    assert s["resume"]["trailing_error"] is False


def test_resume_ready_false_after_cancel() -> None:
    rows: list[dict[str, Any]] = [
        {
            "event_type": "model.response",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        {"event_type": "session.cancelled", "phase": "turn_loop"},
    ]
    s = build_session_summary(rows)
    assert s["resume"]["resume_ready"] is False
    assert s["resume"]["cancelled"] is True


def test_resume_ready_false_trailing_model_error() -> None:
    rows: list[dict[str, Any]] = [
        {
            "event_type": "model.response",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        {"event_type": "model.error", "reason": "x"},
    ]
    s = build_session_summary(rows)
    assert s["resume"]["resume_ready"] is False
    assert s["resume"]["trailing_error"] is True
