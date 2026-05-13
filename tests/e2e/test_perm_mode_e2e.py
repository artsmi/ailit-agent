"""E2E perm-5: read, read_plan (docs), загрузка perm_tool_mode из YAML."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from ailit_base.capabilities import Capability
from ailit_base.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
    StreamDone,
    StreamEvent,
    ToolCallNormalized,
)
from ailit_base.providers.protocol import ChatProvider
from agent_work.session.loop import SessionRunner, SessionSettings
from agent_work.tool_runtime.approval import ApprovalSession
from agent_work.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_work.tool_runtime.bash_tools import bash_tool_registry
from agent_work.tool_runtime.registry import default_builtin_registry
from workflow_engine.loader import load_workflow_from_mapping


class _ScriptedProvider(ChatProvider):
    """Минимальная очередь ответов для perm e2e."""

    def __init__(self, responses: list[NormalizedChatResponse]) -> None:
        self._responses = list(responses)

    @property
    def provider_id(self) -> str:
        return "scripted_perm_e2e"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT, Capability.TOOLS})

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        del request
        if not self._responses:
            msg = "scripted queue empty"
            raise RuntimeError(msg)
        return self._responses.pop(0)

    def stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        yield StreamDone(response=self.complete(request))


@pytest.mark.e2e
def test_perm_read_denies_write_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В read модель не получает успешного write_file при попытке вызова."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(bash_tool_registry())
    tc = ToolCallNormalized(
        call_id="w1",
        tool_name="write_file",
        arguments_json='{"path":"x.md","content":"nope"}',
        stream_index=0,
        provider_name="scripted",
    )
    r1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r2 = NormalizedChatResponse(
        text_parts=("only read",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        _ScriptedProvider([r1, r2]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        ),
    )
    out = runner.run(
        [ChatMessage(role=MessageRole.USER, content="покажи точки входа")],
        ApprovalSession(),
        SessionSettings(
            model="m",
            perm_mode_enabled=True,
            perm_tool_mode="read",
            perm_classifier_bypass=True,
        ),
    )
    finished_writes = [
        e
        for e in out.events
        if e.get("event_type") == "tool.call_finished"
        and e.get("tool") == "write_file"
    ]
    assert finished_writes
    assert all(
        row.get("ok") is not True for row in finished_writes
    ), finished_writes


@pytest.mark.e2e
def test_read_plan_write_docs_without_successful_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_plan: docs/plan.md пишется; успешного run_shell нет."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(bash_tool_registry())
    sh = ToolCallNormalized(
        call_id="s1",
        tool_name="run_shell",
        arguments_json='{"command":"git status"}',
        stream_index=0,
        provider_name="scripted",
    )
    wf = ToolCallNormalized(
        call_id="w1",
        tool_name="write_file",
        arguments_json='{"path":"docs/plan.md","content":"# plan"}',
        stream_index=0,
        provider_name="scripted",
    )
    r1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(sh,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r2 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(wf,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r3 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        _ScriptedProvider([r1, r2, r3]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        ),
    )
    user_msg = "сгенерируй docs/plan.md"
    out = runner.run(
        [ChatMessage(role=MessageRole.USER, content=user_msg)],
        ApprovalSession(),
        SessionSettings(
            model="m",
            perm_mode_enabled=True,
            perm_tool_mode="read_plan",
            perm_classifier_bypass=True,
        ),
    )
    shells = [
        e
        for e in out.events
        if e.get("event_type") == "tool.call_finished"
        and e.get("tool") == "run_shell"
    ]
    assert shells
    assert all(s.get("ok") is not True for s in shells), shells
    writes_ok = [
        e
        for e in out.events
        if e.get("event_type") == "tool.call_finished"
        and e.get("tool") == "write_file"
        and e.get("ok") is True
    ]
    assert writes_ok, out.events


@pytest.mark.e2e
def test_workflow_task_yaml_perm_tool_mode_in_metadata() -> None:
    """YAML: ``perm_tool_mode`` задачи в metadata."""
    wf = load_workflow_from_mapping(
        {
            "workflow_id": "w",
            "stages": [
                {
                    "id": "s1",
                    "tasks": [
                        {
                            "id": "t1",
                            "perm_tool_mode": "read",
                            "user_text": "hi",
                        },
                    ],
                },
            ],
        },
    )
    meta = wf.stages[0].tasks[0].metadata
    assert meta.get("perm_tool_mode") == "read"
