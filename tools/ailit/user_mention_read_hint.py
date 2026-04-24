# flake8: noqa: E501
"""Парсинг @path#L10-20 в user message (ориентир: @-вложения Claude Code)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserAtFileLineRef:
    """Упоминание файла и опционально диапазона строк (1-based, inclusive)."""

    path: str
    start_line: int
    end_line: int

    def limit_for_read_file(self) -> int:
        return max(1, self.end_line - self.start_line + 1)


_AT_FILE_RE = re.compile(
    r'@(?:"([^"]+)"|([^\s#@]+))(?:#L(\d+)(?:-(\d+))?)?',
    re.UNICODE,
)


def parse_user_at_file_line_refs(text: str) -> list[UserAtFileLineRef]:
    """Найти @path и @path#Lstart-end; путь без #L — ориентир offset=1 limit=60."""
    out: list[UserAtFileLineRef] = []
    if not (text or "").strip():
        return out
    for m in _AT_FILE_RE.finditer(text):
        path = (m.group(1) or m.group(2) or "").strip()
        if not path or path.endswith("(agent)"):
            continue
        a_raw, b_raw = m.group(3), m.group(4)
        if a_raw is None:
            out.append(
                UserAtFileLineRef(path=path, start_line=1, end_line=60),
            )
            continue
        a = int(a_raw)
        b = int(b_raw) if b_raw is not None else a
        start = min(a, b)
        end = max(a, b)
        out.append(
            UserAtFileLineRef(path=path, start_line=start, end_line=end),
        )
    return out


def format_at_file_hints_for_system(refs: list[UserAtFileLineRef]) -> list[str]:
    """Короткие system-строки: предпочитать read_file с offset/limit (grep→range)."""
    if not refs:
        return []
    frags: list[str] = []
    for r in refs[:4]:
        lim = r.limit_for_read_file()
        frags.append(
            "Пользователь сослался на @-упоминание: "
            f"файл `{r.path}` строки {r.start_line}–{r.end_line} (1-based). "
            f"Предпочитай `read_file` с offset={r.start_line} и limit={lim} "
            "(без полного чтения большого файла; при необходимости уточни grep)."
        )
    return frags
