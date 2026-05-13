from __future__ import annotations

from pathlib import Path

import pytest

from agent_memory.sqlite_pag import SqlitePagStore


def test_pag_upsert_fetch_node_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)

    s.upsert_node(
        namespace="default",
        node_id="A:repo",
        level="A",
        kind="project",
        path=".",
        title="repo",
        summary="Test repo",
        attrs={"repo_uri": "x", "branch": "main"},
        fingerprint="c1",
        staleness_state="fresh",
    )
    node = s.fetch_node(namespace="default", node_id="A:repo")
    assert node is not None
    assert node.namespace == "default"
    assert node.node_id == "A:repo"
    assert node.level == "A"
    assert node.attrs.get("branch") == "main"


def test_pag_idempotent_upsert_overwrites_fields(tmp_path: Path) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)

    s.upsert_node(
        namespace="n",
        node_id="B:f1",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="v1",
        attrs={"k": 1},
        fingerprint="h1",
        staleness_state="fresh",
    )
    s.upsert_node(
        namespace="n",
        node_id="B:f1",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="v2",
        attrs={"k": 2},
        fingerprint="h2",
        staleness_state="fresh",
    )
    node = s.fetch_node(namespace="n", node_id="B:f1")
    assert node is not None
    assert node.summary == "v2"
    assert node.attrs.get("k") == 2
    assert node.fingerprint == "h2"


def test_pag_edges_roundtrip_and_list_touching(tmp_path: Path) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)

    s.upsert_node(
        namespace="n",
        node_id="B:a",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="a",
        attrs={},
        fingerprint="h",
    )
    s.upsert_node(
        namespace="n",
        node_id="B:b",
        level="B",
        kind="file",
        path="b.py",
        title="b.py",
        summary="b",
        attrs={},
        fingerprint="h",
    )
    s.upsert_edge(
        namespace="n",
        edge_id="e1",
        edge_class="cross_link",
        edge_type="imports",
        from_node_id="B:a",
        to_node_id="B:b",
        confidence=0.7,
    )
    edges = s.list_edges_touching(namespace="n", node_ids=["B:a"])
    assert edges
    assert edges[0].edge_id == "e1"
    assert edges[0].edge_type == "imports"
    assert pytest.approx(edges[0].confidence, rel=1e-6) == 0.7


def test_pag_mark_stale_and_delete_stale_deletes_edges(tmp_path: Path) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)

    s.upsert_node(
        namespace="n",
        node_id="B:a",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="a",
        attrs={},
        fingerprint="h",
        staleness_state="fresh",
    )
    s.upsert_node(
        namespace="n",
        node_id="B:b",
        level="B",
        kind="file",
        path="b.py",
        title="b.py",
        summary="b",
        attrs={},
        fingerprint="h",
        staleness_state="fresh",
    )
    s.upsert_edge(
        namespace="n",
        edge_id="e1",
        edge_class="cross_link",
        edge_type="imports",
        from_node_id="B:a",
        to_node_id="B:b",
        confidence=1.0,
    )

    updated = s.mark_stale(
        namespace="n",
        node_ids=["B:a"],
        staleness_state="stale",
    )
    assert updated == 1

    dn, de = s.delete_stale(namespace="n")
    assert dn == 1
    assert de == 1
    assert s.fetch_node(namespace="n", node_id="B:a") is None
    assert s.fetch_node(namespace="n", node_id="B:b") is not None
    assert s.list_edges_touching(namespace="n", node_ids=["B:b"]) == []


def test_pag_delete_outgoing_edges_and_delete_nodes_by_ids(
    tmp_path: Path,
) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)
    for nid, level, path in (
        ("B:f", "B", "a.py"),
        ("C:1", "C", "a.py"),
        ("C:2", "C", "a.py"),
    ):
        s.upsert_node(
            namespace="n",
            node_id=nid,
            level=level,
            kind="x",
            path=path,
            title=nid,
            summary="s",
            attrs={},
            fingerprint="h",
        )
    s.upsert_edge(
        namespace="n",
        edge_id="e_imp",
        edge_class="cross_link",
        edge_type="imports",
        from_node_id="B:f",
        to_node_id="B:other",
        confidence=0.5,
    )
    s.upsert_edge(
        namespace="n",
        edge_id="e_c",
        edge_class="containment",
        edge_type="contains",
        from_node_id="B:f",
        to_node_id="C:1",
        confidence=1.0,
    )
    de = s.delete_outgoing_edges(
        namespace="n",
        from_node_id="B:f",
        edge_class="cross_link",
        edge_type="imports",
    )
    assert de == 1
    dn, dne = s.delete_nodes_by_ids(namespace="n", node_ids=["C:2"])
    assert dn == 1
    assert dne == 0
    assert s.fetch_node(namespace="n", node_id="C:2") is None
    assert s.fetch_node(namespace="n", node_id="C:1") is not None


def test_pag_delete_nodes_by_level_and_path_and_edges_touching(
    tmp_path: Path,
) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)
    s.upsert_node(
        namespace="n",
        node_id="B:f",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="a",
        attrs={},
        fingerprint="h",
    )
    s.upsert_node(
        namespace="n",
        node_id="C:f#1",
        level="C",
        kind="function",
        path="a.py",
        title="f",
        summary="f",
        attrs={},
        fingerprint="1:1",
    )
    s.upsert_edge(
        namespace="n",
        edge_id="e1",
        edge_class="containment",
        edge_type="contains",
        from_node_id="B:f",
        to_node_id="C:f#1",
        confidence=1.0,
    )
    dn = s.delete_nodes_by_level_and_path(
        namespace="n",
        level="C",
        path="a.py",
    )
    assert dn == 1
    de = s.delete_edges_touching_node_ids(
        namespace="n",
        node_ids=["C:f#1"],
    )
    assert de == 1
