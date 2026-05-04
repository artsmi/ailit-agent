"""Каталог внешних событий AgentMemory и маппинг internal→compact (S2).

G-IMPL-5: D-OBS-1 см. ``context/proto/runtime-event-contract.md``;
здесь discriminant ``agent_memory.external_event.v1`` (OR-010) и golden map
stdout/wire → ``event=`` в ``compact.log``.

``schema_version`` внешнего конверта: ``agent_memory.external_event.v1``.

Нормативные краткие поля ``payload`` по ``event_type``:

- **heartbeat:** ``session_alive`` (bool) = true.
- **progress:** ``runtime_state`` (str), ``message`` (str, compact).
- **highlighted_nodes:** ``node_ids`` (str[], bounded),
  ``reason`` (str, short).
- **link_candidates:** массив ``agent_memory_link_candidate.v1``
  (pre-validation).
- **links_updated:** ``applied`` (array),
  ``rejected`` (array of ``link_id`` + ``reason``).
- **nodes_updated:** ``upserted_node_ids`` (array),
  ``kind`` ∈ {``B``, ``C``, ``D``}, bounded.
- **partial_result** / **complete_result** / **blocked_result:**
  ссылка/подмножество ``agent_memory_result.v1`` + hash;
  **forbidden** raw prompts и CoT.

Durable vs ephemeral (внешний конверт ``agent_memory.external_event.v1``):
``heartbeat`` и fine-grained ``progress`` — ephemeral на пути adapter →
потребитель; финальные ``complete_result`` / ``blocked_result`` /
``partial_result`` — durable.

Внутренний ``MemoryJournalStore``: ``memory.runtime.step`` и шаги W14 —
**durable** в JSONL (G14R.10). Частичный прогресс индекса
``memory.index.partial`` — **ephemeral** (``journal_durability_…`` в
``memory_journal.py``).

Golden stdout → ``compact.log`` (``failure-retry-observability.md``):

- ``pag.node.upsert`` / ``pag.edge.upsert`` → ``memory.pag_graph``
- ``memory.w14.graph_highlight`` → ``memory.w14_graph_highlight``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Final, Literal, Mapping

AGENT_MEMORY_EXTERNAL_EVENT_V1: Final[str] = "agent_memory.external_event.v1"

# stdout/wire (topic.publish) → нормализованное имя compact.log
STDOUT_INTERNAL_TO_COMPACT_EVENT: Final[dict[str, str]] = {
    "pag.node.upsert": "memory.pag_graph",
    "pag.edge.upsert": "memory.pag_graph",
    "memory.w14.graph_highlight": "memory.w14_graph_highlight",
}

ExternalEventType = Literal[
    "heartbeat",
    "progress",
    "highlighted_nodes",
    "link_candidates",
    "links_updated",
    "nodes_updated",
    "partial_result",
    "complete_result",
    "blocked_result",
]


def map_stdout_internal_to_compact_event(internal_event: str) -> str:
    """internal stdout ``event_name`` → ``event=`` для compact.log."""
    key = str(internal_event or "").strip()
    return STDOUT_INTERNAL_TO_COMPACT_EVENT.get(key, key)


def normalize_compact_event_name(raw_event: str) -> str:
    """
    Нормализация ``event=`` для compact.log: golden map, иначе без изменений.

    Имена вида ``memory.pag_graph`` не в map и проходят как есть.
    """
    s = str(raw_event or "").strip()
    return STDOUT_INTERNAL_TO_COMPACT_EVENT.get(s, s)


def build_external_event_v1(
    *,
    event_type: ExternalEventType | str,
    query_id: str,
    payload: Mapping[str, Any],
    truncated: bool = False,
    units: str | None = None,
) -> dict[str, Any]:
    """
    Объект внешнего события без смешивания с internal journal keys.

    Верхний уровень — ``external-protocol.md`` schema-like блок.
    """
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out: dict[str, Any] = {
        "schema_version": AGENT_MEMORY_EXTERNAL_EVENT_V1,
        "event_type": str(event_type),
        "query_id": str(query_id or "").strip(),
        "timestamp": ts,
        "payload": dict(payload),
        "truncated": bool(truncated),
    }
    if units is not None and str(units).strip():
        out["units"] = str(units).strip()
    return out
