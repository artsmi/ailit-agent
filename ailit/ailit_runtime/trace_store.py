"""Durable trace store: append-only JSONL (G8.1.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from ailit_runtime.errors import RuntimeProtocolError


@dataclass(frozen=True, slots=True)
class TraceRow:
    """Одна строка trace store (JSON object)."""

    data: Mapping[str, Any]

    def to_json_line(self) -> str:
        return json.dumps(
            dict(self.data),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class JsonlTraceStore:
    """Append-only JSONL журнал для runtime trace."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Файл JSONL."""
        return self._path

    def append(self, row: TraceRow) -> None:
        """Добавить строку в конец."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = row.to_json_line()
        if "\n" in line:
            raise RuntimeProtocolError(
                code="invalid_trace_row",
                message="trace row must be single-line json",
            )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")

    def append_many(self, rows: Iterable[TraceRow]) -> int:
        """Добавить несколько строк; возвращает число записанных."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with self._path.open("a", encoding="utf-8") as f:
            for row in rows:
                line = row.to_json_line()
                if "\n" in line:
                    raise RuntimeProtocolError(
                        code="invalid_trace_row",
                        message="trace row must be single-line json",
                    )
                f.write(line)
                f.write("\n")
                n += 1
        return n

    def iter_rows(self) -> Iterator[TraceRow]:
        """Читать весь журнал построчно."""
        if not self._path.exists():
            return iter(())
        return self._iter_rows_from_file(self._path)

    def filter_rows(
        self,
        *,
        chat_id: str | None = None,
        broker_id: str | None = None,
        agent_instance_id: str | None = None,
        namespace: str | None = None,
        goal_id: str | None = None,
        trace_id: str | None = None,
    ) -> Iterator[TraceRow]:
        """Фильтровать строки по ключам (если ключа нет — не матчится)."""
        for row in self.iter_rows():
            d = row.data
            if chat_id is not None and str(d.get("chat_id", "")) != chat_id:
                continue
            if (
                broker_id is not None
                and str(d.get("broker_id", "")) != broker_id
            ):
                continue
            if (
                namespace is not None
                and str(d.get("namespace", "")) != namespace
            ):
                continue
            if goal_id is not None and str(d.get("goal_id", "")) != goal_id:
                continue
            if trace_id is not None and str(d.get("trace_id", "")) != trace_id:
                continue
            if agent_instance_id is not None:
                fa = str(d.get("from_agent", ""))
                ta = str(d.get("to_agent", ""))
                if agent_instance_id not in fa and agent_instance_id not in ta:
                    continue
            yield row

    @staticmethod
    def _iter_rows_from_file(path: Path) -> Iterator[TraceRow]:
        with path.open("r", encoding="utf-8") as f:
            for ln, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise RuntimeProtocolError(
                        code="trace_decode_error",
                        message=f"{path}:{ln}: {e}",
                    ) from e
                if not isinstance(obj, dict):
                    raise RuntimeProtocolError(
                        code="trace_invalid_shape",
                        message=f"{path}:{ln}: expected json object",
                    )
                yield TraceRow(data=obj)
