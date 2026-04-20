"""Тесты поиска JSONL-логов агента (канонический каталог и legacy ~/.ailit)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ailit.agent_usage_cli import discover_latest_agent_log


def test_discover_prefers_newer_file_in_canonical_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """При двух каталогах выбирается файл с большим mtime."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AILIT_STATE_DIR", raising=False)
    monkeypatch.delenv("AILIT_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    from ailit.user_paths import global_logs_dir

    primary = global_logs_dir()
    primary.mkdir(parents=True)
    legacy = home / ".ailit"
    legacy.mkdir(parents=True, exist_ok=True)
    older = primary / "ailit-agent-older.log"
    newer = legacy / "ailit-agent-newer.log"
    older.write_text('{"event_type":"x"}\n', encoding="utf-8")
    newer.write_text('{"event_type":"x"}\n', encoding="utf-8")
    time.sleep(0.05)
    newer.touch()
    found = discover_latest_agent_log()
    assert found is not None
    assert found.resolve() == newer.resolve()
