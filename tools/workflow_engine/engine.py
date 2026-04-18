"""Исполнение workflow с эмиссией событий workflow_run_events_v1."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, TextIO

from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.protocol import ChatProvider
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.registry import ToolRegistry
from .graph import Workflow
from .hybrid import hybrid_event_payload


@dataclass(frozen=True, slots=True)
class WorkflowRunConfig:
    """Параметры прогона workflow."""

    model: str = "deepseek-chat"
    max_turns: int = 6
    dry_run: bool = False
    extra_system_messages: tuple[str, ...] = ()
    shortlist_keywords: frozenset[str] | None = None
    temperature: float = 0.0


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
        settings = SessionSettings(
            model=run_config.model,
            max_turns=run_config.max_turns,
            shortlist_keywords=run_config.shortlist_keywords,
            temperature=run_config.temperature,
        )
        runner = SessionRunner(self._provider, self._registry)
        approvals = ApprovalSession()

        for stage in self._workflow.stages:
            yield self._emit(
                out,
                "stage.entered",
                {"workflow_id": self._workflow.workflow_id, "stage_id": stage.stage_id},
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
                yield self._emit(
                    out,
                    "task.started",
                    {
                        "workflow_id": self._workflow.workflow_id,
                        "stage_id": stage.stage_id,
                        "task_id": task.task_id,
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
                messages: list[ChatMessage] = [
                    ChatMessage(role=MessageRole.SYSTEM, content=body)
                    for body in run_config.extra_system_messages
                ]
                messages.extend(
                    [
                        ChatMessage(role=MessageRole.SYSTEM, content=task.system_prompt),
                        ChatMessage(role=MessageRole.USER, content=task.user_text),
                    ]
                )
                session_out = runner.run(messages, approvals, settings)
                yield self._emit(
                    out,
                    "task.finished",
                    {
                        "workflow_id": self._workflow.workflow_id,
                        "stage_id": stage.stage_id,
                        "task_id": task.task_id,
                        "session_state": session_out.state.value,
                        "reason": session_out.reason,
                    },
                )
            yield self._emit(
                out,
                "stage.exited",
                {"workflow_id": self._workflow.workflow_id, "stage_id": stage.stage_id},
            )

        yield self._emit(
            out,
            "workflow.finished",
            {"workflow_id": self._workflow.workflow_id},
        )
