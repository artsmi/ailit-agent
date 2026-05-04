"""Финальный пользовательский summary для ``memory init`` (UC-02, C7)."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Final, Literal, TextIO

from agent_core.runtime.compact_observability_sink import (
    normalize_compact_event_name,
)

# События compact sink: явные подписи в блоке ``events_by_kind``.
_LABELLED_AGGREGATION_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "orch_memory_init_started",
        "orch_memory_init_phase",
        "memory.result.returned",
        "memory.why_llm",
        "memory.pag_graph",
        "memory.w14_graph_highlight",
        "memory.link_candidates",
        "memory.links_updated",
        "memory.summarize_c.apply_failed",
    },
)

_OTHER_BUCKET: Final[str] = "other"


def parse_compact_flat_kv(line: str) -> dict[str, str]:
    """
    Разбор одной строки ``compact.log`` в стиле ``build_compact_line``:

    пары ``key=value`` или ``key="quoted"`` через пробел; без вложенного JSON.
    """
    s = line.strip()
    out: dict[str, str] = {}
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        eq = s.find("=", i)
        if eq < 0:
            break
        key = s[i:eq].strip()
        if not key:
            break
        j = eq + 1
        if j < n and s[j] == '"':
            j += 1
            buf: list[str] = []
            while j < n:
                c = s[j]
                if c == "\\" and j + 1 < n:
                    buf.append(s[j + 1])
                    j += 2
                    continue
                if c == '"':
                    j += 1
                    break
                buf.append(c)
                j += 1
            out[key] = "".join(buf)
            i = j
            continue
        start = j
        while j < n and not s[j].isspace():
            j += 1
        out[key] = s[start:j]
        i = j
    return out


class CompactLineAggregator:
    """Счётчики по ``event=`` (второй проход, нормализация имён)."""

    def __init__(self) -> None:
        self._counts: defaultdict[str, int] = defaultdict(int)

    def feed_line(self, line: str) -> None:
        fields = parse_compact_flat_kv(line)
        raw_ev = fields.get("event", "").strip()
        if not raw_ev:
            return
        norm = normalize_compact_event_name(raw_ev)
        if norm in _LABELLED_AGGREGATION_EVENTS:
            self._counts[norm] += 1
        else:
            self._counts[_OTHER_BUCKET] += 1

    def feed_file(self, path: Path) -> None:
        p = path.resolve()
        if not p.exists():
            return
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            return
        for line in body.splitlines():
            self.feed_line(line)

    def bucket_counts(self) -> dict[str, int]:
        items = sorted(
            self._counts.items(),
            key=lambda kv: (kv[0] == _OTHER_BUCKET, kv[0]),
        )
        return dict(items)


class MemoryInitSummaryFormatter:
    """Сборка текста summary: D4, агрегация, UI-trace (без broker JSON)."""

    @staticmethod
    def d4_lines(counters: tuple[int, int, int]) -> list[str]:
        n_why, n_pg_node, n_w14 = counters
        return [
            f"  memory.why_llm: {n_why}",
            f"  memory.pag_graph(node): {n_pg_node}",
            f"  memory.w14_graph_highlight: {n_w14}",
        ]

    @staticmethod
    def event_bucket_lines(counts: dict[str, int]) -> list[str]:
        if not counts:
            return ["  (no event= lines)"]
        lines: list[str] = []
        keys = sorted(counts.keys(), key=lambda k: (k == _OTHER_BUCKET, k))
        for k in keys:
            lines.append(f"  {k}: {counts[k]}")
        return lines

    @staticmethod
    def ui_trace_lines(compact_path: Path) -> list[str]:
        p = compact_path.resolve()
        if not p.exists():
            return ["  (compact log missing)"]
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            return ["  (compact log unreadable)"]
        out: list[str] = []
        for line in body.splitlines():
            fields = parse_compact_flat_kv(line)
            raw_ev = fields.get("event", "").strip()
            if not raw_ev:
                continue
            norm = normalize_compact_event_name(raw_ev)
            if norm == "memory.pag_graph":
                op = fields.get("op", "").strip()
                if op in ("node", "edge", "edge_batch"):
                    parts = [f"op={op}"]
                    for key in (
                        "ns",
                        "rev",
                        "subject",
                        "count",
                        "first",
                        "last",
                    ):
                        if key in fields:
                            parts.append(f"{key}={fields[key]}")
                    out.append(f"  graph {' '.join(parts)}")
            elif norm == "memory.w14_graph_highlight":
                parts = []
                for key in (
                    "query_id",
                    "w14_command",
                    "n_node",
                    "n_edge",
                ):
                    if key in fields:
                        parts.append(f"{key}={fields[key]}")
                if parts:
                    out.append(f"  w14 highlight {' '.join(parts)}")
                else:
                    out.append("  w14 highlight")
            elif norm == "memory.link_candidates":
                parts_lc = []
                for key in ("query_id", "n_cand"):
                    if key in fields:
                        parts_lc.append(f"{key}={fields[key]}")
                if parts_lc:
                    out.append(f"  {norm} {' '.join(parts_lc)}")
            elif norm == "memory.links_updated":
                parts_lu = []
                for key in ("query_id", "n_applied", "n_rejected"):
                    if key in fields:
                        parts_lu.append(f"{key}={fields[key]}")
                if parts_lu:
                    out.append(f"  {norm} {' '.join(parts_lu)}")
            elif norm == "memory.summarize_c.apply_failed":
                parts_af = []
                for key in ("reason", "node", "lines", "command_id"):
                    if key in fields:
                        parts_af.append(f"{key}={fields[key]}")
                if parts_af:
                    out.append(f"  {norm} {' '.join(parts_af)}")
            elif norm == "memory.llm.completed":
                ph = fields.get("phase", "").strip()
                rsn = fields.get("reason", "").strip()
                if ph in ("summarize_c_repair", "summarize_b_repair"):
                    clip = rsn[:160] if rsn else ""
                    out.append(
                        f"  memory.llm.completed phase={ph} reason={clip}",
                    )
                elif ph in ("summarize_c", "summarize_b") and (
                    "parse_ok" in rsn or "parse_failed" in rsn
                ):
                    clip = rsn[:200] if rsn else ""
                    out.append(
                        f"  memory.llm.completed phase={ph} reason={clip}",
                    )
        if not out:
            return ["  (no graph / highlight rows)"]
        return out


def emit_memory_init_user_summary(
    compact_path: Path,
    exit_kind: Literal["complete", "partial", "blocked"],
    d4: tuple[int, int, int],
    *,
    reason_short: str | None = None,
    out: TextIO | None = None,
) -> None:
    """
    Печать финального блока на stderr: абсолютный путь, статус, D4, агрегация,
    краткий UI-trace по graph/highlight (только плоские поля compact).
    """
    sink: TextIO = out if out is not None else sys.stderr
    abs_compact = compact_path.resolve()
    agg = CompactLineAggregator()
    agg.feed_file(abs_compact)

    lines: list[str] = [
        "=== memory init summary ===",
        f"compact_log={abs_compact}",
        f"status={exit_kind}",
    ]
    if reason_short and exit_kind != "complete":
        safe = reason_short.replace("\n", " ").strip()
        if safe:
            lines.append(f"abort_reason={safe}")
    lines.append("d4:")
    lines.extend(MemoryInitSummaryFormatter.d4_lines(d4))
    lines.append("events_by_kind:")
    lines.extend(
        MemoryInitSummaryFormatter.event_bucket_lines(agg.bucket_counts()),
    )
    lines.append("ui_trace:")
    lines.extend(MemoryInitSummaryFormatter.ui_trace_lines(abs_compact))
    for ln in lines:
        sink.write(ln + "\n")
    sink.flush()
