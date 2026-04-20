"""Файловый журнал процесса: ``<global_logs_dir>/ailit-{chat|agent}-*.log``."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TextIO

from ailit.user_paths import global_logs_dir

ProcessLogRole = Literal["chat", "agent"]
DiagSink = Callable[[dict[str, Any]], None]

_FILE_PREFIX = "ailit"


@dataclass(frozen=True, slots=True)
class ProcessLogHandle:
    """Открытый лог и функция записи JSONL-строк диагностики."""

    path: Path
    sink: DiagSink


_state: ProcessLogHandle | None = None


def _ailit_log_dir() -> Path:
    """Каталог журналов: см. ``ailit.user_paths.global_logs_dir``."""
    d = global_logs_dir()
    return d


def _timestamp_for_filename() -> str:
    """Метка времени без двоеточий (имя файла)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _open_log_file(role: ProcessLogRole) -> tuple[Path, TextIO]:
    """Создать каталог и открыть файл лога на дозапись."""
    base = _ailit_log_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{_FILE_PREFIX}-{role}-{_timestamp_for_filename()}.log"
    handle = path.open("a", encoding="utf-8")
    return path, handle


def _make_sink(handle: TextIO) -> DiagSink:
    """Построить sink: одна JSONL-строка на вызов."""

    def _write(row: dict[str, Any]) -> None:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()

    return _write


def ensure_process_log(role: ProcessLogRole) -> ProcessLogHandle:
    """Один файл и sink на процесс; повторные вызовы — тот же handle."""
    global _state
    if _state is not None:
        return _state
    path, fh = _open_log_file(role)
    sink = _make_sink(fh)
    header: dict[str, Any] = {
        "contract": "ailit_process_log_v1",
        "event_type": "process.start",
        "role": role,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "argv": list(sys.argv),
        "log_path": str(path),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    sink(header)
    _state = ProcessLogHandle(path=path, sink=sink)
    return _state
