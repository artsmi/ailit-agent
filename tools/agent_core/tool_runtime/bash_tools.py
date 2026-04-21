"""Инструмент ``run_shell`` (этап B ailit-bash-strategy)."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from agent_core.bash_runner import BashRunOutcome, run_bash_command
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec
from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.workdir_paths import work_root

_DEFAULT_TIMEOUT_MS = 120_000


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
    cmd = str(arguments.get("command", "")).strip()
    if not cmd:
        msg = "run_shell: command is required"
        raise ValueError(msg)
    raw_timeout = arguments.get("timeout_ms")
    if raw_timeout is None or raw_timeout == "":
        timeout_ms = _DEFAULT_TIMEOUT_MS
    else:
        timeout_ms = int(raw_timeout)
    if timeout_ms < 1:
        msg = "run_shell: timeout_ms must be >= 1"
        raise ValueError(msg)
    root = work_root()
    outcome = run_bash_command(cmd, cwd=root, timeout_ms=timeout_ms)
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
