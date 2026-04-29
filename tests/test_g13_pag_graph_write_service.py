"""G13.1: PagGraphWriteService, traced vs offline PAG writes, static guard."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.pag_graph_write_service import (
    OFFLINE_PAG_WRITER_MODULES,
    RUNTIME_UNTRACED_WRITE_ALLOWLIST,
    PagGraphWriteService,
)


def test_runtime_write_emits_trace_delta(tmp_path: Path) -> None:
    """
    Traced node upsert -> one trace row;
    edge batch -> one callback, edges[].
    """
    db = tmp_path / "w.sqlite3"
    store = SqlitePagStore(db)
    w = PagGraphWriteService(store)
    calls: list[tuple[str, str, int, Any]] = []

    def hook(
        op: str,
        namespace: str,
        rev: int,
        data: dict[str, Any],
    ) -> None:
        calls.append((op, namespace, rev, data))

    with store.graph_trace(hook):
        w.upsert_node(
            namespace="ns1",
            node_id="A:x",
            level="A",
            kind="project",
            path=".",
            title="t",
            summary="s",
            attrs={},
            fingerprint="f1",
        )
    assert len(calls) == 1
    assert calls[0][0] == "node"
    assert calls[0][2] == 1
    calls.clear()
    with store.graph_trace(hook):
        w.upsert_edges_batch(
            namespace="ns1",
            edges=[
                {
                    "edge_id": "e1",
                    "edge_class": "c",
                    "edge_type": "t1",
                    "from_node_id": "A:x",
                    "to_node_id": "B:a",
                },
                {
                    "edge_id": "e2",
                    "edge_class": "c",
                    "edge_type": "t2",
                    "from_node_id": "A:x",
                    "to_node_id": "B:b",
                },
            ],
        )
    assert len(calls) == 1
    assert calls[0][0] == "edge_batch"
    d = calls[0][3]
    assert isinstance(d, dict)
    assert len(d.get("edges", [])) == 2


def test_offline_writer_bumps_rev_without_trace(tmp_path: Path) -> None:
    """Offline path: graph_rev bumps, no trace callback (indexer-style)."""
    db = tmp_path / "o.sqlite3"
    store = SqlitePagStore(db)
    w = PagGraphWriteService(store)
    seen: list[str] = []

    def hook(
        op: str,
        namespace: str,
        rev: int,
        data: dict[str, Any],
    ) -> None:
        seen.append(op)

    with store.graph_trace(hook):
        w.upsert_node(
            namespace="off",
            node_id="A:o",
            level="A",
            kind="project",
            path=".",
            title="t",
            summary="s",
            attrs={},
            fingerprint="f",
        )
    assert len(seen) == 1
    rev_after = store.get_graph_rev(namespace="off")
    seen.clear()
    w.upsert_node(
        namespace="off",
        node_id="B:f",
        level="B",
        kind="file",
        path="x.py",
        title="x",
        summary="s",
        attrs={},
        fingerprint="h2",
    )
    assert seen == []
    assert store.get_graph_rev(namespace="off") == rev_after + 1


def _files_with_regex(
    ac: Path,
    repo: Path,
    pattern: re.Pattern[str],
) -> set[str]:
    """Все .py под ``ac`` с вхождением ``pattern``."""
    out: set[str] = set()
    for path in sorted(ac.rglob("*.py")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if pattern.search(text):
            out.add(str(path.resolve().relative_to(repo)))
    return out


def test_runtime_direct_upsert_is_guarded() -> None:
    """
    Только `pag_graph_write_service` трогает `self._store.upsert_*`.
    Whitelist offline-модулей задокументирован.
    """
    repo = Path(__file__).resolve().parents[1]
    ac = repo / "tools" / "agent_core"
    rel = _files_with_regex(
        ac,
        repo,
        re.compile(r"_store\.upsert_(node|edge|edges_batch)\("),
    )
    assert rel == {
        "tools/agent_core/runtime/pag_graph_write_service.py",
    }
    assert "agent_core.memory.pag_indexer" in OFFLINE_PAG_WRITER_MODULES
    assert "agent_core.session.d_level_compact" in OFFLINE_PAG_WRITER_MODULES
    assert len(RUNTIME_UNTRACED_WRITE_ALLOWLIST) == 0


def test_rg_upsert_call_sites_match_plan_whitelist() -> None:
    """Стат-лист файлов с ``upsert_node(``/``upsert_edge(`` (G13.1)."""
    repo = Path(__file__).resolve().parents[1]
    ac = repo / "tools" / "agent_core"
    rel_files = _files_with_regex(
        ac,
        repo,
        re.compile(r"upsert_node\(|upsert_edge\("),
    )
    expected = {
        "tools/agent_core/memory/sqlite_pag.py",
        "tools/agent_core/runtime/pag_graph_write_service.py",
        "tools/agent_core/memory/pag_indexer.py",
        "tools/agent_core/runtime/d_creation_policy.py",
        "tools/agent_core/runtime/link_claim_resolver.py",
        "tools/agent_core/runtime/memory_c_remap.py",
        "tools/agent_core/runtime/memory_growth.py",
        "tools/agent_core/runtime/agent_memory_query_pipeline.py",
        "tools/agent_core/runtime/agent_memory_summary_service.py",
        "tools/agent_core/session/d_level_compact.py",
    }
    assert rel_files == expected
