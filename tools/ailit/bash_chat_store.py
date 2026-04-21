"""Хранилище записей shell для Streamlit chat (этап D.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping

from agent_core.shell_invocation_record import ShellInvocationRecord
from agent_core.shell_output_preview import DetachedViewHeuristic

SESSION_KEY_RUNS = "ailit_bash_runs"
SESSION_KEY_VIEW_LINES = "ailit_bash_view_tail_lines"
SESSION_KEY_SELECTED = "ailit_bash_selected_call_id"
_MAX_RUNS_DEFAULT = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def runs_list(store: MutableMapping[str, Any]) -> list[dict[str, Any]]:
    """Список dict записей (копия для безопасной итерации)."""
    raw = store.get(SESSION_KEY_RUNS)
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


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
    lst.append(rec.to_dict())
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
