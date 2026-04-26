"""CLI: `ailit project add` (Workflow 9, G9.3)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ailit.project_registry import ProjectRegistryEditor


def cmd_project_add(args: argparse.Namespace) -> int:
    """Записать проект в глобальный ``~/.ailit`` и активировать."""
    raw = getattr(args, "path", None)
    project_root = (
        Path(str(raw)).expanduser().resolve() if raw else Path.cwd().resolve()
    )
    if not project_root.exists() or not project_root.is_dir():
        sys.stderr.write(f"Некорректный путь проекта: {project_root}\n")
        return 2

    res = ProjectRegistryEditor().add_project(project_root)
    sys.stdout.write(f"registry_file={res.registry_file}\n")
    sys.stdout.write(f"project_id={res.project_id}\n")
    sys.stdout.write(f"namespace={res.namespace}\n")
    sys.stdout.write(f"path={res.path}\n")
    sys.stdout.write(
        "next=ailit memory index --project-root " + str(res.path) + "\n"
    )
    return 0


def cmd_project_list(args: argparse.Namespace) -> int:
    """Human/JSON listing; только глобальный ``~/.ailit``."""
    res = ProjectRegistryEditor().read_registry()
    as_json = bool(getattr(args, "as_json", False))
    if as_json:
        payload: dict[str, Any] = {
            "ok": True,
            "registry_file": str(res.registry_file),
            "active_project_ids": list(res.active_project_ids),
            "entries": list(res.entries),
        }
        sys.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            + "\n"
        )
        return 0
    sys.stdout.write(f"registry_file={res.registry_file}\n")
    for pid in res.active_project_ids:
        sys.stdout.write(f"active_project_id={pid}\n")
    for row in res.entries:
        if not row:
            continue
        sys.stdout.write(
            f"project_id={row.get('project_id', '')} "
            f"path={row.get('path', '')} "
            f"namespace={row.get('namespace', '')}\n"
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
        help="Добавить проект в глобальный registry (~/.ailit)",
    )
    p_add.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Путь к проекту (по умолчанию текущий каталог)",
    )
    p_add.set_defaults(func=cmd_project_add)
    p_list = p_sub.add_parser(
        "list",
        help="Показать зарегистрированные проекты (глобальный ~/.ailit)",
    )
    p_list.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Вывести JSON на stdout (один объект)",
    )
    p_list.set_defaults(func=cmd_project_list)
