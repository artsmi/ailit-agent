"""Persistent AgentMemory journal for Workflow 11."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from agent_core.runtime.errors import RuntimeProtocolError

JOURNAL_SCHEMA: str = "ailit_memory_journal_v1"
_REDACTED: str = "[redacted]"
_SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "authorization",
    "chain_of_thought",
    "cot",
    "env",
    "password",
    "prompt",
    "raw_prompt",
    "reasoning",
    "secret",
    "token",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_memory_journal_path() -> Path:
    """Return the canonical AgentMemory journal path."""
    explicit = os.environ.get("AILIT_MEMORY_JOURNAL_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (
        Path.home() / ".ailit" / "runtime" / "memory-journal.jsonl"
    ).resolve()


def _is_sensitive_key(key: str) -> bool:
    k = str(key or "").strip().lower()
    return any(part in k for part in _SENSITIVE_KEY_PARTS)


def redact_journal_value(value: Any) -> Any:
    """Redact raw prompts, CoT, secrets and env-like payload fields."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            out[key] = (
                _REDACTED
                if _is_sensitive_key(key)
                else redact_journal_value(v)
            )
        return out
    if isinstance(value, list):
        return [redact_journal_value(v) for v in value]
    if isinstance(value, tuple):
        return [redact_journal_value(v) for v in value]
    return value


def _str_list(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(str(v).strip() for v in values if str(v).strip())


@dataclass(frozen=True, slots=True)
class MemoryJournalRow:
    """One structured AgentMemory journal row."""

    chat_id: str
    event_name: str
    request_id: str = ""
    namespace: str = ""
    project_id: str = ""
    summary: str = ""
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)
    schema: str = JOURNAL_SCHEMA

    def validate(self) -> None:
        """Validate required journal fields."""
        if self.schema != JOURNAL_SCHEMA:
            raise RuntimeProtocolError(
                code="memory_journal_schema_mismatch",
                message=f"expected {JOURNAL_SCHEMA}, got {self.schema!r}",
            )
        if not str(self.chat_id).strip():
            raise RuntimeProtocolError(
                code="memory_journal_missing_chat_id",
                message="chat_id is required",
            )
        if not str(self.event_name).strip():
            raise RuntimeProtocolError(
                code="memory_journal_missing_event_name",
                message="event_name is required",
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a redacted JSON-ready row."""
        self.validate()
        return {
            "schema": self.schema,
            "created_at": self.created_at,
            "chat_id": self.chat_id,
            "request_id": self.request_id,
            "namespace": self.namespace,
            "project_id": self.project_id,
            "event_name": self.event_name,
            "summary": self.summary,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "payload": redact_journal_value(dict(self.payload)),
        }

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> MemoryJournalRow:
        """Parse a journal row from JSON data."""
        payload_raw = raw.get("payload")
        payload = payload_raw if isinstance(payload_raw, Mapping) else {}
        row = MemoryJournalRow(
            schema=str(raw.get("schema", "")),
            created_at=str(raw.get("created_at", "")),
            chat_id=str(raw.get("chat_id", "")),
            request_id=str(raw.get("request_id", "")),
            namespace=str(raw.get("namespace", "")),
            project_id=str(raw.get("project_id", "")),
            event_name=str(raw.get("event_name", "")),
            summary=str(raw.get("summary", "")),
            node_ids=_str_list(
                raw.get("node_ids")
                if isinstance(raw.get("node_ids"), list)
                else None,
            ),
            edge_ids=_str_list(
                raw.get("edge_ids")
                if isinstance(raw.get("edge_ids"), list)
                else None,
            ),
            payload=payload,
        )
        row.validate()
        return row


class MemoryJournalStore:
    """Append-only JSONL store for AgentMemory journal rows."""

    def __init__(self, path: Path | None = None) -> None:
        if path is not None:
            self._path = path.resolve()
        else:
            self._path = default_memory_journal_path()

    @property
    def path(self) -> Path:
        """Return the JSONL journal path."""
        return self._path

    def append(self, row: MemoryJournalRow) -> None:
        """Append one row as a single redacted JSON line."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            row.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if "\n" in line:
            raise RuntimeProtocolError(
                code="memory_journal_invalid_row",
                message="journal row must be single-line json",
            )
        fd = os.open(
            str(self._path),
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)

    def iter_rows(self) -> Iterator[MemoryJournalRow]:
        """Read all journal rows."""
        if not self._path.exists():
            return iter(())
        return self._iter_rows_from_file(self._path)

    def filter_rows(
        self,
        *,
        chat_id: str | None = None,
        namespace: str | None = None,
        project_id: str | None = None,
        request_id: str | None = None,
        event_name: str | None = None,
    ) -> Iterator[MemoryJournalRow]:
        """Filter journal rows by common AgentMemory dimensions."""
        for row in self.iter_rows():
            if chat_id is not None and row.chat_id != chat_id:
                continue
            if namespace is not None and row.namespace != namespace:
                continue
            if project_id is not None and row.project_id != project_id:
                continue
            if request_id is not None and row.request_id != request_id:
                continue
            if event_name is not None and row.event_name != event_name:
                continue
            yield row

    @staticmethod
    def _iter_rows_from_file(path: Path) -> Iterator[MemoryJournalRow]:
        with path.open("r", encoding="utf-8") as f:
            for ln, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise RuntimeProtocolError(
                        code="memory_journal_decode_error",
                        message=f"{path}:{ln}: {e}",
                    ) from e
                if not isinstance(obj, dict):
                    raise RuntimeProtocolError(
                        code="memory_journal_invalid_shape",
                        message=f"{path}:{ln}: expected json object",
                    )
                yield MemoryJournalRow.from_dict(obj)
