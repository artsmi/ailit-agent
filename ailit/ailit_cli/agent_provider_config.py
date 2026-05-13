"""Сборка dict провайдера для ``ailit agent run`` и ``ailit chat``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ailit_cli.merged_config import deep_merge_config_mappings, load_merged_ailit_config
from ailit_cli.paths import repo_root


class DevRepoTestLocalSource:
    """Слой ``<repo>/config/test.local.yaml`` с наименьшим приоритетом (под клон разработки)."""

    def __init__(self, repo_root_override: Path | None = None) -> None:
        """Переопределение корня репозитория только для тестов."""
        self._repo_root_override = repo_root_override

    def yaml_path(self) -> Path:
        """Путь к ``test.local.yaml`` в корне репозитория пакета."""
        root = (
            self._repo_root_override.resolve()
            if self._repo_root_override is not None
            else repo_root().resolve()
        )
        return root / "config" / "test.local.yaml"

    def load_if_present(self) -> dict[str, Any]:
        """Прочитать YAML или ``{}``, если файла нет."""
        p = self.yaml_path()
        if not p.is_file():
            return {}
        raw = p.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if data is None:
            return {}
        if not isinstance(data, dict):
            msg = f"test.local.yaml root must be a mapping: {p}"
            raise ValueError(msg)
        return dict(data)


class AgentRunProviderConfigBuilder:
    """Объединяет merged user config (G.2) и опциональный dev-слой репозитория."""

    def __init__(self, dev_source: DevRepoTestLocalSource | None = None) -> None:
        """Инициализировать источник dev-слоя (по умолчанию реальный ``repo_root``)."""
        self._dev = dev_source if dev_source is not None else DevRepoTestLocalSource()

    def build(self, project_root: Path | None, *, use_dev_repo_yaml: bool) -> dict[str, Any]:
        """Собрать итоговый ``dict`` для фабрики провайдера.

        При ``use_dev_repo_yaml`` и существующем ``test.local.yaml`` в клоне
        этот файл подмешивается **под** глобальным/проектным merge (конфликты
        выигрывает ``load_merged_ailit_config``).
        """
        merged_user = dict(load_merged_ailit_config(project_root))
        if not use_dev_repo_yaml:
            return merged_user
        dev = self._dev.load_if_present()
        return deep_merge_config_mappings(dev, merged_user)
