"""Session loop: scripted provider, approval resume, budget."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx

from ailit_base.capabilities import Capability
from ailit_base.models import (
    ChatMessage,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
    StreamDone,
    StreamEvent,
    ToolCallNormalized,
)
from agent_work.session.budget import BudgetGovernance
from agent_work.session.loop import SessionRunner, SessionSettings
from agent_work.session.state import SessionState
from agent_work.session.stream_reducer import StreamReducer
from agent_work.tool_runtime.approval import ApprovalSession
from agent_work.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_work.tool_runtime.bash_tools import bash_tool_registry
from agent_work.tool_runtime.registry import default_builtin_registry
from agent_memory.kb_tools import KbToolsConfig, build_kb_tool_registry
from agent_memory.pag_indexer import index_project_to_default_store
from agent_memory.sqlite_pag import SqlitePagStore


class ScriptedProvider:
    """Провайдер с заранее заданной очередью ответов."""

    def __init__(
        self,
        responses: list[NormalizedChatResponse],
        *,
        stream: bool = False,
    ) -> None:
        self._responses = list(responses)
        self._stream = stream

    @property
    def provider_id(self) -> str:
        return "scripted"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT, Capability.TOOLS})

    def complete(self, request: object) -> NormalizedChatResponse:
        if not self._responses:
            msg = "scripted provider queue empty"
            raise RuntimeError(msg)
        return self._responses.pop(0)

    def stream(self, request: object) -> Iterator[StreamEvent]:
        if not self._stream:
            yield StreamDone(response=self.complete(request))
            return
        r = self.complete(request)
        yield StreamDone(response=r)


class CapturingScriptedProvider(ScriptedProvider):
    """Scripted provider that captures the last ChatRequest."""

    def __init__(
        self,
        responses: list[NormalizedChatResponse],
        *,
        stream: bool = False,
    ) -> None:
        super().__init__(responses, stream=stream)
        self.last_request: object | None = None

    def complete(self, request: object) -> NormalizedChatResponse:
        self.last_request = request
        return super().complete(request)

    def stream(self, request: object) -> Iterator[StreamEvent]:
        self.last_request = request
        yield from super().stream(request)


class ReadTimeoutOnceProvider(ScriptedProvider):
    """Stream provider that times out once before any delta."""

    def __init__(self, response: NormalizedChatResponse) -> None:
        super().__init__([response], stream=True)
        self.stream_calls: int = 0

    def stream(self, request: object) -> Iterator[StreamEvent]:
        self.stream_calls += 1
        if self.stream_calls == 1:
            raise httpx.ReadTimeout("The read operation timed out")
        yield from super().stream(request)


def test_loop_injects_pag_slice_when_available(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """PAG-first: inject a system message with PAG slice + emit telemetry."""
    root = Path(str(tmp_path)).resolve()
    monkeypatch.setenv("AILIT_WORK_ROOT", str(root))
    db_path = root / "pag.sqlite3"
    monkeypatch.setenv("AILIT_PAG", "1")
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db_path))
    # Create a tiny project and index it into PAG.
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "cli.py").write_text(
        "def main() -> int:\n    return 0\n",
        encoding="utf-8",
    )
    ns = index_project_to_default_store(
        project_root=root,
        db_path=db_path,
        full=True,
    )
    assert ns

    r1 = NormalizedChatResponse(
        text_parts=("ok",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    prov = CapturingScriptedProvider([r1])
    runner = SessionRunner(prov, default_builtin_registry())
    messages = [ChatMessage(role=MessageRole.USER, content="Где entrypoint?")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    # Ensure PAG slice was injected into the request context.
    req = prov.last_request
    assert req is not None
    ctx = getattr(req, "messages", None)
    assert ctx is not None
    sys_msgs = [
        m
        for m in ctx
        if getattr(m, "role", None) is MessageRole.SYSTEM
    ]
    assert any("PAG slice" in (m.content or "") for m in sys_msgs)
    # Telemetry: requested/responded and used (or rejected).
    types = [e.get("event_type") for e in out.events]
    assert "agent_memory.requested" in types
    assert "agent_memory.responded" in types
    assert "agent_work.pag_slice_used" in types


def test_session_retries_read_timeout_once_before_stream_delta() -> None:
    """ReadTimeout before stream output is retried once and then succeeds."""
    r1 = NormalizedChatResponse(
        text_parts=("ok",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    prov = ReadTimeoutOnceProvider(r1)
    runner = SessionRunner(prov, default_builtin_registry())
    out = runner.run(
        [ChatMessage(MessageRole.USER, "hello")],
        ApprovalSession(),
        SessionSettings(model="m", use_stream=True, max_turns=1),
    )
    assert out.state is SessionState.FINISHED
    assert prov.stream_calls == 2
    retry_events = [
        e for e in out.events if e.get("event_type") == "model.retry"
    ]
    assert len(retry_events) == 1
    assert retry_events[0]["error_class"] == "timeout"


def test_loop_pag_sync_after_write_file(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """After write_file, runtime sync updates PAG for the written path."""
    root = Path(str(tmp_path)).resolve()
    monkeypatch.setenv("AILIT_WORK_ROOT", str(root))
    db_path = root / "pag.sqlite3"
    monkeypatch.setenv("AILIT_PAG", "1")
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db_path))
    monkeypatch.setenv("AILIT_PAG_SYNC_ON_WRITE", "1")
    # Seed PAG with A node for the project.
    ns = index_project_to_default_store(
        project_root=root,
        db_path=db_path,
        full=True,
    )
    assert ns

    tc = ToolCallNormalized(
        call_id="w1",
        tool_name="write_file",
        arguments_json='{"path":"new.txt","content":"hi"}',
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
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1, r2]),
        default_builtin_registry(),
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        ),
    )
    messages = [ChatMessage(role=MessageRole.USER, content="write")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    store = SqlitePagStore(db_path)
    b = store.fetch_node(namespace=ns, node_id="B:new.txt")
    assert b is not None
    types = [e.get("event_type") for e in out.events]
    assert "agent_memory.synced_changes" in types


def test_loop_two_write_file_one_user_turn(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Два write_file подряд в одном ``runner.run()`` без legacy-suppress."""
    monkeypatch.delenv("AILIT_SUPPRESS_TOOLS_AFTER_WRITE", raising=False)
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc1 = ToolCallNormalized(
        call_id="w1",
        tool_name="write_file",
        arguments_json='{"path":"a.txt","content":"1"}',
        stream_index=0,
        provider_name="scripted",
    )
    tc2 = ToolCallNormalized(
        call_id="w2",
        tool_name="write_file",
        arguments_json='{"path":"b.txt","content":"2"}',
        stream_index=0,
        provider_name="scripted",
    )
    r1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc1,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r2 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc2,),
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
        ScriptedProvider([r1, r2, r3]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        ),
    )
    messages = [ChatMessage(role=MessageRole.USER, content="write two")]
    out = runner.run(
        messages,
        ApprovalSession(),
        SessionSettings(model="m"),
    )
    assert out.state is SessionState.FINISHED
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "1"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "2"
    assert messages[-1].role is MessageRole.ASSISTANT
    assert "done" in (messages[-1].content or "")


