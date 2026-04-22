from __future__ import annotations

import json
from pathlib import Path

from agent_core.memory.kb_tools import KbToolsConfig, build_kb_tool_registry


def test_kb_write_search_fetch_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "kb.sqlite3"
    cfg = KbToolsConfig(enabled=True, db_path=db, namespace="default")
    reg = build_kb_tool_registry(cfg)

    out_w = reg.get_handler("kb_write_fact")(
        {
            "id": "f_1",
            "scope": "project",
            "namespace": "default",
            "title": "Test fact",
            "summary": "This is a fact about token economy.",
            "body": "Longer details.",
            "tags": ["a", "b"],
            "provenance": {"commit": "abc"},
        },
    )
    j = json.loads(out_w)
    assert j["status"] == "ok"
    assert j["id"] == "f_1"

    out_s = reg.get_handler("kb_search")(
        {
            "query": "token",
            "scope": "project",
            "namespace": "default",
            "top_k": 5,
        },
    )
    rows = json.loads(out_s)
    assert isinstance(rows, list)
    assert rows and rows[0]["id"] == "f_1"

    out_f = reg.get_handler("kb_fetch")({"id": "f_1", "max_chars": 10})
    rec = json.loads(out_f)
    assert rec["id"] == "f_1"
    assert rec["title"] == "Test fact"
    assert rec["body_snippet"] == "Longer det"
    assert rec.get("memory_layer") == "semantic"
    assert rec.get("promotion_status") == "draft"


def test_kb_supersede_marks_old_inactive_in_search(
    tmp_path: Path,
) -> None:
    """Новая запись с supersedes_id закрывает valid_to у старой (M3)."""
    db = tmp_path / "kb.sqlite3"
    cfg = KbToolsConfig(enabled=True, db_path=db, namespace="default")
    reg = build_kb_tool_registry(cfg)
    h = reg.get_handler

    h("kb_write_fact")(
        {
            "id": "fact_a",
            "scope": "project",
            "namespace": "default",
            "title": "Token policy",
            "summary": "Old version",
            "body": "v1",
        },
    )
    h("kb_write_fact")(
        {
            "id": "fact_b",
            "scope": "project",
            "namespace": "default",
            "title": "Token policy",
            "summary": "New version",
            "body": "v2",
            "supersedes_id": "fact_a",
        },
    )
    out_old = json.loads(h("kb_fetch")({"id": "fact_a", "max_chars": 200}))
    assert out_old.get("promotion_status") == "superseded"
    assert out_old.get("valid_to")

    out_s = h("kb_search")(
        {"query": "Token", "namespace": "default", "top_k": 5},
    )
    rows = json.loads(out_s)
    ids = [r["id"] for r in rows]
    assert "fact_b" in ids
    assert "fact_a" not in ids

    out_all = h("kb_search")(
        {
            "query": "Token",
            "namespace": "default",
            "top_k": 5,
            "include_expired": True,
        },
    )
    ids2 = [r["id"] for r in json.loads(out_all)]
    assert "fact_a" in ids2
