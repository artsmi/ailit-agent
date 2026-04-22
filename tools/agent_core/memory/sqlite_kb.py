"""SQLite KB backend (local-first) for hybrid memory workflow."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                    author TEXT NOT NULL
                )
                """,
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS kb_records_scope "
                "ON kb_records(scope)",
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS kb_records_namespace "
                "ON kb_records(namespace)",
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
    ) -> str:
        """Insert or replace record; returns id."""
        now = _utc_now_iso()
        prov = dict(provenance) if provenance is not None else {}
        tags_t = tuple(str(x) for x in tags if str(x).strip())
        links_t = tuple(str(x) for x in links if str(x).strip())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO kb_records (
                    id, kind, scope, namespace, title, summary, body,
                    tags_json, links_json, provenance_json,
                    created_at, updated_at, author
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
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
                    author=excluded.author
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
                ),
            )
        return record_id

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

    def search(
        self,
        *,
        query: str,
        scope: str | None,
        namespace: str | None,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        """Search by LIKE over title/summary/body; returns lightweight rows."""
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
        where_sql = " AND ".join(where)
        sql = (
            "SELECT id, kind, scope, namespace, title, summary, updated_at "
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
        )
