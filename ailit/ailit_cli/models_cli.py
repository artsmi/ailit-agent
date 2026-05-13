"""CLI: список известных провайдеров/моделей и текущих значений из config."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ailit_cli.config_secrets import ConfigSecretRedactor
from ailit_cli.merged_config import load_merged_ailit_config
from ailit_cli.provider_catalog import PROVIDERS


def cmd_models_list(_args: argparse.Namespace) -> int:
    """Печать справочника моделей и текущих значений из merge."""
    merged = dict(load_merged_ailit_config(None))
    safe = ConfigSecretRedactor().redact(merged)
    dflt = safe.get("default") if isinstance(safe.get("default"), dict) else {}
    sys.stdout.write("# default\n")
    sys.stdout.write(f"default.provider={dflt.get('provider', '')}\n")
    sys.stdout.write(f"default.model={dflt.get('model', '')}\n\n")
    sys.stdout.write("# providers\n")
    for p in PROVIDERS:
        sys.stdout.write(f"\n[{p.provider_id}]\n")
        sys.stdout.write(f"default_model={p.default_model}\n")
        for m in p.models:
            sys.stdout.write(f"- {m}\n")
    sys.stdout.write("\n")
    return 0


def register_models_parser(sub: Any) -> None:
    """Добавить `models list`."""
    p = sub.add_parser("models", help="Справочник провайдеров и моделей")
    sub2 = p.add_subparsers(dest="models_cmd", required=True)
    p_list = sub2.add_parser(
        "list",
        help="Список провайдеров и известных моделей",
    )
    p_list.set_defaults(func=cmd_models_list)
