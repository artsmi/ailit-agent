from __future__ import annotations

from ailit_base.shell_output_preview import (
    DetachedViewHeuristic,
    LineSplitter,
    LineTailSelector,
    MergedStreamsPreview,
    TailPreviewConfig,
)


def test_line_splitter_empty() -> None:
    assert LineSplitter.split_lines("") == []


def test_line_splitter_preserves_internal_blank_lines() -> None:
    assert LineSplitter.split_lines("a\n\nb\n") == ["a", "", "b"]


def test_line_tail_selector_last_lines() -> None:
    text = "l1\nl2\nl3\nl4\n"
    assert LineTailSelector.last_lines(text, 3) == "l2\nl3\nl4"


def test_line_tail_selector_max_lines_zero() -> None:
    assert LineTailSelector.last_lines("a\nb", 0) == ""


def test_detached_view_heuristic_duration() -> None:
    cfg = TailPreviewConfig(detached_min_duration_ms=100)
    assert DetachedViewHeuristic.suggest_detached_view(
        elapsed_ms=150,
        byte_len=0,
        line_count=0,
        cfg=cfg,
    )


def test_detached_view_heuristic_bytes() -> None:
    cfg = TailPreviewConfig(detached_min_bytes=10)
    assert DetachedViewHeuristic.suggest_detached_view(
        elapsed_ms=0,
        byte_len=20,
        line_count=0,
        cfg=cfg,
    )


def test_detached_view_heuristic_lines() -> None:
    cfg = TailPreviewConfig(detached_min_total_lines=3)
    assert DetachedViewHeuristic.suggest_detached_view(
        elapsed_ms=0,
        byte_len=0,
        line_count=5,
        cfg=cfg,
    )


def test_merged_streams_preview_stdout_only() -> None:
    assert MergedStreamsPreview.merge("ok\n", "") == "ok"


def test_merged_streams_preview_both() -> None:
    m = MergedStreamsPreview.merge("out", "err")
    assert "out" in m and "stderr" in m and "err" in m
