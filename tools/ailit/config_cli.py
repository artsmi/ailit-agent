"""Подкоманды ``ailit config`` (путь, показ merge без секретов)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from ailit.config_secrets import ConfigSecretRedactor
from ailit.config_store import apply_config_set
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
    home = os.environ.get("AILIT_HOME", "")
    lines = (
        f"AILIT_HOME={home or '(не задан)'}",
        f"global_config_dir={gcfg}",
        f"global_state_dir={gst}",
        f"global_logs_dir={gst / 'logs'}",
        f"global_config_file={gfile}",
        f"detected_project_root={proj if proj else '(не найден)'}",
    )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    """Записать значение в глобальный ``config.yaml`` (allowlist)."""
    key = str(args.key).strip()
    value = str(args.value).strip()
    try:
        written = apply_config_set(key, value)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(f"Записано в {written}\n")
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
    """Добавить ``config`` с подкомандами ``path``, ``show``, ``set``."""
    p_cfg = sub.add_parser(
        "config",
        help="Пути и эффективная конфигурация (без секретов в show)",
    )
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)

    p_path = cfg_sub.add_parser(
        "path",
        help="Каталоги конфигурации и корень проекта",
    )
    p_path.set_defaults(func=cmd_config_path)

    p_set = cfg_sub.add_parser(
        "set",
        help="Записать ключ в глобальный config.yaml (allowlist)",
    )
    p_set.add_argument(
        "key",
        help="Ключ с точками, например deepseek.model",
    )
    p_set.add_argument(
        "value",
        help="Значение (для live.run: true/false/1/0)",
    )
    p_set.set_defaults(func=cmd_config_set)

    p_show = cfg_sub.add_parser(
        "show",
        help="Показать merge YAML (секреты замаскированы)",
    )
    p_show.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Корень проекта для .ailit/config.yaml (иначе от cwd)",
    )
    p_show.set_defaults(func=cmd_config_show)
