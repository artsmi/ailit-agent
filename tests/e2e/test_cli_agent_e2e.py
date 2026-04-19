"""E2E: `ailit agent run` на сгенерированном приложении и pytest приложения."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli_runner import AilitCliRunner


@pytest.mark.e2e
def test_cli_agent_run_dry_run_emits_finished(
    mini_app_root: Path,
) -> None:
    """Dry-run: код 0, в stdout есть workflow.finished."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=mini_app_root,
        provider="mock",
        dry_run=True,
        max_turns=4,
    )
    assert res.returncode == 0, res.stderr
    assert "workflow.finished" in res.stdout
    raw_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    lines = [json.loads(line) for line in raw_lines]
    types = {row["event_type"] for row in lines}
    assert "workflow.loaded" in types
    assert "task.skipped_dry_run" in types


@pytest.mark.e2e
def test_cli_agent_run_mock_completes_task(
    mini_app_root: Path,
) -> None:
    """Mock-провайдер завершает задачу workflow (без dry-run)."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=mini_app_root,
        provider="mock",
        dry_run=False,
        max_turns=12,
        extra_env={"AILIT_WORK_ROOT": str(mini_app_root.resolve())},
    )
    assert res.returncode == 0, res.stderr
    raw_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    lines = [json.loads(line) for line in raw_lines]
    finished_tasks = [
        row for row in lines if row["event_type"] == "task.finished"
    ]
    assert finished_tasks, res.stdout
    assert all(
        row.get("session_state") == "finished"
        for row in finished_tasks
    ), finished_tasks


@pytest.mark.e2e
def test_generated_app_tests_pass(
    mini_app_root: Path,
) -> None:
    """Тесты внутри сгенерированного приложения проходят в subprocess."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    tests_dir = mini_app_root / "tests"
    res = runner.pytest_on(tests_dir, cwd=mini_app_root)
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
