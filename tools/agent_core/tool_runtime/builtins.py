"""Встроенные инструменты с ограничением путей по рабочему корню."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Final, Mapping

from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec
from agent_core.tool_runtime.python_read_symbol import (
    builtin_read_symbol,
    read_symbol_tool_spec,
)
from agent_core.tool_runtime.read_file_envelope import (
    format_read_file_with_meta,
)
from agent_core.tool_runtime.workdir_paths import (
    GLOB_MAX_FILES_DEFAULT,
    LIST_DIR_MAX_ENTRIES,
    MAX_READ_BYTES,
    MAX_READ_LINES,
    normalize_relative,
    read_file_slice,
    resolve_dir_under_root,
    resolve_file_under_root,
    resolve_under_root,
    list_dir_should_skip_entry,
    suggest_for_missing_file,
    work_root,
    _path_has_vcs_component,
)

_FILE_UNCHANGED_STUB: Final[str] = (
    "File unchanged since last read in this process: same path, line range, "
    "and modification time. Refer to the earlier tool result in this thread."
)

_READ_DEDUP: dict[tuple[str, int, int | None], tuple[float, str]] = {}


def _dedup_key(
    rel_norm: str,
    offset_line: int,
    limit_line: int | None,
) -> tuple[str, int, int | None]:
    return (rel_norm, offset_line, limit_line)


def _rel_posix_from_root(path: Path) -> str:
    root = work_root()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def builtin_echo(arguments: Mapping[str, Any]) -> str:
    """Вернуть поле message."""
    return str(arguments.get("message", ""))


def builtin_read_file(arguments: Mapping[str, Any]) -> str:
    """Прочитать UTF-8 файл под корнем (только файл; см. схему)."""
    rel = str(arguments.get("path", ""))
    path = resolve_file_under_root(rel)
    if not path.exists():
        hint = suggest_for_missing_file(work_root(), rel)
        msg = f"not found: {rel}. {hint}"
        raise FileNotFoundError(msg)
    if not path.is_file():
        msg = f"not a file: {rel}"
        raise FileNotFoundError(msg)

    offset_line = int(arguments.get("offset", 1) or 1)
    raw_limit = arguments.get("limit")
    limit_line: int | None
    if raw_limit is None or raw_limit == "":
        limit_line = None
    else:
        limit_line = int(raw_limit)

    rel_norm = normalize_relative(rel)
    key = _dedup_key(rel_norm, offset_line, limit_line)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0.0
    prev = _READ_DEDUP.get(key)
    if prev is not None and prev[0] == mtime_ns:
        return _FILE_UNCHANGED_STUB

    res = read_file_slice(
        path,
        max_bytes=MAX_READ_BYTES,
        offset_line=offset_line,
        limit_line=limit_line,
    )
    out = format_read_file_with_meta(
        relative_path=rel_norm,
        body=res.body,
        from_line=res.from_line,
        to_line=res.to_line,
        total_lines=res.total_lines,
        source=res.source,
    )
    _READ_DEDUP[key] = (mtime_ns, out)
    return out


def builtin_write_file(arguments: Mapping[str, Any]) -> str:
    """Записать файл под рабочим корнем."""
    rel = str(arguments.get("path", ""))
    content = str(arguments.get("content", ""))
    if normalize_relative(rel) in ("", ".", ".."):
        msg = (
            "write_file: path must be a concrete relative file path "
            "(not '.' or '..')."
        )
        raise ValueError(msg)
    path = resolve_under_root(rel)
    if path.exists() and path.is_dir():
        msg = f"write_file: '{rel}' is a directory; choose a file path."
        raise IsADirectoryError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote:{rel}"


def builtin_list_dir(arguments: Mapping[str, Any]) -> str:
    """Список имён в каталоге (один уровень) под AILIT_WORK_ROOT."""
    raw = arguments.get("path", "")
    rel = str(raw) if raw is not None else ""
    base = resolve_dir_under_root(rel)
    root = work_root()
    rows: list[dict[str, str]] = []
    try:
        it = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        msg = f"list_dir failed: {exc}"
        raise OSError(msg) from exc
    for p in it[:LIST_DIR_MAX_ENTRIES]:
        if list_dir_should_skip_entry(p, list_base=base, root=root):
            continue
        kind = "dir" if p.is_dir() else "file"
        rows.append({"name": p.name, "type": kind})
    out = {
        "path": _rel_posix_from_root(base) or ".",
        "entries": rows,
        "truncated": len(it) > LIST_DIR_MAX_ENTRIES,
    }
    return json.dumps(out, ensure_ascii=False)


def builtin_glob_file(arguments: Mapping[str, Any]) -> str:
    """Поиск путей по glob внутри подкаталога AILIT_WORK_ROOT."""
    pattern = str(arguments.get("pattern", "")).strip()
    if not pattern:
        msg = "glob_file: pattern is required"
        raise ValueError(msg)
    raw_path = arguments.get("path", "")
    rel_dir = str(raw_path).strip() if raw_path is not None else ""
    base = resolve_dir_under_root(rel_dir if rel_dir else ".")
    max_files = int(arguments.get("max_files", GLOB_MAX_FILES_DEFAULT))
    if max_files < 1:
        msg = "max_files must be >= 1"
        raise ValueError(msg)

    root = work_root()
    hits: list[tuple[float, str]] = []
    truncated = False
    try:
        for p in base.glob(pattern):
            if not p.is_file():
                continue
            if _path_has_vcs_component(p, root):
                continue
            try:
                mt = p.stat().st_mtime
            except OSError:
                mt = 0.0
            rel = _rel_posix_from_root(p)
            hits.append((mt, rel))
            if len(hits) >= max_files:
                truncated = True
                break
    except ValueError as exc:
        msg = f"glob_file: invalid pattern: {exc}"
        raise ValueError(msg) from exc

    hits.sort(key=lambda t: (-t[0], t[1]))
    paths = [h[1] for h in hits]
    out = {
        "pattern": pattern,
        "base": _rel_posix_from_root(base) or ".",
        "filenames": paths,
        "num_files": len(paths),
        "truncated": truncated,
    }
    return json.dumps(out, ensure_ascii=False)


def builtin_grep(arguments: Mapping[str, Any]) -> str:
    """Поиск по содержимому через ripgrep (rg)."""
    rg = shutil.which("rg")
    if not rg:
        msg = (
            "ripgrep (rg) is required for grep but was not found on PATH. "
            "Install ripgrep and ensure `rg` is available."
        )
        raise RuntimeError(msg)

    pattern = str(arguments.get("pattern", ""))
    if not pattern:
        msg = "grep: pattern is required"
        raise ValueError(msg)

    raw_path = arguments.get("path")
    search_rel = str(raw_path).strip() if raw_path is not None else ""
    search_dir = resolve_dir_under_root(search_rel if search_rel else ".")

    om_raw = arguments.get("output_mode", "files_with_matches")
    output_mode = str(om_raw).strip()
    if output_mode not in ("content", "files_with_matches", "count"):
        msg = f"grep: invalid output_mode: {output_mode!r}"
        raise ValueError(msg)

    head_limit = arguments.get("head_limit")
    hl = 250 if head_limit is None or head_limit == "" else int(head_limit)

    cmd: list[str] = [rg, "--glob", "!.git/**"]
    if bool(arguments.get("-i", False)):
        cmd.append("-i")
    if bool(arguments.get("multiline", False)):
        cmd.extend(["-U", "--multiline-dotall"])

    glob_pat = arguments.get("glob")
    if glob_pat:
        cmd.extend(["--glob", str(glob_pat)])

    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    else:
        cmd.extend(["-n", "--no-heading"])

    if hl > 0:
        cmd.extend(["-m", str(hl)])

    cmd.append(pattern)
    cmd.append(".")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(search_dir),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        msg = "grep: ripgrep timed out"
        raise TimeoutError(msg) from exc

    out = proc.stdout or ""
    err = proc.stderr or ""
    if proc.returncode not in (0, 1):
        detail = err.strip() or out.strip()
        msg = f"grep: rg exited {proc.returncode}: {detail}"
        raise RuntimeError(msg)
    if err.strip() and not out.strip():
        return err.strip()
    return out if out.strip() else "(no matches)"


BuiltinHandler = Callable[[Mapping[str, Any]], str]

BUILTIN_HANDLERS: dict[str, BuiltinHandler] = {
    "list_dir": builtin_list_dir,
    "glob_file": builtin_glob_file,
    "grep": builtin_grep,
    "read_file": builtin_read_file,
    "read_symbol": builtin_read_symbol,
    "write_file": builtin_write_file,
    "echo": builtin_echo,
}


def builtin_tool_specs() -> dict[str, ToolSpec]:
    """Спеки встроенных tools; list_dir первым (пустой JSON для mock)."""
    path_file_desc = (
        "Relative path to a FILE under AILIT_WORK_ROOT "
        "(not '.', not a directory). "
        "To browse directories use list_dir or glob_file."
    )
    path_dir_desc = (
        "Optional subdirectory under AILIT_WORK_ROOT to list. "
        "Omit or use '.' for the work root. "
        "Do not pass the string 'undefined'."
    )
    glob_path_desc = (
        "Optional subdirectory under AILIT_WORK_ROOT to search in. "
        "Omit for the work root. Do not pass the string 'undefined'."
    )
    return {
        "list_dir": ToolSpec(
            name="list_dir",
            description=(
                "List file and directory names in a single directory under "
                "AILIT_WORK_ROOT (like ls). Use this instead of read_file for "
                "directory listings."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": path_dir_desc,
                    },
                },
                "additionalProperties": False,
            },
            side_effect=SideEffectClass.READ_ONLY,
            allow_parallel=True,
        ),
        "glob_file": ToolSpec(
            name="glob_file",
            description=(
                "Find file paths by glob under AILIT_WORK_ROOT "
                "(like Glob in Claude Code). "
                "Use for '*.py', '**/*.md', etc."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Glob pattern relative to path (e.g. '**/*.py')."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": glob_path_desc,
                    },
                    "max_files": {
                        "type": "integer",
                        "description": (
                            "Max paths to return "
                            f"(default {GLOB_MAX_FILES_DEFAULT})."
                        ),
                    },
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            side_effect=SideEffectClass.READ_ONLY,
            allow_parallel=True,
        ),
        "grep": ToolSpec(
            name="grep",
            description=(
                "Search file contents with ripgrep (rg), like Grep in Claude. "
                "Requires `rg` on PATH. "
                "Do not simulate grep in text; call this tool."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression (ripgrep syntax).",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional subdirectory under AILIT_WORK_ROOT "
                            "to search. Default is work root."
                        ),
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            "Optional glob filter for rg --glob (e.g. '*.py')."
                        ),
                    },
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files_with_matches", "count"],
                        "description": (
                            "content: lines; files_with_matches: paths; "
                            "count: counts per file."
                        ),
                    },
                    "head_limit": {
                        "type": "integer",
                        "description": (
                            "Max matches (rg -m); default 250. "
                            "Use 0 to omit -m (rg default)."
                        ),
                    },
                    "-i": {
                        "type": "boolean",
                        "description": "Case insensitive search.",
                    },
                    "multiline": {
                        "type": "boolean",
                        "description": (
                            "Multiline mode (rg -U --multiline-dotall)."
                        ),
                    },
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            side_effect=SideEffectClass.READ_ONLY,
            allow_parallel=True,
        ),
        "read_file": ToolSpec(
            name="read_file",
            description=(
                "Read a UTF-8 text file under AILIT_WORK_ROOT only; "
                "not directories. "
                "Use list_dir/glob_file for trees; read_file for one file."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": path_file_desc},
                    "offset": {
                        "type": "integer",
                        "description": (
                            "1-based starting line (optional). "
                            "With limit, reads at most "
                            f"{MAX_READ_LINES} lines per call."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Max lines from offset (optional)."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            side_effect=SideEffectClass.READ_ONLY,
            allow_parallel=True,
        ),
        "read_symbol": read_symbol_tool_spec(),
        "write_file": ToolSpec(
            name="write_file",
            description=(
                "Write a UTF-8 file under AILIT_WORK_ROOT. "
                "Path must be a concrete file path."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative file path under AILIT_WORK_ROOT."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Full new file contents.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            side_effect=SideEffectClass.WRITE,
            requires_approval=False,
        ),
        "echo": ToolSpec(
            name="echo",
            description="Echo message for tests.",
            parameters_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            },
            side_effect=SideEffectClass.NONE,
            allow_parallel=True,
        ),
    }
