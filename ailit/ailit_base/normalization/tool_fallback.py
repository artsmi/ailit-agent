"""Резервный разбор tool calls из текста ответа модели."""

from __future__ import annotations

import json
import re
from typing import Any

from ailit_base.models import ToolCallNormalized


def try_parse_tool_calls_from_text(
    text: str,
    *,
    provider_id: str,
) -> list[ToolCallNormalized]:
    """Попытаться извлечь tool calls из свободного текста (резервный путь)."""
    stripped = text.strip()
    if not stripped:
        return []

    # Блок ```json ... ```
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped, re.IGNORECASE)
    candidate = fence.group(1).strip() if fence else stripped

    parsed: Any
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, dict) and "tool_calls" in parsed:
        parsed = parsed["tool_calls"]
    if not isinstance(parsed, list):
        return []

    out: list[ToolCallNormalized] = []
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("tool_name") or "")
        args = item.get("arguments") or item.get("args") or {}
        args_str = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        call_id = str(item.get("id") or item.get("call_id") or f"fallback_{idx}")
        if not name:
            continue
        out.append(
            ToolCallNormalized(
                call_id=call_id,
                tool_name=name,
                arguments_json=args_str,
                stream_index=idx,
                provider_name=provider_id,
                is_complete=True,
            )
        )
    return out
