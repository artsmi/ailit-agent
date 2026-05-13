"""CLI: сводка событий token-economy (pager, budget, prune) по JSONL-логу."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from ailit_cli.agent_usage_cli import discover_latest_agent_log
from ailit_cli.user_paths import global_logs_dir

_INTEREST: frozenset[str] = frozenset(
    {
        "context.pager.page_created",
        "context.pager.page_used",
        "tool.output_budget.enforced",
        "tool.output_prune.applied",
    },
)


def _parse_jsonl_path(path: Path) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    if not path.is_file():
        return out
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def token_econ_summary_from_rows(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Агрегаты по event_type (оба ключа: сырой и contract diag)."""
    c: Counter[str] = Counter()
    last: dict[str, dict[str, Any]] = {}
    for row in rows:
        et = row.get("event_type")
        if not isinstance(et, str):
            et2 = row.get("type")
            et = et2 if isinstance(et2, str) else None
        if not et:
            continue
        if et in _INTEREST:
            c[et] += 1
            if isinstance(row, dict):
                last[et] = dict(row)
    return {"counts": dict(c), "last": last}


def print_token_econ_report(
    path: Path,
) -> int:
    """Печать сводки в stdout; 0 = успех, 1 = нет файла/строк."""
    raw = _parse_jsonl_path(path)
    s = token_econ_summary_from_rows(raw)
    counts: dict[str, int] = s.get("counts") or {}
    if not any(counts.values()):
        sys.stdout.write(
            f"# log: {path}\n"
            f"Событий token-economy (pager/budget/prune) не найдено. "
            f"Проверьте, что в лог пишутся event_type, и включите:\n"
            f"  AILIT_CONTEXT_PAGER=1, AILIT_TOOL_OUTPUT_BUDGET=1, "
            f"AILIT_TOOL_PRUNE=1 (см. plan workflow-token-economy W-TE-*).\n",
        )
    else:
        sys.stdout.write(f"# log: {path}\n")
        sys.stdout.write("## Счётчики\n")
        for k in sorted(_INTEREST):
            n = int(counts.get(k, 0) or 0)
            if n:
                sys.stdout.write(f"  {k}: {n}\n")
        last = s.get("last") or {}
        if last:
            sys.stdout.write("\n## Последние payload (сжатые)\n")
            for k in sorted(_INTEREST):
                if k not in last:
                    continue
                row = last[k]
                slim = {x: row.get(x) for x in row if x in (
                    "event_type",
                    "page_id",
                    "replaced_count",
                    "pruned_tools_count",
                    "limit",
                    "total_before",
                    "total_after",
                )}
                line = json.dumps(slim, ensure_ascii=False)
                sys.stdout.write(f"  {k}: {line}\n")
    return 0


def run_token_econ_from_explicit_or_latest(explicit: Path | None) -> int:
    """Entry: путь к JSONL или последний ailit-agent-*.log в global logs."""
    p = explicit
    if p is None:
        q = discover_latest_agent_log()
        p = q
    if p is None or not p.is_file():
        gd = global_logs_dir()
        msg = (
            f"Нет JSONL-лога (--log-file) или ailit-agent-*.log в {gd}\n"
        )
        sys.stderr.write(msg)
        return 1
    return print_token_econ_report(p.resolve())
