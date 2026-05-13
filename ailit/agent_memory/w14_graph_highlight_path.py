"""M1: построение `node_ids` / `edge_ids` для W14
`memory.w14.graph_highlight` (2.2).

M1 (детерминизм, приоритет **перед** полным BFS):
1) **Containment-дерево (роль parent в PAG):** если в каждом шаге
   вверх от целевой ноды к `A` по рёбрам
   `edge_class == "containment"` /
   `to_node == current` в точности **один** родитель —
   используем этот единственный путь.
2) **Иначе:** BFS в **неориентированном** виде
   (ребро соединяет `from` и `to`) от
   `A:{namespace}` к целевой ноде. Кратчайшая длина; на равенстве расстояния
   **tie-break** при *первом* открытии: соседи сортируются по
   `(neighbor_id, edge_id)`; очередь FIFO, как в обычном BFS.
3) **Store недоступен / путь не найден:** устойчивая цепочка по
   `A` + иерархия путей `B` по `PagNode.path` (для C — после B-цепи).

Без O(N) полного перебора PAG: только `list_edges_touching` по волнам BFS
или один проход upwalk, плюс точечные `fetch_node` при fallback.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_memory.sqlite_pag import SqlitePagStore

_CONTAINMENT: Final = "containment"
_CONTAINS: Final = "contains"


@dataclass(frozen=True, slots=True)
class W14GraphHighlightPath:
    """Id для `emit_w14_graph_highlight` (схема не менялась)."""

    node_ids: list[str]
    edge_ids: list[str]


def a_node_id(namespace: str) -> str:
    return f"A:{str(namespace or '').strip()}"


def _norm_rel_path(raw: str) -> str:
    return str(raw or "").replace("\\", "/").strip().lstrip("./")


def b_node_id_from_path(rel: str) -> str:
    return f"B:{_norm_rel_path(rel)}"


def _edge_id(
    edge_class: str, edge_type: str, from_id: str, to_id: str,
) -> str:
    raw = f"{edge_class}:{edge_type}:{from_id}->{to_id}"
    h = hashlib.sha1(
        raw.encode("utf-8", errors="replace"),
    ).hexdigest()[:16]
    return f"e:{h}"


def _b_chain_node_ids(namespace: str, rel: str) -> list[str]:
    a_id = a_node_id(namespace)
    nrel = _norm_rel_path(rel)
    if not nrel:
        return [a_id]
    parent = Path(nrel).parent.as_posix()
    dirs: list[str] = []
    while parent and parent != ".":
        dirs.append(parent)
        parent = Path(parent).parent.as_posix()
    dirs.reverse()
    out: list[str] = [a_id]
    for d in dirs:
        out.append(b_node_id_from_path(d))
    out.append(b_node_id_from_path(nrel))
    return out


def _pairwise_edge_ids(
    node_ids: Sequence[str], edge_class: str, edge_type: str,
) -> list[str]:
    eids: list[str] = []
    for i in range(len(node_ids) - 1):
        a, b = node_ids[i], node_ids[i + 1]
        eids.append(
            _edge_id(edge_class, edge_type, a, b),
        )
    return eids


def _neighbors_sorted(
    store: SqlitePagStore, namespace: str, u: str,
) -> list[tuple[str, str]]:
    raw = store.list_edges_touching(namespace=namespace, node_ids=[u])
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for e in raw:
        a, b = e.from_node_id, e.to_node_id
        if a == b:
            continue
        nbr: str
        if a == u and b != u:
            nbr = b
        elif b == u and a != u:
            nbr = a
        else:
            continue
        tkey = (nbr, e.edge_id)
        if tkey in seen:
            continue
        seen.add(tkey)
        out.append((nbr, e.edge_id))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def _upwalk_containment(
    store: SqlitePagStore, namespace: str, a_id: str, end_id: str,
) -> W14GraphHighlightPath | None:
    if end_id == a_id:
        return W14GraphHighlightPath([a_id], [])
    cur = end_id
    nodes_r: list[str] = [cur]
    edges_r: list[str] = []
    seen: set[str] = {end_id}
    for _ in range(8192):
        if cur == a_id:
            nrev = list(reversed(nodes_r))
            erev = list(reversed(edges_r))
            return W14GraphHighlightPath(nrev, erev)
        parents: list[tuple[str, str]] = []
        for e in store.list_edges_touching(
            namespace=namespace, node_ids=[cur],
        ):
            if e.from_node_id == e.to_node_id:
                continue
            if e.to_node_id != cur:
                continue
            if e.edge_class != _CONTAINMENT:
                continue
            parents.append((e.from_node_id, e.edge_id))
        if len(parents) != 1:
            return None
        p, eid = parents[0]
        if p in seen:
            return None
        seen.add(p)
        cur = p
        nodes_r.append(p)
        edges_r.append(eid)
    return None


def _bfs_shortest_m1(
    store: SqlitePagStore, namespace: str, a_id: str, end_id: str,
) -> W14GraphHighlightPath | None:
    if end_id == a_id:
        return W14GraphHighlightPath([a_id], [])
    q: deque[str] = deque([a_id])
    parent: dict[str, tuple[str, str]] = {}
    visited: set[str] = {a_id}
    while q:
        u = q.popleft()
        for v, eid in _neighbors_sorted(store, namespace, u):
            if v in visited:
                continue
            if v == a_id:
                continue
            visited.add(v)
            parent[v] = (u, eid)
            if v == end_id:
                node_ids: list[str] = []
                edge_ids: list[str] = []
                cur = v
                while cur != a_id:
                    p, pe = parent[cur]
                    edge_ids.append(pe)
                    node_ids.append(cur)
                    cur = p
                node_ids.append(a_id)
                node_ids.reverse()
                edge_ids.reverse()
                return W14GraphHighlightPath(node_ids, edge_ids)
            q.append(v)
    return None


def _fallback_synthetic(
    store: SqlitePagStore, namespace: str, end_id: str,
) -> W14GraphHighlightPath:
    a = a_node_id(namespace)
    s = str(end_id or "").strip()
    if not s:
        return W14GraphHighlightPath([], [])
    n = store.fetch_node(namespace=namespace, node_id=s)
    if n is None:
        if s == a:
            return W14GraphHighlightPath([a], [])
        return W14GraphHighlightPath([a, s], [])
    if n.level == "A" or s == a:
        return W14GraphHighlightPath([a], [])
    rel = _norm_rel_path(n.path)
    b_chain = (
        _b_chain_node_ids(namespace, rel)
        if n.level in ("B", "C")
        else [a]
    )
    if n.level == "B":
        eids = _pairwise_edge_ids(
            b_chain, _CONTAINMENT, _CONTAINS,
        )
        return W14GraphHighlightPath(b_chain, eids)
    if n.level == "C":
        if b_chain and b_chain[-1] == b_node_id_from_path(rel):
            base = b_chain
        else:
            base = _b_chain_node_ids(namespace, rel)
        c_last = s
        if base and base[-1] == c_last:
            nids = base
        else:
            nids = list(base) + [c_last]
        eids = _pairwise_edge_ids(nids, _CONTAINMENT, _CONTAINS)
        return W14GraphHighlightPath(nids, eids)
    nids2 = b_chain if b_chain else [a, s]
    eids2 = _pairwise_edge_ids(
        nids2, _CONTAINMENT, _CONTAINS,
    ) if len(nids2) > 1 else []
    return W14GraphHighlightPath(nids2, eids2)


class W14GraphHighlightPathBuilder:
    """Единая точка: highlight-путь (A → … → целевая ноды)."""

    @staticmethod
    def path_to_end(
        store: SqlitePagStore, namespace: str, end_id: str,
    ) -> W14GraphHighlightPath:
        """M1: путь от A-node до `end_id` (namespace в builder)."""
        a_id = a_node_id(namespace)
        t = str(end_id or "").strip()
        if not t:
            return W14GraphHighlightPath([], [])
        u = _upwalk_containment(store, namespace, a_id, t)
        if u is not None:
            return u
        b = _bfs_shortest_m1(store, namespace, a_id, t)
        if b is not None:
            return b
        return _fallback_synthetic(store, namespace, t)

    @staticmethod
    def union_to_ends(
        store: SqlitePagStore, namespace: str, end_node_ids: Sequence[str],
    ) -> W14GraphHighlightPath:
        """Объединяет пути; порядок — первое вхождение ноды."""
        if not end_node_ids:
            return W14GraphHighlightPath([], [])
        out_n: list[str] = []
        out_e: list[str] = []
        n_seen: set[str] = set()
        e_seen: set[str] = set()
        for end_nid in end_node_ids:
            sub = W14GraphHighlightPathBuilder.path_to_end(
                store, namespace, str(end_nid or "").strip(),
            )
            for x in sub.node_ids:
                if x not in n_seen:
                    n_seen.add(x)
                    out_n.append(x)
            for e in sub.edge_ids:
                if e not in e_seen:
                    e_seen.add(e)
                    out_e.append(e)
        return W14GraphHighlightPath(out_n, out_e)
