"""Манифест плагина ailit (MVP, схема v1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True, slots=True)
class AilitPluginManifestV1:
    """Минимальный контракт ``ailit-plugin.yaml``."""

    schema_version: int
    name: str
    version: str
    skills_paths: tuple[str, ...]
    """Корень плагина на диске (для разрешения ``skills_paths``)."""
    plugin_root: Path


class AilitPluginManifestLoader:
    """Загрузка и валидация манифеста из каталога плагина."""

    @staticmethod
    def load_from_dir(plugin_dir: Path) -> AilitPluginManifestV1:
        """Прочитать ``ailit-plugin.yaml`` в корне каталога плагина."""
        path = (plugin_dir / "ailit-plugin.yaml").resolve()
        if not path.is_file():
            msg = f"ailit-plugin.yaml not found in {plugin_dir}"
            raise FileNotFoundError(msg)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = "ailit-plugin.yaml root must be a mapping"
            raise ValueError(msg)
        return AilitPluginManifestLoader._parse(raw, plugin_root=plugin_dir.resolve())

    @staticmethod
    def _parse(data: Mapping[str, Any], *, plugin_root: Path) -> AilitPluginManifestV1:
        ver = int(data.get("schema_version", 1))
        name = str(data.get("name") or "").strip()
        if not name:
            msg = "plugin manifest: name is required"
            raise ValueError(msg)
        version = str(data.get("version") or "0.0.0").strip()
        sp = data.get("skills_paths") or []
        if isinstance(sp, str):
            paths = (sp,)
        elif isinstance(sp, list):
            paths = tuple(str(x).strip() for x in sp if str(x).strip())
        else:
            msg = "skills_paths must be a list of strings or a single string"
            raise TypeError(msg)
        return AilitPluginManifestV1(
            schema_version=ver,
            name=name,
            version=version,
            skills_paths=paths,
            plugin_root=plugin_root,
        )
