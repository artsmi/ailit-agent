"""Запуск workflow из chat runner."""

from __future__ import annotations

from pathlib import Path

import yaml

from ailit.chat_workflow_runner import resolve_workflow_path, run_workflow_capture_jsonl


def test_resolve_by_yaml_relative_without_project_yaml(tmp_path: Path) -> None:
    """Без project.yaml — путь *.yaml относительно корня."""
    wf = tmp_path / "w.yaml"
    wf.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "x",
                "stages": [{"id": "s", "tasks": [{"id": "t", "system_prompt": "a", "user_text": "b"}]}],
            },
        ),
        encoding="utf-8",
    )
    p = resolve_workflow_path(tmp_path, "w.yaml")
    assert p == wf.resolve()


def test_resolve_workflow_id_via_project_yaml(tmp_path: Path) -> None:
    """С project.yaml — id из реестра."""
    wf = tmp_path / "w.yaml"
    wf.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "x",
                "stages": [{"id": "s", "tasks": [{"id": "t", "system_prompt": "a", "user_text": "b"}]}],
            },
        ),
        encoding="utf-8",
    )
    (tmp_path / "project.yaml").write_text(
        yaml.safe_dump({"project_id": "p", "workflows": {"main": {"path": "w.yaml"}}}),
        encoding="utf-8",
    )
    assert resolve_workflow_path(tmp_path, "main") == wf.resolve()


def test_run_workflow_dry_run_mock(tmp_path: Path) -> None:
    """Dry-run + mock даёт JSONL."""
    wf = tmp_path / "w.yaml"
    wf.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "z",
                "stages": [{"id": "s", "tasks": [{"id": "t", "system_prompt": "x", "user_text": "y"}]}],
            },
        ),
        encoding="utf-8",
    )
    out = run_workflow_capture_jsonl(
        repo_root=tmp_path,
        project_root=tmp_path,
        workflow_ref="w.yaml",
        provider="mock",
        model="mock",
        max_turns=4,
        dry_run=True,
    )
    assert "workflow.loaded" in out
    assert "task.skipped_dry_run" in out
