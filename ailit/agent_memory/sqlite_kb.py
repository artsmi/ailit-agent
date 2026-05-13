"""SQLite KB backend (local-first) for hybrid memory workflow."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from agent_memory.kb_temporal import sql_active_temporal


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
class KbRecord:
    """Normalized KB record stored in SQLite."""

    id: str
    kind: str
    scope: str
    namespace: str
    title: str
    summary: str
    body: str
    tags: tuple[str, ...]
    links: tuple[str, ...]
    provenance: dict[str, Any]
    created_at: str
    updated_at: str
    author: str
    memory_layer: str
    valid_from: str | None
    valid_to: str | None
    supersedes_id: str | None
    source: str | None
    episode_id: str | None
    promotion_status: str


class SqliteKb:
    """Very small KB: write/search/fetch on a single SQLite file."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path.resolve()
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
        return con

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_records (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    links_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    author TEXT NOT NULL,
                    memory_layer TEXT NOT NULL DEFAULT 'semantic',
                    valid_from TEXT,
                    valid_to TEXT,
                    supersedes_id TEXT,
                    source TEXT,
                    episode_id TEXT,
                    promotion_status TEXT NOT NULL DEFAULT 'draft'
                )
                """,
            )
            self._migrate_columns(con)
            con.execute(
                "CREATE INDEX IF NOT EXISTS kb_records_scope "
                "ON kb_records(scope)",
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS kb_records_namespace "
                "ON kb_records(namespace)",
            )

            # Optional acceleration layer (rebuildable).
            self._ensure_fts_schema(con)

    def _ensure_fts_schema(self, con: sqlite3.Connection) -> None:
        """Создать структуру для FTS5, если SQLite её поддерживает."""
        try:
            con.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_records_fts
                USING fts5(id, title, summary, body)
                """,
            )
        except sqlite3.OperationalError:
            # FTS5 может быть отключён в сборке SQLite.
            return

    def rebuild_fts_index(self) -> bool:
        """Пересобрать acceleration index (FTS5/BM25).

        Не является SoT: источник истины — kb_records.
        """
        with self._connect() as con:
            try:
                self._ensure_fts_schema(con)
                con.execute("DELETE FROM kb_records_fts")
                con.execute(
                    """
                    INSERT INTO kb_records_fts(id, title, summary, body)
                    SELECT id, title, summary, body FROM kb_records
                    """,
                )
                # Validate bm25() availability for this build.
                con.execute(
                    "SELECT bm25(kb_records_fts) FROM kb_records_fts LIMIT 1",
                ).fetchone()
            except sqlite3.OperationalError:
                return False
        return True

    def apply_ttl_to_deprecated(self, *, valid_to_iso: str) -> tuple[int, int]:
        """Проставить valid_to для deprecated записей без valid_to.

        Returns:
            (scanned, updated)
        """
        scanned = 0
        updated = 0
        vt = str(valid_to_iso).strip()
        if not vt:
            return 0, 0
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, promotion_status, valid_to
                FROM kb_records
                WHERE promotion_status = 'deprecated'
                """,
            ).fetchall()
            scanned = len(rows)
            for r in rows:
                rid = str(r["id"])
                cur_vt = r["valid_to"]
                if cur_vt is not None and str(cur_vt).strip():
                    continue
                con.execute(
                    """
                    UPDATE kb_records
                    SET valid_to = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (vt, _utc_now_iso(), rid),
                )
                updated += 1
        return scanned, updated

    def count_records_for_namespace(self, *, namespace: str) -> int:
        """Return KB row count for ``namespace``."""
        ns = str(namespace).strip()
        if not ns:
            return 0
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS c FROM kb_records WHERE namespace = ?",
                (ns,),
            ).fetchone()
        return int(row["c"] if row is not None else 0)

    def delete_all_for_namespace(self, *, namespace: str) -> int:
        """Delete all KB records for ``namespace``; sync FTS if present."""
        ns = str(namespace).strip()
        if not ns:
            return 0
        deleted = 0
        with self._connect() as con:
            try:
                con.execute(
                    """
                    DELETE FROM kb_records_fts
                    WHERE id IN (
                        SELECT id FROM kb_records WHERE namespace = ?
                    )
                    """,
                    (ns,),
                )
            except sqlite3.OperationalError:
                pass
            cur = con.execute(
                "DELETE FROM kb_records WHERE namespace = ?",
                (ns,),
            )
            deleted = int(getattr(cur, "rowcount", 0) or 0)
            con.commit()
        return deleted

    def append_audit_event(
        self,
        *,
        record_id: str,
        event: Mapping[str, Any],
    ) -> bool:
        """Append audit event into provenance_json['audit'] list."""
        rid = str(record_id or "").strip()
        if not rid:
            return False
        ev = dict(event) if isinstance(event, Mapping) else {}
        with self._connect() as con:
            row = con.execute(
                "SELECT provenance_json FROM kb_records WHERE id = ?",
                (rid,),
            ).fetchone()
            if row is None:
                return False
            try:
                prov = json.loads(str(row["provenance_json"] or "{}"))
            except json.JSONDecodeError:
                prov = {}
            if not isinstance(prov, dict):
                prov = {}
            audit = prov.get("audit")
            items: list[object] = audit if isinstance(audit, list) else []
            items.append(ev)
            prov["audit"] = items
            con.execute(
                """
                UPDATE kb_records
                SET provenance_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(prov, ensure_ascii=False), _utc_now_iso(), rid),
            )
        return True

    def _migrate_columns(self, con: sqlite3.Connection) -> None:
        """Добавить колонки M3 (temporal/provenance) к старым БД."""
        cur = con.execute("PRAGMA table_info(kb_records)")
        have = {str(r[1]) for r in cur.fetchall()}
        specs: list[tuple[str, str]] = [
            ("memory_layer", "TEXT NOT NULL DEFAULT 'semantic'"),
            ("valid_from", "TEXT"),
            ("valid_to", "TEXT"),
            ("supersedes_id", "TEXT"),
            ("source", "TEXT"),
            ("episode_id", "TEXT"),
            ("promotion_status", "TEXT NOT NULL DEFAULT 'draft'"),
        ]
        for col, decl in specs:
            if col in have:
                continue
            con.execute(
                f"ALTER TABLE kb_records ADD COLUMN {col} {decl}",
            )

    def write(
        self,
        *,
        record_id: str,
        kind: str,
        scope: str,
        namespace: str,
        title: str,
        summary: str,
        body: str,
        tags: Iterable[str] = (),
        links: Iterable[str] = (),
        provenance: Mapping[str, Any] | None = None,
        author: str = "agent",
        memory_layer: str = "semantic",
        valid_from: str | None = None,
        valid_to: str | None = None,
        supersedes_id: str | None = None,
        source: str | None = None,
        episode_id: str | None = None,
        promotion_status: str = "draft",
    ) -> str:
        """Insert or replace record; returns id."""
        now = _utc_now_iso()
        prov = dict(provenance) if provenance is not None else {}
        tags_t = tuple(str(x) for x in tags if str(x).strip())
        links_t = tuple(str(x) for x in links if str(x).strip())
        ml = str(memory_layer or "semantic").strip() or "semantic"
        ps = str(promotion_status or "draft").strip() or "draft"
        vf = _norm_opt_str(valid_from)
        vt = _norm_opt_str(valid_to)
        sid = _norm_opt_str(supersedes_id)
        src = _norm_opt_str(source)
        ep = _norm_opt_str(episode_id)
        with self._connect() as con:
            ex_row = con.execute(
                "SELECT promotion_status FROM kb_records WHERE id = ?",
                (str(record_id),),
            ).fetchone()
            if ex_row is not None:
                ex_ps = str(ex_row[0] or "draft").strip().lower() or "draft"
                if ex_ps == "superseded":
                    msg = f"запись {record_id!r} superseded; правки запрещены"
                    raise ValueError(msg)
                if ps == "draft" and ex_ps != "draft":
                    ps = ex_ps
            if sid is not None:
                ex = con.execute(
                    "SELECT id FROM kb_records WHERE id = ?",
                    (sid,),
                ).fetchone()
                if ex is not None:
                    con.execute(
                        """
                        UPDATE kb_records
                        SET valid_to = ?,
                            promotion_status = 'superseded',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now, now, sid),
                    )
            con.execute(
                """
                INSERT INTO kb_records (
                    id, kind, scope, namespace, title, summary, body,
                    tags_json, links_json, provenance_json,
                    created_at, updated_at, author,
                    memory_layer, valid_from, valid_to, supersedes_id,
                    source, episode_id, promotion_status
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    scope=excluded.scope,
                    namespace=excluded.namespace,
                    title=excluded.title,
                    summary=excluded.summary,
                    body=excluded.body,
                    tags_json=excluded.tags_json,
                    links_json=excluded.links_json,
                    provenance_json=excluded.provenance_json,
                    updated_at=excluded.updated_at,
                    author=excluded.author,
                    memory_layer=excluded.memory_layer,
                    valid_from=excluded.valid_from,
                    valid_to=excluded.valid_to,
                    supersedes_id=excluded.supersedes_id,
                    source=excluded.source,
                    episode_id=excluded.episode_id,
                    promotion_status=excluded.promotion_status
                """,
                (
                    record_id,
                    kind,
                    scope,
                    namespace,
                    title,
                    summary,
                    body,
                    json.dumps(list(tags_t), ensure_ascii=False),
                    json.dumps(list(links_t), ensure_ascii=False),
                    json.dumps(prov, ensure_ascii=False),
                    now,
                    now,
                    str(author),
                    ml,
                    vf,
                    vt,
                    sid,
                    src,
                    ep,
                    ps,
                ),
            )
        return record_id

    def update_record_promotion(
        self,
        record_id: str,
        promotion_status: str,
    ) -> bool:
        """Обновить ``promotion_status`` и ``updated_at``."""
        now = _utc_now_iso()
        st = str(promotion_status or "draft").strip() or "draft"
        with self._connect() as con:
            cur = con.execute(
                """
                UPDATE kb_records
                SET promotion_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (st, now, str(record_id)),
            )
            return int(getattr(cur, "rowcount", 0) or 0) > 0

    def fetch(self, record_id: str) -> KbRecord | None:
        """Fetch record by id."""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM kb_records WHERE id = ?",
                (str(record_id),),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_recent_by_kind(
        self,
        *,
        kind: str,
        namespace: str | None = None,
        limit: int = 20,
    ) -> list[KbRecord]:
        """Последние записи по kind (для истории классификатора perm-5)."""
        k = str(kind or "").strip()
        if not k:
            return []
        lim = max(1, min(int(limit), 100))
        ns_raw = str(namespace or "").strip()
        if ns_raw:
            sql = (
                "SELECT * FROM kb_records WHERE kind = ? AND namespace = ? "
                "ORDER BY updated_at DESC LIMIT ?"
            )
            params: tuple[object, ...] = (k, ns_raw, lim)
        else:
            sql = (
                "SELECT * FROM kb_records WHERE kind = ? "
                "ORDER BY updated_at DESC LIMIT ?"
            )
            params = (k, lim)
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def search(
        self,
        *,
        query: str,
        scope: str | None,
        namespace: str | None,
        top_k: int = 8,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        """Search by LIKE over title/summary/body; returns lightweight rows.

        Acceleration layer (FTS5/BM25) может быть подключён отдельно
        (rebuildable) и используется только при явном вызове
        :meth:`search_fts`.
        """
        q = str(query or "").strip()
        if not q:
            return []
        k = max(1, min(int(top_k), 50))
        like = f"%{q}%"
        where: list[str] = ["(title LIKE ? OR summary LIKE ? OR body LIKE ?)"]
        params: list[object] = [like, like, like]
        if scope:
            where.append("scope = ?")
            params.append(str(scope))
        if namespace:
            where.append("namespace = ?")
            params.append(str(namespace))
        if not include_expired:
            tclause, tparams = sql_active_temporal(_utc_now_iso())
            where.append(tclause)
            params.extend(tparams)
        where_sql = " AND ".join(where)
        sql = (
            "SELECT id, kind, scope, namespace, title, summary, updated_at, "
            "memory_layer, valid_from, valid_to, promotion_status "
            f"FROM kb_records WHERE {where_sql} "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(k)
        with self._connect() as con:
            rows = con.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": str(r["id"]),
                    "kind": str(r["kind"]),
                    "scope": str(r["scope"]),
                    "namespace": str(r["namespace"]),
                    "title": str(r["title"]),
                    "summary": str(r["summary"]),
                    "updated_at": str(r["updated_at"]),
                    "memory_layer": str(r["memory_layer"]),
                    "valid_from": r["valid_from"],
                    "valid_to": r["valid_to"],
                    "promotion_status": str(r["promotion_status"]),
                },
            )
        return out

    def search_fts(
        self,
        *,
        query: str,
        scope: str | None,
        namespace: str | None,
        top_k: int = 8,
    ) -> list[dict[str, Any]] | None:
        """FTS5/BM25 search (если доступно), иначе None."""
        q = str(query or "").strip()
        if not q:
            return []
        k = max(1, min(int(top_k), 50))
        where: list[str] = ["kb_records_fts MATCH ?"]
        params: list[object] = [q]
        if scope:
            where.append("r.scope = ?")
            params.append(str(scope))
        if namespace:
            where.append("r.namespace = ?")
            params.append(str(namespace))
        where_sql = " AND ".join(where)
        sql = (
            "SELECT r.id, r.kind, r.scope, r.namespace, r.title, r.summary, "
            "r.updated_at, r.memory_layer, r.valid_from, r.valid_to, "
            "r.promotion_status "
            "FROM kb_records_fts f "
            "JOIN kb_records r ON r.id = f.id "
            f"WHERE {where_sql} "
            "ORDER BY bm25(kb_records_fts) LIMIT ?"
        )
        params.append(k)
        with self._connect() as con:
            try:
                rows = con.execute(sql, tuple(params)).fetchall()
            except sqlite3.OperationalError:
                return None
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": str(r["id"]),
                    "kind": str(r["kind"]),
                    "scope": str(r["scope"]),
                    "namespace": str(r["namespace"]),
                    "title": str(r["title"]),
                    "summary": str(r["summary"]),
                    "updated_at": str(r["updated_at"]),
                    "memory_layer": str(r["memory_layer"]),
                    "valid_from": r["valid_from"],
                    "valid_to": r["valid_to"],
                    "promotion_status": str(r["promotion_status"]),
                },
            )
        return out

    def _row_to_record(self, row: sqlite3.Row) -> KbRecord:
        tags = json.loads(str(row["tags_json"] or "[]"))
        links = json.loads(str(row["links_json"] or "[]"))
        prov = json.loads(str(row["provenance_json"] or "{}"))
        return KbRecord(
            id=str(row["id"]),
            kind=str(row["kind"]),
            scope=str(row["scope"]),
            namespace=str(row["namespace"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            body=str(row["body"]),
            tags=tuple(str(x) for x in tags if str(x).strip()),
            links=tuple(str(x) for x in links if str(x).strip()),
            provenance=dict(prov) if isinstance(prov, dict) else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            author=str(row["author"]),
            memory_layer=_col_str(row, "memory_layer", "semantic"),
            valid_from=_col_opt(row, "valid_from"),
            valid_to=_col_opt(row, "valid_to"),
            supersedes_id=_col_opt(row, "supersedes_id"),
            source=_col_opt(row, "source"),
            episode_id=_col_opt(row, "episode_id"),
            promotion_status=_col_str(row, "promotion_status", "draft"),
        )
