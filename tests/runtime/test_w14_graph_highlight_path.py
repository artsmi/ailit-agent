"""M1: W14 graph highlight path builder (задача 1.2)."""

from __future__ import annotations

from pathlib import Path

from agent_memory.sqlite_pag import SqlitePagStore
from agent_memory.pag_graph_write_service import PagGraphWriteService
from agent_memory.w14_graph_highlight_path import (
    W14GraphHighlightPathBuilder,
    a_node_id,
)


def _up_node(
    w: PagGraphWriteService,
    ns: str,
    nid: str,
    level: str,
    pth: str,
    kind: str,
) -> None:
    w.upsert_node(
        namespace=ns,
        node_id=nid,
        level=level,
        kind=kind,
        path=pth,
        title="t",
        summary="s",
        attrs={},
        fingerprint="f",
    )


def _up_edge(
    w: PagGraphWriteService,
    ns: str,
    eid: str,
    a: str,
    b: str,
) -> None:
    w.upsert_edge(
        namespace=ns,
        edge_id=eid,
        edge_class="containment",
        edge_type="contains",
        from_node_id=a,
        to_node_id=b,
    )


def test_m1_tree_unique_path_upwalk(tmp_path: Path) -> None:
    """Единственный путь A→B→C по containment — полная цепочка."""
    store = SqlitePagStore(tmp_path / "g.sqlite3")
    w = PagGraphWriteService(store)
    ns = "ns1"
    aid = a_node_id(ns)
    bid = "B:app/x.py"
    cid = "C:stub123"
    _up_node(w, ns, aid, "A", ".", "project")
    _up_node(w, ns, bid, "B", "app/x.py", "file")
    _up_node(
        w, ns, cid, "C", "app/x.py", "symbol",
    )
    _up_edge(w, ns, "e0", aid, bid)
    _up_edge(w, ns, "e1", bid, cid)
    got = W14GraphHighlightPathBuilder.path_to_end(store, ns, cid)
    assert got.node_ids == [aid, bid, cid]
    assert got.edge_ids == ["e0", "e1"]


def test_m1_ambiguous_diamond_bfs_tiebreak(tmp_path: Path) -> None:
    """Два кратчайших A→T: A—m_lo—T и A—m_hi—T, m_lo < m_hi.

    Tie-break: BFS.
    """
    store = SqlitePagStore(tmp_path / "d.sqlite3")
    w = PagGraphWriteService(store)
    ns = "ns1"
    aid = a_node_id(ns)
    mlo = "B:aa"
    mhi = "B:zz"
    tid = "B:target"
    _up_node(w, ns, aid, "A", ".", "project")
    _up_node(w, ns, mlo, "B", "aa", "x")
    _up_node(w, ns, mhi, "B", "zz", "x")
    _up_node(w, ns, tid, "B", "target", "x")
    for e, a, b in [
        ("ea_lo", aid, mlo), ("ea_hi", aid, mhi),
        ("e_lo", mlo, tid), ("e_hi", mhi, tid),
    ]:
        _up_edge(w, ns, e, a, b)
    got = W14GraphHighlightPathBuilder.path_to_end(store, ns, tid)
    assert got.node_ids[0] == aid
    assert got.node_ids[-1] == tid
    assert len(got.node_ids) == 3
    assert got.node_ids[1] == mlo, (
        "лексико-мин. сосед A → B:aa, не B:zz"
    )
    assert mhi not in got.node_ids
    assert len(got.edge_ids) == 2
    assert got.edge_ids[0] == "ea_lo" and got.edge_ids[1] == "e_lo"


def test_union_merges_without_duplicate_nodes(tmp_path: Path) -> None:
    store = SqlitePagStore(tmp_path / "u.sqlite3")
    w = PagGraphWriteService(store)
    ns = "ns1"
    aid = a_node_id(ns)
    bid = "B:only.f"
    _up_node(w, ns, aid, "A", ".", "project")
    _up_node(w, ns, bid, "B", "only.f", "file")
    c1, c2 = "C:one1", "C:two2"
    _up_node(w, ns, c1, "C", "only.f", "a")
    _up_node(w, ns, c2, "C", "only.f", "b")
    _up_edge(w, ns, "eb", aid, bid)
    _up_edge(w, ns, "ec1", bid, c1)
    _up_edge(w, ns, "ec2", bid, c2)
    got = W14GraphHighlightPathBuilder.union_to_ends(
        store, ns, (c1, c2),
    )
    assert got.node_ids[0] == aid
    assert list(dict.fromkeys(got.node_ids)) == got.node_ids
    assert bid in got.node_ids
    assert c1 in got.node_ids and c2 in got.node_ids
    assert len([x for x in got.node_ids if x == aid]) == 1
