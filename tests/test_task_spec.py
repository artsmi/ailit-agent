"""Задача CLI (K.1): TaskSpec и артефакт прогона."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ailit.task_spec import RunTaskArtifactWriter, TaskSource, TaskSpecResolver
from workflow_engine.user_task_merge import merge_cli_task_into_first_user_message


def test_merge_cli_task_into_first_user_message() -> None:
    """CLI-текст идёт перед шаблоном workflow."""
    out = merge_cli_task_into_first_user_message(
        workflow_user_text="YAML user",
        cli_body="Do X",
    )
    assert out.startswith("Do X")
    assert "YAML user" in out


def test_task_spec_resolver_cli_text() -> None:
    """Флаг ``--task``."""
    ns = argparse.Namespace(task="  hello  ", task_file=None)
    spec = TaskSpecResolver.resolve(ns)
    assert spec is not None
    assert spec.source is TaskSource.CLI_TEXT
    assert spec.body == "hello"


def test_task_spec_resolver_task_file(tmp_path: Path) -> None:
    """Флаг ``--task-file``."""
    p = tmp_path / "t.md"
    p.write_text("from file\n", encoding="utf-8")
    ns = argparse.Namespace(task=None, task_file=str(p))
    spec = TaskSpecResolver.resolve(ns)
    assert spec is not None
    assert spec.source is TaskSource.FILE
    assert spec.body.strip() == "from file"
    assert spec.origin_path == str(p.resolve())


def test_task_spec_resolver_task_file_missing(tmp_path: Path) -> None:
    """Отсутствующий файл — понятная ошибка."""
    ns = argparse.Namespace(task=None, task_file=str(tmp_path / "nope.txt"))
    with pytest.raises(ValueError, match="--task-file"):
        TaskSpecResolver.resolve(ns)


def test_run_task_artifact_writer(tmp_path: Path) -> None:
    """Запись ``.ailit/run/<id>/task.md``."""
    spec = TaskSpecResolver.resolve(
        argparse.Namespace(task="body", task_file=None),
    )
    assert spec is not None
    rid = RunTaskArtifactWriter.allocate_run_id()
    paths = RunTaskArtifactWriter.write(project_root=tmp_path, run_id=rid, spec=spec)
    assert paths.task_file.is_file()
    text = paths.task_file.read_text(encoding="utf-8")
    assert "source: cli_text" in text
    assert "body" in text
