"""Несколько корней рабочей области (AILIT_WORK_ROOTS) и абсолютные пути."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Final

_TMP_PREFIX: Final[str] = ".ailit_atomic_"


def work_roots() -> tuple[Path, ...]:
    """
    Корни: JSON AILIT_WORK_ROOTS или один AILIT_WORK_ROOT.
    """
    raw = os.environ.get("AILIT_WORK_ROOTS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = "AILIT_WORK_ROOTS must be valid JSON array of paths"
            raise ValueError(msg) from exc
        if not isinstance(data, list) or not data:
            msg = "AILIT_WORK_ROOTS must be a non-empty JSON array"
            raise ValueError(msg)
        out: list[Path] = []
        for x in data:
            out.append(Path(str(x)).expanduser().resolve())
        return tuple(out)
    single = os.environ.get("AILIT_WORK_ROOT", os.getcwd())
    return (Path(single).expanduser().resolve(),)


def primary_work_root() -> Path:
    """Первый корень (относительные пути read_file/list_dir — под ним)."""
    return work_roots()[0]


def validate_agent_memory_relative_path(raw: str) -> str | None:
    """
    W14 (G14R.7, A14R.9): relpath без parent segments и абсолюта.

    Возвращает нормализованный relpath или None.
    """
    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith(("/", "\\")) or (len(s) > 1 and s[1] == ":"):
        return None
    posix_parts = Path(s).as_posix().split("/")
    if ".." in posix_parts:
        return None
    norm = Path(s).as_posix()
    if not norm or norm == ".":
        return "."
    return norm


def resolve_absolute_file_under_work_roots(file_path: str) -> tuple[Path, str]:
    """Проверить, что абсолютный путь лежит под одним из корней.

    Возвращает ``(absolute_path, relative_posix_under_that_root)``.
    """
    raw = (file_path or "").strip()
    if not raw:
        msg = "filePath is empty"
        raise ValueError(msg)
    candidate = Path(raw).expanduser().resolve()
    roots = work_roots()
    for root in roots:
        try:
            rel = candidate.relative_to(root)
        except ValueError:
            continue
        rel_s = rel.as_posix()
        if rel_s == ".." or rel_s.startswith("../"):
            continue
        return candidate, rel_s if rel_s else "."
    roots_s = ", ".join(str(r) for r in roots)
    msg = f"path not under any work root ({roots_s}): {candidate}"
    raise ValueError(msg)


def atomic_replace_text_file(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Атомарно записать: tmp в каталоге + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=_TMP_PREFIX,
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(content)
        tmp_path.replace(path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
