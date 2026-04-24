# flake8: noqa: E501
"""Пути и проверки внутри AILIT_WORK_ROOT (паттерны Claude Code Read/Glob)."""

from __future__ import annotations

import os
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ReadFileSliceResult:
    """Срез файла: тело, границы, общее число строк (1-based), источник чтения."""

    body: str
    total_lines: int
    from_line: int
    to_line: int
    source: str  # "buffer" | "stream"


def _strip_bom_text(s: str) -> str:
    if s and s[0] == "\ufeff":
        return s[1:]
    return s


def _read_file_slice_buffer(
    path: Path,
    *,
    max_bytes: int,
    offset_line: int,
    limit_line: int | None,
) -> ReadFileSliceResult:
    """Путь readFile+split (файл целиком ≤ max_bytes, как readFileInRange small path)."""
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        msg = (
            f"file too large ({len(raw)} bytes) to read at once; "
            f"max {max_bytes} bytes per slurp. "
            "Use read_file with offset and limit, or grep, then read a range."
        )
        raise OSError(msg)
    t0 = raw.decode("utf-8", errors="replace")
    t0 = _strip_bom_text(t0)
    t0 = t0.replace("\r\n", "\n").replace("\r", "\n")
    all_lines = t0.splitlines(keepends=True)
    total_lines = len(all_lines) if t0 else 0
    off = max(1, offset_line)
    lim = limit_line
    if lim is not None and lim < 1:
        msg = "limit must be >= 1 when provided"
        raise ValueError(msg)
    i0 = off - 1
    if not all_lines:
        return ReadFileSliceResult(
            body="",
            total_lines=0,
            from_line=off,
            to_line=0,
            source="buffer",
        )
    if i0 >= len(all_lines):
        return ReadFileSliceResult(
            body="",
            total_lines=total_lines,
            from_line=off,
            to_line=off - 1,
            source="buffer",
        )
    if lim is None:
        el2 = i0 + MAX_READ_LINES
        part = all_lines[i0:el2]
    else:
        if lim > MAX_READ_LINES:
            msg = f"line slice too large; max {MAX_READ_LINES} lines per read"
            raise ValueError(msg)
        el = i0 + lim
        part = all_lines[i0:el]
    body = "".join(part)
    to_ln = off + max(0, len(part) - 1)
    return ReadFileSliceResult(
        body=body,
        total_lines=total_lines,
        from_line=off,
        to_line=to_ln,
        source="buffer",
    )


def _read_file_slice_stream(
    path: Path,
    offset_line: int,
    limit_line: int | None,
) -> ReadFileSliceResult:
    """Потоковый путь: без read_bytes целиком (сравнение: readFileInRange streaming)."""
    off = max(1, offset_line)
    lim = limit_line
    if lim is not None and lim < 1:
        msg = "limit must be >= 1 when provided"
        raise ValueError(msg)
    if lim is None and off == 1:
        msg = (
            "on a large file use offset+limit (or grep first). "
            "Cannot read the entire file without a buffer budget."
        )
        raise OSError(msg)
    out: list[str] = []
    line_no = 0
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for line in handle:
            line_no += 1
            if line_no < off:
                continue
            if lim is not None:
                if off <= line_no <= off + lim - 1 and len(out) < min(
                    lim,
                    MAX_READ_LINES,
                ):
                    out.append(line)
            elif len(out) < MAX_READ_LINES:
                out.append(line)
    total = line_no
    if not out:
        to_ln = off - 1
    else:
        to_ln = off + len(out) - 1
    if lim is not None:
        to_ln = min(to_ln, off + lim - 1, off + len(out) - 1)
    return ReadFileSliceResult(
        body="".join(out),
        total_lines=total,
        from_line=off,
        to_line=to_ln,
        source="stream",
    )


def read_file_slice(
    path: Path,
    *,
    max_bytes: int = MAX_READ_BYTES,
    offset_line: int = 1,
    limit_line: int | None = None,
) -> ReadFileSliceResult:
    """Срез файла: slurp (≤ max_bytes) или stream (> max_bytes с range)."""
    off = max(1, int(offset_line or 1))
    try:
        st = path.stat()
    except OSError as exc:
        msg = f"read_file: {exc}"
        raise OSError(msg) from exc
    if st.st_size > max_bytes and off == 1 and limit_line is None:
        msg = (
            f"file too large ({st.st_size} bytes) to read entirely; "
            f"max {max_bytes} bytes per read without range. "
            "Use read_file with offset and limit, or grep to locate lines, "
            "then read a range (progressive disclosure / range read)."
        )
        raise OSError(msg)
    if st.st_size <= max_bytes:
        return _read_file_slice_buffer(
            path,
            max_bytes=max_bytes,
            offset_line=off,
            limit_line=limit_line,
        )
    if limit_line is not None and limit_line > MAX_READ_LINES:
        msg = f"line slice too large; max {MAX_READ_LINES} lines per read"
        raise ValueError(msg)
    return _read_file_slice_stream(path, off, limit_line)


def read_file_text_slice(
    path: Path,
    *,
    max_bytes: int = MAX_READ_BYTES,
    offset_line: int = 1,
    limit_line: int | None = None,
) -> str:
    """Совместимость: только текст (без meta-обёртки; см. read_file_slice)."""
    return read_file_slice(
        path,
        max_bytes=max_bytes,
        offset_line=offset_line,
        limit_line=limit_line,
    ).body
