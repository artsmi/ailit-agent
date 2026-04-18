"""Загрузка workflow из YAML (v1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .graph import HumanGate, Stage, Task, Transition, Workflow


def _task_from_dict(data: Mapping[str, Any]) -> Task:
    return Task(
        task_id=str(data["id"]),
        system_prompt=str(data.get("system_prompt", "")),
        user_text=str(data.get("user_text", "")),
        metadata=dict(data.get("metadata", {})),
    )


def _stage_from_dict(data: Mapping[str, Any]) -> Stage:
    hg_raw = data.get("human_gate")
    human_gate: HumanGate | None = None
    if isinstance(hg_raw, dict):
        human_gate = HumanGate(
            gate_id=str(hg_raw.get("id", "gate")),
            description=str(hg_raw.get("description", "")),
        )
    tasks_raw = data.get("tasks", [])
    if not isinstance(tasks_raw, list):
        msg = "stage.tasks must be a list"
        raise ValueError(msg)
    tasks = tuple(_task_from_dict(t) for t in tasks_raw if isinstance(t, dict))
    return Stage(
        stage_id=str(data["id"]),
        tasks=tasks,
        human_gate=human_gate,
        metadata=dict(data.get("metadata", {})),
    )


def _transitions_from_list(raw: Any) -> tuple[Transition, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[Transition] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            Transition(
                from_stage=str(item["from"]),
                to_stage=str(item["to"]),
                condition=str(item["condition"]) if item.get("condition") else None,
            )
        )
    return tuple(out)


def load_workflow_from_mapping(data: Mapping[str, Any]) -> Workflow:
    """Разобрать dict в Workflow."""
    wid = str(data.get("workflow_id", data.get("id", "unnamed")))
    hybrid = bool(data.get("hybrid", False))
    policy_ref = data.get("policy_ref")
    pref = str(policy_ref) if policy_ref else None
    stages_raw = data.get("stages", [])
    if not isinstance(stages_raw, list) or not stages_raw:
        msg = "workflow must contain non-empty stages list"
        raise ValueError(msg)
    stages = tuple(_stage_from_dict(s) for s in stages_raw if isinstance(s, dict))
    transitions = _transitions_from_list(data.get("transitions"))
    return Workflow(
        workflow_id=wid,
        stages=stages,
        hybrid=hybrid,
        policy_ref=pref,
        transitions=transitions,
        metadata=dict(data.get("metadata", {})),
    )


def load_workflow_from_path(path: Path) -> Workflow:
    """Загрузить workflow из YAML файла."""
    raw_text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text)
    if not isinstance(data, dict):
        msg = "workflow YAML root must be a mapping"
        raise ValueError(msg)
    return load_workflow_from_mapping(data)
