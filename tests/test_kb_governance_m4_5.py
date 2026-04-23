"""M4-5: governance (TTL, audit) and acceleration layer (FTS rebuild)."""

from __future__ import annotations

from pathlib import Path

from agent_core.memory.sqlite_kb import SqliteKb


def test_ttl_apply_sets_valid_to_for_deprecated(tmp_path: Path) -> None:
    kb = SqliteKb(tmp_path / "kb.sqlite3")
    kb.write(
        record_id="x",
        kind="fact",
        scope="project",
        namespace="n",
        title="t",
        summary="s",
        body="b",
        promotion_status="deprecated",
    )
    scanned, updated = kb.apply_ttl_to_deprecated(
        valid_to_iso="2026-01-01T00:00:00+00:00",
    )
    assert scanned >= 1
    assert updated == 1
    rec = kb.fetch("x")
    assert rec is not None
    assert rec.valid_to is not None


def test_append_audit_event_updates_provenance(tmp_path: Path) -> None:
    kb = SqliteKb(tmp_path / "kb.sqlite3")
    kb.write(
        record_id="x",
        kind="fact",
        scope="project",
        namespace="n",
        title="t",
        summary="s",
        body="b",
    )
    ok = kb.append_audit_event(record_id="x", event={"action": "test"})
    assert ok is True
    rec = kb.fetch("x")
    assert rec is not None
    audit = rec.provenance.get("audit")
    assert isinstance(audit, list)
    assert audit and isinstance(audit[0], dict)


def test_rebuild_fts_index_ok_or_false(tmp_path: Path) -> None:
    kb = SqliteKb(tmp_path / "kb.sqlite3")
    kb.write(
        record_id="x",
        kind="fact",
        scope="project",
        namespace="n",
        title="hello",
        summary="world",
        body="body",
    )
    ok = kb.rebuild_fts_index()
    assert isinstance(ok, bool)
    if ok:
        res = kb.search_fts(
            query="hello",
            scope="project",
            namespace="n",
            top_k=5,
        )
        assert isinstance(res, list)
        assert any(r.get("id") == "x" for r in res)
