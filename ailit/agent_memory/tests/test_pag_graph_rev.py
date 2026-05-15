from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_memory.storage.sqlite_pag import PagGraphTraceFn, SqlitePagStore


def test_pag_graph_rev_increments_on_upsert(tmp_path: Path) -> None:
    db = tmp_path / "r.sqlite3"
    s = SqlitePagStore(db)
    assert s.get_graph_rev(namespace="ns1") == 0
    r1 = s.upsert_node(
        namespace="ns1",
        node_id="A:x",
        level="A",
        kind="project",
        path=".",
        title="t",
        summary="s",
        attrs={},
        fingerprint="f",
    )
    assert r1 == 1
    r2 = s.upsert_edge(
        namespace="ns1",
        edge_id="e1",
        edge_class="c",
        edge_type="t",
        from_node_id="A:x",
        to_node_id="B:a",
    )
    assert r2 == 2
    assert s.get_graph_rev(namespace="ns1") == 2
    s2 = SqlitePagStore(db)
    assert s2.get_graph_rev(namespace="ns1") == 2


def test_pag_graph_trace_hook_called(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    s = SqlitePagStore(db)
    calls: list[tuple[str, str, int, str]] = []

    def hook(op: str, namespace: str, rev: int, _data: dict[str, Any]) -> None:
        calls.append((op, namespace, rev, "x"))

    fn: PagGraphTraceFn = hook
    with s.graph_trace(fn):
        s.upsert_node(
            namespace="n",
            node_id="B:f",
            level="B",
            kind="file",
            path="f",
            title="f",
            summary="",
            attrs={},
            fingerprint="h",
        )
    assert len(calls) == 1
    assert calls[0][0] == "node"
    assert calls[0][1] == "n"
    assert calls[0][2] == 1


def test_pag_separate_namespaces_independent_revs(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite3"
    s = SqlitePagStore(db)
    s.upsert_node(
        namespace="a",
        node_id="A:a",
        level="A",
        kind="p",
        path=".",
        title="t",
        summary="s",
        attrs={},
        fingerprint="f",
    )
    s.upsert_node(
        namespace="b",
        node_id="A:b",
        level="A",
        kind="p",
        path=".",
        title="t",
        summary="s",
        attrs={},
        fingerprint="f",
    )
    assert s.get_graph_rev(namespace="a") == 1
    assert s.get_graph_rev(namespace="b") == 1
