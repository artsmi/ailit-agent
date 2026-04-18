"""Встроенные инструменты с ограничением путей по рабочему корню."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec


def _work_root() -> Path:
    raw = os.environ.get("AILIT_WORK_ROOT", os.getcwd())
    return Path(raw).resolve()


def _safe_child_path(relative: str) -> Path:
    """Разрешить путь только внутри AILIT_WORK_ROOT."""
    root = _work_root()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        msg = "path escapes work root"
        raise ValueError(msg) from exc
    return candidate


def builtin_echo(arguments: Mapping[str, Any]) -> str:
    """Вернуть поле message."""
    return str(arguments.get("message", ""))


def builtin_read_file(arguments: Mapping[str, Any]) -> str:
    """Прочитать UTF-8 файл под рабочим корнем."""
    rel = str(arguments.get("path", ""))
    path = _safe_child_path(rel)
    if not path.is_file():
        msg = f"not a file: {rel}"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8", errors="replace")


def builtin_write_file(arguments: Mapping[str, Any]) -> str:
    """Записать файл под рабочим корнем."""
    rel = str(arguments.get("path", ""))
    content = str(arguments.get("content", ""))
    path = _safe_child_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote:{rel}"


BuiltinHandler = Callable[[Mapping[str, Any]], str]

BUILTIN_HANDLERS: dict[str, BuiltinHandler] = {
    "echo": builtin_echo,
    "read_file": builtin_read_file,
    "write_file": builtin_write_file,
}


def builtin_tool_specs() -> dict[str, ToolSpec]:
    """Спецификации встроенных инструментов."""
    return {
        "echo": ToolSpec(
            name="echo",
            description="Echo message for tests.",
            parameters_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            side_effect=SideEffectClass.NONE,
            allow_parallel=True,
        ),
        "read_file": ToolSpec(
            name="read_file",
            description="Read UTF-8 file under AILIT_WORK_ROOT.",
            parameters_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            side_effect=SideEffectClass.READ_ONLY,
            allow_parallel=True,
        ),
        "write_file": ToolSpec(
            name="write_file",
            description="Write UTF-8 file under AILIT_WORK_ROOT.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            side_effect=SideEffectClass.WRITE,
            requires_approval=False,
        ),
    }
