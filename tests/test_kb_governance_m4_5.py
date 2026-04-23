"""M4-5: governance (TTL, audit) and acceleration layer (FTS rebuild)."""

from __future__ import annotations

from pathlib import Path

from agent_core.memory.sqlite_kb import SqliteKb


def test_kb_search_uses_fts_by_default_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Если AILIT_KB_ACCEL не задан, пытается FTS и падает обратно."""
    from agent_core.memory.kb_tools import (
        KbToolsConfig,
        build_kb_tool_registry,
    )

    monkeypatch.delenv("AILIT_KB_ACCEL", raising=False)
    monkeypatch.setenv("AILIT_KB", "1")
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(tmp_path / "kb.sqlite3"))
    monkeypatch.setenv("AILIT_KB_NAMESPACE", "t")

    calls: dict[str, int] = {"fts": 0, "like": 0}

    def _fts(self, **_kwargs):  # type: ignore[no-untyped-def]
        calls["fts"] += 1
        return []

    def _like(self, **_kwargs):  # type: ignore[no-untyped-def]
        calls["like"] += 1
        return []

    monkeypatch.setattr(SqliteKb, "search_fts", _fts, raising=True)
    monkeypatch.setattr(SqliteKb, "search", _like, raising=True)

    reg = build_kb_tool_registry(
        KbToolsConfig(
            enabled=True,
            db_path=(tmp_path / "kb.sqlite3"),
            namespace="t",
        ),
    )
    out = reg.handlers["kb_search"]({"query": "x"})
    assert isinstance(out, str)
    assert calls["fts"] == 1
    assert calls["like"] == 0


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
