"""Хранилище записей shell для Streamlit chat (этап D.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping

from agent_core.shell_invocation_record import ShellInvocationRecord
from agent_core.shell_output_preview import DetachedViewHeuristic

SESSION_KEY_RUNS = "ailit_bash_runs"
SESSION_KEY_VIEW_LINES = "ailit_bash_view_tail_lines"
SESSION_KEY_SELECTED = "ailit_bash_selected_call_id"
SESSION_KEY_CHAT_TAIL_LINES = "ailit_bash_chat_tail_lines"
_MAX_RUNS_DEFAULT = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def runs_list(store: MutableMapping[str, Any]) -> list[dict[str, Any]]:
    """Список dict записей (копия для безопасной итерации)."""
    raw = store.get(SESSION_KEY_RUNS)
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


def chat_tail_lines(store: MutableMapping[str, Any]) -> int:
    """N строк превью прямо в чате (по умолчанию 5)."""
    raw = store.get(SESSION_KEY_CHAT_TAIL_LINES)
    if isinstance(raw, int) and raw >= 1:
        return min(raw, 200)
    return 5


def set_chat_tail_lines(store: MutableMapping[str, Any], n: int) -> None:
    """Установить N строк превью прямо в чате."""
    store[SESSION_KEY_CHAT_TAIL_LINES] = max(1, min(int(n), 200))


def upsert_running_call(
    store: MutableMapping[str, Any],
    *,
    call_id: str,
    command: str,
    tool_name: str,
) -> None:
    """Создать/обновить запись вызова, пока он в процессе."""
    lst = store.setdefault(SESSION_KEY_RUNS, [])
    if not isinstance(lst, list):
        lst = []
        store[SESSION_KEY_RUNS] = lst
    for row in lst:
        if isinstance(row, dict) and str(row.get("call_id", "")) == call_id:
            row.setdefault("tool_name", tool_name)
            row["command"] = command
            row.setdefault("status", "running")
            row.setdefault("combined_output", "")
            return
    lst.append(
        {
            "call_id": call_id,
            "tool_name": tool_name,
            "command": command,
            "status": "running",
            "combined_output": "",
        },
    )


def append_output_delta(
    store: MutableMapping[str, Any],
    *,
    call_id: str,
    chunk: str,
) -> None:
    """Добавить stdout/stderr чанк к записи (для превью в процессе)."""
    lst = store.get(SESSION_KEY_RUNS)
    if not isinstance(lst, list):
        return
    for row in lst:
        if isinstance(row, dict) and str(row.get("call_id", "")) == call_id:
            prev = str(row.get("combined_output", "") or "")
            row["combined_output"] = prev + str(chunk)
            return


def mark_finished(
    store: MutableMapping[str, Any],
    *,
    call_id: str,
    ok: bool,
    error: str | None,
) -> None:
    """Пометить запись завершённой (до bash.execution)."""
    lst = store.get(SESSION_KEY_RUNS)
    if not isinstance(lst, list):
        return
    for row in lst:
        if isinstance(row, dict) and str(row.get("call_id", "")) == call_id:
            row["status"] = "ok" if ok else "error"
            if error:
                row["error"] = str(error)
            return


def append_execution(
    store: MutableMapping[str, Any],
    payload: Mapping[str, Any],
    *,
    max_runs: int = _MAX_RUNS_DEFAULT,
) -> ShellInvocationRecord | None:
    """Добавить запись из ``bash.execution``; вернуть запись или None."""
    if not payload.get("call_id"):
        return None
    cmd = str(payload.get("command", ""))
    combined = str(payload.get("combined_output", ""))
    started = str(payload.get("started_at", ""))
    finished = str(payload.get("finished_at", ""))
    ok = bool(payload.get("ok", False))
    err = payload.get("error")
    if err is not None:
        err_s = str(err)
        if err_s and not ok:
            combined = f"{combined}\n(error: {err_s})".strip()
    exit_raw = payload.get("exit_code")
    exit_code: int | None
    if exit_raw is None or exit_raw == "":
        exit_code = None
    else:
        try:
            exit_code = int(exit_raw)
        except (TypeError, ValueError):
            exit_code = None
    truncated = bool(payload.get("truncated", False))

    try:
        t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        t0 = t1 = _utc_now()
    elapsed_ms = int((t1 - t0).total_seconds() * 1000)
    line_count = len(combined.splitlines())
    byte_len = len(combined.encode("utf-8"))
    detached = DetachedViewHeuristic.suggest_detached_view(
        elapsed_ms=max(elapsed_ms, 0),
        byte_len=byte_len,
        line_count=line_count,
    )
    rec = ShellInvocationRecord(
        call_id=str(payload["call_id"]),
        command=cmd,
        started_at=started or t0.isoformat(),
        finished_at=finished or None,
        exit_code=exit_code,
        combined_output=combined,
        truncated=truncated,
        detached_recommended=detached,
    )
    lst = store.setdefault(SESSION_KEY_RUNS, [])
    if not isinstance(lst, list):
        lst = []
        store[SESSION_KEY_RUNS] = lst
    # Replace existing row (running) if present.
    replaced = False
    for i, row in enumerate(lst):
        if (
            isinstance(row, dict)
            and str(row.get("call_id", "")) == rec.call_id
        ):
            merged = dict(row)
            merged.update(rec.to_dict())
            merged["status"] = "ok" if ok else "error"
            lst[i] = merged
            replaced = True
            break
    if not replaced:
        row2 = rec.to_dict()
        row2["status"] = "ok" if ok else "error"
        lst.append(row2)
    while len(lst) > max_runs:
        lst.pop(0)
    store[SESSION_KEY_SELECTED] = rec.call_id
    return rec


def view_tail_lines(store: MutableMapping[str, Any]) -> int:
    """Число последних строк для превью (по умолчанию 200)."""
    raw = store.get(SESSION_KEY_VIEW_LINES)
    if isinstance(raw, int) and raw >= 1:
        return min(raw, 20_000)
    return 200


def set_view_tail_lines(store: MutableMapping[str, Any], n: int) -> None:
    """Установить N строк для вкладки Shell."""
    store[SESSION_KEY_VIEW_LINES] = max(1, min(int(n), 20_000))
