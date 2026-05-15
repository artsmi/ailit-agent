from __future__ import annotations

import json
from pathlib import Path

from agent_memory.storage.sqlite_pag import SqlitePagStore
from ailit_cli.memory_export import build_dot_for_slice, build_pag_export


def test_build_pag_export_contains_nodes_and_edges(tmp_path: Path) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)
    s.upsert_node(
        namespace="n",
        node_id="B:a.py",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="a",
        attrs={"language": "python"},
        fingerprint="h",
    )
    s.upsert_node(
        namespace="n",
        node_id="B:b.py",
        level="B",
        kind="file",
        path="b.py",
        title="b.py",
        summary="b",
        attrs={"language": "python"},
        fingerprint="h",
    )
    s.upsert_edge(
        namespace="n",
        edge_id="e1",
        edge_class="cross_link",
        edge_type="imports",
        from_node_id="B:a.py",
        to_node_id="B:b.py",
        confidence=0.5,
    )
    exp = build_pag_export(store=s, namespace="n")
    raw = json.loads(exp.to_json())
    assert raw["kind"] == "ailit_pag_export_v1"
    assert raw["namespace"] == "n"
    assert isinstance(raw["nodes"], list) and len(raw["nodes"]) == 2
    assert isinstance(raw["edges"], list) and len(raw["edges"]) == 1


def test_build_dot_for_slice_contains_edge_label(tmp_path: Path) -> None:
    db = tmp_path / "pag.sqlite3"
    s = SqlitePagStore(db)
    s.upsert_node(
        namespace="n",
        node_id="B:a.py",
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
        node_id="B:b.py",
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
        from_node_id="B:a.py",
        to_node_id="B:b.py",
        confidence=1.0,
    )
    dot = build_dot_for_slice(
        store=s,
        namespace="n",
        center_node_id="B:a.py",
        max_edges=10,
    )
    assert "digraph" in dot
    assert "imports" in dot
