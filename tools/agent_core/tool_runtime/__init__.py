"""Tool runtime: контракт инструментов, permissions, approvals, исполнение."""

from agent_core.tool_runtime.approval import ApprovalDecision, ApprovalSession
from agent_core.tool_runtime.executor import (
    ApprovalPending,
    ToolExecutor,
    ToolInvocation,
    ToolRejected,
    ToolRunResult,
)
from agent_core.tool_runtime.permission import PermissionDecision, PermissionEngine, SideEffectClass
from agent_core.tool_runtime.registry import ToolRegistry, default_builtin_registry, empty_tool_registry
from agent_core.tool_runtime.spec import ToolSpec

__all__ = [
    "ApprovalDecision",
    "ApprovalPending",
    "ApprovalSession",
    "PermissionDecision",
    "PermissionEngine",
    "SideEffectClass",
    "ToolExecutor",
    "ToolInvocation",
    "ToolRejected",
    "ToolRegistry",
    "ToolRunResult",
    "ToolSpec",
    "default_builtin_registry",
    "empty_tool_registry",
]
