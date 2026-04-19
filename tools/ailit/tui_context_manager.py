"""Мульти-контекст для ``ailit tui`` (этап Q.1)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ailit.tui_chat_controller import TuiChatController

_CTX_NAME_MAX: int = 20


def validate_context_name(name: str) -> str | None:
    """Вернуть сообщение об ошибке или None, если имя допустимо."""
    raw = name.strip()
    if not raw:
        return "Имя контекста не может быть пустым."
    if len(raw) > _CTX_NAME_MAX:
        return f"Имя длиннее {_CTX_NAME_MAX} символов: {raw!r}"
    if any(c in raw for c in " \t\n/\\"):
        return "Имя не должно содержать пробелы, / и \\."
    return None


@dataclass
class TuiContextProfile:
    """Профиль именованного контекста."""

    name: str
    project_root: Path
    agent_id: str = "default"
    workflow_ref: str | None = None


@dataclass
class UsageTotals:
    """Накопление токенов по контексту (согласовано с usage dict из JSONL)."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add_from_usage_dict(self, usage: Mapping[str, Any]) -> None:
        """Добавить один ответ ``usage`` из ``model.response``."""
        if usage.get("usage_missing"):
            return
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        self.reasoning_tokens += int(usage.get("reasoning_tokens") or 0)
        self.cache_read_tokens += int(usage.get("cache_read_tokens") or 0)
        self.cache_write_tokens += int(usage.get("cache_write_tokens") or 0)

    def as_dict(self) -> dict[str, int]:
        """Снимок для таблицы ``/ctx stats``."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }

    def assign_from_totals(self, d: Mapping[str, Any]) -> None:
        """Восстановить накопление из сохранённого снимка (Q.3)."""
        self.input_tokens = int(d.get("input_tokens") or 0)
        self.output_tokens = int(d.get("output_tokens") or 0)
        self.reasoning_tokens = int(d.get("reasoning_tokens") or 0)
        self.cache_read_tokens = int(d.get("cache_read_tokens") or 0)
        self.cache_write_tokens = int(d.get("cache_write_tokens") or 0)


@dataclass
class TuiContextRuntime:
    """Контекст: профиль, чат и учёт usage."""

    profile: TuiContextProfile
    chat: TuiChatController = field(default_factory=TuiChatController)
    usage: UsageTotals = field(default_factory=UsageTotals)
    last_used: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        """Обновить метку последнего использования."""
        self.last_used = time.monotonic()


class TuiContextManager:
    """Именованные контексты и активный; черновики ввода при переключении."""

    def __init__(
        self,
        *,
        default_root: Path,
        default_name: str = "default",
    ) -> None:
        """Создать контекст ``default``."""
        self._contexts: dict[str, TuiContextRuntime] = {}
        self._active: str = default_name
        self._draft_by_context: dict[str, str] = {}
        root = default_root.resolve()
        prof = TuiContextProfile(name=default_name, project_root=root)
        self._contexts[default_name] = TuiContextRuntime(profile=prof)

    def active_name(self) -> str:
        """Имя активного контекста."""
        return self._active

    def active_profile(self) -> TuiContextProfile:
        """Профиль активного контекста."""
        return self._contexts[self._active].profile

    def active_runtime(self) -> TuiContextRuntime:
        """Полный runtime активного контекста."""
        return self._contexts[self._active]

    def active_chat(self) -> TuiChatController:
        """Контроллер чата активного контекста."""
        return self._contexts[self._active].chat

    def save_draft(self, name: str, text: str) -> None:
        """Сохранить черновик строки ввода для контекста."""
        self._draft_by_context[name] = text

    def take_draft(self, name: str) -> str:
        """Забрать и удалить черновик (после переключения)."""
        return self._draft_by_context.pop(name, "")

    def peek_draft(self, name: str) -> str:
        """Прочитать черновик без удаления."""
        return self._draft_by_context.get(name, "")

    def list_sorted_names(self) -> list[str]:
        """Имена контекстов по порядку цикла."""
        return sorted(self._contexts.keys())

    def new_context(
        self,
        name: str,
        *,
        project_root: Path | None = None,
        agent_id: str | None = None,
    ) -> str | None:
        """Создать контекст; вернуть текст ошибки или None."""
        err = validate_context_name(name)
        if err:
            return err
        key = name.strip()
        if key in self._contexts:
            return f"Контекст уже существует: {key}"
        root = (project_root or self.active_profile().project_root).resolve()
        aid = (agent_id or "default").strip() or "default"
        prof = TuiContextProfile(
            name=key,
            project_root=root,
            agent_id=aid,
            workflow_ref=None,
        )
        self._contexts[key] = TuiContextRuntime(profile=prof)
        return None

    def switch(self, name: str) -> str | None:
        """Переключить активный контекст; вернуть ошибку или None."""
        key = name.strip()
        if key not in self._contexts:
            return f"Нет контекста: {key}"
        self._contexts[self._active].touch()
        self._active = key
        self._contexts[self._active].touch()
        return None

    def rename_active(self, new_name: str) -> str | None:
        """Переименовать активный контекст."""
        err = validate_context_name(new_name)
        if err:
            return err
        key = new_name.strip()
        old = self._active
        if old == key:
            return None
        if key in self._contexts:
            return f"Имя занято: {key}"
        rt = self._contexts.pop(old)
        rt.profile = TuiContextProfile(
            name=key,
            project_root=rt.profile.project_root,
            agent_id=rt.profile.agent_id,
            workflow_ref=rt.profile.workflow_ref,
        )
        self._contexts[key] = rt
        self._active = key
        if old in self._draft_by_context:
            self._draft_by_context[key] = self._draft_by_context.pop(old)
        return None

    def activate_next(self) -> None:
        """Следующий контекст по сортировке имён (цикл)."""
        names = self.list_sorted_names()
        if not names:
            return
        i = names.index(self._active)
        nxt = names[(i + 1) % len(names)]
        self.switch(nxt)

    def activate_prev(self) -> None:
        """Предыдущий контекст по сортировке имён (цикл)."""
        names = self.list_sorted_names()
        if not names:
            return
        i = names.index(self._active)
        prv = names[(i - 1) % len(names)]
        self.switch(prv)

    def record_turn_usage(self, usage: Mapping[str, Any] | None) -> None:
        """Учесть usage последнего ответа модели для активного контекста."""
        if not usage:
            return
        self._contexts[self._active].usage.add_from_usage_dict(usage)

    def all_usage_rows(self) -> list[tuple[str, dict[str, int]]]:
        """Имя контекста и накопленные токены."""
        out: list[tuple[str, dict[str, int]]] = []
        for n in self.list_sorted_names():
            out.append((n, self._contexts[n].usage.as_dict()))
        return out

    def describe_contexts(self) -> list[tuple[str, Path, bool]]:
        """Имя, корень проекта, признак активного."""
        rows: list[tuple[str, Path, bool]] = []
        for n in self.list_sorted_names():
            prof = self._contexts[n].profile
            rows.append((n, prof.project_root, n == self._active))
        return rows

    def set_active_project_root(self, path: Path) -> None:
        """Сменить ``project_root`` у активного профиля."""
        self._contexts[self._active].profile.project_root = path.resolve()
        self._contexts[self._active].touch()

    def all_runtimes(self) -> list[tuple[str, TuiContextRuntime]]:
        """Пары имя → runtime (упорядочено по имени)."""
        return [(n, self._contexts[n]) for n in self.list_sorted_names()]

    def replace_from_serialized(
        self,
        *,
        active: str,
        runtimes: dict[str, TuiContextRuntime],
    ) -> None:
        """Восстановить состояние из снимка (Q.3)."""
        self._contexts = dict(runtimes)
        names = self.list_sorted_names()
        if active in self._contexts:
            self._active = active
        else:
            self._active = names[0] if names else "default"
