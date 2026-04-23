"""E2E: M4 memory auto policy (repo context + auto KB calls)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_core.memory.kb_tools import KbToolsConfig, build_kb_tool_registry
from agent_core.models import (
    ChatMessage,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
)
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.state import SessionState
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_core.tool_runtime.registry import default_builtin_registry


class _ScriptedProvider:
    provider_id = "scripted"

    def capabilities(self) -> frozenset[object]:
        return frozenset()

    def __init__(self, resp: NormalizedChatResponse) -> None:
        self._resp = resp

    def complete(self, request: object) -> NormalizedChatResponse:
        _ = request
        return self._resp


def _git(cwd: Path, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.e2e
def test_m4_auto_memory_emits_repo_context_and_kb_access(
    e2e_workspace: Path,
) -> None:
    """Repo develop → new_feature: policy + kb_search/write access."""
    repo = e2e_workspace / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, ["init"])
    _git(repo, ["config", "user.email", "e2e@example.com"])
    _git(repo, ["config", "user.name", "e2e"])
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, ["add", "README.md"])
    _git(repo, ["commit", "-m", "init"])
    _git(repo, ["checkout", "-b", "develop"])
    _git(repo, ["checkout", "-b", "new_feature"])

    os.environ["AILIT_WORK_ROOT"] = str(repo)

    kb_path = e2e_workspace / "kb.sqlite3"
    reg = default_builtin_registry().merge(
        build_kb_tool_registry(
            KbToolsConfig(enabled=True, db_path=kb_path, namespace="e2e"),
        ),
    )
    r1 = NormalizedChatResponse(
        text_parts=("ok",),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(1, 1, 2, usage_missing=False),
        provider_metadata={},
    )
    runner = SessionRunner(
        provider=_ScriptedProvider(r1),
        registry=reg,
        permission_engine=PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
            network_default=PermissionDecision.ALLOW,
        ),
    )
    msgs = [
        ChatMessage(role=MessageRole.USER, content="изучи репо и запомни"),
    ]
    out = runner.run(
        msgs,
        ApprovalSession(),
        SessionSettings(model="m"),
    )
    assert out.state is SessionState.FINISHED
    assert any(e.get("event_type") == "memory.policy" for e in out.events)
    pol = next(e for e in out.events if e.get("event_type") == "memory.policy")
    assert pol.get("enabled") is True
    repo_pl = pol.get("repo") or {}
    assert isinstance(repo_pl, dict)
    # We are on new_feature; default branch is heuristic develop.
    assert repo_pl.get("branch") == "new_feature"
    assert repo_pl.get("default_branch") in ("develop", "master", "main")
    assert repo_pl.get("default_branch_source") in ("heuristic", "origin_head")

    tools = [
        e.get("tool")
        for e in out.events
        if e.get("event_type") == "memory.access"
    ]
    assert "kb_search" in tools
    assert "kb_write_fact" in tools
