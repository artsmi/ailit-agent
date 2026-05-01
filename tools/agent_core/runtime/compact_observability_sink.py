"""Единый писатель CLI ``compact.log`` + tee на stderr (D2, D4, UC-06)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping

from agent_core.runtime.agent_memory_chat_log import _write_lock
from agent_core.runtime.models import RuntimeRequestEnvelope

_BROKER_W14_HIGHLIGHT: Final[str] = "memory.w14.graph_highlight"
_CANON_W14_HIGHLIGHT: Final[str] = "memory.w14_graph_highlight"


def normalize_compact_event_name(raw_event: str) -> str:
    """D4: broker dotted W14 highlight → canonical underscores."""
    s = str(raw_event or "").strip()
    if s == _BROKER_W14_HIGHLIGHT:
        return _CANON_W14_HIGHLIGHT
    return s


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

    def emit_memory_result_complete_marker(
        self,
        *,
        req: RuntimeRequestEnvelope | None,
        chat_id: str,
        request_id: str,
    ) -> None:
        """D3: grep marker ``memory.result.returned`` + ``status=complete``."""
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cid = str(chat_id or "").strip()
        if not cid and req is not None:
            cid = str(req.chat_id or "").strip()
        rid = str(request_id or "").strip()
        fields: dict[str, str | int | bool] = {
            "status": "complete",
        }
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
