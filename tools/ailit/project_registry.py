"""Project registry storage for `ailit desktop` (Workflow 9, G9.3).

Хранит список проектов в ближайшем `.ailit/config.yaml` (upwards discovery).
Provider/model не являются частью project registry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ailit.project_config_discovery import ProjectAilitConfigDiscovery


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
    """Snapshot of `projects` section in `.ailit/config.yaml`."""

    registry_file: Path
    entries: tuple[dict[str, Any], ...]
    active_project_ids: tuple[str, ...]


class LocalYamlFileStore:
    """Atomic YAML mapping read/write for local `.ailit/config.yaml`."""

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


class ProjectRegistryLocator:
    """Finds nearest `.ailit/config.yaml` to store registry."""

    def find_registry_file(self, start: Path) -> Path:
        found = ProjectAilitConfigDiscovery.collect_deepest_first(start)
        if found:
            return found[0]
        return (start.resolve() / ".ailit" / "config.yaml").resolve()


class ProjectRegistryEditor:
    """Read/modify/write `projects` section inside `.ailit/config.yaml`."""

    def __init__(
        self,
        locator: ProjectRegistryLocator | None = None,
        store: LocalYamlFileStore | None = None,
    ) -> None:
        self._locator = locator or ProjectRegistryLocator()
        self._store = store or LocalYamlFileStore()

    def add_project(
        self, project_root: Path, *, start: Path
    ) -> ProjectRegistryWriteResult:
        abs_path = project_root.resolve()
        project_id = _stable_project_id(abs_path)
        namespace = _derive_namespace(abs_path)
        title = abs_path.name
        registry_file = self._locator.find_registry_file(start)

        data = self._store.load_mapping(registry_file)
        projects = data.get("projects")
        if not isinstance(projects, dict):
            projects = {}
            data["projects"] = projects

        entries = projects.get("entries")
        if not isinstance(entries, list):
            entries = []
            projects["entries"] = entries

        active_ids = projects.get("active_project_ids")
        if not isinstance(active_ids, list):
            active_ids = []
            projects["active_project_ids"] = active_ids

        abs_path_str = str(abs_path)
        existing: dict[str, Any] | None = None
        for row in entries:
            if (
                isinstance(row, dict)
                and str(row.get("path", "")).strip() == abs_path_str
            ):
                existing = row
                break

        if existing is None:
            existing = {}
            entries.append(existing)

        existing.update(
            {
                "project_id": str(project_id),
                "path": abs_path_str,
                "namespace": str(namespace),
                "title": str(title),
                "added_at": str(existing.get("added_at") or _now_utc_iso_z()),
                "active": True,
            }
        )

        if project_id not in active_ids:
            active_ids.append(project_id)

        self._store.save_mapping(registry_file, data)

        return ProjectRegistryWriteResult(
            registry_file=registry_file,
            project_id=project_id,
            namespace=namespace,
            title=title,
            path=abs_path,
        )

    def read_registry(self, *, start: Path) -> ProjectRegistryListResult:
        """Прочитать registry из ближайшего к `start` `.ailit/config.yaml`."""
        registry_file = self._locator.find_registry_file(start)
        data = self._store.load_mapping(registry_file)
        projects = data.get("projects")
        if not isinstance(projects, dict):
            return ProjectRegistryListResult(
                registry_file=registry_file,
                entries=(),
                active_project_ids=(),
            )
        raw_entries = projects.get("entries")
        entries: list[dict[str, Any]] = []
        if isinstance(raw_entries, list):
            for item in raw_entries:
                if isinstance(item, dict):
                    entries.append(dict(item))
        raw_active = projects.get("active_project_ids")
        active: list[str] = []
        if isinstance(raw_active, list):
            for x in raw_active:
                if isinstance(x, str) and x.strip():
                    active.append(x)
        return ProjectRegistryListResult(
            registry_file=registry_file,
            entries=tuple(entries),
            active_project_ids=tuple(active),
        )
