"""Подкоманды ``ailit config`` (путь, показ merge без секретов)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from ailit.config_secrets import ConfigSecretRedactor
from ailit.merged_config import AilitConfigMerger, load_merged_ailit_config
from ailit.project_root_hint import ProjectRootDetector
from ailit.user_paths import global_config_dir, global_state_dir


def cmd_config_path(_args: argparse.Namespace) -> int:
    """Печать канонических путей и обнаруженного корня проекта."""
    gcfg = global_config_dir()
    gst = global_state_dir()
    merger = AilitConfigMerger()
    gfile = merger.global_config_file()
    proj = ProjectRootDetector().find()
    lines = (
        f"global_config_dir={gcfg}",
        f"global_state_dir={gst}",
        f"global_config_file={gfile}",
        f"detected_project_root={proj if proj else '(не найден)'}",
    )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    """Эффективный merge-конфиг в YAML без секретов."""
    start = Path(args.project_root).resolve() if args.project_root else None
    proj = start if start is not None else ProjectRootDetector().find()
    raw = dict(load_merged_ailit_config(proj))
    safe = ConfigSecretRedactor().redact(raw)
    sys.stdout.write(yaml.safe_dump(safe, allow_unicode=True, sort_keys=False))
    return 0


def register_config_parser(sub: Any) -> None:
    """Добавить ``config`` с подкомандами ``path`` и ``show``."""
    p_cfg = sub.add_parser(
        "config",
        help="Пути и эффективная конфигурация (без секретов в show)",
    )
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)

    p_path = cfg_sub.add_parser("path", help="Каталоги конфигурации и корень проекта")
    p_path.set_defaults(func=cmd_config_path)

    p_show = cfg_sub.add_parser(
        "show",
        help="Показать merge YAML (секреты замаскированы)",
    )
    p_show.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Явный корень проекта для слоя .ailit/config.yaml (иначе автоот cwd)",
    )
    p_show.set_defaults(func=cmd_config_show)
