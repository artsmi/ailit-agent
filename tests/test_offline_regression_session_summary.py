"""Offline regression: stable unified session summary fields (M4-4.2)."""

from __future__ import annotations

from pathlib import Path

from ailit.token_economy_aggregates import (
    build_session_summary,
    read_jsonl_session_log,
)


def test_offline_regression_session_summary_min_fixture() -> None:
    """Fixture JSONL should keep key summary fields stable."""
    p = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "logs"
        / "session_summary_min.jsonl"
    )
    rows = read_jsonl_session_log(p)
    s = build_session_summary(rows)

    assert s.get("contract") == "ailit_session_summary_v1"
    assert isinstance(s.get("subsystems"), dict)

    fr = s.get("memory_full_report")
    assert isinstance(fr, dict)
    assert fr.get("kind") == "ailit_memory_full_report_v1"

    rl = fr.get("rate_limit")
    assert isinstance(rl, dict)
    assert rl.get("rate_limited_total") == 1

    aw = fr.get("auto_write")
    assert isinstance(aw, dict)
    done_by = aw.get("done_by_kind")
    assert isinstance(done_by, dict)
    assert done_by.get("repo_identity") == 1
    assert done_by.get("repo_entrypoints") == 1

    skipped_by = aw.get("skipped_by_kind")
    assert isinstance(skipped_by, dict)
    assert skipped_by.get("repo_safe_commands") == 1
