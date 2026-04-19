"""Роль teammate добавляет system addendum."""

from __future__ import annotations

from pathlib import Path

import yaml

from project_layer.bootstrap import compute_chat_tuning
from project_layer.loader import load_project


def test_teammate_role_adds_mailbox_addendum(tmp_path: Path) -> None:
    (tmp_path / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "project_id": "tproj",
                "runtime": "ailit",
                "agents": {
                    "bob": {"role": "teammate", "system_prompt": "x"},
                },
            },
        ),
        encoding="utf-8",
    )
    loaded = load_project(tmp_path / "project.yaml")
    tuning = compute_chat_tuning(loaded, "bob", snapshot=None)
    blob = "\n".join(tuning.extra_system_messages)
    assert "send_teammate_message" in blob
    assert "Teammate" in blob or "teammate" in blob.lower()
