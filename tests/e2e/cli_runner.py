"""Запуск текущего `ailit` из исходников через subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AilitCliResult:
    """Результат вызова CLI."""

    returncode: int
    stdout: str
    stderr: str


class AilitCliRunner:
    """Subprocess с PYTHONPATH=ailit и корнем репозитория."""

    def __init__(self, repo_root: Path) -> None:
        """Запомнить корень репозитория ailit-agent."""
        self._repo = repo_root.resolve()
        self._ailit = self._repo / "ailit"

    def _env(self, *, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Окружение: пакеты из ailit/ (как editable для тестов)."""
        base = os.environ.copy()
        prev = base.get("PYTHONPATH", "")
        sep = os.pathsep
        ailit_s = str(self._ailit)
        base["PYTHONPATH"] = (
            f"{ailit_s}{sep}{prev}" if prev else ailit_s
        )
        if extra:
            base.update(extra)
        return base

    def _python(self) -> str:
        """Путь к интерпретатору Python (предпочитаем .venv)."""
        py = Path(sys.executable).resolve()
        repo_py = (self._repo / ".venv" / "bin" / "python3").resolve()
        if repo_py.exists():
            return str(repo_py)
        return str(py)

    def agent_run(
        self,
        *,
        workflow_ref: str,
        project_root: Path,
        provider: str = "mock",
        dry_run: bool = False,
        max_turns: int = 10_000,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
        no_dev_repo_config: bool = False,
        task: str | None = None,
        task_file: str | None = None,
        input_text: str | None = None,
    ) -> AilitCliResult:
        """Выполнить `python -m ailit_cli.cli agent run …`."""
        cmd: list[str] = [
            self._python(),
            "-m",
            "ailit_cli.cli",
            "agent",
            "run",
            workflow_ref,
            "--project-root",
            str(project_root.resolve()),
            "--provider",
            provider,
            "--max-turns",
            str(max_turns),
            "--model",
            "mock",
        ]
        if dry_run:
            cmd.append("--dry-run")
        if no_dev_repo_config:
            cmd.append("--no-dev-repo-config")
        if task is not None:
            cmd.extend(["--task", task])
        elif task_file is not None:
            cmd.extend(["--task-file", task_file])
        env = self._env(extra=extra_env)
        proc = subprocess.run(
            cmd,
            cwd=str(cwd.resolve()) if cwd else str(self._repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            input=input_text,
        )
        return AilitCliResult(
            returncode=int(proc.returncode),
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )

    def spawn(
        self,
        *args: str,
        project_root: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.Popen[str]:
        """Запустить `python -m ailit_cli.cli <args>` в фоне (Popen).

        Если ``project_root`` задан, в конец добавляется
        ``--project-root <path>`` (для команд вроде ``agent run``).
        Для ``ailit runtime …`` обычно передают только ``--runtime-dir`` в
        ``args`` и оставляют ``project_root=None``.

        Возвращает Popen-объект; вызывающий отвечает за proc.wait/kill.
        stdout/stderr не захватываются (pipe=False), чтобы процесс
        мог работать как долгоживущий сервер.
        """
        cmd: list[str] = [
            self._python(),
            "-m",
            "ailit_cli.cli",
            *args,
        ]
        if project_root is not None:
            cmd.extend(
                [
                    "--project-root",
                    str(project_root.resolve()),
                ]
            )
        env = self._env(extra=extra_env)
        proc = subprocess.Popen(
            cmd,
            cwd=str(self._repo),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc

    def runtime_status(
        self,
        *,
        runtime_dir: Path,
        extra_env: dict[str, str] | None = None,
    ) -> AilitCliResult:
        """Выполнить ``ailit runtime status`` (проверка сокета supervisor)."""
        cmd: list[str] = [
            self._python(),
            "-m",
            "ailit_cli.cli",
            "runtime",
            "status",
            "--runtime-dir",
            str(runtime_dir.resolve()),
        ]
        env = self._env(extra=extra_env)
        proc = subprocess.run(
            cmd,
            cwd=str(self._repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return AilitCliResult(
            returncode=int(proc.returncode),
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )

    def pytest_on(
        self,
        tests_dir: Path,
        *,
        cwd: Path,
        extra_env: dict[str, str] | None = None,
    ) -> AilitCliResult:
        """Запустить pytest на каталоге тестов приложения."""
        py = self._python()
        cmd = [
            py,
            "-m",
            "pytest",
            str(tests_dir.resolve()),
            "-q",
        ]
        env = self._env(extra=extra_env)
        proc = subprocess.run(
            cmd,
            cwd=str(cwd.resolve()),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return AilitCliResult(
            returncode=int(proc.returncode),
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
