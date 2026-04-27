"""perm-5: обратная совместимость — реэкспорт из agent_core."""

from __future__ import annotations

from agent_core.session.perm_turn import (
    PermModeTurnCoordinator as ChatPermModeCoordinator,
    PermTurnResolution as ChatPermTurnResolution,
    build_mode_kb_namespace,
    memory_namespace_from_cfg,
    perm_mode_enabled_from_env,
)

__all__ = (
    "ChatPermModeCoordinator",
    "ChatPermTurnResolution",
    "build_mode_kb_namespace",
    "memory_namespace_from_cfg",
    "perm_mode_enabled_from_env",
)
