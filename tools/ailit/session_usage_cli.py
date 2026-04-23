"""CLI: ailit session usage list|show — логи и сводка usage + token-economy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ailit.token_economy_aggregates import (
    analyze_log_rows,
    build_session_summary,
)
from ailit.user_paths import global_logs_dir


def _read_jsonl_file(
    path: Path,
    *,
    max_bytes: int = 50_000_000,
) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raw = raw[-max_bytes:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    out: list[dict[str, Any]] = []
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


def print_session_show(path: Path) -> int:
    if not path.is_file():
        sys.stderr.write(f"Файл не найден: {path}\n")
        return 1
    rows = _read_jsonl_file(path)
    an = analyze_log_rows(rows)
    u = an.get("usage") or {}
    s = an.get("synthetic_est") or {}
    c = an.get("cumulative") or {}
    sys.stdout.write(f"# log: {path}\n")
    st = an.get("log_start")
    if st:
        sys.stdout.write(f"start_ts (header): {st}\n")
    n_resp = an.get("model_response_n", 0)
    sys.stdout.write(
        f"model.response событий: {n_resp}\n\n",
    )
    sys.stdout.write("## Суммарно usage (по всем model.response в файле)\n")
    inp = u.get("input_tokens")
    out_t = u.get("output_tokens")
    cr = u.get("cache_read_tokens")
    cw = u.get("cache_write_tokens")
    sys.stdout.write(
        f"  input={inp}  output={out_t}  cache_r={cr}  cache_w={cw}\n",
    )
    sys.stdout.write("\n## События механизмов (счётчики в логе)\n")
    sys.stdout.write(
        f"  pager: page_created={c.get('pager_page_created')}, "
        f"page_used={c.get('pager_page_used')}\n"
        f"  budget: событий={c.get('budget_events')}, "
        f"символов сжато~={c.get('budget_chars_saved')}\n"
        f"  prune: проходов={c.get('prune_passes')}, "
        f"tool={c.get('prune_tools')}, bytes~={c.get('prune_bytes_freed')}\n",
    )
    sys.stdout.write(
        f"  compaction: restored_files={c.get('compaction_restore_files')}, "
        f"injected_chars={c.get('compaction_restore_injected_chars')}\n",
    )
    sys.stdout.write(
        f"  tool exposure: applied={c.get('tool_exposure_applied')}, "
        f"schema_chars~={c.get('tool_exposure_schema_chars_sum')}\n",
    )
    sys.stdout.write(
        "\n## Синтетика нагрузки, снятой слоями (оценка)\n",
    )
    sys.stdout.write(
        f"  pager:   bytes≈{s.get('pager_bytes')}  "
        f"pseudo_tok~={s.get('pager_pseudo_tokens')}\n"
        f"  budget:  saved_chars={s.get('budget_chars_saved')}  "
        f"pseudo_tok~={s.get('budget_pseudo_tokens')}\n"
        f"  prune:   bytes_freed={s.get('prune_bytes_freed')}  "
        f"pseudo_tok~={s.get('prune_pseudo_tokens')}\n"
        f"  сумма псевдо-токенов (слои): {s.get('layers_sum_pseudo_tokens')}\n"
        f"  ({s.get('note', '')})\n",
    )
    return 0


def print_session_subsystem(path: Path, subsystem: str) -> int:
    """Отчёт по одной подсистеме (отдельная команда CLI)."""
    if not path.is_file():
        sys.stderr.write(f"Файл не найден: {path}\n")
        return 1
    sub = (subsystem or "").strip().lower()
    rows = _read_jsonl_file(path)
    an = analyze_log_rows(rows)
    c = an.get("cumulative") or {}
    sys.stdout.write(f"# subsystem={sub}\n# log: {path}\n\n")
    if sub in ("usage", "tokens", "model"):
        u = an.get("usage") or {}
        sys.stdout.write("## usage (суммарно по model.response)\n")
        line = (
            f"  input={u.get('input_tokens')}  "
            f"output={u.get('output_tokens')}  "
            f"cache_r={u.get('cache_read_tokens')}  "
            f"cache_w={u.get('cache_write_tokens')}\n"
        )
        sys.stdout.write(line)
        return 0
    if sub == "pager":
        sys.stdout.write("## pager (context.pager)\n")
        sys.stdout.write(
            f"  page_created={c.get('pager_page_created')}, "
            f"page_used={c.get('pager_page_used')}\n",
        )
        return 0
    if sub in ("budget", "tool-budget", "output_budget"):
        sys.stdout.write("## tool output budget\n")
        sys.stdout.write(
            f"  событий={c.get('budget_events')}, "
            f"символов сжато~={c.get('budget_chars_saved')}\n",
        )
        return 0
    if sub in ("prune", "tool_prune"):
        sys.stdout.write("## tool output prune\n")
        sys.stdout.write(
            f"  проходов={c.get('prune_passes')}, "
            f"tool={c.get('prune_tools')}, "
            f"bytes~={c.get('prune_bytes_freed')}\n",
        )
        return 0
    if sub in ("compaction", "restore", "post_compact"):
        sys.stdout.write("## post-compaction file restore\n")
        sys.stdout.write(
            f"  restored_files={c.get('compaction_restore_files')}, "
            f"injected_chars={c.get('compaction_restore_injected_chars')}\n",
        )
        return 0
    if sub in ("memory", "kb", "mcp"):
        n = 0
        n_pok = 0
        n_pden = 0
        for row in rows:
            et = row.get("event_type")
            if et == "memory.access":
                n += 1
            elif et == "memory.promotion.applied":
                n_pok += 1
            elif et == "memory.promotion.denied":
                n_pden += 1
        sys.stdout.write("## memory.access\n")
        sys.stdout.write(f"  событий: {n}\n")
        sys.stdout.write("## memory.promotion\n")
        sys.stdout.write(
            f"  applied: {n_pok}  denied: {n_pden}\n",
        )
        return 0
    if sub in ("exposure", "tools", "tool_exposure"):
        sys.stdout.write("## tool.exposure (selective schema)\n")
        sys.stdout.write(
            f"  applied={c.get('tool_exposure_applied')}, "
            f"schema_chars~={c.get('tool_exposure_schema_chars_sum')}\n",
        )
        return 0
    sys.stderr.write(
        f"Неизвестная подсистема: {subsystem!r}. "
        f"Ожидается: usage|pager|budget|prune|compaction|memory|exposure\n",
    )
    return 2


def print_session_summary(path: Path, *, as_json: bool) -> int:
    """Единый отчёт (M3): usage + подсистемы + resume_ready."""
    if not path.is_file():
        sys.stderr.write(f"Файл не найден: {path}\n")
        return 1
    rows = _read_jsonl_file(path)
    summary = build_session_summary(rows)
    if as_json:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 0
    u = summary.get("usage") or {}
    c = summary.get("cumulative") or {}
    s = summary.get("synthetic_est") or {}
    rs = summary.get("resume") or {}
    sys.stdout.write(f"# unified session summary\n# log: {path}\n")
    st = summary.get("log_start")
    if st:
        sys.stdout.write(f"start_ts (header): {st}\n")
    sys.stdout.write(
        f"resume_ready: {bool(rs.get('resume_ready'))}\n"
        f"  last_event: {rs.get('last_event_type')!r}\n"
        f"  notes: {rs.get('notes')}\n\n",
    )
    sys.stdout.write("## usage (суммарно по model.response)\n")
    uline = (
        f"  input={u.get('input_tokens')}  "
        f"output={u.get('output_tokens')}  "
        f"cache_r={u.get('cache_read_tokens')}  "
        f"cache_w={u.get('cache_write_tokens')}\n\n"
    )
    sys.stdout.write(uline)
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
        f"schema_chars~={c.get('tool_exposure_schema_chars_sum')}\n",
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
        f"  layers sum pseudo_tok: {s.get('layers_sum_pseudo_tokens')}\n",
    )
    return 0
