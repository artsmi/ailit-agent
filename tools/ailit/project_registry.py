"""Project registry в глобальном ``~/.ailit`` (Workflow 9, G9.3).

Структура:
- ``~/.ailit/config.yaml`` — ``active_project_ids`` и ``schema_version``
- ``~/.ailit/projects/<project_id>/config.yaml`` — метаданные одного проекта

Перемещение репозитория на диск = новый ``project_id`` (строго новый проект).
Provider/model не являются частью project registry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ailit.global_ailit_layout import (
    user_global_config_path,
    user_project_dir,
    user_projects_root,
)


def _now_utc_iso_z() -> str:
    dt = datetime.now(tz=timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    raw = value.strip().lower()
    acc: list[str] = []
    last_dash = False
    for ch in raw:
        ok = ch.isalnum() or ch in ("-", "_")
        if ok:
            acc.append(ch)
            last_dash = False
        else:
            if not last_dash:
                acc.append("-")
                last_dash = True
    out = "".join(acc).strip("-")
    return out or "project"


def _stable_project_id(abs_path: Path) -> str:
    title = abs_path.name
    digest = hashlib.sha1(str(abs_path).encode("utf-8")).hexdigest()[:8]
    return f"{_slugify(title)}-{digest}"


def _derive_namespace(abs_path: Path) -> str:
    return _slugify(abs_path.name)


@dataclass(frozen=True, slots=True)
class ProjectRegistryWriteResult:
    """Result of `project add` write."""

    registry_file: Path
    project_id: str
    namespace: str
    title: str
    path: Path


@dataclass(frozen=True, slots=True)
class ProjectRegistryListResult:
    """Снимок глобального registry."""

    registry_file: Path
    entries: tuple[dict[str, Any], ...]
    active_project_ids: tuple[str, ...]


class LocalYamlFileStore:
    """Atomic YAML read/write."""

    def load_mapping(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if data is None:
            return {}
        if not isinstance(data, dict):
            msg = f"Корень {path} должен быть mapping"
            raise ValueError(msg)
        return data

    def save_mapping(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        except OSError:
            if tmp.is_file():
                tmp.unlink(missing_ok=True)
            raise


class ProjectRegistryEditor:
    """Read/modify глобальный project registry в ``~/.ailit``."""

    def __init__(self, store: LocalYamlFileStore | None = None) -> None:
        self._store = store or LocalYamlFileStore()

    def _global_path(self) -> Path:
        return user_global_config_path()

    def _load_global(self) -> dict[str, Any]:
        return self._store.load_mapping(self._global_path())

    def _save_global(self, data: dict[str, Any]) -> None:
        self._store.save_mapping(self._global_path(), data)

    def add_project(
        self,
        project_root: Path,
    ) -> ProjectRegistryWriteResult:
        """Добавить/обновить проект: id от абсолютного пути (стабилен)."""
        abs_path = project_root.resolve()
        project_id = _stable_project_id(abs_path)
        namespace = _derive_namespace(abs_path)
        title = abs_path.name
        pdir = user_project_dir(project_id)
        per_project_file = pdir / "config.yaml"

        per_data: dict[str, Any] = self._store.load_mapping(per_project_file)
        per_data.update(
            {
                "project_id": str(project_id),
                "path": str(abs_path),
                "namespace": str(namespace),
                "title": str(title),
                "added_at": str(
                    per_data.get("added_at") or _now_utc_iso_z()
                ),
                "active": True,
            }
        )
        self._store.save_mapping(per_project_file, per_data)

        g = self._load_global()
        if g.get("schema_version") is None:
            g["schema_version"] = 1
        active = g.get("active_project_ids")
        if not isinstance(active, list):
            active = []
        g["active_project_ids"] = active
        if project_id not in active:
            active.append(project_id)
        self._save_global(g)

        return ProjectRegistryWriteResult(
            registry_file=self._global_path(),
            project_id=project_id,
            namespace=namespace,
            title=title,
            path=abs_path,
        )

    def read_registry(self) -> ProjectRegistryListResult:
        """Считать ``projects/`` и глобальный список active."""
        g = self._load_global()
        raw_active = g.get("active_project_ids")
        active: list[str] = []
        if isinstance(raw_active, list):
            for x in raw_active:
                if isinstance(x, str) and x.strip():
                    active.append(x.strip())

        entries: list[dict[str, Any]] = []
        proot = user_projects_root()
        if proot.is_dir():
            for sub in sorted(proot.iterdir(), key=lambda p: p.name):
                if not sub.is_dir():
                    continue
                f = sub / "config.yaml"
                if not f.is_file():
                    continue
                row = self._store.load_mapping(f)
                if not row.get("project_id") or not row.get("path"):
                    continue
                row = dict(row)
                pid = str(row.get("project_id", ""))
                row["active"] = pid in set(active) or bool(row.get("active"))
                entries.append(row)

        entries.sort(key=lambda r: str(r.get("project_id", "")))
        return ProjectRegistryListResult(
            registry_file=self._global_path(),
            entries=tuple(entries),
            active_project_ids=tuple(active),
        )
