"""CLI: `ailit project add` (Workflow 9, G9.3)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from ailit.project_registry import ProjectRegistryEditor


def cmd_project_add(args: argparse.Namespace) -> int:
    """Register project in local `.ailit/config.yaml` and activate it."""
    raw = getattr(args, "path", None)
    project_root = (
        Path(str(raw)).expanduser().resolve() if raw else Path.cwd().resolve()
    )
    if not project_root.exists() or not project_root.is_dir():
        sys.stderr.write(f"Некорректный путь проекта: {project_root}\n")
        return 2

    res = ProjectRegistryEditor().add_project(project_root, start=Path.cwd())
    sys.stdout.write(f"registry_file={res.registry_file}\n")
    sys.stdout.write(f"project_id={res.project_id}\n")
    sys.stdout.write(f"namespace={res.namespace}\n")
    sys.stdout.write(f"path={res.path}\n")
    sys.stdout.write(
        "next=ailit memory index --project-root " + str(res.path) + "\n"
    )
    return 0


def register_project_parser(sub: Any) -> None:
    """Добавить `project` с подкомандой `add`."""
    p = sub.add_parser(
        "project",
        help="Project registry для desktop (Workflow 9)",
    )
    p_sub = p.add_subparsers(dest="project_cmd", required=True)
    p_add = p_sub.add_parser(
        "add",
        help="Добавить проект в локальный registry (.ailit/config.yaml)",
    )
    p_add.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Путь к проекту (по умолчанию текущий каталог)",
    )
    p_add.set_defaults(func=cmd_project_add)
