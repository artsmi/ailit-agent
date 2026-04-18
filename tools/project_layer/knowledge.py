"""Canonical context / knowledge_refresh: порт и файловая реализация."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from project_layer.loader import LoadedProject


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Снимок canonical context для shortlist и превью."""

    shortlist_keywords: frozenset[str]
    canonical_rel_paths: tuple[str, ...]
    preview_text: str
    warnings: tuple[str, ...]


_STOPWORDS: frozenset[str] = frozenset(
    {
        "about",
        "after",
        "also",
        "been",
        "before",
        "being",
        "between",
        "both",
        "could",
        "does",
        "doing",
        "done",
        "each",
        "from",
        "have",
        "here",
        "into",
        "itself",
        "just",
        "like",
        "make",
        "more",
        "most",
        "much",
        "only",
        "other",
        "should",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "those",
        "through",
        "under",
        "very",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "would",
        "your",
    },
)


def _tokenize_for_keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", text)
    out: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in _STOPWORDS:
            continue
        out.append(lw)
    return out


def _markdown_headings(text: str) -> list[str]:
    heads: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            heads.append(s.lstrip("#").strip())
    return heads


@runtime_checkable
class KnowledgeRefreshPort(Protocol):
    """Порт обновления знаний (thin adapter для внешних реализаций)."""

    def refresh(self, loaded: LoadedProject) -> ContextSnapshot:
        """Построить снимок canonical context."""


class StubKnowledgeRefresh:
    """Заглушка: только memory_hints и пустой shortlist."""

    def refresh(self, loaded: LoadedProject) -> ContextSnapshot:
        hints = " ".join(loaded.config.memory_hints)
        kws = frozenset(_tokenize_for_keywords(hints)) if hints else frozenset()
        preview = "\n".join(f"- {h}" for h in loaded.config.memory_hints) or "(no memory_hints)"
        return ContextSnapshot(
            shortlist_keywords=kws,
            canonical_rel_paths=(),
            preview_text=preview,
            warnings=("knowledge_refresh mode=stub",),
        )


class FilesystemKnowledgeRefresh:
    """Чтение canonical файлов по glob относительно корня проекта."""

    def refresh(self, loaded: LoadedProject) -> ContextSnapshot:
        cfg = loaded.config.context.knowledge_refresh
        warnings: list[str] = []
        files: list[Path] = []
        for pattern in loaded.config.context.canonical_globs:
            hits = sorted(loaded.root.glob(pattern))
            for p in hits:
                if p.is_file() and p.suffix.lower() in {".md", ".txt", ".yaml", ".yml"}:
                    files.append(p)
        dedup: dict[str, Path] = {}
        for p in files:
            try:
                rel = str(p.resolve().relative_to(loaded.root.resolve()))
            except ValueError:
                rel = str(p)
            dedup[rel] = p
        ordered = list(dedup.items())[: cfg.max_files]
        rel_paths = tuple(r for r, _ in ordered)

        freq: dict[str, int] = {}
        preview_chunks: list[str] = []
        char_budget = cfg.max_chars_per_file * min(len(ordered), cfg.max_files)
        used = 0
        for rel, p in ordered:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                warnings.append(f"read failed {rel}: {exc}")
                continue
            slice_len = min(len(text), cfg.max_chars_per_file)
            chunk = text[:slice_len]
            if used + len(chunk) > char_budget:
                chunk = chunk[: max(0, char_budget - used)]
            used += len(chunk)
            preview_chunks.append(f"### {rel}\n{chunk}")
            for h in _markdown_headings(text):
                for t in _tokenize_for_keywords(h):
                    freq[t] = freq.get(t, 0) + 3
            for t in _tokenize_for_keywords(text):
                freq[t] = freq.get(t, 0) + 1
            if used >= char_budget:
                break

        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
        kws_list = [w for w, _ in ranked[: cfg.max_keywords]]
        extra = loaded.config.memory_hints
        for h in extra:
            kws_list.extend(_tokenize_for_keywords(h))
        keywords = frozenset(kws_list)

        preview = "\n\n".join(preview_chunks) if preview_chunks else "(no canonical files matched)"
        return ContextSnapshot(
            shortlist_keywords=keywords,
            canonical_rel_paths=rel_paths,
            preview_text=preview,
            warnings=tuple(warnings),
        )
