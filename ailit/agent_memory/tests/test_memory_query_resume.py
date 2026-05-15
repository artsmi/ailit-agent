"""RESUME-строки для ``ailit memory query``."""

from __future__ import annotations

from pathlib import Path

from agent_memory.storage.sqlite_pag import SqlitePagStore
from agent_memory.query.memory_query_orchestrator import (
    build_memory_query_resume_lines,
)


def test_build_memory_query_resume_lines_from_pag(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite3"
    store = SqlitePagStore(db)
    ns = "ns_demo"
    store.upsert_node(
        namespace=ns,
        node_id="B:a.py",
        level="B",
        kind="file",
        path="a.py",
        title="a",
        summary="Alpha module.",
        attrs={},
        fingerprint="fp1",
        staleness_state="fresh",
        source_contract="test",
    )
    ms = {"node_ids": ["B:a.py", "B:missing.py"]}
    lines = build_memory_query_resume_lines(
        namespace=ns,
        db_path=db,
        memory_slice=ms,
        max_nodes=10,
        summary_max_chars=80,
    )
    assert any("B:a.py" in ln for ln in lines)
    assert any("Alpha" in ln for ln in lines)
    assert any("not found in PAG" in ln for ln in lines)
