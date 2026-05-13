"""Workflow engine: загрузка YAML, dry-run, hybrid vs native."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from ailit_base.capabilities import Capability
from ailit_base.models import FinishReason, NormalizedChatResponse, NormalizedUsage
from agent_work.tool_runtime.registry import default_builtin_registry
from ailit_base.models import ChatRequest, MessageRole

from workflow_engine.engine import WorkflowEngine, WorkflowRunConfig
from workflow_engine.loader import load_workflow_from_mapping, load_workflow_from_path


class OneShotProvider:
    """Один ответ без tool calls."""

    @property
    def provider_id(self) -> str:
        return "oneshot"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT})

    def complete(self, request: object) -> NormalizedChatResponse:
        return NormalizedChatResponse(
            text_parts=("ok",),
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            usage=NormalizedUsage(1, 1, 2, usage_missing=False),
            provider_metadata={},
        )

    def stream(self, request: object):
        from ailit_base.models import StreamDone

        yield StreamDone(response=self.complete(request))


def test_load_minimal_example() -> None:
    """YAML из examples загружается."""
    root = Path(__file__).resolve().parents[1]
    wf_path = root / "examples" / "workflows" / "minimal.yaml"
    wf = load_workflow_from_path(wf_path)
    assert wf.workflow_id == "minimal_example"
    assert wf.hybrid is True


def test_dry_run_emits_linear_events() -> None:
    """Dry-run не вызывает session, но эмитит стадии и задачи."""
    data = {
        "workflow_id": "w",
        "stages": [
            {
                "id": "s1",
                "tasks": [{"id": "t1", "system_prompt": "a", "user_text": "b"}],
            }
        ],
    }
    wf = load_workflow_from_mapping(data)
    eng = WorkflowEngine(wf, OneShotProvider(), default_builtin_registry())
    events = list(eng.iter_run_events(WorkflowRunConfig(dry_run=True), sink=StringIO()))
    types = [e["event_type"] for e in events]
    assert "workflow.loaded" in types
    assert "task.skipped_dry_run" in types
    assert "workflow.finished" in types


class CaptureUserProvider(OneShotProvider):
    """Фиксирует последнее user-сообщение перед ответом."""

    def __init__(self) -> None:
        """Инициализировать список захватов."""
        super().__init__()
        self.user_contents: list[str] = []

    def complete(self, request: object) -> NormalizedChatResponse:
        """Запомнить user-текст и вернуть ответ как у родителя."""
        assert isinstance(request, ChatRequest)
        users = [m.content for m in request.messages if m.role is MessageRole.USER]
        if users:
            self.user_contents.append(users[-1])
        return super().complete(request)


def test_cli_task_applied_only_to_first_executed_task() -> None:
    """``cli_task_body`` подмешивается только в первую не dry-run задачу."""
    data = {
        "workflow_id": "w2",
        "stages": [
            {
                "id": "s1",
                "tasks": [
                    {"id": "t1", "system_prompt": "s", "user_text": "u1"},
                    {"id": "t2", "system_prompt": "s", "user_text": "u2"},
                ],
            }
        ],
    }
    wf = load_workflow_from_mapping(data)
    cap = CaptureUserProvider()
    eng = WorkflowEngine(wf, cap, default_builtin_registry())
    list(
        eng.iter_run_events(
            WorkflowRunConfig(
                dry_run=False,
                cli_task_body="CLI",
                run_id="abc",
                task_artifact_rel=".ailit/run/abc/task.md",
            ),
            sink=StringIO(),
        ),
    )
    assert len(cap.user_contents) == 2
    assert cap.user_contents[0].startswith("CLI")
    assert "u1" in cap.user_contents[0]
    assert cap.user_contents[1] == "u2"


def test_run_started_event_when_run_id_set() -> None:
    """Событие ``run.started`` при переданном ``run_id``."""
    data = {
        "workflow_id": "wr",
        "stages": [
            {"id": "s", "tasks": [{"id": "t", "system_prompt": "x", "user_text": "y"}]},
        ],
    }
    wf = load_workflow_from_mapping(data)
    eng = WorkflowEngine(wf, OneShotProvider(), default_builtin_registry())
    sink = StringIO()
    list(
        eng.iter_run_events(
            WorkflowRunConfig(dry_run=True, run_id="r1", task_artifact_rel=".ailit/run/r1/task.md"),
            sink=sink,
        ),
    )
    lines = [json.loads(l) for l in sink.getvalue().strip().splitlines() if l]
    started = [x for x in lines if x["event_type"] == "run.started"]
    assert len(started) == 1
    assert started[0]["run_id"] == "r1"
    assert started[0]["task_artifact"] == ".ailit/run/r1/task.md"


def test_hybrid_vs_native_policy_event() -> None:
    """Hybrid добавляет policy_ref в payload события."""
    base = {
        "workflow_id": "cmp",
        "stages": [
            {"id": "s", "tasks": [{"id": "t", "system_prompt": "x", "user_text": "y"}]},
        ],
    }
    native = load_workflow_from_mapping({**base, "hybrid": False, "policy_ref": None})
    hybrid = load_workflow_from_mapping({**base, "hybrid": True, "policy_ref": "rules/x.md"})
    sink_native = StringIO()
    list(WorkflowEngine(native, OneShotProvider(), default_builtin_registry()).iter_run_events(WorkflowRunConfig(dry_run=True), sink=sink_native))
    sink_h = StringIO()
    list(WorkflowEngine(hybrid, OneShotProvider(), default_builtin_registry()).iter_run_events(WorkflowRunConfig(dry_run=True), sink=sink_h))
    lines_n = [json.loads(l) for l in sink_native.getvalue().strip().splitlines() if l]
    lines_h = [json.loads(l) for l in sink_h.getvalue().strip().splitlines() if l]
    pol_n = next(x for x in lines_n if x["event_type"] == "project.policy.ref")
    pol_h = next(x for x in lines_h if x["event_type"] == "project.policy.ref")
    assert pol_n.get("hybrid") is False
    assert pol_h.get("hybrid") is True
    assert pol_h.get("policy_ref") == "rules/x.md"
