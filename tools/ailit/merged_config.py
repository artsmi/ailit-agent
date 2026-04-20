"""Слияние слоёв пользовательской конфигурации ``ailit``."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ailit.project_config_discovery import ProjectAilitConfigDiscovery
from ailit.user_paths import GlobalDirResolver

GLOBAL_USER_CONFIG_FILENAME = "config.yaml"


def _deep_merge(
    base: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    """Рекурсивно объединить mapping; overlay перекрывает base."""
    result: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_mapping_file(path: Path) -> dict[str, Any]:
    """Прочитать YAML/JSON mapping; при отсутствии файла — ``{}``."""
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".json",):
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = f"Config root must be a mapping: {path}"
        raise ValueError(msg)
    return data


def _default_ailit_config() -> dict[str, Any]:
    """Встроенные значения по умолчанию (нижайший приоритет)."""
    return {
        "schema_version": "1",
        "default": {"provider": "mock", "model": ""},
        "live": {"run": False},
        "deepseek": {},
        "kimi": {},
        "tests": {},
    }


class ProviderEnvOverlay:
    """Накладывает известные переменные окружения на уже смёрдженный dict."""

    def apply(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """Вернуть новый dict с подмешанными секретами и флагами из env."""
        out = _deep_merge({}, cfg)
        ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if ds_key:
            ds = out.get("deepseek")
            base_ds: dict[str, Any] = dict(ds) if isinstance(ds, dict) else {}
            base_ds["api_key"] = ds_key
            out["deepseek"] = base_ds
        for env_name in (
            "KIMI_API_KEY",
            "MOONSHOT_API_KEY",
        ):
            km_key = os.environ.get(env_name, "").strip()
            if km_key:
                km = out.get("kimi")
                base_km: dict[str, Any] = (
                    dict(km) if isinstance(km, dict) else {}
                )
                base_km["api_key"] = km_key
                out["kimi"] = base_km
                break
        if os.environ.get("AILIT_RUN_LIVE", "").strip() == "1":
            live = out.get("live")
            base_live: dict[str, Any] = (
                dict(live) if isinstance(live, dict) else {}
            )
            base_live["run"] = True
            out["live"] = base_live
        return out


class AilitConfigMerger:
    """Загрузка и merge; слои описаны в ``ailit.config_layer_order``."""

    def __init__(
        self,
        path_resolver: GlobalDirResolver | None = None,
        env_overlay: ProviderEnvOverlay | None = None,
    ) -> None:
        """Инициализировать merger.

        Args:
            path_resolver: Резолвер глобальных путей (по умолчанию: env).
            env_overlay: Слой env; по умолчанию ProviderEnvOverlay.
        """
        self._paths = path_resolver or GlobalDirResolver()
        self._env_overlay = (
            env_overlay if env_overlay is not None else ProviderEnvOverlay()
        )

    def global_config_file(self) -> Path:
        """Путь к глобальному пользовательскому ``config.yaml``."""
        return self._paths.global_config_dir() / GLOBAL_USER_CONFIG_FILENAME

    def load(self, project_root: Path | None) -> dict[str, Any]:
        """Собрать конфиг: defaults → global file → project → env overlay."""
        merged = _deep_merge({}, _default_ailit_config())
        merged = _deep_merge(
            merged,
            _load_mapping_file(self.global_config_file()),
        )
        if project_root is not None:
            discovered = ProjectAilitConfigDiscovery.collect_deepest_first(
                Path(project_root),
            )
            for proj_file in reversed(discovered):
                merged = _deep_merge(merged, _load_mapping_file(proj_file))
        return self._env_overlay.apply(merged)


def load_merged_ailit_config(
    project_root: Path | None = None,
) -> Mapping[str, Any]:
    """Merge: см. :mod:`ailit.config_layer_order`.

    Проект: от ``project_root`` к корню ФС; ниже по дереву перекрывает выше.

    Args:
        project_root: Корень проекта или ``None`` (без проектного слоя).

    Returns:
        Новый ``dict``, совместимый с :class:`typing.Mapping`.
    """
    return AilitConfigMerger().load(project_root)


def deep_merge_config_mappings(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Публичный рекурсивный merge: ``overlay`` перекрывает ``base``."""
    return _deep_merge(dict(base), dict(overlay))
