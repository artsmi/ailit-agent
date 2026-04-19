"""E2E: demo_workspace + CLI agent run в tmp_path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ailit.demo_workspace import materialize_demo_app
from ailit.paths import repo_root
from cli_runner import AilitCliRunner


@pytest.mark.e2e
def test_demo_workspace_materializes_and_cli_finishes(
    tmp_path: Path,
) -> None:
    """Материализация, структура файлов, ailit agent run с mock."""
    app = tmp_path / "demo_app"
    materialize_demo_app(app, overwrite=True)
    assert (app / "project.yaml").is_file()
    assert (app / "workflows" / "smoke.yaml").is_file()
    assert (app / "README.md").is_file()
    assert (app / "context" / "README.md").is_file()
    assert (app / "INFO.txt").is_file()
    assert (app / "tests" / "test_bootstrap.py").is_file()

    runner = AilitCliRunner(repo_root())
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=app,
        provider="mock",
        dry_run=True,
        max_turns=4,
    )
    assert res.returncode == 0, res.stderr
    assert "workflow.finished" in res.stdout

    res2 = runner.agent_run(
        workflow_ref="smoke",
        project_root=app,
        provider="mock",
        dry_run=False,
        max_turns=12,
        extra_env={"AILIT_WORK_ROOT": str(app.resolve())},
    )
    assert res2.returncode == 0, res2.stderr
    raw_lines = [ln for ln in res2.stdout.splitlines() if ln.strip()]
    lines = [json.loads(line) for line in raw_lines]
    finished = [r for r in lines if r["event_type"] == "task.finished"]
    assert finished
    assert all(r.get("session_state") == "finished" for r in finished)
