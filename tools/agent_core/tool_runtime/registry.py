"""Реестр имя инструмента → спецификация и обработчик."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from agent_core.tool_runtime.builtins import BUILTIN_HANDLERS, builtin_tool_specs
from agent_core.tool_runtime.spec import ToolSpec

ToolHandler = Callable[[Mapping[str, object]], str]


@dataclass(frozen=True, slots=True)
class ToolRegistry:
    """Реестр инструментов."""

    specs: dict[str, ToolSpec]
    handlers: dict[str, ToolHandler]

    def get_spec(self, name: str) -> ToolSpec:
        """Получить спецификацию или бросить KeyError."""
        return self.specs[name]

    def get_handler(self, name: str) -> ToolHandler:
        """Получить обработчик или бросить KeyError."""
        return self.handlers[name]

    def merge(self, other: ToolRegistry) -> ToolRegistry:
        """Объединить реестри (other перекрывает ключи)."""
        specs = {**self.specs, **other.specs}
        handlers = {**self.handlers, **other.handlers}
        return ToolRegistry(specs=specs, handlers=handlers)


def default_builtin_registry() -> ToolRegistry:
    """Реестр встроенных list_dir, glob_file, grep, read_file, read_symbol, write_file."""
    specs = builtin_tool_specs()
    handlers: dict[str, ToolHandler] = {k: BUILTIN_HANDLERS[k] for k in specs if k in BUILTIN_HANDLERS}
    return ToolRegistry(specs=specs, handlers=handlers)


def empty_tool_registry() -> ToolRegistry:
    """Реестр без инструментов (обычный чат без tool calling)."""
    return ToolRegistry(specs={}, handlers={})
