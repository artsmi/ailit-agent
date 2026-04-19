"""Инструмент ``send_teammate_message`` для merge в реестр (L.2)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec

from ailit.teams import TeamRootSelector, TeamSession


def _project_root_for_teams() -> Path:
    raw = os.environ.get("AILIT_TEAM_PROJECT_ROOT") or os.environ.get("AILIT_WORK_ROOT")
    if not raw:
        msg = (
            "send_teammate_message: set AILIT_WORK_ROOT or AILIT_TEAM_PROJECT_ROOT "
            "to the project root (mailbox lives under .ailit/teams)."
        )
        raise ValueError(msg)
    return Path(raw).resolve()


def builtin_send_teammate_message(arguments: Mapping[str, Any]) -> str:
    """Записать сообщение во inbox получателя (файловый mailbox)."""
    team_id = str(arguments.get("team_id") or os.environ.get("AILIT_TEAM_ID") or "default").strip()
    to_agent = str(arguments.get("to_agent", "")).strip()
    text = str(arguments.get("text", "")).strip()
    from_agent = str(arguments.get("from_agent", "")).strip()
    if not from_agent:
        from_agent = str(os.environ.get("AILIT_CHAT_AGENT_ID", "agent")).strip() or "agent"
    if not to_agent:
        msg = "send_teammate_message: to_agent is required"
        raise ValueError(msg)
    if not text:
        msg = "send_teammate_message: text is required"
        raise ValueError(msg)
    root = _project_root_for_teams()
    session = TeamSession(TeamRootSelector.for_project(root), team_id)
    record = session.send(from_agent, to_agent, text)
    out = {
        "ok": True,
        "team_id": team_id,
        "to": to_agent,
        "from": from_agent,
        "ts": record.ts,
        "inbox_rel": f".ailit/teams/{team_id}/inboxes/{to_agent}.json",
    }
    return json.dumps(out, ensure_ascii=False)


def teammate_tool_registry() -> ToolRegistry:
    """Реестр с одним инструментом межагентной почты (merge с ``default_builtin_registry``)."""
    spec = ToolSpec(
        name="send_teammate_message",
        description=(
            "Send a message to another agent's mailbox on disk. "
            "Required for teammate communication; user chat is not delivered to peers."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "to_agent": {
                    "type": "string",
                    "description": "Recipient agent id (inbox file name).",
                },
                "text": {
                    "type": "string",
                    "description": "Message body (plain text).",
                },
                "from_agent": {
                    "type": "string",
                    "description": "Sender agent id (defaults to AILIT_CHAT_AGENT_ID).",
                },
                "team_id": {
                    "type": "string",
                    "description": "Team id directory under .ailit/teams (default: default).",
                },
            },
            "required": ["to_agent", "text"],
            "additionalProperties": False,
        },
        side_effect=SideEffectClass.WRITE,
        allow_parallel=False,
    )
    return ToolRegistry(
        specs={"send_teammate_message": spec},
        handlers={"send_teammate_message": builtin_send_teammate_message},
    )
