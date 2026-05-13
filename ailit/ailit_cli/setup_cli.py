"""CLI: мастер глобальной настройки провайдера (ailit setup)."""

from __future__ import annotations

import argparse
import getpass
import sys
from dataclasses import dataclass
from typing import Any, Callable

from ailit_cli.config_store import apply_config_set
from ailit_cli.provider_catalog import catalog_for, provider_ids


Prompt = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class SetupInputs:
    """Итоговые настройки, записываемые в глобальный config."""

    provider: str
    model: str
    api_key: str


class SetupPrompter:
    """Ввод значений из stdin (интерактив)."""

    def __init__(self, prompt: Prompt | None = None) -> None:
        self._prompt = prompt if prompt is not None else input

    def choose_provider(self) -> str:
        """Выбор провайдера."""
        ids = provider_ids()
        while True:
            raw = self._prompt(
                f"Выберите провайдера {ids} (или 'mock'): "
            ).strip()
            if not raw:
                continue
            pid = raw.lower()
            if pid in ids:
                return pid
            sys.stdout.write(f"Неизвестный провайдер: {raw!r}\n")

    def choose_model(self, provider: str) -> str:
        """Выбор модели."""
        cat = catalog_for(provider)
        if cat is None:
            return ""
        models = cat.models
        default = cat.default_model
        raw = self._prompt(
            f"Модель для {provider} {models} (Enter = {default}): "
        ).strip()
        return raw or default

    def prompt_api_key(self, provider: str) -> str:
        """Запрос API key (скрытый ввод)."""
        if provider == "mock":
            return ""
        v = getpass.getpass(f"API key для {provider}: ").strip()
        return v


class SetupWriter:
    """Запись выбранных значений в глобальный config."""

    def write(self, inputs: SetupInputs) -> None:
        """Записать provider/model/api_key."""
        apply_config_set("default.provider", inputs.provider)
        apply_config_set("default.model", inputs.model)
        if inputs.provider == "deepseek":
            if inputs.api_key:
                apply_config_set("deepseek.api_key", inputs.api_key)
            if inputs.model:
                apply_config_set("deepseek.model", inputs.model)
        if inputs.provider == "kimi":
            if inputs.api_key:
                apply_config_set("kimi.api_key", inputs.api_key)
            if inputs.model:
                apply_config_set("kimi.model", inputs.model)


def cmd_setup(args: argparse.Namespace) -> int:
    """Мастер настройки: интерактивно или флагами."""
    provider = str(getattr(args, "provider", "") or "").strip().lower()
    model = str(getattr(args, "model", "") or "").strip()
    api_key = str(getattr(args, "api_key", "") or "").strip()
    non_interactive = bool(getattr(args, "non_interactive", False))

    prompter = SetupPrompter()
    if not provider and not non_interactive:
        provider = prompter.choose_provider()
    if provider and not model and not non_interactive:
        model = prompter.choose_model(provider)
    if provider and provider != "mock" and not api_key and not non_interactive:
        api_key = prompter.prompt_api_key(provider)

    if not provider:
        sys.stderr.write("Нужен --provider или интерактивный ввод.\n")
        return 2
    if provider not in provider_ids():
        sys.stderr.write(f"Неизвестный провайдер: {provider!r}\n")
        return 2
    if provider != "mock" and not api_key:
        sys.stderr.write("Нужен --api-key (или интерактивный ввод).\n")
        return 2

    cat = catalog_for(provider)
    if not model and cat is not None:
        model = cat.default_model

    SetupWriter().write(
        SetupInputs(provider=provider, model=model, api_key=api_key)
    )
    sys.stdout.write(
        "Готово. Проверка: `ailit config show` или `/config show` в TUI.\n"
    )
    return 0


def register_setup_parser(sub: Any) -> None:
    """Добавить `setup`."""
    p = sub.add_parser("setup", help="Глобальная настройка провайдера и ключа")
    p.add_argument(
        "--provider",
        type=str,
        default=None,
        help=f"Провайдер ({', '.join(provider_ids())})",
    )
    p.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "Имя модели (можно переопределять в TUI и через --model в "
            "agent run)"
        ),
    )
    p.add_argument(
        "--api-key",
        type=str,
        default=None,
        dest="api_key",
        help="API key (будет записан в глобальный config.yaml)",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Не спрашивать ничего; требовать параметры флагами",
    )
    p.set_defaults(func=cmd_setup)
