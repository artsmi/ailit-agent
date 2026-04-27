"""Исполнение workflow с эмиссией событий workflow_run_events_v1."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Any, TextIO

from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.protocol import ChatProvider
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.perm_tool_mode import normalize_perm_tool_mode
from agent_core.system_prompt_builder import (
    SystemPromptLayers,
    build_effective_system_messages,
)
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_core.tool_runtime.registry import ToolRegistry
from .graph import Workflow
from .hybrid import hybrid_event_payload
from .user_task_merge import merge_cli_task_into_first_user_message


def _write_file_changes_from_events(
    events: tuple[dict[str, Any], ...],
) -> list[dict[str, str]]:
    """Список created/updated по write_file из событий session loop."""
    items: list[dict[str, str]] = []
    for row in events:
        if row.get("event_type") != "tool.call_finished":
            continue
        if row.get("tool") not in (
            "write_file",
            "apply_patch",
        ) or row.get("ok") is not True:
            continue
        rp = row.get("relative_path")
        k = row.get("file_change_kind")
        if isinstance(rp, str) and isinstance(k, str):
            items.append({"relative_path": rp, "file_change_kind": k})
    return items


@dataclass(frozen=True, slots=True)
class WorkflowRunConfig:
    """Параметры прогона workflow."""

    model: str = "deepseek-chat"
    max_turns: int = 10_000
    dry_run: bool = False
    extra_system_messages: tuple[str, ...] = ()
    shortlist_keywords: frozenset[str] | None = None
    temperature: float = 0.0
    # Идентификатор прогона (артефакты ``.ailit/run/<run_id>/``).
    run_id: str | None = None
    # Текст CLI-задачи; только в первую исполняемую задачу.
    cli_task_body: str | None = None
    # Относительный путь к ``task.md`` для события ``run.started``.
    task_artifact_rel: str | None = None
    # Переопределяет SessionSettings.suppress_tools_after_write_file.
    suppress_tools_after_write_file: bool | None = None
    # perm-5: явный режим инструментов без LLM-классификатора в worker.
    perm_tool_mode: str = "edit"
    perm_classifier_bypass: bool = True


class WorkflowEngine:
    """Машинный движок: стадии и задачи → session loop."""

    def __init__(
        self,
        workflow: Workflow,
        provider: ChatProvider,
        registry: ToolRegistry,
    ) -> None:
        """Связать workflow с провайдером и инструментами."""
        self._workflow = workflow
        self._provider = provider
        self._registry = registry

    def _emit(
        self,
        sink: TextIO,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "v": 1,
            "contract": "workflow_run_events_v1",
            "event_type": event_type,
            **payload,
        }
        sink.write(json.dumps(row, ensure_ascii=False) + "\n")
        sink.flush()
        return row

    def iter_run_events(
        self,
        run_config: WorkflowRunConfig,
        *,
        sink: TextIO | None = None,
        diag_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Итерировать события исполнения (и дублировать в sink как JSONL)."""
        out = sink or sys.stdout
        yield self._emit(
            out,
            "workflow.loaded",
            {"workflow_id": self._workflow.workflow_id},
        )
        yield self._emit(
            out,
            "project.policy.ref",
            hybrid_event_payload(self._workflow),
        )
        if run_config.run_id is not None:
            yield self._emit(
                out,
                "run.started",
                {
                    "workflow_id": self._workflow.workflow_id,
                    "run_id": run_config.run_id,
                    "task_artifact": run_config.task_artifact_rel,
                },
            )
        cli_task_pending: str | None = (
            run_config.cli_task_body.strip()
            if run_config.cli_task_body and run_config.cli_task_body.strip()
            else None
        )
        settings_kw: dict[str, Any] = {
            "model": run_config.model,
            "max_turns": run_config.max_turns,
            "shortlist_keywords": run_config.shortlist_keywords,
            "temperature": run_config.temperature,
        }
        if run_config.suppress_tools_after_write_file is not None:
            settings_kw["suppress_tools_after_write_file"] = (
                run_config.suppress_tools_after_write_file
            )
        settings_kw["perm_mode_enabled"] = True
        ptm = normalize_perm_tool_mode(
            str(run_config.perm_tool_mode or "edit"),
        )
        settings_kw["perm_tool_mode"] = ptm
        settings_kw["perm_classifier_bypass"] = bool(
            run_config.perm_classifier_bypass,
        )
        settings_base = SessionSettings(**settings_kw)
        perm = PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        )
        runner = SessionRunner(
            self._provider,
            self._registry,
            permission_engine=perm,
        )
        approvals = ApprovalSession()

        for stage in self._workflow.stages:
            yield self._emit(
                out,
                "stage.entered",
                {
                    "workflow_id": self._workflow.workflow_id,
                    "stage_id": stage.stage_id,
                },
            )
            if stage.human_gate:
                yield self._emit(
                    out,
                    "human.gate.requested",
                    {
                        "workflow_id": self._workflow.workflow_id,
                        "stage_id": stage.stage_id,
                        "gate_id": stage.human_gate.gate_id,
                        "description": stage.human_gate.description,
                    },
                )
            for task in stage.tasks:
                raw_override = task.metadata.get("perm_tool_mode")
                if raw_override is not None and str(raw_override).strip():
                    eff_ptm = normalize_perm_tool_mode(str(raw_override))
                    settings = replace(settings_base, perm_tool_mode=eff_ptm)
                else:
                    settings = settings_base
                    eff_ptm = ptm
                yield self._emit(
                    out,
                    "task.started",
                    {
                        "workflow_id": self._workflow.workflow_id,
                        "stage_id": stage.stage_id,
                        "task_id": task.task_id,
                        "perm_tool_mode": eff_ptm,
                        "perm_classifier_bypass": bool(
                            run_config.perm_classifier_bypass,
                        ),
                    },
                )
                if run_config.dry_run:
                    yield self._emit(
                        out,
                        "task.skipped_dry_run",
                        {
                            "workflow_id": self._workflow.workflow_id,
                            "task_id": task.task_id,
                        },
                    )
                    continue
                layers = SystemPromptLayers(
                    default=(),
                    append=tuple(run_config.extra_system_messages),
                )
                messages = build_effective_system_messages(layers)
                user_text = task.user_text
                if cli_task_pending is not None:
                    user_text = merge_cli_task_into_first_user_message(
                        workflow_user_text=task.user_text,
                        cli_body=cli_task_pending,
                    )
                    cli_task_pending = None
                messages.extend(
                    [
                        ChatMessage(
                            role=MessageRole.SYSTEM,
                            content=task.system_prompt,
                        ),
                        ChatMessage(
                            role=MessageRole.USER,
                            content=user_text,
                        ),
                    ]
                )
                session_out = runner.run(
                    messages,
                    approvals,
                    settings,
                    diag_sink=diag_sink,
                )
                yield self._emit(
                    out,
                    "task.finished",
                    {
                        "workflow_id": self._workflow.workflow_id,
                        "stage_id": stage.stage_id,
                        "task_id": task.task_id,
                        "perm_tool_mode": eff_ptm,
                        "session_state": session_out.state.value,
                        "reason": session_out.reason,
                        "file_changes": _write_file_changes_from_events(
                            session_out.events,
                        ),
                    },
                )
            yield self._emit(
                out,
                "stage.exited",
                {
                    "workflow_id": self._workflow.workflow_id,
                    "stage_id": stage.stage_id,
                },
            )

        yield self._emit(
            out,
            "workflow.finished",
            {"workflow_id": self._workflow.workflow_id},
        )
