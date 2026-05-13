"""Паритет merge + дельты для рантайма (agent_core → trace)."""

from __future__ import annotations

import unicodedata

from ailit_base.normalization.stream_text_merge import merge_stream_text
from ailit_base.normalization.stream_to_incremental import (
    MergingToIncremental,
    TEXT_MODE_INCREMENTAL,
)


def test_merge_cumulative() -> None:
    assert merge_stream_text("", "hello") == "hello"
    assert merge_stream_text("hel", "hello") == "hello"
    assert merge_stream_text("hello", "hello") == "hello"


def test_merge_append() -> None:
    assert merge_stream_text("a", "b") == "ab"
    assert merge_stream_text("hello", " world") == "hello world"


def test_incremental_only_suffix_on_cumulative_chunk() -> None:
    inc: MergingToIncremental = MergingToIncremental()
    d0 = inc.consume("content", "hel")
    assert d0 is not None
    assert d0.text == "hel" and d0.text_mode == TEXT_MODE_INCREMENTAL
    d1 = inc.consume("content", "hello")
    assert d1 is not None
    assert d1.text == "lo"
    d2 = inc.consume("content", "hello")
    assert d2 is None
    d3 = inc.consume("content", "hello world")
    assert d3 is not None
    assert d3.text == " world"
    assert inc.total("content") == "hello world"


def test_nfc_precomposed_stored() -> None:
    t: str = unicodedata.normalize("NFC", "caf\u00e9")
    assert merge_stream_text("", t) == t
