"""S3: централизованная валидация ``agent_memory_link_candidate.v1`` (UC-03).

Матрица нарушений и действий:
``context/algorithms/agent-memory/memory-graph-links.md``.
Запись в ``pag_edges`` / ``pag_pending_edges`` только через переданный
``PagGraphWriteService`` после прохождения проверок.

G-IMPL-3: не нормализуем шаблон ``A`` ``node_id``; проверяем существование
узла в store как передано (дрейф A — ``implementation_backlog``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Final, Mapping

from agent_memory.storage.sqlite_pag import SqlitePagStore
from agent_memory.contracts.agent_memory_runtime_contract import (
    AGENT_MEMORY_LINK_CANDIDATE_SCHEMA,
)
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService

_LINK_TYPES: Final[frozenset[str]] = frozenset(
    {
        "contains",
        "imports",
        "defines",
        "calls",
        "references",
        "summarizes",
        "supports_answer",
        "supersedes",
    },
)

_CONFIDENCE: Final[frozenset[str]] = frozenset(
    {"high", "medium", "low"},
)

_CREATED_BY: Final[frozenset[str]] = frozenset(
    {"static_analysis", "llm_inferred", "runtime_observed"},
)

_SYMBOL_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {"symbol_name", "import_statement"},
)

_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "line_range",
        "symbol_name",
        "heading_text",
        "import_statement",
        "llm_summary",
    },
)

# (source_level, target_level); "X" — внешняя цель (``target_external_ref``).
_ENDPOINT_MATRIX: Final[dict[str, frozenset[tuple[str, str]]]] = {
    "contains": frozenset(
        {("A", "B"), ("B", "B"), ("B", "C")},
    ),
    "imports": frozenset(
        {("B", "B"), ("B", "C"), ("B", "X")},
    ),
    "defines": frozenset({("B", "C")}),
    "calls": frozenset({("C", "C")}),
    "references": frozenset(
        {
            ("B", "B"),
            ("B", "C"),
            ("B", "D"),
            ("C", "B"),
            ("C", "C"),
            ("C", "D"),
            ("D", "B"),
            ("D", "C"),
            ("D", "D"),
        },
    ),
    "summarizes": frozenset({("D", "B"), ("D", "C")}),
    "supports_answer": frozenset({("B", "D"), ("C", "D")}),
    "supersedes": frozenset({("D", "D")}),
}

_MAX_LINKS_PER_ROUND: Final[int] = 64
_MAX_REASON_LEN: Final[int] = 512
_MAX_EVIDENCE_VALUE_LEN: Final[int] = 4_096
_MAX_COMPACT_REJECT: Final[int] = 220

_SOURCE_CONTRACT: Final[str] = "agent_memory_link_candidate.v1"


def _compact_reject_reason(msg: str) -> str:
    s = str(msg or "").strip().replace("\n", " ")
    if len(s) <= _MAX_COMPACT_REJECT:
        return s
    return s[: _MAX_COMPACT_REJECT - 3] + "..."


def _level_from_node_id(node_id: str) -> str | None:
    s = str(node_id or "").strip()
    if len(s) < 2 or s[1] != ":":
        return None
    p = s[0].upper()
    if p in {"A", "B", "C", "D"}:
        return p
    return None


def _repo_relative_path_ok(path: str) -> bool:
    s = str(path or "").strip().replace("\\", "/")
    if not s:
        return False
    if s.startswith("/"):
        return False
    if len(s) > 1 and s[1] == ":":
        return False
    if s.startswith("~"):
        return False
    parts = s.split("/")
    return ".." not in parts


def _confidence_to_float(level: str) -> float:
    low = str(level or "").strip().lower()
    if low == "high":
        return 0.95
    if low == "medium":
        return 0.75
    return 0.45


def _edge_id_for_link(namespace: str, link_id: str) -> str:
    raw = f"{namespace}:{link_id}"
    h = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"e:aml:{h}"


def _map_link_type_to_pag(link_type: str) -> tuple[str, str]:
    lt = str(link_type or "").strip()
    if lt == "contains":
        return "containment", "contains"
    return "semantic", lt


@dataclass(frozen=True, slots=True)
class LinkCandidateProcessResult:
    """Итог батча после валидации и записи."""

    applied_edges: list[dict[str, str]] = field(default_factory=list)
    applied_pending: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)


class AgentMemoryLinkCandidateValidator:
    """Валидация кандидатов и единственная точка DML рёбер из LLM JSON (S3)."""

    def __init__(
        self,
        *,
        max_links_per_round: int = _MAX_LINKS_PER_ROUND,
    ) -> None:
        self._max_links = max(1, int(max_links_per_round))

    def process_batch(
        self,
        *,
        store: SqlitePagStore,
        write: PagGraphWriteService,
        namespace: str,
        candidates: list[dict[str, Any]],
    ) -> LinkCandidateProcessResult:
        """Проверить кандидатов и записать допустимые рёбра или pending."""
        ns = str(namespace or "").strip()
        out = LinkCandidateProcessResult()
        if not ns:
            return out
        seen_ids: set[str] = set()
        for idx, raw in enumerate(candidates[:self._max_links]):
            lid, rej = self._validate_one(
                store=store,
                namespace=ns,
                raw=raw,
                batch_index=idx,
                seen_link_ids=seen_ids,
            )
            if rej:
                out.rejected.append({"link_id": lid, "reason": rej})
                continue
            assert raw is not None
            applied = self._apply_one(
                write=write,
                namespace=ns,
                raw=raw,
            )
            if applied is None:
                continue
            if applied[0] == "edge":
                out.applied_edges.append(
                    {"link_id": applied[1], "edge_id": applied[2]},
                )
            else:
                out.applied_pending.append(
                    {"link_id": applied[1], "pending_id": applied[2]},
                )
        for overflow in candidates[self._max_links:]:
            lid = str((overflow or {}).get("link_id") or "").strip() or "?"
            out.rejected.append(
                {
                    "link_id": lid,
                    "reason": _compact_reject_reason(
                        "round_limit_exceeded",
                    ),
                },
            )
        return out

    def _validate_one(
        self,
        *,
        store: SqlitePagStore,
        namespace: str,
        raw: Mapping[str, Any],
        batch_index: int,
        seen_link_ids: set[str],
    ) -> tuple[str, str | None]:
        """Возвращает link_id и причину отказа (None если кандидат принят)."""
        if not isinstance(raw, Mapping):
            return str(batch_index), _compact_reject_reason("not_an_object")
        link_id = str(raw.get("link_id") or "").strip()
        if not link_id:
            return f"#{batch_index}", _compact_reject_reason("missing_link_id")
        if link_id in seen_link_ids:
            return link_id, _compact_reject_reason("duplicate_link_id")
        seen_link_ids.add(link_id)

        ver = str(raw.get("schema_version") or "").strip()
        if ver != AGENT_MEMORY_LINK_CANDIDATE_SCHEMA:
            return link_id, _compact_reject_reason(
                f"invalid_schema_version:{ver!r}",
            )

        lt = str(raw.get("link_type") or "").strip()
        if lt not in _LINK_TYPES:
            return link_id, _compact_reject_reason(
                f"unknown_link_type:{lt!r}",
            )

        src = str(raw.get("source_node_id") or "").strip()
        if not src:
            return link_id, _compact_reject_reason("missing_source_node_id")

        tgt = str(raw.get("target_node_id") or "").strip()
        ext_raw = raw.get("target_external_ref")
        ext_s = str(ext_raw).strip() if ext_raw is not None else ""
        if ext_s and lt != "imports":
            return link_id, _compact_reject_reason(
                "target_external_ref_only_for_imports",
            )
        if lt == "imports" and ext_s and tgt:
            return link_id, _compact_reject_reason(
                "ambiguous_internal_and_external_target",
            )
        is_external = bool(ext_s) and lt == "imports"
        if not tgt and not is_external:
            return link_id, _compact_reject_reason("missing_target_node_id")
        if is_external and tgt:
            return link_id, _compact_reject_reason(
                "external_target_with_node_id",
            )

        sp = str(raw.get("source_path") or "").strip()
        if not _repo_relative_path_ok(sp):
            return link_id, _compact_reject_reason("invalid_source_path")

        tp_raw = raw.get("target_path")
        if tp_raw is not None and str(tp_raw).strip():
            if not _repo_relative_path_ok(str(tp_raw)):
                return link_id, _compact_reject_reason("invalid_target_path")

        ev = raw.get("evidence")
        if not isinstance(ev, dict):
            return link_id, _compact_reject_reason("evidence_must_be_object")
        ek = str(ev.get("kind") or "").strip()
        if not ek:
            return link_id, _compact_reject_reason("evidence.kind_required")
        if ek not in _EVIDENCE_KINDS:
            return link_id, _compact_reject_reason(
                f"unknown_evidence_kind:{ek!r}",
            )
        val = str(ev.get("value") or "").strip()
        if not val:
            return link_id, _compact_reject_reason("evidence.value_required")
        if len(val) > _MAX_EVIDENCE_VALUE_LEN:
            return link_id, _compact_reject_reason("evidence.value_too_long")

        conf = str(raw.get("confidence") or "").strip().lower()
        if conf not in _CONFIDENCE:
            return link_id, _compact_reject_reason("invalid_confidence")

        cb = str(raw.get("created_by") or "").strip()
        if cb not in _CREATED_BY:
            return link_id, _compact_reject_reason("invalid_created_by")

        reason = str(raw.get("reason") or "").strip()
        if not reason:
            return link_id, _compact_reject_reason("reason_required")
        if len(reason) > _MAX_REASON_LEN:
            return link_id, _compact_reject_reason("reason_too_long")

        if lt == "calls" and ek not in _SYMBOL_EVIDENCE_KINDS:
            return link_id, _compact_reject_reason(
                "calls_requires_symbol_evidence",
            )

        sl = _level_from_node_id(src)
        if sl is None:
            return link_id, _compact_reject_reason(
                "invalid_source_node_id_level",
            )
        if is_external:
            tl = "X"
        else:
            tl = _level_from_node_id(tgt)
            if tl is None:
                return link_id, _compact_reject_reason(
                    "invalid_target_node_id_level",
                )

        allowed = _ENDPOINT_MATRIX.get(lt, frozenset())
        if (sl, tl) not in allowed:
            return link_id, _compact_reject_reason(
                f"endpoint_pair_not_allowed:{sl}->{tl}",
            )

        if store.fetch_node(namespace=namespace, node_id=src) is None:
            return link_id, _compact_reject_reason("source_node_missing")
        if not is_external and store.fetch_node(
            namespace=namespace,
            node_id=tgt,
        ) is None:
            return link_id, _compact_reject_reason("target_node_missing")

        return link_id, None

    def _apply_one(
        self,
        *,
        write: PagGraphWriteService,
        namespace: str,
        raw: Mapping[str, Any],
    ) -> tuple[str, str, str] | None:
        """Записать одно принятое решение: edge или pending."""
        link_id = str(raw.get("link_id") or "").strip()
        lt = str(raw.get("link_type") or "").strip()
        src = str(raw.get("source_node_id") or "").strip()
        tgt = str(raw.get("target_node_id") or "").strip()
        ext_s = str(raw.get("target_external_ref") or "").strip()
        conf = str(raw.get("confidence") or "").strip().lower()
        cb = str(raw.get("created_by") or "").strip()

        use_pending = False
        if conf == "low" and cb == "llm_inferred":
            use_pending = True
        if ext_s:
            use_pending = True

        if use_pending:
            pid = _edge_id_for_link(namespace, f"pend:{link_id}")
            claim = json.dumps(dict(raw), ensure_ascii=False)
            write.insert_pending_link_claim(
                namespace=namespace,
                pending_id=pid,
                from_node_id=src,
                relation=lt,
                target_name=(tgt or ext_s)[:512],
                target_kind="external" if ext_s else "internal",
                path_hint=str(raw.get("source_path") or "")[:512],
                language="",
                confidence=_confidence_to_float(conf),
                claim_json=claim[:50_000],
            )
            return ("pending", link_id, pid)

        edge_class, edge_type = _map_link_type_to_pag(lt)
        eid = _edge_id_for_link(namespace, link_id)
        write.upsert_edge(
            namespace=namespace,
            edge_id=eid,
            edge_class=edge_class,
            edge_type=edge_type,
            from_node_id=src,
            to_node_id=tgt,
            confidence=_confidence_to_float(conf),
            source_contract=_SOURCE_CONTRACT,
        )
        return ("edge", link_id, eid)
