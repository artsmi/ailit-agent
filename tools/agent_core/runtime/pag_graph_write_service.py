"""Единый runtime-слой записи PAG (G13.1, D13.1).

Все DML ``upsert_*`` в ``tools/agent_core`` — через этот сервис, кроме
``sqlite_pag.SqlitePagStore``.

Режимы: **runtime_traced**, **offline_writer** (только ``graph_rev``),
**runtime_untraced** (allowlist).
Чтения: ``write.store``.

Контракт: ``plan/13-agent-memory-contract-recovery.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from agent_core.memory.sqlite_pag import SqlitePagStore

# Модули: запись без graph_trace. Добавлять с тестом «rev без trace».
OFFLINE_PAG_WRITER_MODULES: Final[frozenset[str]] = frozenset(
    {
        "agent_core.memory.pag_indexer",
        "agent_core.session.d_level_compact",
    },
)

# Пути без trace (G13.1). Пустой allowlist = untraced отключён.
RUNTIME_UNTRACED_WRITE_ALLOWLIST: Final[frozenset[str]] = frozenset()


@dataclass(frozen=True, slots=True)
class PagGraphWriteService:
    """DML в ``SqlitePagStore``; ``upsert_*`` при активном ``graph_trace``."""

    _store: SqlitePagStore

    @property
    def store(self) -> SqlitePagStore:
        return self._store

    def upsert_node(
        self,
        *,
        namespace: str,
        node_id: str,
        level: str,
        kind: str,
        path: str,
        title: str,
        summary: str,
        attrs: Mapping[str, Any] | None,
        fingerprint: str,
        staleness_state: str = "fresh",
        source_contract: str = "ailit_pag_store_v1",
        updated_at: str | None = None,
    ) -> int:
        return self._store.upsert_node(
            namespace=namespace,
            node_id=node_id,
            level=level,
            kind=kind,
            path=path,
            title=title,
            summary=summary,
            attrs=attrs,
            fingerprint=fingerprint,
            staleness_state=staleness_state,
            source_contract=source_contract,
            updated_at=updated_at,
        )

    def upsert_edge(
        self,
        *,
        namespace: str,
        edge_id: str,
        edge_class: str,
        edge_type: str,
        from_node_id: str,
        to_node_id: str,
        confidence: float = 1.0,
        source_contract: str = "ailit_pag_store_v1",
        updated_at: str | None = None,
    ) -> int:
        return self._store.upsert_edge(
            namespace=namespace,
            edge_id=edge_id,
            edge_class=edge_class,
            edge_type=edge_type,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            confidence=confidence,
            source_contract=source_contract,
            updated_at=updated_at,
        )

    def upsert_edges_batch(
        self,
        *,
        namespace: str,
        edges: Sequence[Mapping[str, Any]],
        updated_at: str | None = None,
    ) -> int:
        return self._store.upsert_edges_batch(
            namespace=namespace,
            edges=edges,
            updated_at=updated_at,
        )
