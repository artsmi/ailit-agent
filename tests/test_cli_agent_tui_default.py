"""Тесты CLI: `ailit agent` запускает интерактив (DP-2.1)."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

import ailit.cli as cli


def test_agent_without_subcommand_calls_agent_tui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ailit agent` без подкоманды выбирает обработчик интерактива."""
    called = Mock(return_value=0)
    monkeypatch.setattr(cli, "_cmd_agent_tui", called)
    rc = cli.main(["agent"])
    assert rc == 0
    assert called.call_count == 1
