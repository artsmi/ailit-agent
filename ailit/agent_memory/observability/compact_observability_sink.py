"""Единый писатель CLI ``compact.log`` + tee на stderr (D2, D4, UC-06)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from agent_memory.observability.agent_memory_chat_log import _write_lock
from agent_memory.contracts.agent_memory_external_events import (
    normalize_compact_event_name,
)
from ailit_runtime.models import RuntimeRequestEnvelope


def _scalar_to_compact_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(int(v))
    s = str(v).replace("\n", " ").replace("\r", " ")
    if "{" in s or "}" in s:
        s = s.replace("{", "").replace("}", "")
    return s.strip()


def _fmt_kv(key: str, value: str) -> str:
    if not value and key not in ("status", "event"):
        return ""
    if any(c in value for c in (" ", "\t", '"', "=")):
        esc = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{esc}"'
    return f"{key}={value}"


def build_compact_line(
    *,
    timestamp: str,
    init_session_id: str,
    chat_id: str,
    event: str,
    fields: Mapping[str, str | int | bool] | None = None,
) -> str:
    """Одна строка плоских ``key=value`` без вложенного JSON."""
    norm_event = normalize_compact_event_name(event)
    parts: list[str] = [
        _fmt_kv("timestamp", timestamp),
        _fmt_kv("init_session_id", str(init_session_id)),
        _fmt_kv("chat_id", str(chat_id)),
        _fmt_kv("event", norm_event),
    ]
    if fields:
        for k, v in sorted(fields.items()):
            ks = str(k).strip()
            if not ks:
                continue
            sv = _scalar_to_compact_value(v)
            if not sv:
                continue
            piece = _fmt_kv(ks, sv)
            if piece:
                parts.append(piece)
    line = " ".join(p for p in parts if p)
    if "\n" in line:
        line = line.replace("\n", " ")
    return line + "\n"


def build_memory_llm_completed_compact_line(
    *,
    timestamp: str,
    duration_ms: int,
    phase: str,
    reason: str,
    node: str | None = None,
    lines: str | None = None,
) -> str:
    """Минимальная строка ``memory.llm.completed`` без init_session/chat_id."""
    norm_event = normalize_compact_event_name("memory.llm.completed")
    parts: list[str] = [
        _fmt_kv("timestamp", timestamp),
        _fmt_kv("event", norm_event),
        _fmt_kv("duration_ms", _scalar_to_compact_value(duration_ms)),
        _fmt_kv("phase", _scalar_to_compact_value(phase)),
        _fmt_kv("reason", _scalar_to_compact_value(reason)),
    ]
    ns = str(node or "").strip()
    if ns:
        parts.append(_fmt_kv("node", _scalar_to_compact_value(ns)))
    ls = str(lines or "").strip()
    if ls:
        parts.append(_fmt_kv("lines", _scalar_to_compact_value(ls)))
    line = " ".join(p for p in parts if p)
    if "\n" in line:
        line = line.replace("\n", " ")
    return line + "\n"


def _clip_compact_token(value: str, max_len: int = 0) -> str:
    """
    Нормализация пробелов; при ``max_len > 0`` — обрезка с ``...``.

    По умолчанию (``max_len <= 0``) значение пишется в ``compact.log``
    полностью (одна строка; переносы заменяются пробелом).
    """
    s = str(value).replace("\n", " ").replace("\r", " ").strip()
    if max_len <= 0 or len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def build_memory_pag_graph_compact_line(
    *,
    timestamp: str,
    op: str,
    rev: int,
    namespace: str | None = None,
    subject: str | None = None,
    count: int | None = None,
    first: str | None = None,
    last: str | None = None,
) -> str:
    """Минимальная строка ``memory.pag_graph`` (node / edge / edge_batch)."""
    norm_event = normalize_compact_event_name("memory.pag_graph")
    parts: list[str] = [
        _fmt_kv("timestamp", timestamp),
        _fmt_kv("event", norm_event),
        _fmt_kv("op", _scalar_to_compact_value(op)),
        _fmt_kv("rev", _scalar_to_compact_value(int(max(0, rev)))),
    ]
    ns = str(namespace or "").strip()
    if ns:
        parts.append(_fmt_kv("ns", _clip_compact_token(ns)))
    subj = str(subject or "").strip()
    if subj:
        parts.append(_fmt_kv("subject", _clip_compact_token(subj)))
    if count is not None:
        parts.append(_fmt_kv("count", _scalar_to_compact_value(int(count))))
    fst = str(first or "").strip()
    if fst:
        parts.append(_fmt_kv("first", _clip_compact_token(fst)))
    lst = str(last or "").strip()
    if lst:
        parts.append(_fmt_kv("last", _clip_compact_token(lst)))
    line = " ".join(p for p in parts if p)
    if "\n" in line:
        line = line.replace("\n", " ")
    return line + "\n"


def build_memory_w14_graph_highlight_compact_line(
    *,
    timestamp: str,
    query_id: str,
    w14_command: str,
    n_node: int,
    n_edge: int,
) -> str:
    """Минимальная строка ``memory.w14_graph_highlight``."""
    norm_event = normalize_compact_event_name("memory.w14.graph_highlight")
    parts: list[str] = [
        _fmt_kv("timestamp", timestamp),
        _fmt_kv("event", norm_event),
        _fmt_kv("query_id", _clip_compact_token(str(query_id))),
        _fmt_kv("w14_command", _clip_compact_token(str(w14_command))),
        _fmt_kv("n_node", _scalar_to_compact_value(int(max(0, n_node)))),
        _fmt_kv("n_edge", _scalar_to_compact_value(int(max(0, n_edge)))),
    ]
    line = " ".join(p for p in parts if p)
    if "\n" in line:
        line = line.replace("\n", " ")
    return line + "\n"


def build_memory_link_candidates_compact_line(
    *,
    timestamp: str,
    query_id: str,
    n_cand: int,
) -> str:
    """Компактная строка wire ``link_candidates`` (без списка кандидатов)."""
    parts: list[str] = [
        _fmt_kv("timestamp", timestamp),
        _fmt_kv("event", "memory.link_candidates"),
        _fmt_kv("query_id", _clip_compact_token(str(query_id))),
        _fmt_kv("n_cand", _scalar_to_compact_value(int(max(0, n_cand)))),
    ]
    line = " ".join(p for p in parts if p)
    return line + "\n"


def build_memory_links_updated_compact_line(
    *,
    timestamp: str,
    query_id: str,
    n_applied: int,
    n_rejected: int,
) -> str:
    """Компактная строка wire ``links_updated``."""
    parts: list[str] = [
        _fmt_kv("timestamp", timestamp),
        _fmt_kv("event", "memory.links_updated"),
        _fmt_kv("query_id", _clip_compact_token(str(query_id))),
        _fmt_kv("n_applied", _scalar_to_compact_value(int(max(0, n_applied)))),
        _fmt_kv(
            "n_rejected",
            _scalar_to_compact_value(int(max(0, n_rejected))),
        ),
    ]
    line = " ".join(p for p in parts if p)
    return line + "\n"


def build_memory_summarize_c_apply_failed_compact_line(
    *,
    timestamp: str,
    reason: str,
    node: str | None = None,
    lines: str | None = None,
    command_id: str | None = None,
    stage: str | None = None,
    top_keys: str | None = None,
) -> str:
    """Ошибка записи summarize_c в PAG после успешного LLM (отладка)."""
    parts: list[str] = [
        _fmt_kv("timestamp", timestamp),
        _fmt_kv("event", "memory.summarize_c.apply_failed"),
        _fmt_kv("reason", _clip_compact_token(str(reason))),
    ]
    stg = str(stage or "").strip()
    if stg:
        parts.append(_fmt_kv("stage", _clip_compact_token(stg)))
    tk = str(top_keys or "").strip()
    if tk:
        parts.append(_fmt_kv("top_keys", _clip_compact_token(tk)))
    ns = str(node or "").strip()
    if ns:
        parts.append(_fmt_kv("node", _clip_compact_token(ns)))
    ls = str(lines or "").strip()
    if ls:
        parts.append(_fmt_kv("lines", _clip_compact_token(ls)))
    cid = str(command_id or "").strip()
    if cid:
        parts.append(_fmt_kv("command_id", _clip_compact_token(cid)))
    line = " ".join(p for p in parts if p)
    if "\n" in line:
        line = line.replace("\n", " ")
    return line + "\n"


class CompactObservabilitySink:
    """Append-only ``compact.log`` и полная строка на stderr (D2)."""

    def __init__(
        self,
        *,
        compact_file: Path,
        init_session_id: str,
        tee_stderr: bool = True,
    ) -> None:
        self._path: Path = compact_file
        self._init_session_id: str = str(init_session_id)
        self._tee_stderr: bool = tee_stderr

    @property
    def init_session_id(self) -> str:
        return self._init_session_id

    def emit(
        self,
        *,
        req: RuntimeRequestEnvelope | None,
        chat_id: str,
        event: str,
        fields: Mapping[str, str | int | bool] | None = None,
    ) -> None:
        """Пишет одну завершённую строку в файл и дублирует на stderr."""
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cid = str(chat_id or "").strip()
        if not cid and req is not None:
            cid = str(req.chat_id or "").strip()
        extra: dict[str, str | int | bool] = {}
        if fields:
            for k, v in dict(fields).items():
                if v is None:
                    continue
                if isinstance(v, str) and not v.strip():
                    continue
                extra[k] = v
        line = build_compact_line(
            timestamp=ts,
            init_session_id=self._init_session_id,
            chat_id=cid,
            event=event,
            fields=extra,
        )
        self._write_line(line)

    def emit_memory_llm_completed(
        self,
        *,
        duration_ms: int,
        phase: str,
        reason: str,
        node: str | None = None,
        lines: str | None = None,
    ) -> None:
        """timestamp, event, duration_ms, phase, reason; опц. node/lines."""
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        line = build_memory_llm_completed_compact_line(
            timestamp=ts,
            duration_ms=int(max(0, duration_ms)),
            phase=phase,
            reason=reason,
            node=node,
            lines=lines,
        )
        self._write_line(line)

    def emit_memory_pag_graph(
        self,
        *,
        op: str,
        rev: int,
        namespace: str | None = None,
        subject: str | None = None,
        count: int | None = None,
        first: str | None = None,
        last: str | None = None,
    ) -> None:
        """Минимальный ``memory.pag_graph`` (node/edge/edge_batch)."""
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        line = build_memory_pag_graph_compact_line(
            timestamp=ts,
            op=str(op).strip(),
            rev=int(max(0, rev)),
            namespace=namespace,
            subject=subject,
            count=count,
            first=first,
            last=last,
        )
        self._write_line(line)

    def emit_memory_w14_graph_highlight_compact(
        self,
        *,
        query_id: str,
        w14_command: str,
        n_node: int,
        n_edge: int,
    ) -> None:
        """Минимальный ``memory.w14_graph_highlight``."""
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        line = build_memory_w14_graph_highlight_compact_line(
            timestamp=ts,
            query_id=str(query_id or "").strip(),
            w14_command=str(w14_command or "").strip(),
            n_node=int(max(0, n_node)),
            n_edge=int(max(0, n_edge)),
        )
        self._write_line(line)

    def emit_memory_link_candidates(
        self,
        *,
        query_id: str,
        n_cand: int,
    ) -> None:
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        line = build_memory_link_candidates_compact_line(
            timestamp=ts,
            query_id=str(query_id or "").strip(),
            n_cand=int(max(0, n_cand)),
        )
        self._write_line(line)

    def emit_memory_links_updated(
        self,
        *,
        query_id: str,
        n_applied: int,
        n_rejected: int,
    ) -> None:
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        line = build_memory_links_updated_compact_line(
            timestamp=ts,
            query_id=str(query_id or "").strip(),
            n_applied=int(max(0, n_applied)),
            n_rejected=int(max(0, n_rejected)),
        )
        self._write_line(line)

    def emit_memory_summarize_c_apply_failed(
        self,
        *,
        reason: str,
        node: str | None = None,
        lines: str | None = None,
        command_id: str | None = None,
        stage: str | None = None,
        top_keys: str | None = None,
    ) -> None:
        """``memory.summarize_c.apply_failed`` — apply после LLM не удался."""
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        line = build_memory_summarize_c_apply_failed_compact_line(
            timestamp=ts,
            reason=str(reason or "").strip() or "unknown",
            node=node,
            lines=lines,
            command_id=command_id,
            stage=stage,
            top_keys=top_keys,
        )
        self._write_line(line)

    def emit_memory_result_returned_marker(
        self,
        *,
        req: RuntimeRequestEnvelope | None,
        chat_id: str,
        request_id: str,
        status: str,
    ) -> None:
        """
        Compact + stderr: ``memory.result.returned`` с канон. ``status``.
        """
        st = str(status or "").strip()
        if st not in ("complete", "partial", "blocked"):
            st = "blocked"
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cid = str(chat_id or "").strip()
        if not cid and req is not None:
            cid = str(req.chat_id or "").strip()
        rid = str(request_id or "").strip()
        fields: dict[str, str | int | bool] = {"status": st}
        if rid:
            fields["request_id"] = rid
        line = build_compact_line(
            timestamp=ts,
            init_session_id=self._init_session_id,
            chat_id=cid,
            event="memory.result.returned",
            fields=fields,
        )
        self._write_line(line)

    def emit_memory_result_complete_marker(
        self,
        *,
        req: RuntimeRequestEnvelope | None,
        chat_id: str,
        request_id: str,
    ) -> None:
        """D3: grep marker ``memory.result.returned`` + ``status=complete``."""
        self.emit_memory_result_returned_marker(
            req=req,
            chat_id=chat_id,
            request_id=request_id,
            status="complete",
        )

    def _write_line(self, line: str) -> None:
        if not line.endswith("\n"):
            line = line + "\n"
        with _write_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        if self._tee_stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
