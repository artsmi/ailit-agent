"""Post-compaction restore of recently read files (M3).

Goal: after compaction/shortlist, re-inject a small, budgeted slice of recently
read file content so the model does not immediately re-read the same files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_core.models import ChatMessage, MessageRole
from agent_core.tool_runtime.workdir_paths import (
    resolve_file_under_root,
    work_root,
)


@dataclass(frozen=True, slots=True)
class RecentFileRead:
    """One recent `read_file` result."""

    path: str
    offset: int
    limit: int | None
    mtime_ns: int
    content: str
    order: int

    def marker(self) -> str:
        """Stable marker for dedup within a prompt window."""
        lim = "" if self.limit is None else str(self.limit)
        return (
            "[restored file] "
            f"path={self.path} "
            f"offset={self.offset} "
            f"limit={lim}"
        )


@dataclass(frozen=True, slots=True)
class RestorePlan:
    """What we decided to restore into the next context."""

    restored: tuple[RecentFileRead, ...]
    injected_chars: int


class RecentFileReadStore:
    """Tracks recent file reads and builds restore messages."""

    def __init__(self) -> None:
        self._by_key: dict[
            tuple[str, int, int | None, int],
            RecentFileRead,
        ] = {}
        self._order: int = 0

    def observe_read_file(
        self,
        *,
        arguments_json: str,
        tool_output: str,
    ) -> None:
        """Record a successful read_file output if it contains content."""
        try:
            raw = json.loads(arguments_json) if arguments_json.strip() else {}
        except json.JSONDecodeError:
            return
        if not isinstance(raw, dict):
            return
        p = raw.get("path")
        if not isinstance(p, str) or not p.strip():
            return
        offset = int(raw.get("offset", 1) or 1)
        lim_raw = raw.get("limit")
        limit: int | None
        if lim_raw is None or lim_raw == "":
            limit = None
        else:
            try:
                limit = int(lim_raw)
            except (TypeError, ValueError):
                limit = None

        body = str(tool_output or "")
        if not body.strip():
            return
        # If tool returned the "unchanged stub", we don't have fresh content.
        if body.startswith("File unchanged since last read in this process:"):
            return

        try:
            mtime_ns = int(resolve_file_under_root(p).stat().st_mtime_ns)
        except OSError:
            mtime_ns = 0

        self._order += 1
        rec = RecentFileRead(
            path=p.strip(),
            offset=offset,
            limit=limit,
            mtime_ns=mtime_ns,
            content=body,
            order=self._order,
        )
        key = (rec.path, rec.offset, rec.limit, rec.mtime_ns)
        self._by_key[key] = rec

    def build_restore_message(
        self,
        *,
        already_in_context: str,
        max_files: int,
        max_chars_per_file: int,
        max_total_chars: int,
    ) -> tuple[ChatMessage | None, RestorePlan]:
        """Build a single SYSTEM message with restored file slices."""
        if max_files <= 0 or max_chars_per_file <= 0 or max_total_chars <= 0:
            return None, RestorePlan(restored=(), injected_chars=0)

        # Order by recency (order increasing).
        recent = sorted(
            self._by_key.values(),
            key=lambda r: r.order,
            reverse=True,
        )
        picked: list[RecentFileRead] = []
        injected = 0
        blocks: list[str] = []
        for rec in recent:
            if len(picked) >= max_files:
                break
            if rec.marker() in already_in_context:
                continue
            snippet = rec.content
            if len(snippet) > max_chars_per_file:
                snippet = snippet[:max_chars_per_file] + "\n...[truncated]"
            block = f"{rec.marker()}\n{snippet}".rstrip()
            if injected + len(block) + 2 > max_total_chars:
                continue
            picked.append(rec)
            blocks.append(block)
            injected += len(block) + 2

        if not blocks:
            return None, RestorePlan(restored=(), injected_chars=0)

        hdr = (
            "Ниже — восстановленные фрагменты недавно прочитанных файлов "
            "(post-compaction restore). Не перечитывай их заново, если этого "
            "достаточно; запрашивай range read только при необходимости."
        )
        root = Path(work_root())
        text = "\n\n".join(
            [hdr, f"work_root={root.as_posix()}", *blocks],
        ).rstrip()
        msg = ChatMessage(role=MessageRole.SYSTEM, content=text)
        plan = RestorePlan(restored=tuple(picked), injected_chars=len(text))
        return msg, plan
