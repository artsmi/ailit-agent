"""CLI: PAG indexing utilities (workflow arch-graph-7, G7.2)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_core.memory.pag_indexer import (
    PagIndexer,
    index_project_to_default_store,
)
from agent_core.memory.sqlite_pag import PagEdge, PagNode, SqlitePagStore


def _node_json(n: PagNode) -> dict[str, Any]:
    return {
        "namespace": n.namespace,
        "node_id": n.node_id,
        "level": n.level,
        "kind": n.kind,
        "path": n.path,
        "title": n.title,
        "summary": n.summary,
        "attrs": dict(n.attrs),
        "fingerprint": n.fingerprint,
        "staleness_state": n.staleness_state,
        "source_contract": n.source_contract,
        "updated_at": n.updated_at,
    }


def _edge_json(e: PagEdge) -> dict[str, Any]:
    return {
        "namespace": e.namespace,
        "edge_id": e.edge_id,
        "edge_class": e.edge_class,
        "edge_type": e.edge_type,
        "from_node_id": e.from_node_id,
        "to_node_id": e.to_node_id,
        "confidence": float(e.confidence),
        "source_contract": e.source_contract,
        "updated_at": e.updated_at,
    }


@dataclass(frozen=True, slots=True)
class PagIndexResult:
    """Result payload for `ailit memory index`."""

    ok: bool
    namespace: str
    db_path: str
    project_root: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "namespace": str(self.namespace),
            "db_path": str(self.db_path),
            "project_root": str(self.project_root),
        }


def cmd_memory_index(args: object) -> int:
    """Index a project root into PAG store (SQLite)."""
    root_raw = getattr(args, "project_root", None)
    root = Path(str(root_raw)).resolve() if root_raw else Path.cwd().resolve()
    db_raw = getattr(args, "db_path", None)
    db_path = Path(str(db_raw)).expanduser().resolve() if db_raw else None
    full = bool(getattr(args, "full", False))
    ns = index_project_to_default_store(
        project_root=root,
        db_path=db_path or PagIndexer.default_db_path(),
        full=full,
    )
    out = PagIndexResult(
        ok=True,
        namespace=ns,
        db_path=str(db_path or PagIndexer.default_db_path()),
        project_root=str(root),
    )
    line = json.dumps(out.as_dict(), ensure_ascii=False) + "\n"
    os.write(1, line.encode())
    return 0


def _pag_slice_payload(
    *,
    namespace: str,
    db_path: Path,
    level: str | None,
    node_limit: int,
    node_offset: int,
    edge_limit: int,
    edge_offset: int,
) -> dict[str, Any]:
    store = SqlitePagStore(db_path)
    nodes = store.list_nodes(
        namespace=namespace,
        level=level,
        limit=node_limit,
        offset=node_offset,
        include_stale=True,
    )
    edges = store.list_edges(
        namespace=namespace,
        limit=edge_limit,
        offset=edge_offset,
    )
    return {
        "ok": True,
        "kind": "ailit_pag_graph_slice_v1",
        "namespace": namespace,
        "db_path": str(db_path),
        "level_filter": level,
        "nodes": [_node_json(n) for n in nodes],
        "edges": [_edge_json(e) for e in edges],
        "limits": {
            "node_limit": node_limit,
            "node_offset": node_offset,
            "edge_limit": edge_limit,
            "edge_offset": edge_offset,
        },
        "has_more": {
            "nodes": len(nodes) >= node_limit,
            "edges": len(edges) >= edge_limit,
        },
    }


def cmd_memory_pag_slice(args: object) -> int:
    """JSON slice of PAG for ailit desktop (G9.8), main bridge only."""
    namespace = str(getattr(args, "namespace", "") or "").strip()
    db_arg = getattr(args, "db_path", None)
    level_raw = getattr(args, "level", None)
    if namespace == "":
        out = {
            "ok": False,
            "kind": "ailit_pag_graph_slice_v1",
            "code": "bad_args",
            "error": "namespace required",
        }
        os.write(1, (json.dumps(out, ensure_ascii=False) + "\n").encode())
        return 2
    level: str | None
    if level_raw in (None, "", "all", "ALL"):
        level = None
    else:
        lv = str(level_raw).strip().upper()
        if lv not in ("A", "B", "C"):
            out = {
                "ok": False,
                "kind": "ailit_pag_graph_slice_v1",
                "code": "bad_args",
                "error": "level must be one of: A, B, C, all",
            }
            os.write(1, (json.dumps(out, ensure_ascii=False) + "\n").encode())
            return 2
        level = lv
    db_path = (
        Path(str(db_arg)).expanduser().resolve()
        if db_arg
        else PagIndexer.default_db_path()
    )
    if not db_path.is_file():
        out = {
            "ok": False,
            "kind": "ailit_pag_graph_slice_v1",
            "code": "missing_db",
            "error": f"sqlite not found: {db_path}",
            "namespace": namespace,
        }
        os.write(1, (json.dumps(out, ensure_ascii=False) + "\n").encode())
        return 0
    nlim = max(1, min(int(getattr(args, "node_limit", 500)), 2000))
    noff = max(0, int(getattr(args, "node_offset", 0)))
    elim = max(1, min(int(getattr(args, "edge_limit", 500)), 5000))
    eoff = max(0, int(getattr(args, "edge_offset", 0)))
    payload = _pag_slice_payload(
        namespace=namespace,
        db_path=db_path,
        level=level,
        node_limit=nlim,
        node_offset=noff,
        edge_limit=elim,
        edge_offset=eoff,
    )
    st = "ok"
    empty_page = not payload["nodes"] and not payload["edges"]
    empty_page = empty_page and noff == 0 and eoff == 0
    if empty_page:
        n1 = SqlitePagStore(db_path).list_nodes(
            namespace=namespace,
            level=None,
            limit=1,
            offset=0,
            include_stale=True,
        )
        if not n1:
            st = "empty"
    out = dict(payload)
    out["pag_state"] = st
    line = json.dumps(out, ensure_ascii=False) + "\n"
    os.write(1, line.encode())
    return 0
