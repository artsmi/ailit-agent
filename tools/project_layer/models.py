"""Типизированные модели project.yaml (v1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class RuntimeMode(str, Enum):
    """Режим исполнения (совместимость с legacy pipeline — этап 8)."""

    AILIT = "ailit"
    LEGACY = "legacy"


@dataclass(frozen=True, slots=True)
class WorkflowRef:
    """Ссылка на workflow YAML относительно корня проекта."""

    workflow_id: str
    path: str


@dataclass(frozen=True, slots=True)
class AgentPreset:
    """Пресет агента для чата или задач."""

    agent_id: str
    system_append: str = ""
    system_prompt: str | None = None
    temperature: float | None = None
    max_turns: int | None = None
    shortlist_extra: frozenset[str] = field(default_factory=frozenset)
    """Роль агента: ``teammate`` — режим межагентной почты (addendum + tool)."""
    role: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRefreshModel:
    """Параметры слоя knowledge_refresh."""

    mode: str = "filesystem"
    max_files: int = 20
    max_chars_per_file: int = 4000
    max_keywords: int = 40


@dataclass(frozen=True, slots=True)
class ContextSectionModel:
    """Секция context: canonical paths и refresh."""

    canonical_globs: tuple[str, ...] = ("context/**/*.md",)
    knowledge_refresh: KnowledgeRefreshModel = field(default_factory=KnowledgeRefreshModel)


@dataclass(frozen=True, slots=True)
class PathsSectionModel:
    """Пути относительно корня проекта."""

    context_root: str = "context"
    rules: str | None = None


@dataclass(frozen=True, slots=True)
class RolloutSectionModel:
    """Фаза rollout (этап 9; опционально уже в project.yaml)."""

    phase: str = "internal_alpha"


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Корневой контракт project.yaml v1."""

    project_id: str
    runtime: RuntimeMode = RuntimeMode.AILIT
    paths: PathsSectionModel = field(default_factory=PathsSectionModel)
    agents: dict[str, AgentPreset] = field(default_factory=dict)
    workflows: dict[str, WorkflowRef] = field(default_factory=dict)
    context: ContextSectionModel = field(default_factory=ContextSectionModel)
    memory_hints: tuple[str, ...] = ()
    rollout: RolloutSectionModel = field(default_factory=RolloutSectionModel)
    extra: dict[str, Any] = field(default_factory=dict)


def _preset_from_mapping(agent_id: str, raw: Mapping[str, Any]) -> AgentPreset:
    extra_raw = raw.get("shortlist_extra_keywords") or raw.get("shortlist_extra") or []
    if not isinstance(extra_raw, list):
        msg = "shortlist_extra_keywords must be a list of strings"
        raise TypeError(msg)
    extras = frozenset(str(x) for x in extra_raw)
    temp = raw.get("temperature")
    mt = raw.get("max_turns")
    role_raw = raw.get("role")
    role = str(role_raw).strip().lower() if role_raw else None
    if role == "":
        role = None
    return AgentPreset(
        agent_id=agent_id,
        system_append=str(raw.get("system_append", "") or ""),
        system_prompt=str(raw["system_prompt"]) if raw.get("system_prompt") else None,
        temperature=float(temp) if temp is not None else None,
        max_turns=int(mt) if mt is not None else None,
        shortlist_extra=extras,
        role=role,
    )


def _workflow_ref_from_mapping(wid: str, raw: Mapping[str, Any]) -> WorkflowRef:
    path = raw.get("path")
    if not path:
        msg = f"workflow {wid!r} must contain 'path'"
        raise ValueError(msg)
    return WorkflowRef(workflow_id=wid, path=str(path))


def project_config_from_mapping(data: Mapping[str, Any]) -> ProjectConfig:
    """Разобрать dict (YAML) в ProjectConfig."""
    pid = data.get("project_id") or data.get("id")
    if not pid:
        msg = "project.yaml must contain project_id (or id)"
        raise ValueError(msg)
    runtime_raw = str(data.get("runtime", RuntimeMode.AILIT.value)).lower()
    try:
        runtime = RuntimeMode(runtime_raw)
    except ValueError as exc:
        msg = f"invalid runtime: {runtime_raw!r}"
        raise ValueError(msg) from exc

    paths_raw = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    paths = PathsSectionModel(
        context_root=str(paths_raw.get("context_root", "context")),
        rules=str(paths_raw["rules"]) if paths_raw.get("rules") else None,
    )

    agents: dict[str, AgentPreset] = {}
    agents_raw = data.get("agents")
    if isinstance(agents_raw, dict):
        for aid, body in agents_raw.items():
            if isinstance(body, dict):
                agents[str(aid)] = _preset_from_mapping(str(aid), body)

    workflows: dict[str, WorkflowRef] = {}
    wf_raw = data.get("workflows")
    if isinstance(wf_raw, dict):
        for wid, body in wf_raw.items():
            if isinstance(body, dict):
                workflows[str(wid)] = _workflow_ref_from_mapping(str(wid), body)

    ctx_raw = data.get("context") if isinstance(data.get("context"), dict) else {}
    globs_raw = ctx_raw.get("canonical_globs", ("context/**/*.md",))
    if isinstance(globs_raw, str):
        canonical_globs = (globs_raw,)
    elif isinstance(globs_raw, (list, tuple)):
        canonical_globs = tuple(str(g) for g in globs_raw)
    else:
        msg = "context.canonical_globs must be str, list[str], or tuple[str, ...]"
        raise TypeError(msg)
    kr_raw = ctx_raw.get("knowledge_refresh") if isinstance(ctx_raw.get("knowledge_refresh"), dict) else {}
    kr = KnowledgeRefreshModel(
        mode=str(kr_raw.get("mode", "filesystem")),
        max_files=int(kr_raw.get("max_files", 20)),
        max_chars_per_file=int(kr_raw.get("max_chars_per_file", 4000)),
        max_keywords=int(kr_raw.get("max_keywords", 40)),
    )
    context = ContextSectionModel(canonical_globs=canonical_globs, knowledge_refresh=kr)

    mem_raw = data.get("memory_hints", [])
    if isinstance(mem_raw, list):
        memory_hints = tuple(str(x) for x in mem_raw)
    else:
        msg = "memory_hints must be a list of strings"
        raise TypeError(msg)

    rollout_raw = data.get("rollout") if isinstance(data.get("rollout"), dict) else {}
    rollout = RolloutSectionModel(phase=str(rollout_raw.get("phase", "internal_alpha")))

    known_keys = {
        "project_id",
        "id",
        "runtime",
        "paths",
        "agents",
        "workflows",
        "context",
        "memory_hints",
        "rollout",
    }
    extra = {k: v for k, v in data.items() if k not in known_keys}
    return ProjectConfig(
        project_id=str(pid),
        runtime=runtime,
        paths=paths,
        agents=agents,
        workflows=workflows,
        context=context,
        memory_hints=memory_hints,
        rollout=rollout,
        extra=extra,
    )