def test_loop_tool_then_text(tmp_path: object, monkeypatch: object) -> None:
    """Один tool round (echo) затем финальный текст."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc = ToolCallNormalized(
        call_id="t1",
        tool_name="echo",
        arguments_json='{"message":"hi"}',
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
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(ScriptedProvider([r1, r2]), reg)
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(
        messages,
        ApprovalSession(),
        SessionSettings(model="m"),
    )
    assert out.state is SessionState.FINISHED
    assert messages[-1].role is MessageRole.ASSISTANT
    assert "done" in messages[-1].content


def test_loop_waiting_approval_resume(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """WRITE tool → approval → продолжение."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc = ToolCallNormalized(
        call_id="w1",
        tool_name="write_file",
        arguments_json='{"path":"a.txt","content":"z"}',
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
        text_parts=("ok",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    prov = ScriptedProvider([r1, r2])
    runner = SessionRunner(prov, reg)
    messages = [ChatMessage(role=MessageRole.USER, content="write")]
    approvals = ApprovalSession()
    out1 = runner.run(messages, approvals, SessionSettings(model="m"))
    assert out1.state is SessionState.WAITING_APPROVAL
    approvals.approve("w1")
    out2 = runner.run(messages, approvals, SessionSettings(model="m"))
    assert out2.state is SessionState.FINISHED


def test_loop_turn_cap_text_only_finalize(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Исчерпание max_turns → FINISHED с text-only резюме, не ERROR."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc1 = ToolCallNormalized(
        call_id="t1",
        tool_name="echo",
        arguments_json='{"message":"hi"}',
        stream_index=0,
        provider_name="scripted",
    )
    tc2 = ToolCallNormalized(
        call_id="t2",
        tool_name="echo",
        arguments_json='{"message":"hi2"}',
        stream_index=0,
        provider_name="scripted",
    )
    r_tool1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc1,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_tool2 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc2,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_final = NormalizedChatResponse(
        text_parts=("cap summary done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(ScriptedProvider([r_tool1, r_tool2, r_final]), reg)
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(
        messages,
        ApprovalSession(),
        SessionSettings(model="m", max_turns=2),
    )
    assert out.state is SessionState.FINISHED
    assert messages[-1].role is MessageRole.ASSISTANT
    assert "cap summary done" in messages[-1].content


def test_loop_agent_steps_cap_finalize_text_only(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """agent_steps_cap: после N tool-turn → финализация text-only."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc1 = ToolCallNormalized(
        call_id="t1",
        tool_name="echo",
        arguments_json='{"message":"hi"}',
        stream_index=0,
        provider_name="scripted",
    )
    r_tool1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc1,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_final = NormalizedChatResponse(
        text_parts=("final",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(ScriptedProvider([r_tool1, r_final]), reg)
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(
        messages,
        ApprovalSession(),
        SessionSettings(model="m", agent_steps_cap=1, max_turns=50),
    )
    assert out.state is SessionState.FINISHED
    assert "final" in (messages[-1].content or "")


def test_loop_doom_loop_finalize_text_only(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Повтор одного и того же tool_calls → session.doom_loop и финализация."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry()
    tc = ToolCallNormalized(
        call_id="t1",
        tool_name="echo",
        arguments_json='{"message":"hi"}',
        stream_index=0,
        provider_name="scripted",
    )
    r_tool = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_tool2 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_tool3 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_final = NormalizedChatResponse(
        text_parts=("final",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r_tool, r_tool2, r_tool3, r_final]),
        reg,
    )
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert any(e.get("event_type") == "session.doom_loop" for e in out.events)


def test_loop_run_shell_guardrail_injects_timeout(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """run_shell без timeout + "длинная" команда → inject timeout_ms."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(bash_tool_registry())
    tc = ToolCallNormalized(
        call_id="s1",
        tool_name="run_shell",
        arguments_json='{"command":"make -j4"}',
        stream_index=0,
        provider_name="scripted",
    )
    r_tool = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_final = NormalizedChatResponse(
        text_parts=("final",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r_tool, r_final]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        ),
    )
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert any(
        e.get("event_type") == "run_shell.guardrail" for e in out.events
    )
    started = next(
        e for e in out.events if e.get("event_type") == "tool.call_started"
    )
    assert "\"timeout_ms\"" in str(started.get("arguments_json") or "")


def test_loop_auto_kb_search_emits_memory_access(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Если KB tools включены, loop делает авто kb_search."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    kb_cfg = KbToolsConfig(
        enabled=True,
        db_path=(tmp_path / "kb.sqlite3"),
        namespace="t",
    )
    reg = default_builtin_registry().merge(build_kb_tool_registry(kb_cfg))
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    messages = [
        ChatMessage(role=MessageRole.USER, content="remember this repo"),
    ]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert any(e.get("event_type") == "memory.access" for e in out.events)


def test_loop_auto_kb_search_rate_limited_emits_event(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """AILIT_AUTO_KB_SEARCH_CAP=1: fallback search → rate limited."""
    import subprocess
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "unit@example.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "unit"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "checkout", "-b", "develop"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "new_feature"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    monkeypatch.setenv("AILIT_WORK_ROOT", str(repo))
    monkeypatch.setenv("AILIT_AUTO_KB_SEARCH_CAP", "1")

    kb_cfg = KbToolsConfig(
        enabled=True,
        db_path=(tmp_path / "kb.sqlite3"),
        namespace="t",
    )
    reg = default_builtin_registry().merge(build_kb_tool_registry(kb_cfg))
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1, r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    assert any(
        e.get("event_type") == "memory.auto_kb.rate_limited"
        and e.get("tool") == "kb_search"
        and e.get("reason") == "auto_kb_search_default_fallback"
        for e in runner.run(
            [ChatMessage(role=MessageRole.USER, content="q1")],
            ApprovalSession(),
            SessionSettings(model="m"),
        ).events
    )


def test_loop_auto_kb_write_fact_emits_memory_access(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """При наличии kb_write_fact loop пишет repo-факт автоматически."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(
                enabled=True,
                db_path=(tmp_path / "kb.sqlite3"),
                namespace="t",
            ),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert any(
        e.get("event_type") == "memory.access"
        and e.get("tool") == "kb_write_fact"
        for e in out.events
    )


def test_loop_auto_kb_write_tree_fact_emits_memory_access(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Auto repo tree write: list_dir + kb_write_fact (root entries)."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(
                enabled=True,
                db_path=(tmp_path / "kb.sqlite3"),
                namespace="t",
            ),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert any(
        e.get("event_type") == "memory.access"
        and e.get("tool") == "kb_write_fact"
        for e in out.events
    )


def test_loop_auto_kb_write_signals_fact_emits_memory_access(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Auto repo signals write via glob_file + kb_write_fact."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    (tmp_path / "pyproject.toml").write_text("[x]\n", encoding="utf-8")
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(
                enabled=True,
                db_path=(tmp_path / "kb.sqlite3"),
                namespace="t",
            ),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert any(
        e.get("event_type") == "memory.access"
        and e.get("tool") == "kb_write_fact"
        for e in out.events
    )


def test_loop_auto_kb_write_session_intent_is_normalized(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Intent факт не тащит сырой чат и режет длину."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(
                enabled=True,
                db_path=(tmp_path / "kb.sqlite3"),
                namespace="t",
            ),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    raw = ("hello \n\n" * 200) + "end"
    messages = [ChatMessage(role=MessageRole.USER, content=raw)]
    out = runner.run(messages, ApprovalSession(), SessionSettings(model="m"))
    assert out.state is SessionState.FINISHED
    assert any(
        e.get("event_type") == "memory.auto_write.done"
        and e.get("kind") == "session_intent"
        for e in out.events
    )


def test_loop_auto_kb_write_session_outcome_emits_done(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """При финализации пишет run-scoped outcome summary (без raw chat)."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(
                enabled=True,
                db_path=(tmp_path / "kb.sqlite3"),
                namespace="t",
            ),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    out = runner.run(
        [ChatMessage(role=MessageRole.USER, content="go")],
        ApprovalSession(),
        SessionSettings(model="m"),
    )
    assert out.state is SessionState.FINISHED
    assert any(
        e.get("event_type") == "memory.auto_write.done"
        and e.get("kind") == "session_outcome"
        for e in out.events
    )


def test_loop_auto_kb_write_repo_entrypoints_emits_done(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Repo entrypoints факт создаётся без run_shell."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(
                enabled=True,
                db_path=(tmp_path / "kb.sqlite3"),
                namespace="t",
            ),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    out = runner.run(
        [ChatMessage(role=MessageRole.USER, content="go")],
        ApprovalSession(),
        SessionSettings(model="m"),
    )
    assert out.state is SessionState.FINISHED
    assert not any(
        e.get("event_type") == "tool.call_started"
        and e.get("tool") == "run_shell"
        for e in out.events
    )
    assert any(
        e.get("event_type") == "memory.auto_write.done"
        and e.get("kind") == "repo_entrypoints"
        for e in out.events
    )


def test_loop_auto_kb_write_repo_safe_commands_emits_done(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """Repo safe commands факт создаётся и не триггерит shell."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(
                enabled=True,
                db_path=(tmp_path / "kb.sqlite3"),
                namespace="t",
            ),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("done",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        ScriptedProvider([r1]),
        reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
        ),
    )
    out = runner.run(
        [ChatMessage(role=MessageRole.USER, content="go")],
        ApprovalSession(),
        SessionSettings(model="m"),
    )
    assert out.state is SessionState.FINISHED
    assert not any(
        e.get("event_type") == "tool.call_started"
        and e.get("tool") == "run_shell"
        for e in out.events
    )
    assert any(
        e.get("event_type") == "memory.auto_write.done"
        and e.get("kind") == "repo_safe_commands"
        for e in out.events
    )


def test_effective_max_turns_respects_hard_cap_env(
    tmp_path: object,
    monkeypatch: object,
) -> None:
    """HARD_CAP из env ограничивает ходы ниже settings.max_turns."""
    monkeypatch.setenv("AILIT_WORK_ROOT", str(tmp_path))
    monkeypatch.setenv("AILIT_AGENT_HARD_CAP", "2")
    reg = default_builtin_registry()
    tc1 = ToolCallNormalized(
        call_id="t1",
        tool_name="echo",
        arguments_json='{"message":"a"}',
        stream_index=0,
        provider_name="scripted",
    )
    tc2 = ToolCallNormalized(
        call_id="t2",
        tool_name="echo",
        arguments_json='{"message":"b"}',
        stream_index=0,
        provider_name="scripted",
    )
    r_tool1 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc1,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_tool2 = NormalizedChatResponse(
        text_parts=(),
        tool_calls=(tc2,),
        finish_reason=FinishReason.TOOL_CALLS,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    r_final = NormalizedChatResponse(
        text_parts=("hard-cap finalize",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(ScriptedProvider([r_tool1, r_tool2, r_final]), reg)
    messages = [ChatMessage(role=MessageRole.USER, content="go")]
    out = runner.run(
        messages,
        ApprovalSession(),
        SessionSettings(model="m", max_turns=50),
    )
    assert out.state is SessionState.FINISHED
    assert "hard-cap finalize" in messages[-1].content


def test_budget_stops_run() -> None:
    """Бюджет обрывает цикл до бесконечных ходов."""
    reg = default_builtin_registry()
    heavy = NormalizedChatResponse(
        text_parts=("x",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1000, 1000, 2000, usage_missing=False),
        provider_metadata={},
    )
    prov = ScriptedProvider([heavy])
    runner = SessionRunner(prov, reg)
    messages = [ChatMessage(role=MessageRole.USER, content="u")]
    bud = BudgetGovernance(max_total_tokens=50)
    out = runner.run(
        messages,
        ApprovalSession(),
        SessionSettings(model="m"),
        budget=bud,
    )
    assert out.state is SessionState.BUDGET_EXCEEDED


def test_stream_reducer_with_scripted_stream() -> None:
    """StreamReducer на stream провайдера."""
    r = NormalizedChatResponse(
        text_parts=("z",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    prov = ScriptedProvider([r], stream=True)
    from ailit_base.models import ChatRequest

    req = ChatRequest(messages=[], model="m")
    out = StreamReducer.consume(iter(prov.stream(req)))
    assert out.text_parts == ("z",)
