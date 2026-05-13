"""CLI-задача для `ailit agent run`: нормализация в TaskSpec и артефакт run."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TaskSource(str, Enum):
    """Откуда взята текстовая задача."""

    CLI_TEXT = "cli_text"
    FILE = "file"
    STDIN = "stdin"


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Нормализованная пользовательская задача (один канал на прогон)."""

    source: TaskSource
    body: str
    """Путь к файлу (только для ``TaskSource.FILE``)."""
    origin_path: str | None = None


class TaskSpecResolver:
    """Собрать ``TaskSpec`` из флагов CLI и stdin."""

    _MAX_STDIN_BYTES: int = 4 * 1024 * 1024

    @classmethod
    def resolve(cls, ns: argparse.Namespace) -> TaskSpec | None:
        """Разрешить задачу: ``--task`` / ``--task-file`` / stdin (если не TTY)."""
        task = getattr(ns, "task", None)
        task_file = getattr(ns, "task_file", None)
        if task is not None and str(task).strip():
            return TaskSpec(
                source=TaskSource.CLI_TEXT,
                body=str(task).strip(),
                origin_path=None,
            )
        if task_file is not None and str(task_file).strip():
            path = Path(str(task_file)).expanduser().resolve()
            if not path.is_file():
                msg = f"--task-file: файл не найден или не файл: {path}"
                raise ValueError(msg)
            text = path.read_text(encoding="utf-8")
            return TaskSpec(
                source=TaskSource.FILE,
                body=text,
                origin_path=str(path),
            )
        if not sys.stdin.isatty():
            data = sys.stdin.buffer.read(cls._MAX_STDIN_BYTES + 1)
            if len(data) > cls._MAX_STDIN_BYTES:
                msg = (
                    f"Задача из stdin превышает {cls._MAX_STDIN_BYTES} байт. "
                    "Используйте --task-file.\n"
                )
                raise ValueError(msg)
            decoded = data.decode("utf-8", errors="replace").strip()
            if decoded:
                return TaskSpec(
                    source=TaskSource.STDIN,
                    body=decoded,
                    origin_path=None,
                )
        return None


@dataclass(frozen=True, slots=True)
class RunTaskArtifactPaths:
    """Каталог прогона и путь к task.md."""

    run_id: str
    run_dir: Path
    task_file: Path

    @property
    def task_rel_posix(self) -> str:
        """Путь относительно корня проекта (POSIX для JSONL)."""
        name = self.task_file.name
        return f".ailit/run/{self.run_id}/{name}"


class RunTaskArtifactWriter:
    """Материализация ``task.md`` под ``.ailit/run/<run_id>/``."""

    @staticmethod
    def allocate_run_id() -> str:
        """Короткий уникальный идентификатор прогона."""
        return uuid.uuid4().hex[:16]

    @classmethod
    def write(
        cls,
        *,
        project_root: Path,
        run_id: str,
        spec: TaskSpec,
    ) -> RunTaskArtifactPaths:
        """Создать каталог и записать тело задачи."""
        run_dir = (project_root.resolve() / ".ailit" / "run" / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        task_path = run_dir / "task.md"
        header_lines = [
            "<!-- ailit: materialized CLI task -->",
            f"source: {spec.source.value}",
        ]
        if spec.origin_path:
            header_lines.append(f"origin_path: {spec.origin_path}")
        header_lines.append("")
        task_path.write_text(
            "\n".join(header_lines) + spec.body.lstrip("\ufeff"),
            encoding="utf-8",
        )
        return RunTaskArtifactPaths(run_id=run_id, run_dir=run_dir, task_file=task_path)
