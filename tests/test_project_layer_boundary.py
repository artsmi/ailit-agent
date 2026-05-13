"""Границы project layer vs session runtime."""

from __future__ import annotations

from pathlib import Path


def test_project_layer_sources_avoid_session_loop() -> None:
    """project_layer не импортирует agent_core.session.* в исходниках."""
    root = Path(__file__).resolve().parents[1] / "ailit" / "project_layer"
    for path in sorted(root.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "agent_work.session" not in text, path.name
