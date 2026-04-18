"""Сборка debug bundle (zip) для оператора."""

from __future__ import annotations

import json
import platform
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DebugBundleResult:
    """Путь к архиву и перечень включённых файлов."""

    zip_path: Path
    members: tuple[str, ...]


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def build_debug_bundle(
    *,
    project_root: Path,
    dest_zip: Path,
    extra_paths: tuple[Path, ...] = (),
) -> DebugBundleResult:
    """Упаковать project.yaml, .ailit/*, манифест версий."""
    root = project_root.resolve()
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    members: list[str] = []
    manifest: dict[str, Any] = {
        "python": sys.version,
        "platform": platform.platform(),
        "project_root": str(root),
    }
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        meta_name = "manifest.json"
        zf.writestr(meta_name, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        members.append(meta_name)

        proj = root / "project.yaml"
        if proj.is_file():
            arc = _safe_rel(proj, root)
            zf.write(proj, arcname=f"project/{arc}")
            members.append(f"project/{arc}")

        ailit_dir = root / ".ailit"
        if ailit_dir.is_dir():
            for p in sorted(ailit_dir.rglob("*")):
                if p.is_file():
                    arc = _safe_rel(p, root)
                    zf.write(p, arcname=f"ailit_state/{arc}")
                    members.append(f"ailit_state/{arc}")

        for extra in extra_paths:
            if extra.is_file():
                zf.write(extra, arcname=f"extra/{extra.name}")
                members.append(f"extra/{extra.name}")

    return DebugBundleResult(zip_path=dest_zip.resolve(), members=tuple(members))


def default_rollout_phase(project_root: Path) -> str:
    """Прочитать rollout.phase из project.yaml без полной валидации UI."""
    try:
        import yaml  # noqa: PLC0415

        from project_layer.loader import default_project_yaml_path, load_project

        p = default_project_yaml_path(project_root)
        if not p.is_file():
            return "unknown"
        loaded = load_project(p)
        return loaded.config.rollout.phase
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        return "unknown"
