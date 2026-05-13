"""Тесты CLI: `ailit agent` требует подкоманду (run, usage, …)."""

from __future__ import annotations

import pytest

import ailit_cli.cli as cli


def test_agent_without_subcommand_returns_error() -> None:
    """`ailit agent` без подкоманды завершается с кодом 2 (argparse)."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["agent"])
    assert exc.value.code == 2
