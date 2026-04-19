"""Пути и проверки внутри AILIT_WORK_ROOT (паттерны Claude Code Read/Glob)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

# Сопоставимо с исключениями поиска в Claude Code GrepTool.
VCS_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {".git", ".svn", ".hg", ".bzr", ".jj"},
)

MAX_READ_BYTES: Final[int] = 512_000
MAX_READ_LINES: Final[int] = 2_000
GLOB_MAX_FILES_DEFAULT: Final[int] = 100
LIST_DIR_MAX_ENTRIES: Final[int] = 500


def work_root() -> Path:
    """Корень рабочей области (репозиторий / проект)."""
    raw = os.environ.get("AILIT_WORK_ROOT", os.getcwd())
    return Path(raw).resolve()


def normalize_relative(rel: str) -> str:
    """Нормализовать относительный путь: trim, убрать ведущие ./."""
    s = rel.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def resolve_under_root(relative: str) -> Path:
    """Разрешить путь только внутри work_root (без выхода за пределы)."""
    rel = normalize_relative(relative)
    if rel == "" or rel == ".":
        return work_root()
    root = work_root()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        msg = "path escapes AILIT_WORK_ROOT"
        raise ValueError(msg) from exc
    return candidate


def resolve_file_under_root(relative: str) -> Path:
    """Путь к файлу: запрет пустого, «.» и «..» как цели чтения файла."""
    rel = normalize_relative(relative)
    if rel == "":
        msg = (
            "read_file: path is empty. Pass a relative file path under "
            "AILIT_WORK_ROOT (not a directory). Use list_dir or glob_file "
            "to browse the tree."
        )
        raise ValueError(msg)
    if rel in (".", ".."):
        msg = (
            f"read_file: '{rel}' is not a file path. "
            "This tool reads files only. "
            "Use list_dir (optional path) or glob_file to list or find paths."
        )
        raise ValueError(msg)
    path = resolve_under_root(rel)
    if path.is_dir():
        msg = (
            f"read_file: '{rel}' is a directory, not a file. "
            "Use list_dir or glob_file instead."
        )
        raise IsADirectoryError(msg)
    return path


def resolve_dir_under_root(relative: str) -> Path:
    """Каталог под корнем; пустая строка или '.' — корень."""
    rel = normalize_relative(relative)
    if rel == "" or rel == ".":
        return work_root()
    if rel == "..":
        msg = "path must not be '..'"
        raise ValueError(msg)
    path = resolve_under_root(rel)
    if not path.is_dir():
        msg = f"not a directory: {rel}"
        raise NotADirectoryError(msg)
    return path


def _path_has_vcs_component(path: Path, root: Path) -> bool:
    """Проверить, входит ли путь под root в сегмент из VCS_DIRECTORY_NAMES."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in VCS_DIRECTORY_NAMES for part in rel.parts)


def _any_path_part_is_vcs(rel: Path) -> bool:
    """Есть ли среди частей относительного пути имя из ``VCS_DIRECTORY_NAMES``."""
    return any(part in VCS_DIRECTORY_NAMES for part in rel.parts)


def list_dir_should_skip_entry(path: Path, *, list_base: Path, root: Path) -> bool:
    """Скрывать VCS-метаданные при обычном обходе; не пустить явный ``list_dir .git``.

    Сопоставимо с практикой Claude Code / OpenCode: поиск и glob не заходят в
    ``.git`` (см. ``glob_file`` / ``grep``), но если модель явно запрашивает
    листинг каталога ``.git`` или внутри него — показываем одноуровневое
    содержимое, а не пустой список из-за фильтра по сегменту ``.git`` в пути.
    """
    root_r = root.resolve()
    base_r = list_base.resolve()
    path_r = path.resolve()
    try:
        rel_base = base_r.relative_to(root_r)
    except ValueError:
        return True
    if _any_path_part_is_vcs(rel_base):
        return False
    if not path_r.is_dir():
        return False
    return path_r.name in VCS_DIRECTORY_NAMES


def suggest_for_missing_file(root: Path, rel: str, *, limit: int = 8) -> str:
    """Подсказка при отсутствии файла: имена в корне с похожим префиксом."""
    prefix = normalize_relative(rel).split("/")[0].lower()
    try:
        names = sorted(p.name for p in root.iterdir() if p.is_file())
    except OSError:
        return f"Note: AILIT_WORK_ROOT is {root}"
    if not prefix:
        sample = names[:limit]
    else:
        sample = [n for n in names if n.lower().startswith(prefix)][:limit]
        if not sample:
            sample = names[:limit]
    if not sample:
        return f"Note: AILIT_WORK_ROOT is {root}"
    joined = ", ".join(sample)
    return f"Note: AILIT_WORK_ROOT is {root}. Some files at root: {joined}"


def read_file_text_slice(
    path: Path,
    *,
    max_bytes: int = MAX_READ_BYTES,
    offset_line: int = 1,
    limit_line: int | None = None,
) -> str:
    """Прочитать UTF-8 с лимитом байт и срезом строк (1-based)."""
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        msg = (
            f"file too large ({len(raw)} bytes); "
            f"max {max_bytes}"
        )
        raise OSError(msg)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    start = max(1, offset_line) - 1
    lim = limit_line
    if lim is None:
        chunk = lines[start:]
    else:
        if lim < 1:
            msg = "limit must be >= 1 when provided"
            raise ValueError(msg)
        end = start + lim
        chunk = lines[start:end]
    if len(chunk) > MAX_READ_LINES:
        msg = f"line slice too large; max {MAX_READ_LINES} lines per read"
        raise ValueError(msg)
    return "".join(chunk)
