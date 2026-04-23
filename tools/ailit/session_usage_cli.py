"""CLI: ailit session usage list|show — логи и сводка usage + token-economy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ailit.token_economy_aggregates import (
    build_session_summary,
    read_jsonl_session_log,
)
from ailit.user_paths import global_logs_dir


def _role_from_name(name: str) -> str:
    if "ailit-chat-" in name:
        return "chat"
    if "ailit-agent-" in name:
        return "agent"
    return "?"


def list_session_logs(logs_dir: Path | None = None) -> list[dict[str, Any]]:
    """Список файлов ailit-*.log с временем старта (первый process.start)."""
    base = (logs_dir or global_logs_dir()).resolve()
    if not base.is_dir():
        return []
    items: list[Path] = sorted(
        base.glob("ailit-*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result: list[dict[str, Any]] = []
    for path in items:
        start_ts: str | None = None
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for _ in range(32):
                    line = fh.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if row.get("event_type") == "process.start":
                        ts = row.get("ts")
                        if isinstance(ts, str):
                            start_ts = ts
                        break
        except OSError:
            start_ts = None
        st = path.stat()
        result.append(
            {
                "path": path,
                "role": _role_from_name(path.name),
                "start_ts": start_ts,
                "mtime_iso": st.st_mtime,
            },
        )
    return result


def print_session_list() -> int:
    rows = list_session_logs()
    if not rows:
        sys.stdout.write(
            f"В {global_logs_dir()} нет файлов ailit-*.log\n",
        )
        return 0
    sys.stdout.write(
        f"# каталог: {global_logs_dir()}\n"
        f"{'роль':<6} {'старт (process.start)':<32} путь\n",
    )
    for r in rows:
        p = r["path"]
        role = str(r.get("role", ""))
        ts = r.get("start_ts") or "—"
        sys.stdout.write(f"{role:<6} {str(ts)[:32]:<32} {p}\n")
    return 0


def _write_unified_summary_text_block(summary: dict[str, Any]) -> None:
    """Текстовый блок: те же цифры, что `build_session_summary` / `--json`."""
    u = summary.get("usage") or {}
    c = summary.get("cumulative") or {}
    s = summary.get("synthetic_est") or {}
    rs = summary.get("resume") or {}
    st = summary.get("log_start")
    if st:
        sys.stdout.write(f"start_ts (header): {st}\n")
    n_m = int(summary.get("model_response_n") or 0)
    sys.stdout.write(
        f"model.response событий: {n_m}\n\n",
    )
    sys.stdout.write(
        f"resume_ready: {bool(rs.get('resume_ready'))}\n"
        f"  last_event: {rs.get('last_event_type')!r}\n"
        f"  notes: {rs.get('notes')}\n\n",
    )
    sys.stdout.write("## usage (суммарно по model.response)\n")
    sys.stdout.write(
        f"  input={u.get('input_tokens')}  output={u.get('output_tokens')}  "
        f"cache_r={u.get('cache_read_tokens')}  "
        f"cache_w={u.get('cache_write_tokens')}\n\n",
    )
    sys.stdout.write("## token-economy (счётчики в логе)\n")
    sys.stdout.write(
        f"  pager: page_created={c.get('pager_page_created')}, "
        f"page_used={c.get('pager_page_used')}\n"
        f"  budget: events={c.get('budget_events')}, "
        f"saved_chars~={c.get('budget_chars_saved')}\n"
        f"  prune: passes={c.get('prune_passes')}, "
        f"tools={c.get('prune_tools')}, "
        f"bytes~={c.get('prune_bytes_freed')}\n"
        f"  compaction: files={c.get('compaction_restore_files')}, "
        f"injected_chars={c.get('compaction_restore_injected_chars')}\n"
        f"  tool exposure: applied={c.get('tool_exposure_applied')}, "
        f"schema_chars~={c.get('tool_exposure_schema_chars_sum')}, "
        f"savings~={c.get('tool_exposure_schema_savings_sum')}\n"
        f"  fs read_file: calls={c.get('fs_read_file_calls')}, "
        f"range_reads={c.get('fs_read_file_range_calls')}\n",
    )
    sys.stdout.write(
        f"  memory.access (счётчик): {rs.get('memory_access_n', 0)}\n"
        f"  memory.promotion applied={c.get('memory_promotion_applied', 0)} "
        f"denied={c.get('memory_promotion_denied', 0)}\n\n",
    )
    sys.stdout.write("## synthetic (оценка слоёв)\n")
    sys.stdout.write(
        f"  pager bytes≈{s.get('pager_bytes')}  "
        f"pseudo_tok~={s.get('pager_pseudo_tokens')}\n"
        f"  budget saved_chars={s.get('budget_chars_saved')}  "
        f"pseudo_tok~={s.get('budget_pseudo_tokens')}\n"
        f"  prune bytes_freed={s.get('prune_bytes_freed')}  "
        f"pseudo_tok~={s.get('prune_pseudo_tokens')}\n"
        f"  layers sum pseudo_tok: {s.get('layers_sum_pseudo_tokens')}\n"
        f"  ({s.get('note', '')})\n",
    )
    sub = summary.get("subsystems")
    if isinstance(sub, dict) and sub:
        sys.stdout.write(
            "\n## subsystems (срез; совпадает с JSON `subsystems`)\n",
        )
        sys.stdout.write(json.dumps(sub, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")


def print_session_show(path: Path) -> int:
    if not path.is_file():
        sys.stderr.write(f"Файл не найден: {path}\n")
        return 1
    rows = read_jsonl_session_log(path)
    sm = build_session_summary(rows)
    sys.stdout.write(
        f"# session usage show (тот же one-source, что summary)\n"
        f"# log: {path}\n",
    )
    ct = sm.get("contract")
    if ct:
        sys.stdout.write(f"contract: {ct}\n")
    sys.stdout.write("\n")
    _write_unified_summary_text_block(sm)
    return 0


def print_session_subsystem(path: Path, subsystem: str) -> int:
    """Срез одной подсистемы: summary['subsystems']."""
    if not path.is_file():
        sys.stderr.write(f"Файл не найден: {path}\n")
        return 1
    name = (subsystem or "").strip().lower()
    rows = read_jsonl_session_log(path)
    summary = build_session_summary(rows)
    subs = summary.get("subsystems")
    if not isinstance(subs, dict):
        subs = {}
    sys.stdout.write(
        f"# subsystem={name}\n# one-source: build_session_summary\n"
        f"# log: {path}\n\n",
    )
    if name in ("usage", "tokens", "model"):
        u = subs.get("usage") or {}
        sys.stdout.write("## usage (суммарно по model.response)\n")
        in_t = u.get("input_tokens")
        out_t = u.get("output_tokens")
        cr = u.get("cache_read_tokens")
        cw = u.get("cache_write_tokens")
        sys.stdout.write(
            f"  input={in_t}  output={out_t}  cache_r={cr}  cache_w={cw}\n",
        )
        return 0
    if name == "pager":
        p = subs.get("pager") or {}
        sys.stdout.write("## pager (context.pager)\n")
        sys.stdout.write(
            f"  page_created={p.get('page_created')}, "
            f"page_used={p.get('page_used')}\n",
        )
        return 0
    if name in ("budget", "tool-budget", "output_budget"):
        b = subs.get("budget") or {}
        sys.stdout.write("## tool output budget\n")
        sys.stdout.write(
            f"  событий={b.get('events')}, "
            f"символов сжато~={b.get('saved_chars')}\n",
        )
        return 0
    if name in ("prune", "tool_prune"):
        r = subs.get("prune") or {}
        sys.stdout.write("## tool output prune\n")
        sys.stdout.write(
            f"  проходов={r.get('passes')}, "
            f"tool={r.get('tools')}, "
            f"bytes~={r.get('bytes_freed')}\n",
        )
        return 0
    if name in ("compaction", "restore", "post_compact"):
        c = subs.get("compaction") or {}
        sys.stdout.write("## post-compaction file restore\n")
        sys.stdout.write(
            f"  restored_files={c.get('restored_files')}, "
            f"injected_chars={c.get('injected_chars')}\n",
        )
        return 0
    if name in ("memory", "kb", "mcp"):
        m = subs.get("memory") or {}
        sys.stdout.write("## memory (unified summary)\n")
        sys.stdout.write(
            f"  memory.access: {m.get('access_n')}\n"
            f"  memory.promotion: applied={m.get('promotion_applied')} "
            f"denied={m.get('promotion_denied')}\n",
        )
        return 0
    if name in ("exposure", "tools", "tool_exposure"):
        e = subs.get("tool_exposure") or {}
        sys.stdout.write("## tool.exposure (selective schema)\n")
        sys.stdout.write(
            f"  applied={e.get('applied')}, "
            f"schema_chars~={e.get('schema_chars_sum')}, "
            f"savings~={e.get('schema_savings_sum')}\n",
        )
        return 0
    if name in ("fs", "read_file", "fs_read"):
        f = subs.get("fs") or {}
        sys.stdout.write("## fs (события fs.read_file.completed)\n")
        sys.stdout.write(
            f"  read_file calls={f.get('read_file_calls')}, "
            f"range_reads={f.get('read_file_range_calls')}\n",
        )
        return 0
    sys.stderr.write(
        f"Неизвестная подсистема: {subsystem!r}. "
        f"Ожидается: usage|pager|budget|prune|compaction|memory|exposure|fs\n",
    )
    return 2


def print_session_summary(path: Path, *, as_json: bool) -> int:
    """Единый отчёт (M3): usage + подсистемы + resume_ready."""
    if not path.is_file():
        sys.stderr.write(f"Файл не найден: {path}\n")
        return 1
    rows = read_jsonl_session_log(path)
    summary = build_session_summary(rows)
    if as_json:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 0
    sys.stdout.write(
        f"# unified session summary\n# log: {path}\n",
    )
    ct = summary.get("contract")
    if ct:
        sys.stdout.write(f"contract: {ct}\n\n")
    _write_unified_summary_text_block(summary)
    return 0
