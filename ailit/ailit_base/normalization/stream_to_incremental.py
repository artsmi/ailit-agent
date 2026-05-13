"""Сырые `StreamTextDelta` → инкрементальные дельты для trace/UI (+=).

У провайдера (Kimi, …) можно задать метод
`def build_stream_incremental(self) -> IStreamToIncremental` — иначе
`MergingToIncremental` (внутри `merge_stream_text` как на desktop).
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ailit_base.normalization.stream_text_merge import merge_stream_text

TEXT_MODE_INCREMENTAL = "incremental"
TEXT_MODE_SNAPSHOT = "snapshot"


@dataclass
class EmittedDelta:
    """Событие `topic.publish`: `text` и `text_mode` (часто incremental)."""

    text: str
    text_mode: str = TEXT_MODE_INCREMENTAL


@runtime_checkable
class IStreamToIncremental(Protocol):
    def reset(self) -> None:
        """Новый ход / новый request."""
        ...

    def consume(
        self, channel: str, raw_chunk: str
    ) -> EmittedDelta | None:
        """Вернуть пакет с дельтой (или None)."""
        ...


@dataclass
class MergingToIncremental:
    """Дельта: merge полной строки, наружу — суффикс `new[len(prev):]`."""

    _acc: dict[str, str] = field(default_factory=dict)

    def total(self, channel: str) -> str:
        """Накопленная полная строка (NFC) — в основном для тестов/diag."""
        ch: str = channel if channel in ("content", "reasoning") else "content"
        return self._acc.get(ch, "")

    def reset(self) -> None:
        self._acc.clear()

    def consume(self, channel: str, raw_chunk: str) -> EmittedDelta | None:
        ch: str = channel if channel in ("content", "reasoning") else "content"
        prev = self._acc.get(ch, "")
        new = merge_stream_text(prev, raw_chunk)
        if new == prev:
            return None
        if new.startswith(prev):
            delta = new[len(prev):]
            self._acc[ch] = new
            if not delta:
                return None
            return EmittedDelta(text=delta, text_mode=TEXT_MODE_INCREMENTAL)
        self._acc[ch] = new
        return EmittedDelta(text=new, text_mode=TEXT_MODE_SNAPSHOT)


def stream_incremental_for_provider(
    provider: Any,
) -> IStreamToIncremental:
    """`build_stream_incremental()` на провайдере или MergingToIncremental."""
    f = getattr(provider, "build_stream_incremental", None)
    if callable(f):
        out: object = f()
        if isinstance(out, IStreamToIncremental):
            return typing.cast(IStreamToIncremental, out)
    return MergingToIncremental()
