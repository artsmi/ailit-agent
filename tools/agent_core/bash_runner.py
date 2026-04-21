"""Одноразовый запуск shell-команды в cwd (этап B ailit-bash-strategy)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent_core.tool_runtime.cancel_context import current_cancel

_DEFAULT_TIMEOUT_MS: int = 120_000
_MAX_CAPTURE_BYTES_DEFAULT: int = 512_000
MAX_CAPTURE_BYTES_DEFAULT: int = _MAX_CAPTURE_BYTES_DEFAULT


@dataclass(frozen=True, slots=True)
class BashRunOutcome:
    """Результат запуска ``bash -lc``."""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    spill_path: str | None
    cancelled: bool = False


def _pick_bash() -> str:
    import shutil

    found = shutil.which("bash")
    return found if found else "/bin/bash"


def _kill_process_group(proc: subprocess.Popen) -> None:
    pid = proc.pid
    if pid is None:
        proc.kill()
        return
    if sys.platform == "win32":
        proc.kill()
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def run_bash_command(
    command: str,
    *,
    cwd: Path,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    max_capture_bytes: int = _MAX_CAPTURE_BYTES_DEFAULT,
    env: Mapping[str, str] | None = None,
) -> BashRunOutcome:
    """Запустить ``bash -lc`` в ``cwd`` (без ``shell=True`` у Popen).

    На Linux: ``start_new_session=True`` и killpg при таймауте.
    """
    cmd = command.strip()
    if not cmd:
        msg = "run_bash_command: empty command"
        raise ValueError(msg)
    if timeout_ms < 1:
        msg = "run_bash_command: timeout_ms must be positive"
        raise ValueError(msg)

    bash = _pick_bash()
    env_dict = dict(os.environ) if env is None else dict(env)
    if sys.platform == "win32":
        proc = subprocess.Popen(
            [bash, "-lc", cmd],
            cwd=str(cwd.resolve()),
            env=env_dict,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    else:
        proc = subprocess.Popen(
            [bash, "-lc", cmd],
            cwd=str(cwd.resolve()),
            env=env_dict,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    timeout_sec = timeout_ms / 1000.0
    timed_out = False
    cancelled = False
    out_parts: list[str] = []
    err_parts: list[str] = []
    deadline = time.time() + timeout_sec
    step = 0.2
    while True:
        ev = current_cancel()
        if ev is not None and ev.is_set():
            cancelled = True
            _kill_process_group(proc)
            break
        now = time.time()
        if now >= deadline:
            timed_out = True
            _kill_process_group(proc)
            break
        try:
            out, err = proc.communicate(
                timeout=min(step, max(0.0, deadline - now)),
            )
            out_parts.append(out or "")
            err_parts.append(err or "")
            break
        except subprocess.TimeoutExpired as exc:
            if exc.stdout:
                out_parts.append(str(exc.stdout))
            if exc.stderr:
                err_parts.append(str(exc.stderr))
            continue
    if timed_out or cancelled:
        out, err = proc.communicate()
        out_parts.append(out or "")
        err_parts.append(err or "")
    rc = proc.returncode
    exit_code: int | None = int(rc) if rc is not None else None
    if timed_out or cancelled:
        exit_code = None
    so = "".join(out_parts)
    se = "".join(err_parts)
    combined_len = len(so.encode("utf-8")) + len(se.encode("utf-8"))
    truncated = False
    spill: str | None = None
    if combined_len > max_capture_bytes:
        truncated = True
        spill_dir = cwd.resolve() / ".ailit"
        spill_dir.mkdir(parents=True, exist_ok=True)
        spill_path = spill_dir / f"shell-spill-{uuid.uuid4().hex}.txt"
        spill_path.write_text(
            f"--- stdout ---\n{so}\n--- stderr ---\n{se}",
            encoding="utf-8",
            errors="replace",
        )
        spill = str(spill_path)
        enc = "utf-8"
        half = max_capture_bytes // 2
        so_raw = so.encode(enc, errors="replace")[:half]
        se_raw = se.encode(enc, errors="replace")[:half]
        so = so_raw.decode(enc, errors="replace")
        se = se_raw.decode(enc, errors="replace")
    return BashRunOutcome(
        exit_code=exit_code,
        stdout=so,
        stderr=se,
        timed_out=timed_out,
        cancelled=cancelled,
        truncated=truncated,
        spill_path=spill,
    )
