from __future__ import annotations

from pathlib import Path

from agent_memory.pag.pag_indexer import (
    ChangedRange,
    PagIndexConfig,
    PagIndexer,
)
from agent_memory.storage.sqlite_pag import SqlitePagStore


def test_pag_indexer_respects_gitignore_and_policy(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ignored_dir/\nignored.py\n",
        encoding="utf-8",
    )
    (root / "ok.py").write_text(
        "def a():\n    return 1\n",
        encoding="utf-8",
    )
    (root / "ignored.py").write_text(
        "def b():\n    return 2\n",
        encoding="utf-8",
    )
    (root / "ignored_dir").mkdir()
    (root / "ignored_dir" / "x.py").write_text("x=1\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.py").write_text("x=1\n", encoding="utf-8")

    db = tmp_path / "pag.sqlite3"
    store = SqlitePagStore(db)
    idx = PagIndexer(store)
    ns = idx.index_project(PagIndexConfig(project_root=root, db_path=db))

    nodes = store.list_nodes(namespace=ns, level="B", limit=1000)
    paths = {n.path for n in nodes}
    assert "ok.py" in paths
    assert "ignored.py" not in paths
    assert "ignored_dir/x.py" not in paths
    assert "__pycache__/x.py" not in paths


def test_pag_indexer_whole_file_ingest_python_symbols(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text(
        "import b\n\n"
        "class C:\n"
        "    pass\n\n"
        "def f(x: int) -> int:\n"
        "    return x + 1\n",
        encoding="utf-8",
    )
    (root / "b.py").write_text("def g():\n    return 1\n", encoding="utf-8")

    db = tmp_path / "pag.sqlite3"
    store = SqlitePagStore(db)
    idx = PagIndexer(store)
    ns = idx.index_project(PagIndexConfig(project_root=root, db_path=db))

    c_nodes = store.list_nodes(namespace=ns, level="C", limit=1000)
    titles = {n.title for n in c_nodes}
    assert "C" in titles
    assert "f" in titles

    edges = store.list_edges_touching(
        namespace=ns,
        node_ids=["B:a.py"],
        limit=5000,
    )
    assert any(
        (e.edge_type == "imports" and e.to_node_id == "B:b.py") for e in edges
    )


def test_pag_incremental_sync_preserves_c_llm_attrs(tmp_path: Path) -> None:
    """Reindex merge keeps summary_fingerprint when chunk is unchanged."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    db = tmp_path / "pag.sqlite3"
    store = SqlitePagStore(db)
    idx = PagIndexer(store)
    ns = idx.index_project(PagIndexConfig(project_root=root, db_path=db))

    c_nodes = store.list_nodes(namespace=ns, level="C", limit=1000)
    assert c_nodes
    cn = c_nodes[0]
    merged_attrs = dict(cn.attrs) if isinstance(cn.attrs, dict) else {}
    merged_attrs["summary_fingerprint"] = "c_sum_v1:sha256-preserved"
    store.upsert_node(
        namespace=ns,
        node_id=cn.node_id,
        level=cn.level,
        kind=cn.kind,
        path=cn.path,
        title=cn.title,
        summary="LLM summary text",
        attrs=merged_attrs,
        fingerprint=cn.fingerprint,
        staleness_state=cn.staleness_state,
        source_contract=cn.source_contract,
    )

    idx.sync_changes(
        namespace=ns,
        project_root=root,
        changed_paths=["a.py"],
    )
    again = store.fetch_node(namespace=ns, node_id=cn.node_id)
    assert again is not None
    a2 = again.attrs if isinstance(again.attrs, dict) else {}
    assert a2.get("summary_fingerprint") == "c_sum_v1:sha256-preserved"
    assert again.summary == "LLM summary text"


def test_pag_indexer_incremental_sync_updates_symbols(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    db = tmp_path / "pag.sqlite3"
    store = SqlitePagStore(db)
    idx = PagIndexer(store)
    ns = idx.index_project(PagIndexConfig(project_root=root, db_path=db))

    (root / "a.py").write_text("def f2():\n    return 2\n", encoding="utf-8")
    idx.sync_changes(
        namespace=ns,
        project_root=root,
        changed_paths=["a.py"],
        changed_ranges=[ChangedRange(path="a.py", start_line=1, end_line=2)],
    )
    c_nodes = store.list_nodes(namespace=ns, level="C", limit=1000)
    titles = {n.title for n in c_nodes}
    assert "f2" in titles
    assert "f" not in titles


def test_pag_indexer_large_text_file_not_skipped(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    big = "x" * 200_000
    (root / "big.txt").write_text(big, encoding="utf-8")

    db = tmp_path / "pag.sqlite3"
    store = SqlitePagStore(db)
    idx = PagIndexer(store)
    ns = idx.index_project(PagIndexConfig(project_root=root, db_path=db))

    nodes = store.list_nodes(namespace=ns, level="B", limit=1000)
    paths = {n.path for n in nodes}
    assert "big.txt" in paths
