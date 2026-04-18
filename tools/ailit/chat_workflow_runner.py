"""Запуск workflow из UI чата (тот же контракт, что и `ailit agent run`)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

from agent_core.config_loader import load_test_local_yaml
from agent_core.providers.factory import ProviderFactory, ProviderKind
from agent_core.providers.mock_provider import MockProvider
from agent_core.tool_runtime.registry import default_builtin_registry
from project_layer.bootstrap import compute_workflow_augmentation
from project_layer.loader import default_project_yaml_path, load_project
from project_layer.registry import ProjectRegistries
from workflow_engine.engine import WorkflowEngine, WorkflowRunConfig
from workflow_engine.loader import load_workflow_from_path


def resolve_workflow_path(project_root: Path, workflow_ref: str) -> Path:
    """Путь к YAML: из project.yaml или относительный путь от корня проекта."""
    root = project_root.resolve()
    ref = workflow_ref.strip()
    cfg_path = default_project_yaml_path(root)
    if cfg_path.is_file():
        loaded = load_project(cfg_path)
        return ProjectRegistries(loaded).workflow_path(ref)
    if ref.endswith((".yaml", ".yml")):
        p = (root / ref).resolve()
        if p.is_file():
            return p
        msg = f"Файл workflow не найден: {p}"
        raise FileNotFoundError(msg)
    msg = "Без project.yaml укажите путь к *.yaml относительно корня проекта."
    raise ValueError(msg)


def run_workflow_capture_jsonl(
    *,
    repo_root: Path,
    project_root: Path,
    workflow_ref: str,
    provider: str,
    model: str,
    max_turns: int,
    dry_run: bool,
) -> str:
    """Исполнить workflow и вернуть JSONL (как stdout у CLI)."""
    wf_path = resolve_workflow_path(project_root, workflow_ref)
    aug_extra: tuple[str, ...] = ()
    aug_keys: frozenset[str] | None = None
    aug_temp = 0.0
    cfg_path = default_project_yaml_path(project_root.resolve())
    if cfg_path.is_file():
        loaded = load_project(cfg_path)
        aug = compute_workflow_augmentation(loaded)
        aug_extra = aug.extra_system_messages
        aug_keys = aug.shortlist_keywords
        aug_temp = aug.temperature

    wf = load_workflow_from_path(wf_path)
    cfg = dict(load_test_local_yaml(repo_root / "config" / "test.local.yaml"))
    prov: Any
    if provider == "mock":
        prov = MockProvider()
    elif provider == "deepseek":
        prov = ProviderFactory.create(ProviderKind.DEEPSEEK, config=cfg)
    else:
        msg = f"unknown provider: {provider!r}"
        raise ValueError(msg)

    eng = WorkflowEngine(wf, prov, default_builtin_registry())  # type: ignore[arg-type]
    run_cfg = WorkflowRunConfig(
        model=model,
        dry_run=dry_run,
        max_turns=max_turns,
        extra_system_messages=aug_extra,
        shortlist_keywords=aug_keys,
        temperature=aug_temp,
    )
    buf = StringIO()
    list(eng.iter_run_events(run_cfg, sink=buf))
    return buf.getvalue()
