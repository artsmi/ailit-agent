"""Резолв дефолтных provider/model из merge-конфига для разных режимов CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ailit.merged_config import load_merged_ailit_config
from ailit.provider_catalog import catalog_for, provider_ids


@dataclass(frozen=True, slots=True)
class DefaultProviderModel:
    """Дефолтные значения для provider/model."""

    provider: str
    model: str


class DefaultProviderModelResolver:
    """Достаёт default.provider/default.model из merge-конфига."""

    def resolve(
        self,
        *,
        project_root: Path | None,
    ) -> DefaultProviderModel:
        """Вернуть provider/model с нормализацией и фолбэками."""
        cfg = dict(load_merged_ailit_config(project_root))
        return self.from_mapping(cfg)

    def from_mapping(self, cfg: Mapping[str, Any]) -> DefaultProviderModel:
        """Вернуть provider/model из mapping (для тестов)."""
        dflt_raw = cfg.get("default")
        dflt = dflt_raw if isinstance(dflt_raw, dict) else {}
        provider = str(dflt.get("provider") or "").strip().lower() or "mock"
        if provider not in provider_ids():
            provider = "mock"
        model = str(dflt.get("model") or "").strip()
        if not model:
            cat = catalog_for(provider)
            if cat is not None:
                model = cat.default_model
        return DefaultProviderModel(provider=provider, model=model)
