"""Compatibility adapter: project runtime + JSONL + status.md."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, TextIO

from agent_core.config_loader import load_test_local_yaml
from agent_core.providers.factory import ProviderFactory, ProviderKind
from agent_core.providers.mock_provider import MockProvider
from agent_core.providers.protocol import ChatProvider
from agent_core.tool_runtime.registry import ToolRegistry, default_builtin_registry
from project_layer.bootstrap import compute_workflow_augmentation
from project_layer.loader import default_project_yaml_path, load_project
from project_layer.models import RuntimeMode
from project_layer.registry import ProjectRegistries
from workflow_engine.engine import WorkflowEngine, WorkflowRunConfig
from workflow_engine.loader import load_workflow_from_path


def _repo_config_for_providers(repo_root: Path) -> dict[str, Any]:
    p = repo_root / "config" / "test.local.yaml"
    return dict(load_test_local_yaml(p)) if p.is_file() else {}


def _make_provider(provider: str, repo_root: Path) -> ChatProvider:
    cfg = _repo_config_for_providers(repo_root)
    if provider == "mock":
        return MockProvider()  # type: ignore[return-value]
    if provider == "deepseek":
        return ProviderFactory.create(ProviderKind.DEEPSEEK, config=cfg)  # type: ignore[return-value]
    msg = f"unknown provider: {provider!r}"
    raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AdapterRunResult:
    """Итог прогона через adapter."""

    runtime: RuntimeMode
    status_path: Path
    event_lines: int
    legacy_skipped: bool


def _emit(sink: TextIO, payload: dict[str, Any]) -> None:
    sink.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sink.flush()


def _write_status(project_root: Path, body: str) -> Path:
    out_dir = project_root / ".ailit"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "status.md"
    path.write_text(body, encoding="utf-8")
    return path


def run_compat_workflow(
    *,
    project_root: Path,
    workflow_ref: str,
    provider: str,
    model: str,
    max_turns: int,
    dry_run: bool,
    sink: TextIO,
    repo_root: Path | None = None,
) -> AdapterRunResult:
    """Исполнить workflow с учётом runtime из project.yaml и записать status.md."""
    root = project_root.resolve()
    cfg_path = default_project_yaml_path(root)
    loaded = load_project(cfg_path)
    repo = repo_root.resolve() if repo_root else Path(__file__).resolve().parents[2]

    lines = [
        "# ailit compat status",
        "",
        f"- project_id: `{loaded.config.project_id}`",
        f"- runtime: `{loaded.config.runtime.value}`",
        f"- workflow_ref: `{workflow_ref}`",
        "",
    ]

    if loaded.config.runtime is RuntimeMode.LEGACY:
        _emit(
            sink,
            {
                "v": 1,
                "contract": "workflow_run_events_v1",
                "event_type": "adapter.legacy_skip",
                "reason": "project.runtime=legacy",
                "project_id": loaded.config.project_id,
            },
        )
        lines.append("Режим **legacy**: исполнение на стороне ailit workflow engine отключено.")
        lines.append("Подключите внешний pipeline (ai-multi-agents) или переключите `runtime: ailit`.")
        path = _write_status(root, "\n".join(lines) + "\n")
        return AdapterRunResult(
            runtime=loaded.config.runtime,
            status_path=path,
            event_lines=1,
            legacy_skipped=True,
        )

    reg = ProjectRegistries(loaded)
    wf_path = reg.workflow_path(workflow_ref)
    wf = load_workflow_from_path(wf_path)
    aug = compute_workflow_augmentation(loaded)
    prov = _make_provider(provider, repo)
    registry: ToolRegistry = default_builtin_registry()
    eng = WorkflowEngine(wf, prov, registry)
    run_cfg = WorkflowRunConfig(
        model=model,
        dry_run=dry_run,
        max_turns=max_turns,
        extra_system_messages=aug.extra_system_messages,
        shortlist_keywords=aug.shortlist_keywords,
        temperature=aug.temperature,
    )
    buf = StringIO()
    events = list(eng.iter_run_events(run_cfg, sink=buf))
    text = buf.getvalue()
    sink.write(text)
    sink.flush()
    lines.append("Режим **ailit**: прогон workflow engine завершён.")
    lines.append(f"- событий: `{len(events)}`")
    lines.append("")
    lines.append("## Последние события (срез)")
    for row in events[-8:]:
        lines.append(f"- `{row.get('event_type')}`")
    path = _write_status(root, "\n".join(lines) + "\n")
    return AdapterRunResult(
        runtime=loaded.config.runtime,
        status_path=path,
        event_lines=len(text.splitlines()),
        legacy_skipped=False,
    )


def read_status(project_root: Path) -> str | None:
    """Прочитать `.ailit/status.md` если есть."""
    p = project_root / ".ailit" / "status.md"
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")
