"""Compat adapter: legacy vs ailit runtime."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import yaml

from ailit.compat_adapter import read_status, run_compat_workflow


def _write_minimal_workflow(tmp: Path) -> None:
    wf = tmp / "w.yaml"
    wf.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "t",
                "stages": [{"id": "s", "tasks": [{"id": "a", "system_prompt": "x", "user_text": "y"}]}],
            },
        ),
        encoding="utf-8",
    )


def test_legacy_emits_skip_and_status(tmp_path: Path) -> None:
    """runtime=legacy не гоняет engine."""
    _write_minimal_workflow(tmp_path)
    proj = tmp_path / "project.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "project_id": "p",
                "runtime": "legacy",
                "workflows": {"minimal": {"path": "w.yaml"}},
            },
        ),
        encoding="utf-8",
    )
    buf = StringIO()
    res = run_compat_workflow(
        project_root=tmp_path,
        workflow_ref="minimal",
        provider="mock",
        model="mock",
        max_turns=4,
        dry_run=True,
        sink=buf,
        repo_root=tmp_path,
    )
    assert res.legacy_skipped is True
    row = json.loads(buf.getvalue().strip().splitlines()[0])
    assert row["event_type"] == "adapter.legacy_skip"
    text = read_status(tmp_path)
    assert text and "legacy" in text.lower()


def test_ailit_runs_engine_dry_run(tmp_path: Path) -> None:
    """runtime=ailit исполняет dry-run."""
    _write_minimal_workflow(tmp_path)
    proj = tmp_path / "project.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "project_id": "p",
                "runtime": "ailit",
                "workflows": {"minimal": {"path": "w.yaml"}},
                "context": {"knowledge_refresh": {"mode": "stub"}},
            },
        ),
        encoding="utf-8",
    )
    buf = StringIO()
    res = run_compat_workflow(
        project_root=tmp_path,
        workflow_ref="minimal",
        provider="mock",
        model="mock",
        max_turns=4,
        dry_run=True,
        sink=buf,
        repo_root=tmp_path,
    )
    assert res.legacy_skipped is False
    lines = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
    types = {x["event_type"] for x in lines}
    assert "workflow.loaded" in types
    assert read_status(tmp_path)
