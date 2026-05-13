"""G12.9: D creation policy, fingerprint dedupe, tiered memory slice."""

from __future__ import annotations

from pathlib import Path

from agent_memory.sqlite_pag import SqlitePagStore
from agent_memory.agent_memory_config import DPolicySubConfig
from agent_memory.pag_graph_write_service import PagGraphWriteService
from agent_memory.d_creation_policy import (
    DCreationPolicy,
    d_fingerprint,
    enrich_memory_slice_tiered,
    merge_d_into_node_ids,
    normalize_summary_for_d_fingerprint,
)


def _st(tmp: Path) -> SqlitePagStore:
    return SqlitePagStore(tmp / "d.sqlite3")


def test_d_fingerprint_stable() -> None:
    fp1 = d_fingerprint(
        "query_digest",
        "  Hello   world ",
        ("B:a", "C:b", "B:a"),
    )
    fp2 = d_fingerprint(
        "query_digest",
        "hello world",
        ("C:b", "B:a"),
    )
    assert fp1 == fp2


def test_normalize_summary() -> None:
    assert normalize_summary_for_d_fingerprint("  A  B  ") == "a b"


def test_at_most_one_new_d_per_query(tmp_path: Path) -> None:
    st = _st(tmp_path)
    ns = "ns1"
    st.upsert_node(
        namespace=ns,
        node_id="A:ns1",
        level="A",
        kind="project",
        path=".",
        title="p",
        summary="s",
        attrs={},
        fingerprint="1",
    )
    st.upsert_node(
        namespace=ns,
        node_id="B:a.py",
        level="B",
        kind="file",
        path="a.py",
        title="a.py",
        summary="f",
        attrs={},
        fingerprint="2",
    )
    pol = DCreationPolicy(
        DPolicySubConfig(max_d_per_query=1, min_linked_nodes=2),
    )
    o1 = pol.maybe_upsert_query_digest(
        PagGraphWriteService(st),
        namespace=ns,
        goal="find tests",
        node_ids=["A:ns1", "B:a.py"],
    )
    assert o1.gate in ("created", "reused")
    o2 = pol.maybe_upsert_query_digest(
        PagGraphWriteService(st),
        namespace=ns,
        goal="find tests",
        node_ids=["A:ns1", "B:a.py"],
    )
    assert o2.gate == "reused"
    assert o1.d_node_id == o2.d_node_id


def test_min_linked_skips(tmp_path: Path) -> None:
    st = _st(tmp_path)
    ns = "ns2"
    pol = DCreationPolicy(
        DPolicySubConfig(max_d_per_query=1, min_linked_nodes=3),
    )
    o = pol.maybe_upsert_query_digest(
        PagGraphWriteService(st),
        namespace=ns,
        goal="x",
        node_ids=["A:ns2", "B:x"],
    )
    assert o.gate == "skipped"
    assert o.reason == "min_linked_not_met"


def test_enrich_tiered() -> None:
    ms: dict = {
        "node_ids": ["A:1", "B:2", "C:3", "D:4"],
    }
    enrich_memory_slice_tiered(ms, namespace="1")
    assert "B:2" in (ms.get("b_node_ids") or [])
    assert "D:4" in (ms.get("d_node_ids") or [])


def test_merge_d() -> None:
    o = merge_d_into_node_ids(["A:x", "B:y"], "D:q")
    assert o[-1] == "D:q"
    o2 = merge_d_into_node_ids(["A:x"], None)
    assert "D" not in "".join(o2)
