"""G14R.10: компактные journal payload для W14.

Без сырого текста в ``results[]``.
"""

from __future__ import annotations

from typing import Any, Mapping


def count_am_v1_result_kinds(
    agent_memory_result: Mapping[str, Any] | None,
) -> dict[str, int]:
    """
    Считает ``results[]`` по полю ``kind`` для ``memory.result.returned``.

    Сырые summary / read_lines не копируются: только агрегат по видам.
    """
    if not agent_memory_result:
        return {}
    raw = agent_memory_result.get("results")
    if not isinstance(raw, list) or not raw:
        return {}
    out: dict[str, int] = {}
    for it in raw:
        if not isinstance(it, dict):
            continue
        kind: str = str(it.get("kind", "") or "unknown").strip() or "unknown"
        out[kind] = out.get(kind, 0) + 1
    return out
