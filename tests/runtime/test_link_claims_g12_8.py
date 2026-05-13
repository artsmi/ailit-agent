"""G12.8: C link claims, pending resolver, real graph edges."""

from __future__ import annotations

from pathlib import Path

from agent_memory.sqlite_pag import SqlitePagStore
from agent_memory.link_claim_resolver import (
    LinkClaimResolver,
    MVP_LINK_RELATIONS,
    SEMANTIC_LINK_RELATION_TYPES,
)
from agent_memory.pag_graph_write_service import PagGraphWriteService


def _store(tmp_path: Path) -> SqlitePagStore:
    return SqlitePagStore(tmp_path / "p.sqlite3")


def test_mvp_relations_cover_plan() -> None:
    assert MVP_LINK_RELATIONS == SEMANTIC_LINK_RELATION_TYPES
    assert "calls" in SEMANTIC_LINK_RELATION_TYPES
    assert "imports" in SEMANTIC_LINK_RELATION_TYPES
    assert "related_to" in SEMANTIC_LINK_RELATION_TYPES
    assert "tests" in SEMANTIC_LINK_RELATION_TYPES


def test_resolve_creates_real_edge_cross_link(tmp_path: Path) -> None:
    st = _store(tmp_path)
    ns = "ns-a"
    st.upsert_node(
        namespace=ns,
        node_id="C:src/a.go#from",
        level="C",
        kind="function",
        path="src/a.go",
        title="main",
        summary="s",
        attrs={},
        fingerprint="1",
    )
    st.upsert_node(
        namespace=ns,
        node_id="C:src/b.go#to",
        level="C",
        kind="function",
        path="src/b.go",
        title="helper",
        summary="s",
        attrs={},
        fingerprint="1",
    )
    r = LinkClaimResolver()
    res = r.process_claim_dict(
        PagGraphWriteService(st),
        namespace=ns,
        claim={
            "from": {"node_id": "C:src/a.go#from"},
            "relation": "calls",
            "target": {
                "name": "helper",
                "kind": "function",
                "path_hint": "src/b.go",
                "language": "go",
            },
            "confidence": 0.9,
        },
    )
    assert res.path == "resolved"
    assert res.edge_id
    edges = st.list_edges(namespace=ns, limit=20)
    assert any(
        e.edge_type == "calls"
        and e.from_node_id == "C:src/a.go#from"
        and e.to_node_id == "C:src/b.go#to"
        and e.edge_class == "semantic"
        for e in edges
    )
    assert not st.list_pending_link_claims(namespace=ns)


def test_no_target_goes_pending_then_resolved(tmp_path: Path) -> None:
    st = _store(tmp_path)
    ns = "ns-b"
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
            "relation": "references",
            "target": {
                "name": "laterFn",
                "kind": "function",
                "path_hint": "src/y.py",
                "language": "python",
            },
            "confidence": 0.7,
        },
    )
    assert o.path == "pending"
    pends = st.list_pending_link_claims(namespace=ns)
    assert len(pends) == 1
    st.upsert_node(
        namespace=ns,
        node_id="C:src/y.py#2",
        level="C",
        kind="function",
        path="src/y.py",
        title="laterFn",
        summary="s",
        attrs={},
        fingerprint="2",
    )
    n2 = r.resolve_all_pending(PagGraphWriteService(st), namespace=ns)
    assert n2 == 1
    assert not st.list_pending_link_claims(namespace=ns)
    ed = st.list_edges(namespace=ns, limit=20)
    assert any(e.edge_type == "related_to" for e in ed)


def test_ambiguous_stays_pending(tmp_path: Path) -> None:
    st = _store(tmp_path)
    ns = "ns-c"
    st.upsert_node(
        namespace=ns,
        node_id="C:a.md#1",
        level="C",
        kind="md_section",
        path="a.md",
        title="Setup",
        summary="s1",
        attrs={},
        fingerprint="1",
    )
    st.upsert_node(
        namespace=ns,
        node_id="C:b.md#2",
        level="C",
        kind="md_section",
        path="b.md",
        title="Setup",
        summary="s2",
        attrs={},
        fingerprint="1",
    )
    st.upsert_node(
        namespace=ns,
        node_id="C:c.md#3",
        level="C",
        kind="md_section",
        path="c.md",
        title="Other",
        summary="s3",
        attrs={},
        fingerprint="1",
    )
    r = LinkClaimResolver()
    o = r.process_claim_dict(
        PagGraphWriteService(st),
        namespace=ns,
        claim={
            "from": {"node_id": "C:c.md#3"},
            "relation": "documents",
            "target": {
                "name": "Setup",
                "kind": "md_section",
                "path_hint": "",
                "language": "markdown",
            },
            "confidence": 0.5,
        },
    )
    assert o.path == "pending"
    assert o.reason == "ambiguous_target"
    assert st.list_pending_link_claims(namespace=ns)


def test_from_not_c_skipped(tmp_path: Path) -> None:
    st = _store(tmp_path)
    ns = "ns-d"
    st.upsert_node(
        namespace=ns,
        node_id="B:README.md",
        level="B",
        kind="file",
        path="README.md",
        title="README.md",
        summary="s",
        attrs={},
        fingerprint="1",
    )
    r = LinkClaimResolver()
    o = r.process_claim_dict(
        PagGraphWriteService(st),
        namespace=ns,
        claim={
            "from": {"node_id": "B:README.md"},
            "relation": "calls",
            "target": {
                "name": "x",
                "kind": "function",
                "path_hint": "a.py",
                "language": "py",
            },
            "confidence": 0.2,
        },
    )
    assert o.path == "skipped"
