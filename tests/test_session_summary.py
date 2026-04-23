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
        {
            "event_type": "memory.policy",
            "enabled": True,
            "repo": {
                "repo_path": "/tmp/x",
                "repo_uri": "github.com/acme/repo",
                "branch": "develop",
                "commit": "abc",
                "default_branch": "develop",
                "default_branch_source": "origin_head",
            },
        },
        {
            "event_type": "memory.retrieval.fallback",
            "policy": "branch_first_default_fallback",
            "from_namespace": "x:feature",
            "to_namespace": "x:develop",
        },
    ]
    s = build_session_summary(rows)
    assert s.get("contract") == SESSION_SUMMARY_CONTRACT
    assert "subsystems" in s
    assert "m3_eval_signals" in s
    assert s["m3_eval_signals"].get("kind") == "m3_eval_proxy_v1"
    assert s["resume"]["resume_ready"] is True
    assert s["resume"]["trailing_error"] is False
    mp = s.get("memory_policy")
    assert isinstance(mp, dict)
    assert mp.get("enabled") is True
    repo = mp.get("repo")
    assert isinstance(repo, dict)
    assert repo.get("repo_uri") == "github.com/acme/repo"
    mem = s.get("subsystems", {}).get("memory")
    assert isinstance(mem, dict)
    assert mem.get("doom_loop_total") == 0
    assert mem.get("auto_write_skipped") == 0
    assert mem.get("retrieval_fallback_total") == 1
    assert mem.get("auto_write_done") == 0
    fb = s.get("memory_retrieval_fallback")
    assert isinstance(fb, dict)
    assert fb.get("policy") == "branch_first_default_fallback"


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


def test_auto_write_done_counted_in_subsystems() -> None:
    rows: list[dict[str, Any]] = [
        {
            "event_type": "memory.auto_write.done",
            "tool": "kb_write_fact",
            "kind": "repo_identity",
        },
    ]
    s = build_session_summary(rows)
    mem = s.get("subsystems", {}).get("memory")
    assert isinstance(mem, dict)
    assert mem.get("auto_write_done") == 1
    by = mem.get("auto_write_done_by_kind")
    assert isinstance(by, dict)
    assert by.get("repo_identity") == 1


def test_memory_retrieval_match_in_summary() -> None:
    rows: list[dict[str, Any]] = [
        {
            "event_type": "memory.retrieval.match",
            "level": "commit_exact",
            "id": "x",
            "namespace": "n",
            "fact_commit": "a",
            "repo_commit": "a",
        },
    ]
    s = build_session_summary(rows)
    mem = s.get("subsystems", {}).get("memory")
    assert isinstance(mem, dict)
    assert mem.get("retrieval_match_total") == 1
    by = mem.get("retrieval_match_by_level")
    assert isinstance(by, dict)
    assert by.get("commit_exact") == 1
    last = s.get("memory_retrieval_match")
    assert isinstance(last, dict)
    assert last.get("level") == "commit_exact"


def test_memory_rate_limited_counted_in_subsystems() -> None:
    rows: list[dict[str, Any]] = [
        {
            "event_type": "memory.auto_kb.rate_limited",
            "tool": "kb_search",
            "cap": 30,
            "count": 30,
            "reason": "auto_kb_search_branch",
        },
        {
            "event_type": "memory.auto_kb.rate_limited",
            "tool": "kb_fetch",
            "cap": 30,
            "count": 30,
            "reason": "auto_kb_fetch_match",
        },
    ]
    s = build_session_summary(rows)
    mem = s.get("subsystems", {}).get("memory")
    assert isinstance(mem, dict)
    assert mem.get("auto_kb_rate_limited_total") == 2
    by = mem.get("auto_kb_rate_limited_by_tool")
    assert isinstance(by, dict)
    assert by.get("kb_search") == 1
    assert by.get("kb_fetch") == 1


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
