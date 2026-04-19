"""Тесты форматирования usage для TUI (этап Q.2)."""

from __future__ import annotations

from pathlib import Path

from ailit.tui_context_manager import TuiContextManager
from ailit.tui_context_stats import (
    CtxUsageMarkdownTable,
    TuiSubtitleUsageFormatter,
)


def test_ctx_stats_markdown_table(tmp_path: Path) -> None:
    """Таблица ``/ctx stats`` содержит заголовок и строки по контекстам."""
    mgr = TuiContextManager(default_root=tmp_path, default_name="a")
    mgr.new_context("b", project_root=tmp_path)
    mgr.switch("b")
    mgr.record_turn_usage({"input_tokens": 10, "output_tokens": 2})
    lines = CtxUsageMarkdownTable().render_lines(mgr)
    joined = "\n".join(lines)
    assert "| context |" in joined
    assert "`b` *" in joined
    assert "| `a`" in joined


def test_subtitle_idle_and_after_turn(tmp_path: Path) -> None:
    """Подзаголовок: Σ в idle и last+Σ после хода."""
    fmt = TuiSubtitleUsageFormatter()
    cum = {
        "input_tokens": 5,
        "output_tokens": 1,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    idle = fmt.format_idle(
        context_name="work",
        cumulative=cum,
        provider="mock",
        model="mock",
        max_turns=8,
    )
    assert "work" in idle
    assert "Σ in=5" in idle
    after = fmt.format_after_turn(
        context_name="work",
        last_turn={"input_tokens": 3, "output_tokens": 1},
        cumulative=cum,
        provider="mock",
        model="mock",
        max_turns=8,
    )
    assert "last in=3" in after
