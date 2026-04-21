"""Инструмент ``run_shell`` (этап B ailit-bash-strategy)."""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from agent_core.bash_runner import (
    MAX_CAPTURE_BYTES_DEFAULT,
    BashRunOutcome,
    run_bash_command,
)
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec
from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.workdir_paths import work_root

_DEFAULT_TIMEOUT_MS = 120_000


@dataclass(frozen=True, slots=True)
class BashToolOsConfig:
    """Лимиты и allowlist из env (см. ``project.yaml`` bash:)."""

    default_timeout_ms: int
    max_capture_bytes: int
    allow_patterns: tuple[str, ...]

    @classmethod
    def current(cls) -> BashToolOsConfig:
        """Собрать конфиг из ``os.environ`` (без побочных эффектов)."""
        dt = _DEFAULT_TIMEOUT_MS
        raw_t = os.environ.get("AILIT_BASH_DEFAULT_TIMEOUT_MS")
        if raw_t is not None and str(raw_t).strip() != "":
            dt = max(1, int(raw_t))
        cap = MAX_CAPTURE_BYTES_DEFAULT
        raw_cap = os.environ.get("AILIT_BASH_MAX_CAPTURE_BYTES")
        if raw_cap is not None and str(raw_cap).strip() != "":
            cap = max(1, int(raw_cap))
        patterns: tuple[str, ...] = ()
        raw_p = os.environ.get("AILIT_BASH_ALLOW_PATTERNS_JSON", "").strip()
        if raw_p:
            loaded = json.loads(raw_p)
            if not isinstance(loaded, list):
                msg = (
                    "AILIT_BASH_ALLOW_PATTERNS_JSON must be a JSON list "
                    "of strings"
                )
                raise TypeError(msg)
            patterns = tuple(str(x) for x in loaded)
        return cls(
            default_timeout_ms=dt,
            max_capture_bytes=cap,
            allow_patterns=patterns,
        )


def _command_matches_allowlist(
    command: str,
    patterns: tuple[str, ...],
) -> bool:
    cmd = command.strip()
    return any(fnmatch.fnmatch(cmd, pat) for pat in patterns)


def _format_outcome(outcome: BashRunOutcome) -> str:
    lines: list[str] = []
    lines.append(f"exit_code: {outcome.exit_code!s}")
    lines.append(f"timed_out: {str(outcome.timed_out).lower()}")
    lines.append(f"truncated: {str(outcome.truncated).lower()}")
    if outcome.spill_path:
        lines.append(f"spill_path: {outcome.spill_path}")
    lines.append("")
    lines.append("--- stdout ---")
    lines.append(outcome.stdout or "(empty)")
    lines.append("")
    lines.append("--- stderr ---")
    lines.append(outcome.stderr or "(empty)")
    return "\n".join(lines)


def builtin_run_shell(arguments: Mapping[str, Any]) -> str:
    """Выполнить shell-команду в ``AILIT_WORK_ROOT``."""
    os_cfg = BashToolOsConfig.current()
    cmd = str(arguments.get("command", "")).strip()
    if not cmd:
        msg = "run_shell: command is required"
        raise ValueError(msg)
    if os_cfg.allow_patterns and not _command_matches_allowlist(
        cmd,
        os_cfg.allow_patterns,
    ):
        pat_repr = list(os_cfg.allow_patterns)
        msg = (
            "run_shell: command is not allowed by project "
            f"bash.allow_patterns (patterns={pat_repr!r})"
        )
        raise ValueError(msg)
    raw_timeout = arguments.get("timeout_ms")
    if raw_timeout is None or raw_timeout == "":
        timeout_ms = os_cfg.default_timeout_ms
    else:
        timeout_ms = int(raw_timeout)
    if timeout_ms < 1:
        msg = "run_shell: timeout_ms must be >= 1"
        raise ValueError(msg)
    root = work_root()
    outcome = run_bash_command(
        cmd,
        cwd=root,
        timeout_ms=timeout_ms,
        max_capture_bytes=os_cfg.max_capture_bytes,
    )
    return _format_outcome(outcome)


def run_shell_tool_spec() -> ToolSpec:
    """Спецификация инструмента для провайдера."""
    return ToolSpec(
        name="run_shell",
        description=(
            "Execute a shell command under AILIT_WORK_ROOT using bash -lc. "
            "Respects timeout_ms (default 120000). "
            "Large output may be truncated with spill file under .ailit/."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell script or command for bash -lc.",
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": (
                        "Wall-clock limit in ms (default "
                        f"{_DEFAULT_TIMEOUT_MS})."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Short human description for logs (optional)."
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        side_effect=SideEffectClass.SHELL,
        requires_approval=False,
        allow_parallel=False,
    )


def bash_tool_registry() -> ToolRegistry:
    """Реестр только с ``run_shell``."""
    specs = {"run_shell": run_shell_tool_spec()}
    handlers: dict[str, Callable[[Mapping[str, Any]], str]] = {
        "run_shell": builtin_run_shell,
    }
    return ToolRegistry(specs=specs, handlers=handlers)
