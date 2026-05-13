"""L.2: инструмент send_teammate_message."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ailit_cli.teams_tools import builtin_send_teammate_message


def test_send_teammate_message_writes_inbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Вызов handler с env пишет в mailbox проекта."""
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("AILIT_WORK_ROOT", str(root))
    monkeypatch.setenv("AILIT_TEAM_PROJECT_ROOT", str(root))
    monkeypatch.setenv("AILIT_CHAT_AGENT_ID", "alice")
    out = json.loads(
        builtin_send_teammate_message(
            {"to_agent": "bob", "text": "hello team", "team_id": "t1"},
        ),
    )
    assert out["ok"] is True
    inbox = root / ".ailit" / "teams" / "t1" / "inboxes" / "bob.json"
    assert inbox.is_file()
    data = json.loads(inbox.read_text(encoding="utf-8"))
    assert data["messages"][0]["from"] == "alice"
    assert data["messages"][0]["text"] == "hello team"
