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
