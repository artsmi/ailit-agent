"""L.3: презентер панели команды."""

from __future__ import annotations

from pathlib import Path

from ailit.teams import TeamSession, TeamRootSelector
from ailit.teams_panel_presenter import TeamMailboxPanelPresenter


def test_panel_markdown_lists_messages(tmp_path: Path) -> None:
    """Human-readable digest содержит текст сообщения."""
    team = TeamSession(TeamRootSelector.for_project(tmp_path), "g1")
    team.send("a", "b", "ping-panel")
    md = TeamMailboxPanelPresenter(project_root=tmp_path, team_id="g1").markdown_digest()
    assert "ping-panel" in md
    assert "`b`" in md
