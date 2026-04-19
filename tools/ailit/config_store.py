"""Запись в глобальный ``config.yaml`` только по allowlist ключей."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ailit.merged_config import AilitConfigMerger


class ConfigSetKeyAllowlist:
    """Допустимые ключи в нотации ``секция.поле`` (одна точка или несколько)."""

    _DOT_KEYS: frozenset[str] = frozenset(
        {
            "schema_version",
            "deepseek.model",
            "deepseek.base_url",
            "deepseek.api_key",
            "kimi.model",
            "kimi.api_key",
            "live.run",
            "tests.smoke.max_tokens",
            "tests.smoke.timeout_seconds",
            "tests.large.max_tokens",
            "tests.large.timeout_seconds",
        },
    )

    def allowed_keys_sorted(self) -> tuple[str, ...]:
        """Отсортированный список ключей для подсказок в ошибках."""
        return tuple(sorted(self._DOT_KEYS))

    def is_allowed(self, dot_key: str) -> bool:
        """Проверить, разрешён ли ключ."""
        return dot_key in self._DOT_KEYS


class ConfigValueCoercer:
    """Приведение строки argv к типу по имени ключа."""

    def coerce(self, dot_key: str, raw: str) -> Any:
        """Сконвертировать ``raw`` в значение для YAML."""
        stripped = raw.strip()
        if dot_key == "live.run":
            return stripped.lower() in ("1", "true", "yes", "on")
        if dot_key.endswith(".max_tokens") or dot_key.endswith(".timeout_seconds"):
            return int(stripped, 10)
        return stripped


class DotKeyPathParser:
    """Разбор ``deepseek.model`` → ``("deepseek", "model")``."""

    _SEGMENT = re.compile(r"^[a-zA-Z0-9_]+$")

    def to_tuple(self, dot_key: str) -> tuple[str, ...]:
        """Разобрать ключ на сегменты или бросить ``ValueError``."""
        if not dot_key or ".." in dot_key or dot_key.startswith(".") or dot_key.endswith(
            ".",
        ):
            msg = f"Некорректный ключ: {dot_key!r}"
            raise ValueError(msg)
        parts = tuple(dot_key.split("."))
        for p in parts:
            if not p or not self._SEGMENT.match(p):
                msg = f"Некорректный сегмент в ключе: {dot_key!r}"
                raise ValueError(msg)
        return parts


class NestedMappingWriter:
    """Вложенная запись в ``dict`` по пути из сегментов."""

    def set_path(self, root: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
        """Установить ``value`` по ``path``, создавая промежуточные dict."""
        if not path:
            msg = "Путь ключа не может быть пустым"
            raise ValueError(msg)
        cur: dict[str, Any] = root
        for name in path[:-1]:
            nxt = cur.get(name)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[name] = nxt
            cur = nxt
        cur[path[-1]] = value


class GlobalUserConfigFileStore:
    """Чтение/запись глобального ``config.yaml`` с атомарной заменой файла."""

    def __init__(self, config_file: Path | None = None) -> None:
        """Инициализировать путь к файлу (по умолчанию из :class:`AilitConfigMerger`)."""
        self._path = (
            config_file
            if config_file is not None
            else AilitConfigMerger().global_config_file()
        )

    @property
    def path(self) -> Path:
        """Путь к глобальному ``config.yaml``."""
        return self._path

    def load_mapping(self) -> dict[str, Any]:
        """Загрузить YAML или вернуть пустой dict."""
        if not self._path.is_file():
            return {}
        raw = self._path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if data is None:
            return {}
        if not isinstance(data, dict):
            msg = f"Корень {self._path} должен быть mapping"
            raise ValueError(msg)
        return data

    def save_mapping(self, data: dict[str, Any]) -> None:
        """Атомарно записать YAML."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        tmp = self._path.with_name(f".{self._path.name}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            if tmp.is_file():
                tmp.unlink(missing_ok=True)
            raise


def apply_config_set(dot_key: str, raw_value: str) -> Path:
    """Проверить ключ, записать значение в глобальный конфиг, вернуть путь к файлу.

    Raises:
        ValueError: неразрешённый ключ, неверный формат пути или типа.
    """
    allow = ConfigSetKeyAllowlist()
    if not allow.is_allowed(dot_key):
        allowed = ", ".join(allow.allowed_keys_sorted())
        msg = f"Ключ не в allowlist: {dot_key!r}. Допустимые ключи: {allowed}"
        raise ValueError(msg)
    path_tuple = DotKeyPathParser().to_tuple(dot_key)
    value = ConfigValueCoercer().coerce(dot_key, raw_value)
    store = GlobalUserConfigFileStore()
    data = store.load_mapping()
    NestedMappingWriter().set_path(data, path_tuple, value)
    store.save_mapping(data)
    return store.path
