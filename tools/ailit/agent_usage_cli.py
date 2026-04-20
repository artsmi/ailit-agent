"""CLI: последняя сводка usage из JSONL-лога процесса ``agent``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ailit.usage_display import UsageSummaryPlainTextFormatter
from ailit.user_paths import global_logs_dir


def discover_latest_agent_log(*, logs_dir: Path | None = None) -> Path | None:
    """Новейший ailit-agent-*.log в каталоге логов или legacy ~/.ailit."""
    dirs: list[Path] = []
    if logs_dir is not None:
        dirs.append(logs_dir)
    else:
        primary = global_logs_dir()
        dirs.append(primary)
        legacy = Path.home() / ".ailit"
        legacy_logs = legacy / "logs"
        for cand in (legacy, legacy_logs):
            if cand.resolve() != primary.resolve():
                dirs.append(cand)
    best: Path | None = None
    best_mtime = -1.0
    for base in dirs:
        if not base.is_dir():
            continue
        for path in base.glob("ailit-agent-*.log"):
            m = path.stat().st_mtime
            if m > best_mtime:
                best_mtime = m
                best = path
    return best


def last_usage_pair_from_log_text(
    text: str,
) -> tuple[dict[str, object], dict[str, object]] | None:
    """Последняя пара (usage, usage_session_totals) в тексте лога."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("event_type") != "model.response":
            continue
        u = row.get("usage")
        t = row.get("usage_session_totals")
        if isinstance(u, dict) and isinstance(t, dict):
            return u, t
    return None


def last_usage_pair_from_file(
    path: Path,
    *,
    tail_chars: int = 400_000,
) -> tuple[dict[str, object], dict[str, object]] | None:
    """Прочитать хвост файла и найти последнюю пару usage."""
    raw = path.read_bytes()
    if len(raw) > tail_chars:
        raw = raw[-tail_chars:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return last_usage_pair_from_log_text(text)


def print_last_usage_from_log(explicit: Path | None) -> int:
    """Печать в stdout; код выхода 0 при успехе."""
    path = explicit or discover_latest_agent_log()
    if path is None:
        sys.stderr.write(
            "Не найдены файлы ailit-agent-*.log в "
            f"{global_logs_dir()} (или legacy ~/.ailit).\n",
        )
        return 1
    if not path.is_file():
        sys.stderr.write(f"Файл не найден: {path}\n")
        return 1
    pair = last_usage_pair_from_file(path)
    if pair is None:
        sys.stderr.write(
            f"В логе нет событий model.response с usage: {path}\n",
        )
        return 1
    lu, stt = pair
    block = UsageSummaryPlainTextFormatter().format_block(
        last_usage=lu,
        session_totals=stt,
    )
    sys.stdout.write(f"# log: {path}\n{block}")
    return 0
