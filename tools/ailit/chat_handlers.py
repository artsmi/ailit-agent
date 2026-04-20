"""Логика чата: проектный слой без Streamlit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.models import ChatMessage, MessageRole
from agent_core.system_prompt_builder import (
    SystemPromptLayers,
    build_effective_system_messages,
    dedupe_system_texts,
)
from project_layer.bootstrap import ChatSessionTuning, compute_chat_tuning
from project_layer.knowledge import (
    ContextSnapshot,
    FilesystemKnowledgeRefresh,
    StubKnowledgeRefresh,
)
from project_layer.loader import (
    LoadedProject,
    default_project_yaml_path,
    load_project,
)


@dataclass(frozen=True, slots=True)
class ProjectLoadResult:
    """Результат загрузки project.yaml."""

    loaded: LoadedProject | None
    error: str | None


class ProjectSessionFactory:
    """Загрузка проекта и расчёт tuning для чата."""

    def __init__(self, project_root: Path) -> None:
        """Запомнить корень проекта."""
        self._root = project_root.resolve()

    def load(self) -> ProjectLoadResult:
        """Загрузить project.yaml по умолчанию."""
        path = default_project_yaml_path(self._root)
        if not path.is_file():
            return ProjectLoadResult(None, f"Нет файла: {path}")
        try:
            loaded = load_project(path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return ProjectLoadResult(None, f"{type(exc).__name__}: {exc}")
        return ProjectLoadResult(loaded, None)

    def refresh_snapshot(self, loaded: LoadedProject) -> ContextSnapshot:
        """Построить снимок canonical context (для UI)."""
        mode = loaded.config.context.knowledge_refresh.mode
        if mode == "stub":
            return StubKnowledgeRefresh().refresh(loaded)
        return FilesystemKnowledgeRefresh().refresh(loaded)

    def tuning_for_chat(
        self,
        loaded: LoadedProject,
        agent_id: str,
        snapshot: ContextSnapshot | None,
    ) -> ChatSessionTuning:
        """Параметры сессии с учётом проекта."""
        return compute_chat_tuning(loaded, agent_id, snapshot)


def merge_system_messages(
    base_system: str,
    tuning: ChatSessionTuning,
) -> list[ChatMessage]:
    """Собрать system-слои: проект, затем базовый промпт чата."""
    extras = dedupe_system_texts(tuning.extra_system_messages)
    layers = SystemPromptLayers(
        default=(base_system,),
        append=extras,
    )
    return build_effective_system_messages(layers)


def strip_system_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Убрать все system-сообщения (перед подстановкой project layer)."""
    return [m for m in messages if m.role is not MessageRole.SYSTEM]


def attach_runner_suffix(
    base_system: str,
    tuning: ChatSessionTuning,
    suffix: list[ChatMessage],
) -> list[ChatMessage]:
    """Сообщения для SessionRunner: prefix + хвост диалога."""
    return merge_system_messages(base_system, tuning) + suffix


def store_after_run(
    base_system: str,
    prefix_len: int,
    runner_messages: list[ChatMessage],
) -> list[ChatMessage]:
    """Сжать обратно к одному system для UI-хранилища."""
    tail = runner_messages[prefix_len:]
    return [ChatMessage(role=MessageRole.SYSTEM, content=base_system), *tail]
