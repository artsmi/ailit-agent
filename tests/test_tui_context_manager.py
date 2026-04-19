"""Тесты мульти-контекста TUI (этап Q.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ailit.tui_context_manager import (
    TuiContextManager,
    UsageTotals,
    validate_context_name,
)


def test_validate_context_name_too_long() -> None:
    """Имя длиннее 20 символов отклоняется."""
    err = validate_context_name("x" * 21)
    assert err is not None


def test_validate_context_name_whitespace() -> None:
    """Пробелы в имени запрещены."""
    err = validate_context_name("a b")
    assert err is not None


def test_new_switch_rename(tmp_path: Path) -> None:
    """Создание, переключение и переименование контекста."""
    mgr = TuiContextManager(default_root=tmp_path, default_name="default")
    assert mgr.active_name() == "default"
    err = mgr.new_context("work", project_root=tmp_path)
    assert err is None
    assert mgr.switch("work") is None
    assert mgr.active_name() == "work"
    assert mgr.rename_active("job") is None
    assert mgr.active_name() == "job"
    assert "job" in mgr.list_sorted_names()


def test_switch_unknown() -> None:
    """Переключение на несуществующий контекст даёт ошибку."""
    mgr = TuiContextManager(default_root=Path("/tmp"), default_name="default")
    err = mgr.switch("nope")
    assert err is not None


def test_duplicate_context() -> None:
    """Дубликат имени при new."""
    mgr = TuiContextManager(default_root=Path("/tmp"), default_name="default")
    assert mgr.new_context("x", project_root=Path("/tmp")) is None
    err = mgr.new_context("x", project_root=Path("/tmp"))
    assert err is not None


def test_draft_roundtrip() -> None:
    """Черновики сохраняются по имени контекста."""
    mgr = TuiContextManager(default_root=Path("/tmp"), default_name="a")
    mgr.new_context("b", project_root=Path("/tmp"))
    mgr.save_draft("a", "hello")
    assert mgr.peek_draft("a") == "hello"
    mgr.switch("b")
    assert mgr.peek_draft("a") == "hello"


def test_usage_totals_add() -> None:
    """Накопление usage как в JSONL."""
    u = UsageTotals()
    u.add_from_usage_dict({"input_tokens": 3, "output_tokens": 2})
    u.add_from_usage_dict({"input_tokens": 1, "cache_read_tokens": 5})
    d = u.as_dict()
    assert d["input_tokens"] == 4
    assert d["output_tokens"] == 2
    assert d["cache_read_tokens"] == 5


def test_activate_next_cycles(tmp_path: Path) -> None:
    """Цикл по именам контекстов."""
    mgr = TuiContextManager(default_root=tmp_path, default_name="a")
    mgr.new_context("b", project_root=tmp_path)
    mgr.new_context("c", project_root=tmp_path)
    mgr.switch("a")
    mgr.activate_next()
    assert mgr.active_name() == "b"
    mgr.activate_next()
    assert mgr.active_name() == "c"
    mgr.activate_next()
    assert mgr.active_name() == "a"


@pytest.mark.parametrize("delta", [-1, 1])
def test_activate_prev_next(tmp_path: Path, delta: int) -> None:
    """Предыдущий и следующий контекст."""
    mgr = TuiContextManager(default_root=tmp_path, default_name="m")
    mgr.new_context("n", project_root=tmp_path)
    mgr.switch("m")
    if delta > 0:
        mgr.activate_next()
        assert mgr.active_name() == "n"
    else:
        mgr.switch("n")
        mgr.activate_prev()
        assert mgr.active_name() == "m"
