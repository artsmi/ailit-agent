"""DTO для `memory.change_feedback` (G13.3, D13.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping

_OP_SET: Final[frozenset[str]] = frozenset(
    ("create", "modify", "delete", "rename"),
)


@dataclass(frozen=True, slots=True)
class TouchedRange:
    """Диапазон строк, затронутый изменением."""

    start: int
    end: int

    @classmethod
    def from_json(cls, raw: Any) -> TouchedRange | None:
        if not isinstance(raw, Mapping):
            return None
        try:
            s = int(raw.get("start", 0) or 0)
            e = int(raw.get("end", 0) or 0)
        except (TypeError, ValueError):
            return None
        if s < 0 or e < 0 or e < s:
            return None
        return cls(start=s, end=e)


@dataclass(frozen=True, slots=True)
class ChangedFileFeedback:
    """Один файл в батче `memory.change_feedback`."""

    path: str
    operation: str
    old_path: str | None
    tool_call_id: str
    message_id: str
    content_before_fingerprint: str | None
    content_after_fingerprint: str
    line_ranges_touched: tuple[TouchedRange, ...]
    symbol_hints: tuple[str, ...]
    change_summary: str
    requires_llm_review: bool

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> ChangedFileFeedback:
        p = str(raw.get("path", "") or "").strip()
        if not p:
            raise ValueError("changed_file.path is required")
        op = str(raw.get("operation", "modify") or "modify").strip().lower()
        if op not in _OP_SET:
            raise ValueError("changed_file.operation is invalid")
        op_old: str | None
        s_old = str(raw.get("old_path", "") or "").strip()
        op_old = s_old or None
        tci = str(raw.get("tool_call_id", "") or "")
        if not tci.strip():
            tci = str(raw.get("tool_name", "") or "unknown")
        msg_id = str(raw.get("message_id", "") or tci)
        c_before = str(raw.get("content_before_fingerprint", "") or "").strip()
        c_b = c_before or None
        c_after = str(raw.get("content_after_fingerprint", "") or "").strip()
        if not c_after:
            raise ValueError("content_after_fingerprint is required")
        ranges: list[TouchedRange] = []
        lr = raw.get("line_ranges_touched")
        if isinstance(lr, list):
            for it in lr:
                tr = TouchedRange.from_json(it)
                if tr is not None:
                    ranges.append(tr)
        hints: list[str] = []
        sh = raw.get("symbol_hints")
        if isinstance(sh, list):
            for x in sh:
                t = str(x or "").strip()
                if t:
                    hints.append(t)
        raw_sum = str(raw.get("change_summary", "") or "change").strip()
        csum = raw_sum or "change"
        rlr = bool(raw.get("requires_llm_review", False))
        return cls(
            path=p,
            operation=op,
            old_path=op_old,
            tool_call_id=tci.strip() or "unknown",
            message_id=msg_id.strip() or tci,
            content_before_fingerprint=c_b,
            content_after_fingerprint=c_after,
            line_ranges_touched=tuple(ranges),
            symbol_hints=tuple(hints),
            change_summary=csum,
            requires_llm_review=rlr,
        )


@dataclass(frozen=True, slots=True)
class MemoryChangeDecision:
    """Решение AgentMemory по одному файлу (compact)."""

    path: str
    mode: str
    reason: str
    b_fingerprint: str
    c_updated: int
    c_needs_llm_remap: int


@dataclass(frozen=True, slots=True)
class AgentWorkChangeFeedback:
    """Service payload `memory.change_feedback` (D13.3)."""

    chat_id: str
    request_id: str
    turn_id: str
    namespace: str
    project_root: str
    source: str
    change_batch_id: str
    goal: str
    user_intent_summary: str
    changed_files: tuple[ChangedFileFeedback, ...] = field(
        default_factory=tuple,
    )

    @classmethod
    def from_payload(cls, pl: Mapping[str, Any]) -> AgentWorkChangeFeedback:
        ch = str(pl.get("chat_id", "") or "").strip()
        if not ch:
            raise ValueError("chat_id is required")
        request_id = str(pl.get("request_id", "") or "").strip() or "req"
        turn_id = str(pl.get("turn_id", "") or "").strip() or "turn"
        namespace = str(pl.get("namespace", "") or "").strip() or "default"
        proot = str(pl.get("project_root", "") or "").strip()
        if not proot:
            raise ValueError("project_root is required")
        src = str(pl.get("source", "") or "AgentWork").strip() or "AgentWork"
        batch = str(pl.get("change_batch_id", "") or "").strip()
        if not batch:
            raise ValueError("change_batch_id is required")
        goal = str(pl.get("goal", "") or "").strip()
        u0 = pl.get("user_intent_summary", "") or pl.get("goal", "") or ""
        ui = str(u0).strip()
        raw_files = pl.get("changed_files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("changed_files[] is required")
        files: list[ChangedFileFeedback] = []
        for it in raw_files:
            if not isinstance(it, Mapping):
                continue
            files.append(ChangedFileFeedback.from_json(it))
        if not files:
            raise ValueError("changed_files has no valid entries")
        return cls(
            chat_id=ch,
            request_id=request_id,
            turn_id=turn_id,
            namespace=namespace,
            project_root=proot,
            source=src,
            change_batch_id=batch,
            goal=goal,
            user_intent_summary=ui,
            changed_files=tuple(files),
        )

    def idempotency_fingerprint(self) -> str:
        """Составной ключ для idempotency (G13.3)."""
        parts: list[str] = [
            self.change_batch_id,
            self.namespace,
            self.project_root,
        ]
        for cf in sorted(self.changed_files, key=lambda c: c.path):
            parts.append(f"{cf.path}:{cf.content_after_fingerprint}")
        return "|".join(parts)
