# flake8: noqa: E501
"""Префикс метаданных read_file (totalLines + диапазон, как у доноров)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Mapping

READ_META_PREFIX: Final[str] = "# ailit:read_meta:"


@dataclass(frozen=True, slots=True)
class ReadFileToolPayload:
    """Распарсенный ответ read_file: meta + тело для модели."""

    raw_for_model: str
    meta: dict[str, Any] | None
    body: str
    body_line_count: int


def _strip_bom(s: str) -> str:
    if s and s[0] == "\ufeff":
        return s[1:]
    return s


def format_read_file_with_meta(
    *,
    relative_path: str,
    body: str,
    from_line: int,
    to_line: int,
    total_lines: int,
    source: str,
) -> str:
    """Первая строка JSON meta; пустая строка; тело (startLine + totalLines)."""
    meta: dict[str, Any] = {
        "path": relative_path,
        "from_line": from_line,
        "to_line": to_line,
        "total_lines": total_lines,
        "source": source,
    }
    b = _strip_bom(body)
    return f"{READ_META_PREFIX}{json.dumps(meta, ensure_ascii=False)}\n\n{b}"


def split_read_file_tool_output(text: str) -> ReadFileToolPayload:
    """Отделить meta-строку от тела; body_line_count — только строки контента."""
    raw = str(text or "")
    if not raw.startswith(READ_META_PREFIX):
        lines = raw.splitlines() if raw else []
        return ReadFileToolPayload(
            raw_for_model=raw,
            meta=None,
            body=raw,
            body_line_count=len(lines),
        )
    nl = raw.find("\n", len(READ_META_PREFIX))
    if nl < 0:
        lines = raw.splitlines() if raw else []
        return ReadFileToolPayload(
            raw_for_model=raw,
            meta=None,
            body=raw,
            body_line_count=len(lines),
        )
    jtxt = raw[len(READ_META_PREFIX):nl].strip()
    try:
        meta: dict[str, Any] = json.loads(jtxt)
    except json.JSONDecodeError:
        rest = raw[nl + 1:].lstrip()
        xlines = rest.splitlines() if rest else []
        return ReadFileToolPayload(
            raw_for_model=raw,
            meta=None,
            body=rest,
            body_line_count=len(xlines),
        )
    rest = raw[nl + 1:].lstrip()
    rlines = rest.splitlines() if rest else []
    return ReadFileToolPayload(
        raw_for_model=raw,
        meta=meta,
        body=rest,
        body_line_count=len(rlines),
    )


def extras_from_read_file_meta(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    """Поля для ToolRunResult.extras и JSONL (без дублирования body)."""
    if not isinstance(meta, Mapping):
        return {}
    return {
        "ailit_read": {
            "from_line": int(meta.get("from_line", 0) or 0),
            "to_line": int(meta.get("to_line", 0) or 0),
            "total_lines": int(meta.get("total_lines", 0) or 0),
            "source": str(meta.get("source", "") or ""),
        },
    }
