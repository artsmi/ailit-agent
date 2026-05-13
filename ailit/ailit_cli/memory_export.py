"""Helpers for `ailit memory` GUI: export and graph slices (G7.3)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from agent_memory.sqlite_pag import PagEdge, PagNode, SqlitePagStore


@dataclass(frozen=True, slots=True)
class PagExport:
    """Portable JSON export for GUI download."""

    kind: str
    namespace: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def build_pag_export(
    *,
    store: SqlitePagStore,
    namespace: str,
    node_limit: int = 50_000,
    edge_limit: int = 50_000,
) -> PagExport:
    ns = str(namespace).strip()
    nodes = store.list_nodes(namespace=ns, level=None, limit=int(node_limit))
    edges = store.list_edges(namespace=ns, limit=int(edge_limit))
    return PagExport(
        kind="ailit_pag_export_v1",
        namespace=ns,
        nodes=[_node_dict(n) for n in nodes],
        edges=[_edge_dict(e) for e in edges],
    )


def build_dot_for_slice(
    *,
    store: SqlitePagStore,
    namespace: str,
    center_node_id: str,
    max_edges: int = 200,
) -> str:
    """Graphviz DOT for a small adjacency slice."""
    ns = str(namespace).strip()
    cid = str(center_node_id).strip()
    if not ns or not cid:
        return "digraph G { }"
    edges = store.list_edges_touching(
        namespace=ns,
        node_ids=[cid],
        limit=int(max_edges),
    )
    node_ids: set[str] = {cid}
    for e in edges:
        node_ids.add(e.from_node_id)
        node_ids.add(e.to_node_id)
    nodes = {
        nid: store.fetch_node(namespace=ns, node_id=nid) for nid in node_ids
    }

    def _label(nid: str) -> str:
        n = nodes.get(nid)
        if n is None:
            return nid
        title = (n.title or "").strip() or nid
        lv = (n.level or "").strip()
        return f"{lv}:{title}"

    lines: list[str] = ["digraph G {"]
    lines.append('  graph [rankdir="LR"];')
    for nid in sorted(node_ids):
        lab = _escape_dot(_label(nid))
        shape = "box" if nid.startswith("B:") else "ellipse"
        if nid.startswith("C:"):
            shape = "note"
        if nid.startswith("A:"):
            shape = "oval"
        nid_esc = _escape_dot(nid)
        lines.append(
            f'  "{nid_esc}" [label="{lab}", shape="{shape}"];'
        )
    for e in edges:
        frm = _escape_dot(e.from_node_id)
        to = _escape_dot(e.to_node_id)
        et = _escape_dot(e.edge_type)
        lines.append(f'  "{frm}" -> "{to}" [label="{et}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _escape_dot(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _node_dict(n: PagNode) -> dict[str, Any]:
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


def _edge_dict(e: PagEdge) -> dict[str, Any]:
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
