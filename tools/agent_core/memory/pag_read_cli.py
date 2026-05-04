"""CLI для чтения локальной PAG SQLite (см. ``scripts/pag-read``)."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


def _db_path_from_env() -> Path:
    raw = (
        os.environ.get("PAG_READ_DB", "").strip()
        or os.environ.get("AILIT_PAG_DB_PATH", "").strip()
    )
    if not raw:
        msg = (
            "Задайте PAG_READ_DB или AILIT_PAG_DB_PATH "
            "(см. scripts/pag-read)."
        )
        print(msg, file=sys.stderr)
        sys.exit(2)
    return Path(raw).expanduser().resolve()


def cmd_count_nodes(db_path: Path) -> int:
    """Печатает количество нод по уровню и по паре level+kind."""
    if not db_path.is_file():
        print(f"PAG файл не найден: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name = 'pag_nodes'
            """,
        )
        if cur.fetchone() is None:
            print("В базе нет таблицы pag_nodes.", file=sys.stderr)
            return 1

        rows = con.execute(
            """
            SELECT namespace, level, kind, COUNT(*) AS cnt
            FROM pag_nodes
            GROUP BY namespace, level, kind
            ORDER BY namespace, level, kind
            """,
        ).fetchall()
    finally:
        con.close()

    by_level: dict[str, int] = defaultdict(int)
    by_ns_level: dict[tuple[str, str], int] = defaultdict(int)
    total = 0
    for ns, level, _kind, cnt in rows:
        by_level[str(level)] += int(cnt)
        by_ns_level[(str(ns), str(level))] += int(cnt)
        total += int(cnt)

    print(f"database: {db_path}")
    print(f"total nodes: {total}")
    print()
    print("by level (all namespaces):")
    for lv in sorted(by_level.keys()):
        print(f"  {lv}: {by_level[lv]}")
    print()
    print("by namespace and level:")
    for (ns, lv) in sorted(by_ns_level.keys()):
        print(f"  [{ns}] {lv}: {by_ns_level[(ns, lv)]}")
    print()
    print("by namespace, level, kind:")
    for ns, level, kind, cnt in rows:
        print(f"  [{ns}] {level}/{kind}: {cnt}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PAG read-only CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_count = sub.add_parser(
        "count-nodes",
        help="Считать ноды по level/kind/namespace",
    )
    p_count.set_defaults(func=_run_count_nodes)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _run_count_nodes(_args: argparse.Namespace) -> int:
    return cmd_count_nodes(_db_path_from_env())


if __name__ == "__main__":
    raise SystemExit(main())
