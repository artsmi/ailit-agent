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
    """Subprocess с PYTHONPATH=tools и корнем репозитория."""

    def __init__(self, repo_root: Path) -> None:
        """Запомнить корень репозитория ailit-agent."""
        self._repo = repo_root.resolve()
        self._tools = self._repo / "tools"

    def _env(self, *, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Окружение: пакеты из tools (как editable для тестов)."""
        base = os.environ.copy()
        prev = base.get("PYTHONPATH", "")
        sep = os.pathsep
        tools_s = str(self._tools)
        base["PYTHONPATH"] = (
            f"{tools_s}{sep}{prev}" if prev else tools_s
        )
        if extra:
            base.update(extra)
        return base

    def agent_run(
        self,
        *,
        workflow_ref: str,
        project_root: Path,
        provider: str = "mock",
        dry_run: bool = False,
        max_turns: int = 8,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> AilitCliResult:
        """Выполнить `python -m ailit.cli agent run …`."""
        cmd: list[str] = [
            sys.executable,
            "-m",
            "ailit.cli",
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
        env = self._env(extra=extra_env)
        proc = subprocess.run(
            cmd,
            cwd=str(cwd.resolve()) if cwd else str(self._repo),
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

    def pytest_on(
        self,
        tests_dir: Path,
        *,
        cwd: Path,
        extra_env: dict[str, str] | None = None,
    ) -> AilitCliResult:
        """Запустить pytest на каталоге тестов приложения."""
        cmd = [
            sys.executable,
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
