# flake8: noqa: E501
"""read_symbol: диапазон по имени сущности в .py (read-6 R2) через ast."""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Mapping

from agent_core.tool_runtime.workdir_paths import (
    MAX_READ_BYTES,
    resolve_file_under_root,
)
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec

_DEFAULT_BODY_LINES: Final[int] = 80
_MAX_NAME_LEN: Final[int] = 200


@dataclass(frozen=True, slots=True)
class PythonSymbolRange:
    """Срез по исходнику: границы и краткое тело."""

    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    body_text: str


class PythonAstTopLevelFinder:
    """Поиск на верхнем уровне модуля: FunctionDef/AsyncFunctionDef/ClassDef."""

    def __init__(self, source: str) -> None:
        """Сохранить исходник (для line slices)."""
        self._source = source
        self._lines: list[str] = source.splitlines(keepends=True)

    def find(self, symbol: str) -> PythonSymbolRange | None:
        """Вернуть срез для первой подходящей сущности или None."""
        try:
            tree = ast.parse(self._source)
        except SyntaxError:
            return None
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == symbol:
                return self._from_function(node, is_async=True)
            if isinstance(node, ast.FunctionDef) and node.name == symbol:
                return self._from_function(node, is_async=False)
            if isinstance(node, ast.ClassDef) and node.name == symbol:
                return self._from_class(node)
        return None

    @staticmethod
    def _span_lines(node: ast.AST) -> tuple[int, int]:
        start = int(getattr(node, "lineno", 1) or 1)
        end_raw = getattr(node, "end_lineno", None)
        end = int(end_raw) if end_raw is not None else start
        return (start, end)

    def _line_text(self, start: int, end: int) -> str:
        a = max(1, start) - 1
        b = min(len(self._lines), end)
        return "".join(self._lines[a:b])

    def _from_class(self, node: ast.ClassDef) -> PythonSymbolRange:
        start, end = self._span_lines(node)
        sig = self._line_text(start, start)
        n_body = min(end, start + _DEFAULT_BODY_LINES - 1)
        return PythonSymbolRange(
            name=node.name,
            kind="class",
            start_line=start,
            end_line=end,
            signature=sig.strip(),
            body_text=self._line_text(start, n_body),
        )

    def _from_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
    ) -> PythonSymbolRange:
        start, end = self._span_lines(node)
        kind = "async_function" if is_async else "function"
        sig = self._line_text(start, start)
        n_body = min(end, start + _DEFAULT_BODY_LINES - 1)
        return PythonSymbolRange(
            name=node.name,
            kind=kind,
            start_line=start,
            end_line=end,
            signature=sig.strip(),
            body_text=self._line_text(start, n_body),
        )


def _read_text_safe(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_READ_BYTES:
        return None
    return raw.decode("utf-8", errors="replace")


def read_symbol_result_json(arguments: Mapping[str, Any], path: Path) -> str:
    """JSON-строка для read_symbol (обработчик + unit-тесты)."""
    sym_raw = str(arguments.get("symbol", "")).strip()
    if not sym_raw:
        return json.dumps({"ok": False, "error": "symbol is required"}, ensure_ascii=False)
    if len(sym_raw) > _MAX_NAME_LEN:
        return json.dumps(
            {"ok": False, "error": "symbol name too long"},
            ensure_ascii=False,
        )
    if path.suffix.lower() != ".py":
        return json.dumps(
            {
                "ok": False,
                "error": "read_symbol supports .py only (use grep + read_file otherwise)",
            },
            ensure_ascii=False,
        )
    text = _read_text_safe(path)
    if text is None:
        return json.dumps(
            {"ok": False, "error": "cannot read file or file too large"},
            ensure_ascii=False,
        )
    found = PythonAstTopLevelFinder(text).find(sym_raw)
    if found is None:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "top-level symbol not found in .py (try grep or nested symbol)"
                ),
            },
            ensure_ascii=False,
        )
    payload: dict[str, Any] = {"ok": True, "path": str(path), **asdict(found)}
    return json.dumps(payload, ensure_ascii=False)


def builtin_read_symbol(arguments: Mapping[str, Any]) -> str:
    """(path, symbol) → границы top-level def/class в Python."""
    rel = str(arguments.get("path", ""))
    try:
        file_path = resolve_file_under_root(rel)
    except (FileNotFoundError, OSError, ValueError) as exc:
        return json.dumps(
            {"ok": False, "error": str(exc)},
            ensure_ascii=False,
        )
    return read_symbol_result_json(arguments, file_path)


def read_symbol_tool_spec() -> ToolSpec:
    """Спецификация для read_symbol."""
    path_d = (
        "Relative path to a .py FILE under AILIT_WORK_ROOT. "
        "Only top-level def/class/async def by name; nested or imported names: use grep."
    )
    return ToolSpec(
        name="read_symbol",
        description=(
            "Find a top-level Python class or function by name: line range, signature, "
            "and a short body preview. Use for targeted reads; fall back to grep+read_file "
            "for other languages or nested names."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": path_d,
                },
                "symbol": {
                    "type": "string",
                    "description": (
                        "Name of a top-level function, async function, or class in the file."
                    ),
                },
            },
            "required": ["path", "symbol"],
            "additionalProperties": False,
        },
        side_effect=SideEffectClass.READ_ONLY,
        allow_parallel=True,
    )
