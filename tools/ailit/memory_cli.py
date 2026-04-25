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
