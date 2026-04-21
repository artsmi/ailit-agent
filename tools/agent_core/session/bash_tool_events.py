"""События телеметрии для bash tools (этап C ailit-bash-strategy)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from agent_core.tool_runtime.executor import ToolInvocation, ToolRunResult

EmitFn = Callable[[str, dict[str, Any]], None]

_CHUNK_CHARS = 8_192


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_run_shell_command(arguments_json: str) -> str:
    try:
        raw = json.loads(arguments_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("command", "") or "").strip()


def _parse_exit_code_from_output(text: str) -> int | None:
    for line in (text or "").splitlines()[:24]:
        if line.strip().lower().startswith("exit_code:"):
            rest = line.split(":", 1)[1].strip()
            if rest.lower() in ("none", "null", ""):
                return None
            try:
                return int(rest)
            except ValueError:
                return None
    return None


def _truthy_flag_line(text: str, key: str) -> bool:
    prefix = f"{key}:"
    for line in (text or "").splitlines()[:24]:
        s = line.strip().lower()
        if s.startswith(prefix.lower()):
            tail = line.split(":", 1)[1].strip().lower()
            return tail in ("true", "1", "yes")
    return False


def emit_bash_shell_telemetry(
    emit: EmitFn,
    inv: ToolInvocation,
    res: ToolRunResult,
) -> None:
    """Эмитить ``bash.output_delta``, ``bash.finished``, ``bash.execution``."""
    if inv.tool_name not in ("run_shell", "run_shell_session", "shell_reset"):
        return
    started = _utc_iso()
    cmd = _parse_run_shell_command(inv.arguments_json)
    text = res.content or ""
    sess_id = (
        str(os.environ.get("AILIT_SHELL_SESSION_KEY", "")).strip() or None
    )
    sess_seq: int | None = None
    if inv.tool_name == "run_shell_session":
        try:
            sess_seq = int(os.environ.get("AILIT_SHELL_SESSION_SEQ", "0") or 0)
        except ValueError:
            sess_seq = None
    n_chunks = max(1, (len(text) + _CHUNK_CHARS - 1) // _CHUNK_CHARS)
    for i in range(0, len(text), _CHUNK_CHARS):
        hi = i + _CHUNK_CHARS
        chunk = text[i:hi]
        emit(
            "bash.output_delta",
            {
                "call_id": inv.call_id,
                "chunk": chunk,
                "chunk_index": i // _CHUNK_CHARS,
                "chunk_count": n_chunks,
                "shell_session_id": sess_id,
                "session_seq": sess_seq,
            },
        )
    byte_len = len(text.encode("utf-8"))
    ok = res.error is None
    emit(
        "bash.finished",
        {
            "call_id": inv.call_id,
            "byte_len": byte_len,
            "ok": ok,
            "error": res.error,
            "shell_session_id": sess_id,
            "session_seq": sess_seq,
        },
    )
    finished = _utc_iso()
    exit_code = _parse_exit_code_from_output(text) if ok else None
    emit(
        "bash.execution",
        {
            "call_id": inv.call_id,
            "command": cmd,
            "combined_output": text,
            "ok": ok,
            "error": res.error,
            "started_at": started,
            "finished_at": finished,
            "exit_code": exit_code,
            "truncated": _truthy_flag_line(text, "truncated"),
            "timed_out": _truthy_flag_line(text, "timed_out"),
            "shell_session_id": sess_id,
            "session_seq": sess_seq,
        },
    )
