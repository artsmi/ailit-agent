"""Установка плагина в ``.ailit/plugins/<id>`` (M.1 MVP)."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from project_layer.plugin_manifest import AilitPluginManifestLoader


def _safe_dir_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", name.strip())[:64]
    return cleaned or "plugin"


@dataclass(frozen=True, slots=True)
class PluginInstallResult:
    """Результат установки."""

    dest_dir: Path
    manifest_name: str


class PluginInstaller:
    """Копирование или shallow clone плагина в каталог проекта."""

    @classmethod
    def install(cls, source: str, *, project_root: Path) -> PluginInstallResult:
        """Установить плагин из локального пути или ``https://`` / ``git@`` URL."""
        root = project_root.resolve()
        plugins = (root / ".ailit" / "plugins").resolve()
        plugins.mkdir(parents=True, exist_ok=True)
        src = source.strip()
        if cls._looks_like_git_url(src):
            return cls._install_from_git(src, plugins_root=plugins)
        return cls._install_from_path(Path(src).expanduser().resolve(), plugins_root=plugins)

    @staticmethod
    def _looks_like_git_url(s: str) -> bool:
        t = s.strip()
        if t.startswith("git@"):
            return True
        if t.startswith("https://") or t.startswith("http://"):
            low = t.lower()
            return (
                "github.com" in low
                or "gitlab.com" in low
                or "bitbucket.org" in low
                or t.rstrip("/").endswith(".git")
            )
        return False

    @classmethod
    def _install_from_path(cls, src_dir: Path, *, plugins_root: Path) -> PluginInstallResult:
        if not src_dir.is_dir():
            msg = f"plugin source is not a directory: {src_dir}"
            raise NotADirectoryError(msg)
        manifest = AilitPluginManifestLoader.load_from_dir(src_dir)
        dest = (plugins_root / _safe_dir_name(manifest.name)).resolve()
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src_dir, dest, dirs_exist_ok=False)
        return PluginInstallResult(dest_dir=dest, manifest_name=manifest.name)

    @classmethod
    def _install_from_git(cls, url: str, *, plugins_root: Path) -> PluginInstallResult:
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "src"
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(clone_dir)],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            manifest = AilitPluginManifestLoader.load_from_dir(clone_dir)
            dest = (plugins_root / _safe_dir_name(manifest.name)).resolve()
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(clone_dir), str(dest))
        return PluginInstallResult(dest_dir=dest, manifest_name=manifest.name)
