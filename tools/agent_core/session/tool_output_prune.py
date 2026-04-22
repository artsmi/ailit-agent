"""W-TE-3: подрезка старых TOOL-сообщений в истории."""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.models import ChatMessage, MessageRole
from agent_core.session.token_economy_env import (
    env_flag,
    token_economy_globally_disabled,
)
from agent_core.session.budget import BudgetGovernance


@dataclass(frozen=True, slots=True)
class ToolOutputPruneConfig:
    """Когда и сколько TOOL-сообщений оставлять «живыми»."""

    enabled: bool
    keep_last_tool_messages: int
    min_messages_to_act: int
    min_context_units: int


def tool_output_prune_config_from_env() -> ToolOutputPruneConfig:
    """AILIT_TOOL_PRUNE* (W-TE-3). По умолчанию вкл."""
    import os

    if token_economy_globally_disabled():
        return ToolOutputPruneConfig(
            enabled=False,
            keep_last_tool_messages=6,
            min_messages_to_act=28,
            min_context_units=0,
        )
    enabled = env_flag("AILIT_TOOL_PRUNE", default=True)
    keep = int(os.environ.get("AILIT_TOOL_PRUNE_KEEP_LAST", "6"))
    min_msg = int(os.environ.get("AILIT_TOOL_PRUNE_MIN_MESSAGES", "28"))
    min_u = int(os.environ.get("AILIT_TOOL_PRUNE_AT_CONTEXT_UNITS", "0"))
    return ToolOutputPruneConfig(
        enabled=enabled,
        keep_last_tool_messages=max(1, min(500, keep)),
        min_messages_to_act=max(4, min_msg),
        min_context_units=max(0, min_u),
    )


def _tool_name_for_call_id(
    messages: list[ChatMessage],
    call_id: str,
) -> str | None:
    """Имя инструмента по call_id (assistant с tool_calls выше в списке)."""
    for m in messages:
        if m.role is MessageRole.ASSISTANT and m.tool_calls:
            for tc in m.tool_calls:
                if tc.call_id == call_id:
                    return tc.tool_name
    return None


def _should_trigger(
    messages: list[ChatMessage],
    cfg: ToolOutputPruneConfig,
) -> bool:
    if len(messages) < cfg.min_messages_to_act:
        return False
    if cfg.min_context_units <= 0:
        return True
    u = BudgetGovernance.estimate_context_units(messages)
    return u >= cfg.min_context_units


def apply_tool_output_prune(
    messages: list[ChatMessage],
    cfg: ToolOutputPruneConfig,
    protected_tools: frozenset[str] | None = None,
) -> dict[str, int | list[str]]:
    """Заменить содержимое старых TOOL на короткие плейсхолдеры.

    Возвращает агрегат для события ``tool.output_prune.applied``.
    """
    protected = protected_tools or frozenset({"write_file"})
    if not cfg.enabled or not _should_trigger(messages, cfg):
        return {
            "pruned_tools_count": 0,
            "pruned_bytes_estimate": 0,
            "protected_skipped": [],
        }
    tool_indices: list[int] = [
        i
        for i, m in enumerate(messages)
        if m.role is MessageRole.TOOL and m.tool_call_id
    ]
    if len(tool_indices) <= cfg.keep_last_tool_messages:
        return {
            "pruned_tools_count": 0,
            "pruned_bytes_estimate": 0,
            "protected_skipped": [],
        }
    to_prune = tool_indices[: -cfg.keep_last_tool_messages]
    pruned = 0
    est = 0
    skipped: list[str] = []
    for i in to_prune:
        m = messages[i]
        cid = m.tool_call_id or ""
        tname = _tool_name_for_call_id(messages, cid) or "unknown"
        if tname in protected:
            skipped.append(f"{tname}:{cid[:8]}")
            continue
        old_len = len(m.content.encode("utf-8"))
        est += old_len
        short = (
            f"[pruned tool output: {tname} call_id={cid} — "
            f"воспроизведи вызов при необходимости]"
        )
        messages[i] = ChatMessage(
            role=MessageRole.TOOL,
            content=short,
            name=m.name,
            tool_call_id=m.tool_call_id,
            tool_calls=m.tool_calls,
        )
        pruned += 1
    return {
        "pruned_tools_count": pruned,
        "pruned_bytes_estimate": est,
        "protected_skipped": skipped,
    }
