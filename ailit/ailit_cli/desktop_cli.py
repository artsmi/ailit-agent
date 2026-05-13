"""CLI: `ailit desktop` launcher (Workflow 9, G9.4)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DesktopLaunchPaths:
    """Resolved paths for desktop launch."""

    install_prefix: Path
    app_image: Path


class DesktopBinaryLocator:
    """Resolves expected locations of installed desktop artifacts."""

    def resolve(self) -> DesktopLaunchPaths:
        """Return expected install prefix and AppImage path.

        Resolution rules:
        - Use ``AILIT_INSTALL_PREFIX`` when set (same as ``scripts/install``).
        - Default to ``~/.local/share/ailit``.
        """
        raw = os.environ.get("AILIT_INSTALL_PREFIX", "").strip()
        prefix = Path(raw).expanduser().resolve() if raw else None
        if prefix is None:
            prefix = (Path.home() / ".local" / "share" / "ailit").resolve()
        app_image = (prefix / "desktop" / "ailit-desktop.AppImage").resolve()
        return DesktopLaunchPaths(install_prefix=prefix, app_image=app_image)


class DesktopDevRunner:
    """Runs desktop in dev mode from the repository workspace."""

    def run(self, repo_root: Path) -> int:
        """Execute `npm run dev` in `desktop/`."""
        desktop_dir = (repo_root / "desktop").resolve()
        if not desktop_dir.is_dir():
            sys.stderr.write(
                "Не найден каталог desktop/ в репозитории. "
                "Запустите `./scripts/install` или установите "
                "desktop artifacts.\n"
            )
            return 2
        return subprocess.call(["npm", "run", "dev"], cwd=str(desktop_dir))


class DesktopLauncher:
    """Launches installed desktop artifact or provides diagnostics."""

    def __init__(
        self,
        locator: DesktopBinaryLocator | None = None,
        dev_runner: DesktopDevRunner | None = None,
    ) -> None:
        self._locator = locator or DesktopBinaryLocator()
        self._dev_runner = dev_runner or DesktopDevRunner()

    def launch(self, *, dev: bool, repo_root: Path) -> int:
        """Launch desktop.

        Args:
            dev: If True, start dev mode (`npm run dev`).
            repo_root: Root of the repository (for dev fallback / hints).
        """
        if dev:
            return self._dev_runner.run(repo_root)

        paths = self._locator.resolve()
        if paths.app_image.is_file():
            try:
                paths.app_image.chmod(0o755)
            except OSError:
                # Best-effort; still try to execute.
                pass
            return subprocess.call([str(paths.app_image)])

        sys.stderr.write("Desktop binary не найден.\n")
        sys.stderr.write(f"Ожидалось: {paths.app_image}\n")
        sys.stderr.write("Переустановите:  ./scripts/install\n")
        sys.stderr.write("Dev-режим:       ailit desktop --dev\n")
        return 2


def cmd_desktop(args: argparse.Namespace) -> int:
    """Entry for `ailit desktop`."""
    repo_root = Path(__file__).resolve().parents[2]
    dev = bool(getattr(args, "dev", False))
    return DesktopLauncher().launch(dev=dev, repo_root=repo_root)


def register_desktop_parser(sub: Any) -> None:
    """Register `desktop` parser."""
    p = sub.add_parser(
        "desktop",
        help="Запустить Electron desktop UI (Linux MVP)",
    )
    p.add_argument(
        "--dev",
        action="store_true",
        help="Запустить dev-режим из репозитория (desktop/ npm run dev)",
    )
    p.set_defaults(func=cmd_desktop)
