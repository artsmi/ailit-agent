"""Загрузка локального `config/test.local.yaml` (gitignored)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml


def default_config_path() -> Path:
    """Путь к `config/test.local.yaml` относительно текущего каталога."""
    return Path.cwd() / "config" / "test.local.yaml"


def load_test_local_yaml(path: Path | None = None) -> Mapping[str, Any]:
    """Прочитать YAML; если файла нет — вернуть пустой dict."""
    p = path or default_config_path()
    if not p.is_file():
        return {}
    raw = p.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = "test.local.yaml root must be a mapping"
        raise ValueError(msg)
    return data


def deepseek_api_key_from_env_or_config(config: Mapping[str, Any] | None = None) -> str:
    """Ключ DeepSeek: приоритет env, затем gitignored yaml."""
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key
    cfg = config or load_test_local_yaml()
    ds = cfg.get("deepseek")
    if isinstance(ds, dict):
        key = str(ds.get("api_key") or "").strip()
        return key
    return ""


def kimi_api_key_from_env_or_config(config: Mapping[str, Any] | None = None) -> str:
    """Ключ Kimi/Moonshot: `KIMI_API_KEY` или `MOONSHOT_API_KEY`, затем yaml."""
    for name in ("KIMI_API_KEY", "MOONSHOT_API_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    cfg = config or load_test_local_yaml()
    km = cfg.get("kimi")
    if isinstance(km, dict):
        return str(km.get("api_key") or "").strip()
    return ""


def live_run_allowed(config: Mapping[str, Any] | None = None) -> bool:
    """True если явно разрешён live прогон (конфиг + опционально env)."""
    if os.environ.get("AILIT_RUN_LIVE", "").strip() == "1":
        return True
    cfg = config or load_test_local_yaml()
    live = cfg.get("live")
    if isinstance(live, dict) and live.get("run") is True:
        return True
    return False
