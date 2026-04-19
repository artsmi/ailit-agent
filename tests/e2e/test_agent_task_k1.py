"""K.1: ``--task``, ``--task-file``, stdin → артефакт и ``run.started``."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli_runner import AilitCliRunner


@pytest.mark.e2e
def test_agent_run_task_flag_writes_artifact_and_emits_run_started(
    mini_app_root: Path,
) -> None:
    """``--task`` материализует ``.ailit/run/*/task.md`` и JSONL ``run.started``."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=mini_app_root,
        provider="mock",
        dry_run=True,
        max_turns=4,
        task="Пользовательская задача из CLI",
    )
    assert res.returncode == 0, res.stderr
    assert "run.started" in res.stdout
    run_root = mini_app_root / ".ailit" / "run"
    assert run_root.is_dir()
    hits = [
        p.read_text(encoding="utf-8")
        for p in run_root.glob("*/task.md")
        if p.is_file()
    ]
    assert any("Пользовательская задача из CLI" in h for h in hits)


@pytest.mark.e2e
def test_agent_run_task_file_equivalent(tmp_path: Path, mini_app_root: Path) -> None:
    """``--task-file`` даёт тот же канон артефакта."""
    tf = tmp_path / "in.txt"
    tf.write_text("from file body\n", encoding="utf-8")
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=mini_app_root,
        provider="mock",
        dry_run=True,
        max_turns=4,
        task_file=str(tf),
    )
    assert res.returncode == 0, res.stderr
    assert "run.started" in res.stdout
    texts = [p.read_text(encoding="utf-8") for p in (mini_app_root / ".ailit" / "run").glob("*/task.md")]
    assert any("source: file" in t and "from file body" in t for t in texts)


@pytest.mark.e2e
def test_agent_run_stdin_task(mini_app_root: Path) -> None:
    """Stdin (без TTY) читается как задача."""
    repo = Path(__file__).resolve().parents[2]
    runner = AilitCliRunner(repo)
    res = runner.agent_run(
        workflow_ref="smoke",
        project_root=mini_app_root,
        provider="mock",
        dry_run=True,
        max_turns=4,
        input_text="stdin задача\n",
    )
    assert res.returncode == 0, res.stderr
    assert "run.started" in res.stdout
    texts = [p.read_text(encoding="utf-8") for p in (mini_app_root / ".ailit" / "run").glob("*/task.md")]
    assert any("source: stdin" in t and "stdin задача" in t for t in texts)
