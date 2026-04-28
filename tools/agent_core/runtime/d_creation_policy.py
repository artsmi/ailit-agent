"""D creation policy and query_digest upsert (G12.9)."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final, Literal, Sequence

from agent_core.memory.sqlite_pag import PagGraphTraceFn
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService
from agent_core.runtime.agent_memory_config import DPolicySubConfig

_GATE = Literal["created", "reused", "skipped"]

_RE_SPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


def normalize_summary_for_d_fingerprint(raw: str) -> str:
    """Нормализация summary для D.fingerprint (G12.9)."""
    t = (raw or "").strip().lower()
    t = _RE_SPACE.sub(" ", t)
    return t


@dataclass(frozen=True, slots=True)
class DCreationOutcome:
    """Результат D-gate на один memory.query_context."""

    gate: _GATE
    reason: str
    d_node_id: str | None
    d_fingerprint: str


def d_fingerprint(
    kind: str,
    summary: str,
    linked_node_ids: Sequence[str],
) -> str:
    """
    D.fingerprint = sha256(
        kind + normalized_summary + sorted(linked_node_ids)
    ) (G12.9).
    """
    s_norm = normalize_summary_for_d_fingerprint(summary)
    uniq = sorted({str(x).strip() for x in linked_node_ids if str(x).strip()})
    body = (
        f"{str(kind).strip()}|{s_norm}|"
        + json.dumps(uniq, ensure_ascii=False)
    )
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()


class DCreationPolicy:
    """Политика: не плодить D на внутренние шаги, dedupe по fingerprint."""

    def __init__(self, d_policy: DPolicySubConfig) -> None:
        self._d_policy = d_policy

    def _linked_tier_abc(
        self,
        node_ids: Sequence[str],
        *,
        namespace: str,
    ) -> list[str]:
        out: list[str] = []
        for raw in node_ids:
            s = str(raw or "").strip()
            if s.startswith("A:") or s.startswith("B:") or s.startswith("C:"):
                out.append(s)
        a_tag = f"A:{namespace}"
        if a_tag not in out and namespace:
            out.insert(0, a_tag)
        uniq: list[str] = []
        seen: set[str] = set()
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq

    def _count_d_in_ids(self, node_ids: Sequence[str]) -> int:
        return sum(1 for n in node_ids if str(n).strip().startswith("D:"))

    def maybe_upsert_query_digest(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        goal: str,
        node_ids: Sequence[str],
        graph_trace_hook: PagGraphTraceFn | None = None,
    ) -> DCreationOutcome:
        """
        Создать/переиспользовать D `query_digest` согласно d_policy.
        """
        ns = str(namespace or "").strip()
        if not ns:
            return DCreationOutcome(
                gate="skipped",
                reason="empty_namespace",
                d_node_id=None,
                d_fingerprint="",
            )
        pol = self._d_policy
        kind = "query_digest"
        if str(kind) not in set(pol.allowed_kinds):
            return DCreationOutcome(
                gate="skipped",
                reason="kind_not_allowed",
                d_node_id=None,
                d_fingerprint="",
            )
        linked = self._linked_tier_abc(node_ids, namespace=ns)
        if len(linked) < int(pol.min_linked_nodes):
            return DCreationOutcome(
                gate="skipped",
                reason="min_linked_not_met",
                d_node_id=None,
                d_fingerprint="",
            )
        if self._count_d_in_ids(node_ids) >= int(pol.max_d_per_query) > 0:
            return DCreationOutcome(
                gate="skipped",
                reason="max_d_per_query_slice",
                d_node_id=None,
                d_fingerprint="",
            )
        g = str(goal or "").strip()[:1_200]
        if not g:
            return DCreationOutcome(
                gate="skipped",
                reason="empty_goal",
                d_node_id=None,
                d_fingerprint="",
            )
        fp = d_fingerprint(kind, g, linked)
        d_id = f"D:query_digest:{fp[:32]}"
        now = datetime.now(timezone.utc).isoformat()
        store = pag.store
        exist = store.fetch_node(namespace=ns, node_id=d_id)
        ctx: Any
        if graph_trace_hook is not None:
            ctx = store.graph_trace(graph_trace_hook)
        else:
            ctx = nullcontext()
        with ctx:
            if exist is not None:
                attrs: dict[str, Any] = dict(exist.attrs)
                attrs["last_used_at"] = now
                attrs["d_policy_fingerprint"] = fp
                pag.upsert_node(
                    namespace=ns,
                    node_id=d_id,
                    level=exist.level,
                    kind=exist.kind,
                    path=exist.path,
                    title=exist.title,
                    summary=exist.summary,
                    attrs=attrs,
                    fingerprint=exist.fingerprint,
                    staleness_state=exist.staleness_state,
                    source_contract=exist.source_contract,
                )
                return DCreationOutcome(
                    gate="reused",
                    reason="fingerprint_matched",
                    d_node_id=d_id,
                    d_fingerprint=fp,
                )
            if int(pol.max_d_per_query) <= 0:
                return DCreationOutcome(
                    gate="skipped",
                    reason="max_d_zero",
                    d_node_id=None,
                    d_fingerprint=fp,
                )
            summary = g[: int(240)]
            attrs2: dict[str, Any] = {
                "d_policy_fingerprint": fp,
                "linked_node_ids": list(linked),
                "last_used_at": now,
                "created_at": now,
            }
            pag.upsert_node(
                namespace=ns,
                node_id=d_id,
                level="D",
                kind=kind,
                path="memory/query_digest",
                title="query_digest",
                summary=summary,
                attrs=attrs2,
                fingerprint=fp,
                staleness_state="fresh",
                source_contract="ailit_agent_memory_d_policy_v1",
            )
            for ref in linked:
                eid = f"{d_id}->from->{ref}"
                pag.upsert_edge(
                    namespace=ns,
                    edge_id=eid,
                    edge_class="provenance",
                    edge_type="derived_from",
                    from_node_id=d_id,
                    to_node_id=ref,
                    confidence=1.0,
                    source_contract="ailit_agent_memory_d_policy_v1",
                )
        return DCreationOutcome(
            gate="created",
            reason="new_digest",
            d_node_id=d_id,
            d_fingerprint=fp,
        )


def enrich_memory_slice_tiered(
    memory_slice: dict[str, Any],
    *,
    namespace: str,
) -> None:
    """In-place: разбивка A/B/C/D, project_ref-friendly ids (G12.9)."""
    ids: list[str] = [
        str(x) for x in (memory_slice.get("node_ids") or []) if str(x).strip()
    ]
    tiered: dict[str, list[str]] = {
        "A": [],
        "B": [],
        "C": [],
        "D": [],
    }
    for nid in ids:
        if nid.startswith("A:"):
            tiered["A"].append(nid)
        elif nid.startswith("B:"):
            tiered["B"].append(nid)
        elif nid.startswith("C:"):
            tiered["C"].append(nid)
        elif nid.startswith("D:"):
            tiered["D"].append(nid)
    memory_slice["a_node_ids"] = tiered["A"]
    memory_slice["b_node_ids"] = tiered["B"]
    memory_slice["c_node_ids"] = tiered["C"]
    memory_slice["d_node_ids"] = tiered["D"]
    memory_slice["backbone_node_ids"] = list(
        dict.fromkeys(
            [f"A:{str(namespace).strip()}", *tiered["B"]],
        ),
    )
    memory_slice["schema_tier"] = "memory.slice.v1+g12.9"
    if str(namespace).strip() and f"A:{namespace}" not in memory_slice.get(
        "a_node_ids",
        [],
    ):
        memory_slice.setdefault("a_node_ids", [])
        a_list = list(memory_slice["a_node_ids"])
        if f"A:{namespace}" not in a_list:
            a_list.insert(0, f"A:{namespace}")
        memory_slice["a_node_ids"] = a_list


def merge_d_into_node_ids(
    node_ids: list[str],
    d_id: str | None,
) -> list[str]:
    if not d_id:
        return list(node_ids)
    out = list(node_ids)
    if d_id not in out:
        out.append(d_id)
    return out
