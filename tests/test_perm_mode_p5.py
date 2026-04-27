"""Unit-тесты perm-5: классификатор, enforcement, read_plan, explore shell."""

from __future__ import annotations

import json

import pytest

from agent_core.session.mode_classifier import (
    ClassifierJsonParser,
    LlmPermModeClassifier,
)
from agent_core.session.mode_permission_policy import ModePermissionPolicy
from agent_core.session.perm_tool_mode import (
    explore_shell_command_allowed,
    read_plan_write_file_allowed,
    tool_definitions_for_perm_mode,
)
from agent_core.tool_runtime.executor import ToolInvocation
from agent_core.tool_runtime.permission import PermissionDecision
from agent_core.tool_runtime.bash_tools import bash_tool_registry
from agent_core.tool_runtime.registry import default_builtin_registry


def test_classifier_json_parse_not_sure() -> None:
    raw = '{"mode": "not_sure", "confidence": 0.2, "reason": "ambiguous"}'
    out = ClassifierJsonParser().parse(raw)
    assert out is not None
    assert out.mode == "not_sure"
    assert out.confidence == pytest.approx(0.2)


def test_read_mode_denies_write_file_and_shell() -> None:
    reg = default_builtin_registry().merge(bash_tool_registry())
    write_spec = reg.specs["write_file"]
    shell_spec = reg.specs["run_shell"]
    pol = ModePermissionPolicy("read")
    wf_inv = ToolInvocation(
        "1",
        "write_file",
        json.dumps({"path": "x.md", "content": "a"}),
    )
    sh_inv = ToolInvocation(
        "2",
        "run_shell",
        json.dumps({"command": "git status"}),
    )
    assert pol.evaluate(write_spec, wf_inv) is PermissionDecision.DENY
    assert pol.evaluate(shell_spec, sh_inv) is PermissionDecision.DENY


def test_read_plan_blocks_py_path() -> None:
    assert read_plan_write_file_allowed("docs/x.md") is True
    assert read_plan_write_file_allowed("src/foo.py") is False
    assert read_plan_write_file_allowed("Makefile") is False


def test_explore_shell_allowlist() -> None:
    assert explore_shell_command_allowed("git status") is True
    assert explore_shell_command_allowed("pip install x") is False


def test_explore_shell_allows_run_shell_by_default() -> None:
    reg = default_builtin_registry().merge(bash_tool_registry())
    spec = reg.specs["run_shell"]
    pol = ModePermissionPolicy("explore")
    inv = ToolInvocation(
        "x",
        "run_shell",
        json.dumps({"command": "pip install foo"}),
    )
    assert pol.evaluate(spec, inv) is PermissionDecision.ALLOW


def test_read_exposes_no_write_tool_definitions() -> None:
    reg = default_builtin_registry()
    defs, meta = tool_definitions_for_perm_mode(reg, "read")
    names = {d.name for d in defs}
    assert "write_file" not in names
    assert "apply_patch" not in names
    assert "run_shell" not in names
    assert "read_file" in names
    assert "read_symbol" in names


def test_mock_classifier_provider_entry_points() -> None:
    from agent_core.models import ChatMessage, ChatRequest, MessageRole
    from agent_core.providers.mock_provider import MockProvider
    from agent_core.session.mode_classifier import CLASSIFIER_PROMPT_MARKER

    p = MockProvider()
    clf = LlmPermModeClassifier(p)
    out = clf.classify(
        model="mock",
        temperature=0.0,
        user_intent="покажи точки входа в проект",
        history_block="(нет)",
    )
    assert out is not None
    assert out.mode == "read"

    req = ChatRequest(
        messages=(
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=CLASSIFIER_PROMPT_MARKER,
            ),
            ChatMessage(role=MessageRole.USER, content="docs/plan.md"),
        ),
        model="mock",
        temperature=0.0,
        tools=(),
    )
    r2 = p.complete(req)
    body = "".join(r2.text_parts)
    parsed = ClassifierJsonParser().parse(body)
    assert parsed is not None
    assert parsed.mode == "read_plan"
