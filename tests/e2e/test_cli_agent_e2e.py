"""E2E: `ailit agent run` на сгенерированном приложении и pytest приложения."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from ailit.demo_workspace import materialize_demo_app
from cli_runner import AilitCliRunner


@pytest.mark.e2e
def test_cli_agent_run_dry_run_without_repo_test_local(
    mini_app_root: Path,
    e2e_workspace: Path,
) -> None:
    """С ``--no-dev-repo-config`` и отдельным ``AILIT_CONFIG_DIR`` достаточно merge."""
    cfg_dir = e2e_workspace / "global_ailit"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "live:\n  run: false\n",
        encoding="utf-8",
    )
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=mini_app_root,
        provider="mock",
        dry_run=True,
        max_turns=4,
        no_dev_repo_config=True,
        extra_env={"AILIT_CONFIG_DIR": str(cfg_dir)},
    )
    assert res.returncode == 0, res.stderr
    assert "workflow.finished" in res.stdout


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


@pytest.mark.e2e
def test_k2_external_temp_materialize_agent_mock_then_pytest() -> None:
    """K.2: проект вне клона, глобальный merge, agent (mock), pytest без ключей."""
    repo = Path(__file__).resolve().parents[2]
    repo_resolved = repo.resolve()
    base = Path(tempfile.gettempdir()) / f"ailit_k2_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        app = base / "materialized_app"
        materialize_demo_app(app, overwrite=True)
        assert repo_resolved not in app.resolve().parents
        assert app.resolve() != repo_resolved

        fake_home = base / "home"
        fake_home.mkdir(parents=True, exist_ok=True)
        cfg_dir = base / "ailit_global"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.yaml").write_text(
            "live:\n  run: false\n",
            encoding="utf-8",
        )
        runner = AilitCliRunner(repo)
        env = {
            "HOME": str(fake_home.resolve()),
            "AILIT_CONFIG_DIR": str(cfg_dir.resolve()),
            "AILIT_WORK_ROOT": str(app.resolve()),
        }
        res_agent = runner.agent_run(
            workflow_ref="smoke",
            project_root=app,
            provider="mock",
            dry_run=False,
            max_turns=12,
            no_dev_repo_config=True,
            extra_env=env,
        )
        assert res_agent.returncode == 0, res_agent.stderr
        assert "workflow.finished" in res_agent.stdout
        raw = [ln for ln in res_agent.stdout.splitlines() if ln.strip()]
        lines = [json.loads(ln) for ln in raw]
        finished = [r for r in lines if r["event_type"] == "task.finished"]
        assert finished
        assert all(r.get("session_state") == "finished" for r in finished)

        res_py = runner.pytest_on(app / "tests", cwd=app, extra_env=env)
        assert res_py.returncode == 0, f"{res_py.stdout}\n{res_py.stderr}"
    finally:
        shutil.rmtree(base, ignore_errors=True)
