"""CLI: KB governance tools (M4-5)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_memory.kb.kb_tools import kb_tools_config_from_env
from agent_memory.storage.sqlite_kb import SqliteKb


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_days(raw: object, default: int) -> int:
    try:
        v = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        v = int(default)
    return max(0, v)


@dataclass(frozen=True, slots=True)
class KbTtlApplyResult:
    """Result for applying TTL rules to deprecated facts."""

    scanned: int
    updated: int
    now_iso: str
    ttl_days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": int(self.scanned),
            "updated": int(self.updated),
            "now_iso": str(self.now_iso),
            "ttl_days": int(self.ttl_days),
        }


def cmd_kb_ttl_apply(args: object) -> int:
    """Apply TTL to deprecated records by setting valid_to."""
    ttl_days = _parse_days(getattr(args, "ttl_days", None), 30)
    cfg = kb_tools_config_from_env()
    kb = SqliteKb(cfg.db_path)
    now_iso = _utc_now_iso()
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    scanned, updated = kb.apply_ttl_to_deprecated(
        valid_to_iso=cutoff.isoformat(),
    )
    out = KbTtlApplyResult(
        scanned=scanned,
        updated=updated,
        now_iso=now_iso,
        ttl_days=ttl_days,
    )
    line = json.dumps(out.as_dict(), ensure_ascii=False) + "\n"
    os.write(1, line.encode())
    return 0


def cmd_kb_rebuild_index(args: object) -> int:
    """Rebuild acceleration index (FTS5/BM25) if supported."""
    cfg = kb_tools_config_from_env()
    kb = SqliteKb(cfg.db_path)
    ok = kb.rebuild_fts_index()
    payload = {"ok": bool(ok), "db_path": str(cfg.db_path)}
    os.write(1, (json.dumps(payload, ensure_ascii=False) + "\n").encode())
    return 0 if ok else 2


def cmd_kb_dump_audit(args: object) -> int:
    """Dump audit trail for a record id."""
    rid = str(getattr(args, "id", "") or "").strip()
    if not rid:
        return 2
    cfg = kb_tools_config_from_env()
    kb = SqliteKb(cfg.db_path)
    rec = kb.fetch(rid)
    payload: dict[str, Any] = {"id": rid, "found": rec is not None}
    if rec is not None:
        payload["audit"] = rec.provenance.get("audit")
    os.write(1, (json.dumps(payload, ensure_ascii=False) + "\n").encode())
    return 0
