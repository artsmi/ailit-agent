"""Project layer: конфигурация проекта, реестры workflow/agent, canonical context."""

from __future__ import annotations

from project_layer.bootstrap import (
    ChatSessionTuning,
    WorkflowAugmentation,
    compute_chat_tuning,
    compute_workflow_augmentation,
)
from project_layer.knowledge import ContextSnapshot, FilesystemKnowledgeRefresh, KnowledgeRefreshPort
from project_layer.loader import LoadedProject, load_project
from project_layer.models import AgentPreset, ProjectConfig, RuntimeMode, WorkflowRef
from project_layer.registry import ProjectRegistries

__all__ = [
    "AgentPreset",
    "ChatSessionTuning",
    "WorkflowAugmentation",
    "ContextSnapshot",
    "FilesystemKnowledgeRefresh",
    "KnowledgeRefreshPort",
    "LoadedProject",
    "ProjectConfig",
    "ProjectRegistries",
    "RuntimeMode",
    "WorkflowRef",
    "compute_chat_tuning",
    "compute_workflow_augmentation",
    "load_project",
]
