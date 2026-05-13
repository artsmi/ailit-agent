"""SQLite PAG store (local-first) for workflow arch-graph-7 (G7.1)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from agent_memory.pag_slice_caps import (
    PAG_SLICE_MAX_EDGES,
    PAG_SLICE_MAX_NODES,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# (op, namespace, graph_rev, compact payload for UI / trace)
PagGraphTraceFn = Callable[[str, str, int, dict[str, Any]], None]


def _norm_opt_str(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _col_str(row: sqlite3.Row, key: str, default: str) -> str:
    if key not in row.keys():
        return default
    raw = row[key]
    if raw is None:
        return default
    s = str(raw).strip()
    return s if s else default


def _col_opt(row: sqlite3.Row, key: str) -> str | None:
    if key not in row.keys():
        return None
    raw = row[key]
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


@dataclass(frozen=True, slots=True)
class PagNode:
    """Normalized PAG node stored in SQLite."""

    namespace: str
    node_id: str
    level: str
    kind: str
    path: str
    title: str
    summary: str
    attrs: dict[str, Any]
    fingerprint: str
    staleness_state: str
    source_contract: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class PagEdge:
    """Normalized PAG edge stored in SQLite."""

    namespace: str
    edge_id: str
    edge_class: str
    edge_type: str
    from_node_id: str
    to_node_id: str
    confidence: float
    source_contract: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class PagPendingLinkClaim:
    """Очередь LLM link_claim до resolve (G12.8)."""

    namespace: str
    pending_id: str
    from_node_id: str
    relation: str
    target_name: str
    target_kind: str
    path_hint: str
    language: str
    confidence: float
    claim_json: str
    created_at: str


class SqlitePagStore:
    """Very small PAG store on a single SQLite file."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path.resolve()
        self._graph_trace_fn: PagGraphTraceFn | None = None
        self._ensure_parent_dir()
        self._ensure_schema()

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_parent_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self._path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS pag_nodes (
                    namespace TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    attrs_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    staleness_state TEXT NOT NULL,
                    source_contract TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, node_id)
                )
                """,
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS pag_edges (
                    namespace TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    edge_class TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    from_node_id TEXT NOT NULL,
                    to_node_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_contract TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, edge_id)
                )
                """,
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS pag_graph_rev (
                    namespace TEXT NOT NULL PRIMARY KEY,
                    graph_rev INTEGER NOT NULL DEFAULT 0
                )
                """,
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS pag_pending_edges (
                    namespace TEXT NOT NULL,
                    pending_id TEXT NOT NULL,
                    from_node_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    path_hint TEXT NOT NULL,
                    language TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    claim_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, pending_id)
                )
                """,
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS pag_pending_ns_from "
                "ON pag_pending_edges(namespace, from_node_id)",
            )
            self._migrate_columns(con, "pag_nodes")
            self._migrate_columns(con, "pag_edges")
            self._ensure_indexes(con)

    def _ensure_indexes(self, con: sqlite3.Connection) -> None:
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_nodes_namespace "
            "ON pag_nodes(namespace)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_nodes_level "
            "ON pag_nodes(namespace, level)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_nodes_path "
            "ON pag_nodes(namespace, path)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_nodes_kind "
            "ON pag_nodes(namespace, kind)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_nodes_staleness "
            "ON pag_nodes(namespace, staleness_state)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_edges_namespace "
            "ON pag_edges(namespace)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_edges_from "
            "ON pag_edges(namespace, from_node_id)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_edges_to "
            "ON pag_edges(namespace, to_node_id)",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS pag_edges_class "
            "ON pag_edges(namespace, edge_class)",
        )

    @contextmanager
    def graph_trace(self, fn: PagGraphTraceFn | None) -> Iterator[None]:
        """Временно включает колбек после успешных upsert (G12)."""
        old = self._graph_trace_fn
        self._graph_trace_fn = fn
        try:
            yield
        finally:
            self._graph_trace_fn = old

    def get_graph_rev(self, *, namespace: str) -> int:
        """Текущий монотонный rev по namespace (0 если ещё не было записей)."""
        ns = str(namespace).strip()
        if not ns:
            return 0
        with self._connect() as con:
            row = con.execute(
                "SELECT graph_rev FROM pag_graph_rev WHERE namespace = ?",
                (ns,),
            ).fetchone()
        if row is None:
            return 0
        return int(row[0] or 0)

    @staticmethod
    def _bump_graph_rev(con: sqlite3.Connection, namespace: str) -> int:
        """Инкремент rev в той же транзакции, что и DML (одно соединение)."""
        ns = str(namespace).strip()
        con.execute(
            """
            INSERT INTO pag_graph_rev (namespace, graph_rev) VALUES (?, 1)
            ON CONFLICT(namespace) DO UPDATE SET graph_rev = graph_rev + 1
            """,
            (ns,),
        )
        row = con.execute(
            "SELECT graph_rev FROM pag_graph_rev WHERE namespace = ?",
            (ns,),
        ).fetchone()
        return int(row[0] if row is not None else 0)

    def _migrate_columns(self, con: sqlite3.Connection, table: str) -> None:
        """Best-effort migrations: add new columns if missing."""
        cur = con.execute(f"PRAGMA table_info({table})")
        have = {str(r[1]) for r in cur.fetchall()}
        if table == "pag_nodes":
            specs: list[tuple[str, str]] = [
                ("namespace", "TEXT NOT NULL"),
                ("node_id", "TEXT NOT NULL"),
                ("level", "TEXT NOT NULL"),
                ("kind", "TEXT NOT NULL"),
                ("path", "TEXT NOT NULL"),
                ("title", "TEXT NOT NULL"),
                ("summary", "TEXT NOT NULL"),
                ("attrs_json", "TEXT NOT NULL"),
                ("fingerprint", "TEXT NOT NULL"),
                ("staleness_state", "TEXT NOT NULL"),
                ("source_contract", "TEXT NOT NULL"),
                ("updated_at", "TEXT NOT NULL"),
            ]
        elif table == "pag_edges":
            specs = [
                ("namespace", "TEXT NOT NULL"),
                ("edge_id", "TEXT NOT NULL"),
                ("edge_class", "TEXT NOT NULL"),
                ("edge_type", "TEXT NOT NULL"),
                ("from_node_id", "TEXT NOT NULL"),
                ("to_node_id", "TEXT NOT NULL"),
                ("confidence", "REAL NOT NULL"),
                ("source_contract", "TEXT NOT NULL"),
                ("updated_at", "TEXT NOT NULL"),
            ]
        else:
            specs = []
        for col, decl in specs:
            if col in have:
                continue
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    def upsert_node(
        self,
        *,
        namespace: str,
        node_id: str,
        level: str,
        kind: str,
        path: str,
        title: str,
        summary: str,
        attrs: Mapping[str, Any] | None,
        fingerprint: str,
        staleness_state: str = "fresh",
        source_contract: str = "ailit_pag_store_v1",
        updated_at: str | None = None,
    ) -> int:
        now = _utc_now_iso() if updated_at is None else str(updated_at)
        ns = str(namespace).strip()
        nid = str(node_id).strip()
        if not ns or not nid:
            raise ValueError("namespace и node_id обязательны")
        a = dict(attrs) if isinstance(attrs, Mapping) else {}
        st = str(staleness_state or "fresh").strip() or "fresh"
        compact = {
            "node_id": nid,
            "level": str(level),
            "kind": str(kind),
            "path": str(path),
            "title": str(title),
        }
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO pag_nodes (
                    namespace, node_id, level, kind, path, title, summary,
                    attrs_json, fingerprint, staleness_state,
                    source_contract, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?
                )
                ON CONFLICT(namespace, node_id) DO UPDATE SET
                    level=excluded.level,
                    kind=excluded.kind,
                    path=excluded.path,
                    title=excluded.title,
                    summary=excluded.summary,
                    attrs_json=excluded.attrs_json,
                    fingerprint=excluded.fingerprint,
                    staleness_state=excluded.staleness_state,
                    source_contract=excluded.source_contract,
                    updated_at=excluded.updated_at
                """,
                (
                    ns,
                    nid,
                    str(level),
                    str(kind),
                    str(path),
                    str(title),
                    str(summary),
                    json.dumps(a, ensure_ascii=False, sort_keys=True),
                    str(fingerprint),
                    st,
                    str(source_contract),
                    now,
                ),
            )
            rev = self._bump_graph_rev(con, ns)
        fn = self._graph_trace_fn
        if fn is not None:
            fn("node", ns, rev, compact)
        return rev

    def upsert_edge(
        self,
        *,
        namespace: str,
        edge_id: str,
        edge_class: str,
        edge_type: str,
        from_node_id: str,
        to_node_id: str,
        confidence: float = 1.0,
        source_contract: str = "ailit_pag_store_v1",
        updated_at: str | None = None,
    ) -> int:
        now = _utc_now_iso() if updated_at is None else str(updated_at)
        ns = str(namespace).strip()
        eid = str(edge_id).strip()
        if not ns or not eid:
            raise ValueError("namespace и edge_id обязательны")
        conf = float(confidence)
        edge_compact: dict[str, Any] = {
            "edge_id": eid,
            "edge_class": str(edge_class),
            "edge_type": str(edge_type),
            "from_node_id": str(from_node_id),
            "to_node_id": str(to_node_id),
        }
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO pag_edges (
                    namespace, edge_id, edge_class, edge_type,
                    from_node_id, to_node_id, confidence,
                    source_contract, updated_at
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?
                )
                ON CONFLICT(namespace, edge_id) DO UPDATE SET
                    edge_class=excluded.edge_class,
                    edge_type=excluded.edge_type,
                    from_node_id=excluded.from_node_id,
                    to_node_id=excluded.to_node_id,
                    confidence=excluded.confidence,
                    source_contract=excluded.source_contract,
                    updated_at=excluded.updated_at
                """,
                (
                    ns,
                    eid,
                    str(edge_class),
                    str(edge_type),
                    str(from_node_id),
                    str(to_node_id),
                    conf,
                    str(source_contract),
                    now,
                ),
            )
            rev = self._bump_graph_rev(con, ns)
        fn = self._graph_trace_fn
        if fn is not None:
            fn("edge", ns, rev, edge_compact)
        return rev

    def upsert_edges_batch(
        self,
        *,
        namespace: str,
        edges: Sequence[Mapping[str, Any]],
        updated_at: str | None = None,
    ) -> int:
        """
        Атомарно upsert рёбер: один bump rev; один trace-callback (G13.1).

        Пустой ``edges`` не меняет rev.
        """
        now = _utc_now_iso() if updated_at is None else str(updated_at)
        ns = str(namespace).strip()
        if not ns:
            raise ValueError("namespace обязателен")
        seq = [e for e in edges if isinstance(e, Mapping)]
        if not seq:
            return self.get_graph_rev(namespace=ns)
        compacts: list[dict[str, Any]] = []
        with self._connect() as con:
            for raw in seq:
                eid = str(raw.get("edge_id", "") or "").strip()
                if not eid:
                    continue
                e_class = str(raw.get("edge_class", "") or "")
                e_type = str(raw.get("edge_type", "") or "")
                from_id = str(raw.get("from_node_id", "") or "")
                to_id = str(raw.get("to_node_id", "") or "")
                if not e_class or not e_type or not from_id or not to_id:
                    continue
                try:
                    conf = float(raw.get("confidence", 1.0) or 1.0)
                except (TypeError, ValueError):
                    conf = 1.0
                s_contract = str(
                    raw.get("source_contract", "ailit_pag_store_v1")
                    or "ailit_pag_store_v1",
                )
                con.execute(
                    """
                    INSERT INTO pag_edges (
                        namespace, edge_id, edge_class, edge_type,
                        from_node_id, to_node_id, confidence,
                        source_contract, updated_at
                    ) VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?
                    )
                    ON CONFLICT(namespace, edge_id) DO UPDATE SET
                        edge_class=excluded.edge_class,
                        edge_type=excluded.edge_type,
                        from_node_id=excluded.from_node_id,
                        to_node_id=excluded.to_node_id,
                        confidence=excluded.confidence,
                        source_contract=excluded.source_contract,
                        updated_at=excluded.updated_at
                    """,
                    (
                        ns,
                        eid,
                        e_class,
                        e_type,
                        from_id,
                        to_id,
                        conf,
                        s_contract,
                        now,
                    ),
                )
                compacts.append(
                    {
                        "edge_id": eid,
                        "edge_class": e_class,
                        "edge_type": e_type,
                        "from_node_id": from_id,
                        "to_node_id": to_id,
                    },
                )
            if not compacts:
                return self.get_graph_rev(namespace=ns)
            rev = self._bump_graph_rev(con, ns)
        fn = self._graph_trace_fn
        if fn is not None:
            fn("edge_batch", ns, rev, {"edges": compacts})
        return rev

    def fetch_node(self, *, namespace: str, node_id: str) -> PagNode | None:
        ns = str(namespace).strip()
        nid = str(node_id).strip()
        if not ns or not nid:
            return None
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM pag_nodes WHERE namespace = ? AND node_id = ?",
                (ns, nid),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def list_projects(self, *, limit: int = 50) -> list[PagNode]:
        lim = max(1, min(int(limit), 500))
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM pag_nodes
                WHERE level = 'A'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def count_nodes(
        self,
        *,
        namespace: str,
        level: str | None = None,
        include_stale: bool = True,
    ) -> int:
        """Число нод в namespace (для has_more при node_limit=max, G12)."""
        ns = str(namespace).strip()
        if not ns:
            return 0
        where: list[str] = ["namespace = ?"]
        params: list[object] = [ns]
        if level is not None:
            where.append("level = ?")
            params.append(str(level))
        if not include_stale:
            where.append("staleness_state = 'fresh'")
        where_sql = " AND ".join(where)
        sql = f"SELECT COUNT(1) FROM pag_nodes WHERE {where_sql}"
        with self._connect() as con:
            row = con.execute(sql, tuple(params)).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def count_edges(
        self,
        *,
        namespace: str,
    ) -> int:
        """Число рёбер в namespace (для has_more при edge_limit=20k)."""
        ns = str(namespace).strip()
        if not ns:
            return 0
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(1) FROM pag_edges WHERE namespace = ?",
                (ns,),
            ).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def delete_all_data_for_namespace(
        self,
        *,
        namespace: str,
    ) -> dict[str, int]:
        """Remove all PAG rows for ``namespace`` (memory init / reset).

        Deletes pending edges, edges, nodes, and graph_rev for the namespace
        and returns approximate deleted row counts per table group.
        """
        ns = str(namespace).strip()
        out: dict[str, int] = {
            "pending_edges": 0,
            "edges": 0,
            "nodes": 0,
            "graph_rev": 0,
        }
        if not ns:
            return out
        with self._connect() as con:
            cur_p = con.execute(
                "DELETE FROM pag_pending_edges WHERE namespace = ?",
                (ns,),
            )
            out["pending_edges"] = int(getattr(cur_p, "rowcount", 0) or 0)
            cur_e = con.execute(
                "DELETE FROM pag_edges WHERE namespace = ?",
                (ns,),
            )
            out["edges"] = int(getattr(cur_e, "rowcount", 0) or 0)
            cur_n = con.execute(
                "DELETE FROM pag_nodes WHERE namespace = ?",
                (ns,),
            )
            out["nodes"] = int(getattr(cur_n, "rowcount", 0) or 0)
            cur_g = con.execute(
                "DELETE FROM pag_graph_rev WHERE namespace = ?",
                (ns,),
            )
            out["graph_rev"] = int(getattr(cur_g, "rowcount", 0) or 0)
        return out

    def list_nodes(
        self,
        *,
        namespace: str,
        level: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_stale: bool = True,
    ) -> list[PagNode]:
        ns = str(namespace).strip()
        if not ns:
            return []
        lim = max(1, min(int(limit), PAG_SLICE_MAX_NODES))
        off = max(0, int(offset))
        where: list[str] = ["namespace = ?"]
        params: list[object] = [ns]
        if level is not None:
            where.append("level = ?")
            params.append(str(level))
        if not include_stale:
            where.append("staleness_state = 'fresh'")
        where_sql = " AND ".join(where)
        sql = (
            f"SELECT * FROM pag_nodes WHERE {where_sql} "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([lim, off])
        with self._connect() as con:
            rows = con.execute(sql, tuple(params)).fetchall()
        return [self._row_to_node(r) for r in rows]

    def list_nodes_for_path(
        self,
        *,
        namespace: str,
        path: str,
        level: str | None = None,
        limit: int = 500,
    ) -> list[PagNode]:
        """Все ноды с данным относительным path (для C remap, G12.7)."""
        ns = str(namespace).strip()
        p = str(path or "").strip().replace("\\", "/").lstrip("./")
        if not ns or not p:
            return []
        lim = max(1, min(int(limit), PAG_SLICE_MAX_NODES))
        where: list[str] = ["namespace = ?", "path = ?"]
        params: list[object] = [ns, p]
        if level is not None:
            where.append("level = ?")
            params.append(str(level))
        where_sql = " AND ".join(where)
        sql = (
            f"SELECT * FROM pag_nodes WHERE {where_sql} "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(lim)
        with self._connect() as con:
            rows = con.execute(sql, tuple(params)).fetchall()
        return [self._row_to_node(r) for r in rows]

    def list_c_nodes_by_kind_title(
        self,
        *,
        namespace: str,
        kind: str,
        title: str,
        limit: int = 50,
    ) -> list[PagNode]:
        """C-ноды в namespace с kind+title (G12.8 resolver, без path)."""
        ns = str(namespace).strip()
        k = str(kind or "").strip()
        t = str(title or "").strip()
        if not ns or not t:
            return []
        lim = max(1, min(int(limit), 500))
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM pag_nodes
                WHERE namespace = ? AND level = 'C'
                  AND LOWER(kind) = LOWER(?) AND LOWER(title) = LOWER(?)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (ns, k, t, lim),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def list_c_nodes_by_stable_key(
        self,
        *,
        namespace: str,
        stable_key: str,
        limit: int = 32,
    ) -> list[PagNode]:
        """C-ноды с ``attrs['stable_key'] == stable_key`` (G13.5)."""
        ns = str(namespace).strip()
        sk = str(stable_key or "").strip()
        if not ns or not sk:
            return []
        lim = max(1, min(int(limit), 200))
        rows: list[sqlite3.Row] = []
        with self._connect() as con:
            try:
                rows = list(
                    con.execute(
                        """
                        SELECT * FROM pag_nodes
                        WHERE namespace = ? AND level = 'C'
                          AND json_extract(attrs_json, '$.stable_key') = ?
                        ORDER BY updated_at DESC
                        LIMIT ?
                        """,
                        (ns, sk, lim),
                    ).fetchall()
                    or []
                )
            except sqlite3.OperationalError:
                rows = []
        if rows:
            return [self._row_to_node(r) for r in rows]
        # Fallback при отсутствии JSON1
        cands = self.list_nodes(
            namespace=ns,
            level="C",
            limit=PAG_SLICE_MAX_NODES,
        )
        return [
            n
            for n in cands
            if str(n.attrs.get("stable_key", "")).strip() == sk
        ][:lim]

    def insert_pending_link_claim(
        self,
        *,
        namespace: str,
        pending_id: str,
        from_node_id: str,
        relation: str,
        target_name: str,
        target_kind: str,
        path_hint: str,
        language: str,
        confidence: float,
        claim_json: str,
    ) -> None:
        """Сохранить нерезолвенный link_claim (не graph edge)."""
        ns = str(namespace).strip()
        pid = str(pending_id).strip()
        if not ns or not pid:
            raise ValueError("namespace и pending_id обязательны")
        now = _utc_now_iso()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO pag_pending_edges (
                    namespace, pending_id, from_node_id, relation,
                    target_name, target_kind, path_hint, language,
                    confidence, claim_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, pending_id) DO UPDATE SET
                    from_node_id=excluded.from_node_id,
                    relation=excluded.relation,
                    target_name=excluded.target_name,
                    target_kind=excluded.target_kind,
                    path_hint=excluded.path_hint,
                    language=excluded.language,
                    confidence=excluded.confidence,
                    claim_json=excluded.claim_json
                """,
                (
                    ns,
                    pid,
                    str(from_node_id).strip(),
                    str(relation).strip(),
                    str(target_name).strip(),
                    str(target_kind).strip(),
                    str(path_hint or "").strip(),
                    str(language or "").strip(),
                    float(confidence),
                    str(claim_json or "{}"),
                    now,
                ),
            )

    def list_pending_link_claims(
        self,
        *,
        namespace: str,
        limit: int = 20_000,
    ) -> list[PagPendingLinkClaim]:
        """Список pending link_claim по namespace (FIFO по created_at)."""
        ns = str(namespace).strip()
        if not ns:
            return []
        lim = max(1, min(int(limit), 50_000))
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM pag_pending_edges
                WHERE namespace = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (ns, lim),
            ).fetchall()
        return [self._row_to_pending(r) for r in rows]

    def delete_pending_link_claim(
        self,
        *,
        namespace: str,
        pending_id: str,
    ) -> int:
        """Удалить pending после успешного resolve."""
        ns = str(namespace).strip()
        pid = str(pending_id).strip()
        if not ns or not pid:
            return 0
        with self._connect() as con:
            cur = con.execute(
                "DELETE FROM pag_pending_edges "
                "WHERE namespace = ? AND pending_id = ?",
                (ns, pid),
            )
        return int(getattr(cur, "rowcount", 0) or 0)

    def list_edges_touching(
        self,
        *,
        namespace: str,
        node_ids: Sequence[str],
        limit: int = 5000,
    ) -> list[PagEdge]:
        ns = str(namespace).strip()
        if not ns:
            return []
        ids = tuple(str(x).strip() for x in node_ids if str(x).strip())
        if not ids:
            return []
        lim = max(1, min(int(limit), PAG_SLICE_MAX_EDGES))
        ph = ",".join(["?"] * len(ids))
        sql = (
            "SELECT * FROM pag_edges "
            "WHERE namespace = ? AND (from_node_id IN (" + ph + ") "
            "OR to_node_id IN (" + ph + ")) "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        params: list[object] = [ns]
        params.extend(ids)
        params.extend(ids)
        params.append(lim)
        with self._connect() as con:
            rows = con.execute(sql, tuple(params)).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def list_edges(
        self,
        *,
        namespace: str,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[PagEdge]:
        """List edges by namespace (for export and GUI pagination)."""
        ns = str(namespace).strip()
        if not ns:
            return []
        lim = max(1, min(int(limit), PAG_SLICE_MAX_EDGES))
        off = max(0, int(offset))
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM pag_edges
                WHERE namespace = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (ns, lim, off),
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def mark_stale(
        self,
        *,
        namespace: str,
        node_ids: Iterable[str] | None = None,
        staleness_state: str = "stale",
    ) -> int:
        ns = str(namespace).strip()
        if not ns:
            return 0
        st = str(staleness_state or "stale").strip() or "stale"
        now = _utc_now_iso()
        ids = (
            tuple(str(x).strip() for x in node_ids if str(x).strip())
            if node_ids is not None
            else ()
        )
        with self._connect() as con:
            if not ids:
                cur = con.execute(
                    """
                    UPDATE pag_nodes
                    SET staleness_state = ?, updated_at = ?
                    WHERE namespace = ?
                    """,
                    (st, now, ns),
                )
            else:
                ph = ",".join(["?"] * len(ids))
                cur = con.execute(
                    """
                    UPDATE pag_nodes
                    SET staleness_state = ?, updated_at = ?
                    WHERE namespace = ? AND node_id IN ("""
                    + ph
                    + ")",
                    (st, now, ns, *ids),
                )
            return int(getattr(cur, "rowcount", 0) or 0)

    def delete_stale(self, *, namespace: str) -> tuple[int, int]:
        """Delete stale nodes and edges that touch deleted nodes.

        Returns:
            (deleted_nodes, deleted_edges)
        """
        ns = str(namespace).strip()
        if not ns:
            return 0, 0
        deleted_nodes = 0
        deleted_edges = 0
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT node_id FROM pag_nodes
                WHERE namespace = ? AND staleness_state != 'fresh'
                """,
                (ns,),
            ).fetchall()
            ids = [str(r["node_id"]) for r in rows]
            if not ids:
                return 0, 0
            ph = ",".join(["?"] * len(ids))
            cur_e = con.execute(
                """
                DELETE FROM pag_edges
                WHERE namespace = ?
                  AND (from_node_id IN ("""
                + ph
                + ") OR to_node_id IN ("
                + ph
                + "))",
                (ns, *ids, *ids),
            )
            deleted_edges = int(getattr(cur_e, "rowcount", 0) or 0)
            cur_n = con.execute(
                "DELETE FROM pag_nodes WHERE namespace = ? AND node_id IN ("
                + ph
                + ")",
                (ns, *ids),
            )
            deleted_nodes = int(getattr(cur_n, "rowcount", 0) or 0)
        return deleted_nodes, deleted_edges

    def delete_nodes_by_level_and_path(
        self,
        *,
        namespace: str,
        level: str,
        path: str,
    ) -> int:
        """Delete nodes by (namespace, level, path).

        Intended for incremental rebuilds (e.g. delete C nodes for a file).
        """
        ns = str(namespace).strip()
        lv = str(level).strip()
        p = str(path).strip()
        if not ns or not lv or not p:
            return 0
        with self._connect() as con:
            cur = con.execute(
                """
                DELETE FROM pag_nodes
                WHERE namespace = ? AND level = ? AND path = ?
                """,
                (ns, lv, p),
            )
            return int(getattr(cur, "rowcount", 0) or 0)

    def delete_edges_touching_node_ids(
        self,
        *,
        namespace: str,
        node_ids: Sequence[str],
    ) -> int:
        """Delete edges where from/to references any of node_ids."""
        ns = str(namespace).strip()
        if not ns:
            return 0
        ids = tuple(str(x).strip() for x in node_ids if str(x).strip())
        if not ids:
            return 0
        ph = ",".join(["?"] * len(ids))
        with self._connect() as con:
            cur = con.execute(
                """
                DELETE FROM pag_edges
                WHERE namespace = ?
                  AND (from_node_id IN ("""
                + ph
                + ") OR to_node_id IN ("
                + ph
                + "))",
                (ns, *ids, *ids),
            )
            return int(getattr(cur, "rowcount", 0) or 0)

    def delete_outgoing_edges(
        self,
        *,
        namespace: str,
        from_node_id: str,
        edge_class: str | None = None,
        edge_type: str | None = None,
    ) -> int:
        """Delete edges from ``from_node_id``; optional class/type filter."""
        ns = str(namespace).strip()
        fid = str(from_node_id or "").strip()
        if not ns or not fid:
            return 0
        where = ["namespace = ?", "from_node_id = ?"]
        params: list[object] = [ns, fid]
        if edge_class is not None:
            where.append("edge_class = ?")
            params.append(str(edge_class).strip())
        if edge_type is not None:
            where.append("edge_type = ?")
            params.append(str(edge_type).strip())
        sql = "DELETE FROM pag_edges WHERE " + " AND ".join(where)
        with self._connect() as con:
            cur = con.execute(sql, tuple(params))
            return int(getattr(cur, "rowcount", 0) or 0)

    def delete_nodes_by_ids(
        self,
        *,
        namespace: str,
        node_ids: Sequence[str],
    ) -> tuple[int, int]:
        """Delete nodes by id and edges touching them.

        Returns:
            (deleted_nodes, deleted_edges)
        """
        ns = str(namespace).strip()
        if not ns:
            return 0, 0
        ids = tuple(str(x).strip() for x in node_ids if str(x).strip())
        if not ids:
            return 0, 0
        ph = ",".join(["?"] * len(ids))
        with self._connect() as con:
            cur_e = con.execute(
                """
                DELETE FROM pag_edges
                WHERE namespace = ?
                  AND (from_node_id IN ("""
                + ph
                + ") OR to_node_id IN ("
                + ph
                + "))",
                (ns, *ids, *ids),
            )
            deleted_edges = int(getattr(cur_e, "rowcount", 0) or 0)
            cur_n = con.execute(
                "DELETE FROM pag_nodes WHERE namespace = ? AND node_id IN ("
                + ph
                + ")",
                (ns, *ids),
            )
            deleted_nodes = int(getattr(cur_n, "rowcount", 0) or 0)
        return deleted_nodes, deleted_edges

    @staticmethod
    def _row_to_pending(row: sqlite3.Row) -> PagPendingLinkClaim:
        return PagPendingLinkClaim(
            namespace=str(row["namespace"]),
            pending_id=str(row["pending_id"]),
            from_node_id=str(row["from_node_id"]),
            relation=str(row["relation"]),
            target_name=str(row["target_name"]),
            target_kind=str(row["target_kind"]),
            path_hint=str(row["path_hint"] or ""),
            language=str(row["language"] or ""),
            confidence=float(row["confidence"] or 0.0),
            claim_json=str(row["claim_json"] or "{}"),
            created_at=_col_str(row, "created_at", _utc_now_iso()),
        )

    def _row_to_node(self, row: sqlite3.Row) -> PagNode:
        try:
            attrs = json.loads(str(row["attrs_json"] or "{}"))
        except json.JSONDecodeError:
            attrs = {}
        attrs_map = dict(attrs) if isinstance(attrs, dict) else {}
        return PagNode(
            namespace=str(row["namespace"]),
            node_id=str(row["node_id"]),
            level=str(row["level"]),
            kind=str(row["kind"]),
            path=str(row["path"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            attrs=attrs_map,
            fingerprint=_col_str(row, "fingerprint", ""),
            staleness_state=_col_str(row, "staleness_state", "fresh"),
            source_contract=_col_str(
                row,
                "source_contract",
                "ailit_pag_store_v1",
            ),
            updated_at=_col_str(row, "updated_at", _utc_now_iso()),
        )

    def _row_to_edge(self, row: sqlite3.Row) -> PagEdge:
        return PagEdge(
            namespace=str(row["namespace"]),
            edge_id=str(row["edge_id"]),
            edge_class=str(row["edge_class"]),
            edge_type=str(row["edge_type"]),
            from_node_id=str(row["from_node_id"]),
            to_node_id=str(row["to_node_id"]),
            confidence=float(row["confidence"]),
            source_contract=_col_str(
                row,
                "source_contract",
                "ailit_pag_store_v1",
            ),
            updated_at=_col_str(row, "updated_at", _utc_now_iso()),
        )
