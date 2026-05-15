"""G13.5: pending link claims, resolved edge deltas, enum relation_type."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_memory.storage.sqlite_pag import SqlitePagStore
from agent_memory.pag.link_claim_resolver import (
    LinkClaimResolver,
    normalize_semantic_link_relation_type,
)
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService


def _store(tmp_path: Path) -> SqlitePagStore:
    return SqlitePagStore(tmp_path / "lc.sqlite3")


def test_pending_claim_not_graph_edge(tmp_path: Path) -> None:
    """До resolution в ``pag_edges`` нет ребра; pending — отдельная таблица."""
    st = _store(tmp_path)
    ns = "n1"
    st.upsert_node(
        namespace=ns,
        node_id="C:src/x.py#1",
        level="C",
        kind="function",
        path="src/x.py",
        title="a",
        summary="s",
        attrs={},
        fingerprint="1",
    )
    r = LinkClaimResolver()
    o = r.process_claim_dict(
        PagGraphWriteService(st),
        namespace=ns,
        claim={
            "from": {"node_id": "C:src/x.py#1"},
            "relation": "calls",
            "target": {
                "name": "futureFn",
                "kind": "function",
                "path_hint": "src/missing.py",
                "language": "python",
            },
            "confidence": 0.5,
        },
    )
    assert o.path == "pending"
    assert st.count_nodes(namespace=ns) >= 1
    assert st.list_edges(namespace=ns, limit=20) == []
    assert st.list_pending_link_claims(namespace=ns)


def test_resolved_claim_emits_edge_delta(tmp_path: Path) -> None:
    """Trace pag.edge.upsert: edge_class semantic, edge_type из enum."""
    st = _store(tmp_path)
    ns = "n2"
    for nid, p, title in (
        ("C:src/a.py#1", "src/a.py", "a"),
        ("C:src/b.py#2", "src/b.py", "b"),
    ):
        st.upsert_node(
            namespace=ns,
            node_id=nid,
            level="C",
            kind="function",
            path=p,
            title=title,
            summary="s",
            attrs={},
            fingerprint="1",
        )
    out: list[tuple[str, str, int, Any]] = []

    def hook(
        op: str,
        nspace: str,
        rev: int,
        data: dict[str, Any],
    ) -> None:
        out.append((op, nspace, rev, data))

    w = PagGraphWriteService(st)
    r = LinkClaimResolver()
    with st.graph_trace(hook):
        _ = r.process_claim_dict(
            w,
            namespace=ns,
            claim={
                "from": {"node_id": "C:src/a.py#1"},
                "relation_type": "imports",
                "target": {
                    "name": "b",
                    "kind": "function",
                    "path_hint": "src/b.py",
                    "language": "py",
                },
                "confidence": 0.88,
            },
        )
    assert st.list_edges(namespace=ns, limit=5)
    assert out, "должен быть graph_trace"
    if out[0][0] == "edge":
        d = out[0][3]
    elif out[0][0] == "edge_batch":
        d = out[0][3]
    else:
        pytest.fail("ожидались op edge/edge_batch")
    assert d is not None
    edges_payload: list[Any]
    if "edges" in d:
        edges_payload = d["edges"]
    else:
        edges_payload = [d]
    assert any(
        e.get("edge_class") == "semantic" and e.get("edge_type") == "imports"
        for e in edges_payload
        if isinstance(e, dict)
    )


def test_relation_type_enum_enforced(tmp_path: Path) -> None:
    """Неизвестная relation нормализуется в related_to; в graph только enum."""
    st = _store(tmp_path)
    ns = "n3"
    st.upsert_node(
        namespace=ns,
        node_id="C:x#1",
        level="C",
        kind="fn",
        path="x.py",
        title="A",
        summary="s",
        attrs={},
        fingerprint="1",
    )
    st.upsert_node(
        namespace=ns,
        node_id="C:y#1",
        level="C",
        kind="fn",
        path="y.py",
        title="B",
        summary="s",
        attrs={},
        fingerprint="2",
    )
    r = LinkClaimResolver()
    assert (
        normalize_semantic_link_relation_type("totally_unknown_relation_xxx")
        == "related_to"
    )
    res = r.process_claim_dict(
        PagGraphWriteService(st),
        namespace=ns,
        claim={
            "from": {"node_id": "C:x#1"},
            "relation": "totally_unknown_relation_xxx",
            "target": {
                "name": "B",
                "kind": "fn",
                "path_hint": "y.py",
                "language": "py",
            },
        },
    )
    assert res.path == "resolved"
    edg = st.list_edges(namespace=ns, limit=10)
    assert edg[0].edge_type == "related_to"
    assert edg[0].edge_class == "semantic"


def test_resolved_idempotent_repeated_claim(tmp_path: Path) -> None:
    w = PagGraphWriteService(_store(tmp_path))
    ns = "n4"
    s = w.store
    s.upsert_node(
        namespace=ns,
        node_id="C:u#1",
        level="C",
        kind="f",
        path="u.py",
        title="u1",
        summary="s",
        attrs={},
        fingerprint="1",
    )
    s.upsert_node(
        namespace=ns,
        node_id="C:v#1",
        level="C",
        kind="f",
        path="v.py",
        title="u2",
        summary="s",
        attrs={},
        fingerprint="2",
    )
    r = LinkClaimResolver()
    claim: dict[str, object] = {
        "from": {"node_id": "C:u#1"},
        "relation": "tests",
        "target": {
            "name": "u2",
            "kind": "f",
            "path_hint": "v.py",
            "language": "p",
        },
    }
    _ = r.process_claim_dict(w, namespace=ns, claim=claim)
    _ = r.process_claim_dict(w, namespace=ns, claim=claim)
    n_edge = s.list_edges(namespace=ns, limit=5)
    assert len(n_edge) == 1
    assert n_edge[0].edge_type == "tests"
