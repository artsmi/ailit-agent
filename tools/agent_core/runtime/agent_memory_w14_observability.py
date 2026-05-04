"""G14R.10 / S2: компактные journal payload для W14 и счётчики result kinds.

Без сырого текста в ``results[]``.

Каталог внешних событий ``agent_memory.external_event.v1``, golden map
stdout→compact и сборка wire-объекта: модуль
``agent_core.runtime.agent_memory_external_events`` (G-IMPL-5, не дублировать
списки ``event_type`` в вызывающем коде).
"""

from __future__ import annotations

from typing import Any, Mapping

from agent_core.runtime.agent_memory_external_events import (
    AGENT_MEMORY_EXTERNAL_EVENT_V1,
    build_external_event_v1,
)

__all__ = (
    "AGENT_MEMORY_EXTERNAL_EVENT_V1",
    "build_link_candidates_external_event",
    "build_links_updated_external_event",
    "compact_raw_link_candidates_for_payload",
    "count_am_v1_result_kinds",
)


def compact_raw_link_candidates_for_payload(
    candidates: list[dict[str, Any]],
    *,
    max_items: int = 24,
    max_str: int = 240,
) -> tuple[list[dict[str, Any]], bool]:
    """Укороченные кандидаты для ``link_candidates`` (S2, pre-validation)."""
    lim = max(1, min(int(max_items), 128))
    chunk = candidates[:lim]
    truncated = len(candidates) > lim
    out: list[dict[str, Any]] = []

    def _clip(val: Any) -> Any:
        if isinstance(val, str):
            s = val.replace("\n", " ").strip()
            if len(s) > max_str:
                return s[: max_str - 3] + "..."
            return s
        if isinstance(val, dict):
            return {str(k): _clip(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_clip(v) for v in val[:12]]
        return val

    for c in chunk:
        out.append(_clip(dict(c)))
    return out, truncated


def build_link_candidates_external_event(
    *,
    query_id: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Событие S2 ``link_candidates`` (wire до runtime validation)."""
    compact, trunc = compact_raw_link_candidates_for_payload(candidates)
    return build_external_event_v1(
        event_type="link_candidates",
        query_id=query_id,
        payload={"candidates": compact},
        truncated=trunc,
        units="candidates",
    )


def build_links_updated_external_event(
    *,
    query_id: str,
    applied: list[dict[str, str]],
    rejected: list[dict[str, str]],
) -> dict[str, Any]:
    """Событие S2 ``links_updated`` с ``applied`` и ``rejected``."""
    return build_external_event_v1(
        event_type="links_updated",
        query_id=query_id,
        payload={
            "applied": list(applied)[:128],
            "rejected": list(rejected)[:256],
        },
        truncated=len(applied) > 128 or len(rejected) > 256,
        units="links",
    )


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
