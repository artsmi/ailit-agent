"""D-level compact/session artifacts for Context Ledger Workflow 10."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from agent_memory.storage.sqlite_pag import SqlitePagStore
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService
from ailit_base.models import ChatMessage, MessageRole
from agent_work.session.context_ledger import estimate_text_tokens


def _default_pag_db_path() -> Path:
    """Default PAG DB path without importing pag_indexer at import time."""
    return Path("~/.ailit/pag/store.sqlite3").expanduser().resolve()


@dataclass(frozen=True, slots=True)
class DLevelCompactResult:
    """Result of writing a D-level compact artifact."""

    boundary_id: str
    d_node_id: str
    summary: str
    pre_tokens_estimated: int
    post_tokens_estimated: int
    freed_tokens_estimated: int
    linked_node_ids: tuple[str, ...]
    message: ChatMessage

    def to_event_payload(self, *, trigger: str) -> dict[str, Any]:
        """Return a JSON-ready ``context.compacted.v1`` payload."""
        return {
            "schema": "context.compacted.v1",
            "trigger": trigger,
            "boundary_id": self.boundary_id,
            "d_node_id": self.d_node_id,
            "pre_tokens_estimated": self.pre_tokens_estimated,
            "post_tokens_estimated": self.post_tokens_estimated,
            "freed_tokens_estimated": self.freed_tokens_estimated,
            "linked_node_ids": list(self.linked_node_ids),
        }


@dataclass(frozen=True, slots=True)
class DLevelRestoreResult:
    """Restored D-level compact artifact for chat reopen."""

    d_node_id: str
    summary: str
    linked_node_ids: tuple[str, ...]
    message: ChatMessage

    def to_event_payload(self) -> dict[str, Any]:
        """Return a JSON-ready ``context.restored.v1`` payload."""
        return {
            "schema": "context.restored.v1",
            "trigger": "open_chat_restore",
            "d_node_id": self.d_node_id,
            "linked_node_ids": list(self.linked_node_ids),
        }


class DLevelCompactService:
    """Create compact summaries as PAG D-level memory nodes."""

    def __init__(self, store: SqlitePagStore) -> None:
        self._store = store
        self._write = PagGraphWriteService(store)

    @staticmethod
    def default() -> DLevelCompactService:
        """Build the service using the default PAG store path."""
        raw = os.environ.get("AILIT_PAG_DB_PATH", "").strip()
        db_path = (
            Path(raw).expanduser().resolve()
            if raw
            else _default_pag_db_path()
        )
        return DLevelCompactService(SqlitePagStore(db_path))

    def compact(
        self,
        *,
        namespace: str,
        removed_messages: Sequence[ChatMessage],
        kept_messages: Sequence[ChatMessage],
        linked_node_ids: Sequence[str],
        trigger: str,
    ) -> DLevelCompactResult:
        """Write a D-level compact artifact and return prompt summary."""
        ns = str(namespace or "").strip() or "default"
        boundary_id = f"compact-{uuid.uuid4().hex}"
        linked = tuple(dict.fromkeys([x for x in linked_node_ids if x]))
        links = linked if linked else (f"A:{ns}",)
        summary = self._summarize(removed_messages)
        pre_tokens = self._estimate(removed_messages)
        post_tokens_tail = self._estimate(kept_messages)
        summary_tokens = estimate_text_tokens(summary)
        post_tokens = post_tokens_tail + summary_tokens
        freed = max(0, pre_tokens - summary_tokens)
        d_node_id = f"D:compact-summary:{boundary_id}"
        fingerprint = hashlib.sha256(summary.encode("utf-8")).hexdigest()
        attrs = {
            "boundary_id": boundary_id,
            "trigger": str(trigger),
            "linked_node_ids": list(links),
            "pre_tokens_estimated": pre_tokens,
            "post_tokens_estimated": post_tokens,
            "freed_tokens_estimated": freed,
        }
        self._write.upsert_node(
            namespace=ns,
            node_id=d_node_id,
            level="D",
            kind="compact_summary",
            path=f"session/{boundary_id}",
            title="Compact summary",
            summary=summary,
            attrs=attrs,
            fingerprint=fingerprint,
            source_contract="ailit_context_compact_d_v1",
        )
        for linked_id in links:
            edge_id = f"{d_node_id}->summarizes->{linked_id}"
            self._write.upsert_edge(
                namespace=ns,
                edge_id=edge_id,
                edge_class="provenance",
                edge_type="summarizes",
                from_node_id=d_node_id,
                to_node_id=linked_id,
                confidence=1.0,
                source_contract="ailit_context_compact_d_v1",
            )
        message = ChatMessage(
            role=MessageRole.SYSTEM,
            name="agent_memory_d",
            content=self._render_prompt_message(
                d_node_id=d_node_id,
                summary=summary,
                linked_node_ids=links,
            ),
        )
        return DLevelCompactResult(
            boundary_id=boundary_id,
            d_node_id=d_node_id,
            summary=summary,
            pre_tokens_estimated=pre_tokens,
            post_tokens_estimated=post_tokens,
            freed_tokens_estimated=freed,
            linked_node_ids=links,
            message=message,
        )

    def restore_latest(
        self,
        *,
        namespace: str,
    ) -> DLevelRestoreResult | None:
        """Restore the newest valid D-level compact summary for a namespace."""
        ns = str(namespace or "").strip()
        if not ns:
            return None
        nodes = self._store.list_nodes(
            namespace=ns,
            level="D",
            limit=1,
            include_stale=False,
        )
        if not nodes:
            return None
        node = nodes[0]
        if node.kind != "compact_summary":
            return None
        linked_raw = node.attrs.get("linked_node_ids")
        linked: tuple[str, ...]
        if isinstance(linked_raw, list):
            linked = tuple(str(x) for x in linked_raw if str(x).strip())
        else:
            linked = ()
        if not linked:
            linked = (f"A:{ns}",)
        message = ChatMessage(
            role=MessageRole.SYSTEM,
            name="agent_memory_d",
            content=self._render_prompt_message(
                d_node_id=node.node_id,
                summary=node.summary,
                linked_node_ids=linked,
            ),
        )
        return DLevelRestoreResult(
            d_node_id=node.node_id,
            summary=node.summary,
            linked_node_ids=linked,
            message=message,
        )

    @staticmethod
    def _estimate(messages: Sequence[ChatMessage]) -> int:
        total = 0
        for msg in messages:
            total += estimate_text_tokens(msg.content)
        return total

    @staticmethod
    def _summarize(messages: Sequence[ChatMessage]) -> str:
        lines: list[str] = ["D-level compact summary."]
        for msg in messages[-8:]:
            role = msg.role.value
            body = " ".join((msg.content or "").split())
            if not body:
                continue
            if len(body) > 240:
                body = body[:237] + "..."
            lines.append(f"- {role}: {body}")
        if len(lines) == 1:
            lines.append("- no text content")
        return "\n".join(lines)

    @staticmethod
    def _render_prompt_message(
        *,
        d_node_id: str,
        summary: str,
        linked_node_ids: Sequence[str],
    ) -> str:
        links = ", ".join(linked_node_ids)
        return (
            "D-level memory compact summary. Use this instead of the "
            "older raw chat segment.\n"
            f"d_node_id={d_node_id}\n"
            f"linked_node_ids={links}\n\n"
            f"{summary}"
        )
