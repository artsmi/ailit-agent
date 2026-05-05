"""Файл конфигурации workspace для broker → AgentWork / AgentMemory (G8)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agent_core.runtime.errors import RuntimeProtocolError

_MAX_WORKSPACE_EXTRAS: int = 4


@dataclass(frozen=True, slots=True)
class BrokerWorkspaceEntry:
    """Одна пара namespace + корень проекта (абсолютный путь)."""

    namespace: str
    project_root: Path


@dataclass(frozen=True, slots=True)
class BrokerWorkspaceFile:
    """Содержимое JSON-файла workspace (primary + дополнительные корни)."""

    primary_namespace: str
    primary_project_root: Path
    extra: tuple[BrokerWorkspaceEntry, ...]

    @property
    def all_entries(self) -> tuple[BrokerWorkspaceEntry, ...]:
        """Primary первым, затем extra (как в запросе supervisor)."""
        prim = BrokerWorkspaceEntry(
            namespace=self.primary_namespace,
            project_root=self.primary_project_root,
        )
        return (prim,) + self.extra


def parse_workspace_extras_from_request(
    raw: Any,
    *,
    max_extras: int = _MAX_WORKSPACE_EXTRAS,
) -> tuple[BrokerWorkspaceEntry, ...]:
    """Разобрать поле ``workspace`` из JSON-запроса supervisor."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise RuntimeProtocolError(
            code="invalid_args",
            message="workspace must be a JSON array",
        )
    if len(raw) > max_extras:
        raise RuntimeProtocolError(
            code="invalid_args",
            message=f"workspace must have at most {max_extras} entries",
        )
    out: list[BrokerWorkspaceEntry] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RuntimeProtocolError(
                code="invalid_args",
                message=f"workspace[{i}] must be an object",
            )
        ns = str(item.get("namespace", "") or "").strip()
        root_s = str(item.get("project_root", "") or "").strip()
        if not ns or not root_s:
            raise RuntimeProtocolError(
                code="invalid_args",
                message=(
                    f"workspace[{i}]: namespace and project_root "
                    "must be non-empty strings"
                ),
            )
        out.append(
            BrokerWorkspaceEntry(
                namespace=ns,
                project_root=Path(root_s).expanduser().resolve(),
            ),
        )
    return tuple(out)


def broker_workspace_file_from_mapping(
    data: Mapping[str, Any],
) -> BrokerWorkspaceFile:
    """Разобрать объект из JSON-файла (без I/O)."""
    pn = str(data.get("primary_namespace", "") or "").strip()
    pr = str(data.get("primary_project_root", "") or "").strip()
    if not pn or not pr:
        raise RuntimeProtocolError(
            code="invalid_args",
            message="workspace file: primary_namespace/primary_project_root",
        )
    raw_ws = data.get("workspace", [])
    extras = parse_workspace_extras_from_request(raw_ws)
    return BrokerWorkspaceFile(
        primary_namespace=pn,
        primary_project_root=Path(pr).expanduser().resolve(),
        extra=extras,
    )


def write_broker_workspace_file(path: Path, spec: BrokerWorkspaceFile) -> None:
    """Записать JSON для передачи в broker / subprocess (без секретов)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "primary_namespace": spec.primary_namespace,
        "primary_project_root": str(spec.primary_project_root.resolve()),
        "workspace": [
            {
                "namespace": e.namespace,
                "project_root": str(e.project_root.resolve()),
            }
            for e in spec.extra
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def read_broker_workspace_file(path: Path) -> BrokerWorkspaceFile:
    """Прочитать JSON workspace из пути."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeProtocolError(
            code="invalid_args",
            message=f"workspace file json: {e}",
        ) from e
    if not isinstance(raw, dict):
        raise RuntimeProtocolError(
            code="invalid_args",
            message="workspace file must be a JSON object",
        )
    return broker_workspace_file_from_mapping(raw)
