"""Универсальная LLM-сегментация C и механический каталог чанков (G12.6)."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from agent_memory.config.agent_memory_config import (
    ArtifactsSubConfig,
    MemoryLlmSubConfig,
    SourceBoundaryFilter,
)

TextIngestionMode = Literal["forbidden", "full", "chunked"]


_TEXT_LIKE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".py",
        ".md",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".xml",
        ".launch",
        ".urdf",
        ".rs",
        ".go",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
        ".html",
        ".sh",
        ".sql",
    },
)

_MD_HEADING: Final[re.Pattern[str]] = re.compile(
    r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class MechanicalChunk:
    """Один механический чанк B без семантических предположений."""

    chunk_id: str
    start_line: int
    end_line: int
    chunk_kind: str
    preview: str

    def to_catalog_row(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "chunk_kind": self.chunk_kind,
            "preview": self.preview,
        }


class FingerprintService:
    """Единая точка для content/summary отпечатков."""

    @staticmethod
    def sha256_text(text: str) -> str:
        return hashlib.sha256(
            (text or "").encode("utf-8", errors="replace"),
        ).hexdigest()

    @staticmethod
    def b_fingerprint_file_bytes(data: bytes) -> str:
        return hashlib.sha1(data).hexdigest()


class FullBIngestionPolicy:
    """Решение: full-B, chunked или запрет (артефакты / not text-like)."""

    def __init__(self, artifacts: ArtifactsSubConfig) -> None:
        self._boundary: SourceBoundaryFilter = SourceBoundaryFilter(artifacts)

    def classify(
        self,
        relative_path: str,
        *,
        size_bytes: int,
        llm: MemoryLlmSubConfig,
    ) -> TextIngestionMode:
        """Классификация пути и размера — до вызова LLM."""
        rel = str(relative_path or "").replace("\\", "/").strip()
        if self._boundary.is_forbidden_source_path(rel):
            return "forbidden"
        if not is_text_like_path(rel):
            return "forbidden"
        if int(size_bytes) <= int(llm.max_full_b_bytes):
            return "full"
        return "chunked"


def is_text_like_path(relative_path: str) -> bool:
    """Эвристика text-like исходника (не бинарь по суффиксу)."""
    p = Path(str(relative_path or "").replace("\\", "/"))
    suf = p.suffix.lower()
    if not suf:
        return True
    if suf in _TEXT_LIKE_SUFFIXES:
        return True
    return False


def should_read_artifact_bytes(
    relative_path: str,
    *,
    boundary: SourceBoundaryFilter,
    allow_explicit: bool,
) -> bool:
    """
    True — можно читать байты для metadata/content.

    Явный запрос артефакта: сначала metadata; content — если allow_explicit.
    """
    rel = str(relative_path or "").replace("\\", "/").strip()
    forbidden = boundary.is_forbidden_source_path(rel)
    if not forbidden:
        return True
    return bool(allow_explicit)


class MechanicalChunkCatalogBuilder:
    """
    Построение каталога чанков без семантики (G12.6 п.3).

    G13.4: каталог — только кандидаты для LLM, не authority для C identity.
    """

    def __init__(
        self,
        *,
        line_window: int = 200,
        max_chunks: int = 80,
    ) -> None:
        self._line_window: int = max(20, int(line_window))
        self._max_chunks: int = max(1, int(max_chunks))

    def build(
        self,
        text: str,
        relative_path: str,
    ) -> tuple[MechanicalChunk, ...]:
        rel = str(relative_path or "").replace("\\", "/").lower()
        lines = (text or "").splitlines()
        if rel.endswith(".md"):
            return self._markdown_headings(text, lines)
        if rel.endswith((".json", ".yaml", ".yml")):
            return self._line_windows_with_json_top_keys_hint(lines, rel)
        if rel.endswith((".xml", ".launch", ".urdf")):
            return self._xmlish_line_blocks(lines)
        return self._line_windows_only(lines)

    def _line_windows_only(
        self,
        lines: list[str],
    ) -> tuple[MechanicalChunk, ...]:
        out: list[MechanicalChunk] = []
        n = len(lines) or 1
        step = self._line_window
        i = 0
        idx = 0
        while i < n and len(out) < self._max_chunks:
            j = min(n, i + step)
            sl = i + 1
            el = j
            body = "\n".join(lines[i:j])
            pv = body[:1_200]
            idx += 1
            out.append(
                MechanicalChunk(
                    chunk_id=f"line_win_{idx}",
                    start_line=sl,
                    end_line=el,
                    chunk_kind="line_window",
                    preview=pv,
                ),
            )
            i += step
        return tuple(out)

    def _markdown_headings(
        self,
        text: str,
        lines: list[str],
    ) -> tuple[MechanicalChunk, ...]:
        out: list[MechanicalChunk] = []
        matches: list[tuple[int, int, str]] = []
        for m in _MD_HEADING.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            title = str(m.groupdict().get("title", "") or "").strip()
            level = len(str(m.groupdict().get("hashes", "") or ""))
            matches.append((line_no, level, title))
        if not matches:
            return self._line_windows_only(lines)
        nlines = len(lines)
        for i, (ln, _lvl, title) in enumerate(matches[: self._max_chunks]):
            start = ln
            end = (
                matches[i + 1][0] - 1
                if i + 1 < len(matches)
                else nlines
            ) or nlines
            end = max(end, start)
            lo = max(0, start - 1)
            hi = min(nlines, end)
            body = "\n".join(lines[lo:hi])[:1_200]
            out.append(
                MechanicalChunk(
                    chunk_id=f"md_h_{i+1}",
                    start_line=start,
                    end_line=end,
                    chunk_kind="md_section",
                    preview=body or title,
                ),
            )
        return tuple(out) if out else self._line_windows_only(lines)

    def _line_windows_with_json_top_keys_hint(
        self,
        lines: list[str],
        rel: str,
    ) -> tuple[MechanicalChunk, ...]:
        base = self._line_windows_only(lines)
        head = "\n".join(lines[:50])
        extra: list[str] = []
        try:
            if rel.endswith(".json"):
                o = json.loads("\n".join(lines))
                if isinstance(o, dict):
                    extra = [str(k) for k in list(o.keys())[:30]]
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            extra = []
        if not extra:
            return base
        merged: list[MechanicalChunk] = list(base[: self._max_chunks - 1])
        ck = "json_top_keys" if rel.endswith(".json") else "yaml_block"
        merged.append(
            MechanicalChunk(
                chunk_id="struct_top_keys",
                start_line=1,
                end_line=min(50, len(lines) or 1),
                chunk_kind=ck,
                preview=(head + "\nkeys: " + ", ".join(extra))[:1_200],
            ),
        )
        return tuple(merged[: self._max_chunks])


# --- G14R.4: runtime-единообразная декомпозиция B -> C ---


@dataclass(frozen=True, slots=True)
class CNodeBoundary:
    """
    Семантическая граница C для одного B-файла.

    Идентичность C не привязывается к абсолютным номерам строк: ``c_node_id``
    стабилен при вставке строк *вне* сегмента, если тот же symbol_key и
    content_sha256 (содержимое выбранного диапазона не изменилось).
    """

    relative_path: str
    start_line: int
    end_line: int
    semantic_kind: str
    title: str
    symbol_key: str
    content_sha256: str
    pag_kind: str
    source_truncated: bool = False

    def c_node_id(self) -> str:
        return compute_stable_c_node_id(
            self.relative_path,
            self.symbol_key,
            self.content_sha256,
        )

    @staticmethod
    def from_segment(
        rel: str,
        start_line: int,
        end_line: int,
        semantic_kind: str,
        title: str,
        symbol_key: str,
        segment_text: str,
        pag_kind: str,
        *,
        source_truncated: bool = False,
    ) -> CNodeBoundary:
        csha = FingerprintService.sha256_text(segment_text)
        return CNodeBoundary(
            relative_path=rel,
            start_line=int(start_line),
            end_line=int(end_line),
            semantic_kind=semantic_kind,
            title=title,
            symbol_key=symbol_key,
            content_sha256=csha,
            pag_kind=pag_kind,
            source_truncated=source_truncated,
        )


def compute_stable_c_node_id(
    relative_path: str,
    symbol_key: str,
    content_sha256: str,
) -> str:
    rel = str(relative_path or "").replace("\\", "/").strip()
    key = f"{rel}\0{symbol_key}\0{content_sha256}"
    h = hashlib.sha1(
        key.encode("utf-8", errors="replace"),
    ).hexdigest()[:16]
    return f"C:{rel}#{h}"


def _line_slice_text(
    all_lines: list[str],
    start: int,
    end: int,
) -> str:
    lo = max(0, start - 1)
    hi = min(len(all_lines), end)
    return "\n".join(all_lines[lo:hi])


def _ast_top_level_python_boundaries(
    tree: ast.AST,
    text: str,
    rel: str,
) -> list[CNodeBoundary]:
    all_lines = text.splitlines()
    out: list[CNodeBoundary] = []
    for node in getattr(tree, "body", []):
        b: CNodeBoundary | None = None
        if isinstance(node, ast.FunctionDef):
            b = _boundary_from_stmt(
                rel, node, all_lines, "function", "function", node.name
            )
        elif isinstance(node, ast.AsyncFunctionDef):
            b = _boundary_from_stmt(
                rel, node, all_lines, "function", "async_function", node.name
            )
        elif isinstance(node, ast.ClassDef):
            b = _boundary_from_stmt(
                rel, node, all_lines, "class", "class", node.name
            )
        if b is not None:
            out.append(b)
    return out


def _boundary_from_stmt(
    rel: str,
    node: ast.AST,
    all_lines: list[str],
    semantic: str,
    kind: str,
    name: str,
) -> CNodeBoundary:
    start = int(getattr(node, "lineno", 1) or 1)
    end_raw = getattr(node, "end_lineno", None)
    end = int(end_raw) if end_raw is not None else start
    text = _line_slice_text(all_lines, start, end)
    key = f"{kind}:{name}"
    return CNodeBoundary.from_segment(
        rel,
        start,
        end,
        semantic,
        name,
        key,
        text,
        kind,
    )


def _mechanical_chunks_to_c_boundaries(
    rel: str,
    text: str,
    chunks: tuple[MechanicalChunk, ...],
) -> list[CNodeBoundary]:
    all_lines = text.splitlines()
    out: list[CNodeBoundary] = []
    for ch in chunks:
        seg = _line_slice_text(all_lines, ch.start_line, ch.end_line)
        csha = FingerprintService.sha256_text(seg)
        sym = f"{ch.chunk_id}:{csha[:12]}"
        is_md_heading = (ch.chunk_kind or "") == "md_section" or str(
            ch.chunk_id,
        ).startswith("md_h_")
        if is_md_heading:
            sem, kind = "section", "section"
        else:
            sem, kind = "line_window", "line_window"
        out.append(
            CNodeBoundary.from_segment(
                rel,
                ch.start_line,
                ch.end_line,
                sem,
                (ch.preview or ch.chunk_id)[:240],
                sym,
                seg,
                kind,
            ),
        )
    return out


class BToCDecompositionService:
    """
    Единая точка декомпозиции B-файла в набор C-границ (G14R.4).

    - Python: AST, верхнеуровневые def/class; при ошибке — line windows;
    - Markdown: секции по ## или line windows, если нет структуры;
    - Прочий text-like: line windows.
    Путь, запрещённый :class:`FullBIngestionPolicy`, не возвращает C-нод.
    """

    def __init__(
        self,
        *,
        line_window: int = 200,
        max_chunks: int = 80,
    ) -> None:
        self._mechanical: MechanicalChunkCatalogBuilder = (
            MechanicalChunkCatalogBuilder(
                line_window=line_window,
                max_chunks=max_chunks,
            )
        )

    def decompose_b_to_c(
        self,
        relative_path: str,
        text: str,
        *,
        size_bytes: int,
        policy: FullBIngestionPolicy,
        llm: MemoryLlmSubConfig,
        source_truncated: bool = False,
    ) -> list[CNodeBoundary]:
        rel = str(relative_path or "").replace("\\", "/").strip()
        mode = policy.classify(rel, size_bytes=size_bytes, llm=llm)
        if mode == "forbidden":
            return []
        if not (text or "").strip():
            return []
        low = rel.lower()
        if low.endswith(".py"):
            return self._decompose_python(
                rel,
                text,
                source_truncated=source_truncated,
            )
        if low.endswith(".md"):
            return self._decompose_markdown(rel, text)
        return self._decompose_mech_default(rel, text)

    def _decompose_python(
        self,
        rel: str,
        text: str,
        *,
        source_truncated: bool,
    ) -> list[CNodeBoundary]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._decompose_mech_default(rel, text)
        b = _ast_top_level_python_boundaries(tree, text, rel)
        if not b:
            return self._decompose_mech_default(rel, text)
        if source_truncated:
            return [self._with_truncation(x) for x in b]
        return b

    @staticmethod
    def _with_truncation(b: CNodeBoundary) -> CNodeBoundary:
        return CNodeBoundary(
            relative_path=b.relative_path,
            start_line=b.start_line,
            end_line=b.end_line,
            semantic_kind=b.semantic_kind,
            title=b.title,
            symbol_key=b.symbol_key,
            content_sha256=b.content_sha256,
            pag_kind=b.pag_kind,
            source_truncated=True,
        )

    def _decompose_markdown(self, rel: str, text: str) -> list[CNodeBoundary]:
        ch = self._mechanical.build(text, rel)
        if not ch:
            return []
        return _mechanical_chunks_to_c_boundaries(rel, text, ch)

    def _decompose_mech_default(
        self,
        rel: str,
        text: str,
    ) -> list[CNodeBoundary]:
        ch = self._mechanical.build(text, rel)
        if not ch:
            return []
        return _mechanical_chunks_to_c_boundaries(rel, text, ch)
