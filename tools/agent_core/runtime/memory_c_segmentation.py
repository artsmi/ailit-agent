"""Универсальная LLM-сегментация C и механический каталог чанков (G12.6)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from agent_core.runtime.agent_memory_config import (
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
    """Построение каталога чанков без семантики (G12.6 п.3)."""

    def __init__(
        self,
        *,
        line_window: int = 200,
        max_chunks: int = 80,
    ) -> None:
        self._line_window: int = max(20, int(line_window))
        self._max_chunks: int = max(1, int(max_chunks))

    def build(self, text: str, relative_path: str) -> tuple[MechanicalChunk, ...]:
        rel = str(relative_path or "").replace("\\", "/").lower()
        lines = (text or "").splitlines()
        if rel.endswith(".md"):
            return self._markdown_headings(text, lines)
        if rel.endswith((".json", ".yaml", ".yml")):
            return self._line_windows_with_json_top_keys_hint(lines, rel)
        if rel.endswith((".xml", ".launch", ".urdf")):
            return self._xmlish_line_blocks(lines)
        return self._line_windows_only(lines)

    def _line_windows_only(self, lines: list[str]) -> tuple[MechanicalChunk, ...]:
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
            body = "\n".join(
                lines[max(0, start - 1) : min(nlines, end)],
            )[:1_200]
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
        merged.append(
            MechanicalChunk(
                chunk_id="struct_top_keys",
                start_line=1,
                end_line=min(50, len(lines) or 1),
                chunk_kind="json_top_keys" if rel.endswith(".json") else "yaml_block",
                preview=(head + "\nkeys: " + ", ".join(extra))[:1_200],
            ),
        )
        return tuple(merged[: self._max_chunks])

    def _xmlish_line_blocks(self, lines: list[str]) -> tuple[MechanicalChunk, ...]:
        """Маркерный chunk_kind для .xml/.launch/.urdf; сетка — line windows."""
        base = self._line_windows_only(lines)
        merged: list[MechanicalChunk] = []
        for i, ch in enumerate(base):
            merged.append(
                MechanicalChunk(
                    chunk_id=ch.chunk_id,
                    start_line=ch.start_line,
                    end_line=ch.end_line,
                    chunk_kind="xml_urdf_window",
                    preview=ch.preview,
                ),
            )
        return tuple(merged)
