"""C↔C link claims → real pag_edges или pending (G12.8)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from agent_core.memory.sqlite_pag import (
    PagNode,
    PagPendingLinkClaim,
    SqlitePagStore,
)

MVP_LINK_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        "calls",
        "imports_symbol",
        "references",
        "documents",
        "configures",
        "tests",
    },
)


@dataclass(frozen=True, slots=True)
class LinkResolveResult:
    """Итог обработки одного claim (для тестов и логов)."""

    path: str  # "resolved" | "pending" | "skipped"
    reason: str
    edge_id: str = ""
    pending_id: str = ""


class LinkClaimResolver:
    """LLM link_claims → edges или pag_pending_edges (без псевдонод в UI)."""

    def _norm_path(self, raw: str) -> str:
        s = str(raw or "").replace("\\", "/").strip().lstrip("./")
        return s

    def _norm_name(self, raw: str) -> str:
        return str(raw or "").strip()

    def _edge_id(self, relation: str, from_id: str, to_id: str) -> str:
        base = f"link:{relation}:{from_id}->{to_id}"
        if len(base) <= 220:
            return base
        h = hashlib.sha256(
            base.encode("utf-8", errors="replace"),
        ).hexdigest()[:40]
        return f"link:{relation}:{h}"

    def _stable_pending_id(
        self,
        *,
        namespace: str,
        from_node_id: str,
        relation: str,
        target_name: str,
        path_hint: str,
    ) -> str:
        key = {
            "ns": namespace,
            "from": from_node_id,
            "rel": relation,
            "name": target_name,
            "path": path_hint,
        }
        d = json.dumps(key, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha256(d.encode("utf-8")).hexdigest()[:32]
        return f"pnd:{h}"

    def _find_target_nodes(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        path_hint: str,
        target_name: str,
        target_kind: str,
    ) -> list[PagNode]:
        """1) path + title; 2) kind+title в namespace (план G12.8)."""
        name = self._norm_name(target_name)
        ph = self._norm_path(path_hint)
        if ph:
            cands = store.list_nodes_for_path(
                namespace=namespace,
                path=ph,
                level="C",
                limit=2_000,
            )
            out = [
                n
                for n in cands
                if n.title.strip().casefold() == name.casefold()
            ]
            if len(out) != 0:
                return out
        return store.list_c_nodes_by_kind_title(
            namespace=namespace,
            kind=target_kind,
            title=name,
            limit=50,
        )

    def _try_resolve_one(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        from_node_id: str,
        relation: str,
        path_hint: str,
        target_name: str,
        target_kind: str,
        confidence: float,
    ) -> tuple[bool, str]:
        to_nodes = self._find_target_nodes(
            store,
            namespace=namespace,
            path_hint=path_hint,
            target_name=target_name,
            target_kind=target_kind,
        )
        if len(to_nodes) == 1:
            to_id = to_nodes[0].node_id
            eid = self._edge_id(relation, from_node_id, to_id)
            store.upsert_edge(
                namespace=namespace,
                edge_id=eid,
                edge_class="cross_link",
                edge_type=relation,
                from_node_id=from_node_id,
                to_node_id=to_id,
                confidence=float(max(0.0, min(1.0, confidence))),
                source_contract="ailit_link_claim_mvp_v1",
            )
            return True, eid
        return False, ""

    def process_claim_dict(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        claim: Mapping[str, Any],
    ) -> LinkResolveResult:
        """Один элемент `link_claims[]` (сырой dict от LLM)."""
        ns = str(namespace or "").strip()
        if not ns:
            return LinkResolveResult(
                path="skipped",
                reason="empty_namespace",
            )
        raw_from: Any = claim.get("from")
        from_id = ""
        if isinstance(raw_from, dict):
            from_id = str(raw_from.get("node_id", "") or "").strip()
        if not from_id:
            return LinkResolveResult(
                path="skipped",
                reason="missing_from_node_id",
            )
        src = store.fetch_node(namespace=ns, node_id=from_id)
        if src is None or str(src.level) != "C":
            return LinkResolveResult(
                path="skipped",
                reason="from_not_c_level",
            )
        rel = str(claim.get("relation", "") or "").strip()
        if rel not in MVP_LINK_RELATIONS:
            return LinkResolveResult(
                path="skipped",
                reason="unsupported_relation",
            )
        target_raw: Any = claim.get("target", {})
        if not isinstance(target_raw, dict):
            return LinkResolveResult(
                path="skipped",
                reason="bad_target",
            )
        tname = str(target_raw.get("name", "") or "").strip()
        tkind = str(target_raw.get("kind", "") or "").strip()
        ph = str(target_raw.get("path_hint", "") or "").strip()
        lang = str(target_raw.get("language", "") or "").strip()
        try:
            conf = float(claim.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if not tname or not tkind:
            return LinkResolveResult(
                path="skipped",
                reason="missing_target_name_or_kind",
            )
        ok, eid = self._try_resolve_one(
            store,
            namespace=ns,
            from_node_id=from_id,
            relation=rel,
            path_hint=ph,
            target_name=tname,
            target_kind=tkind,
            confidence=conf,
        )
        if ok and eid:
            return LinkResolveResult(
                path="resolved",
                reason="unique_target",
                edge_id=eid,
            )
        cands = self._find_target_nodes(
            store,
            namespace=ns,
            path_hint=ph,
            target_name=tname,
            target_kind=tkind,
        )
        if len(cands) > 1:
            reason = "ambiguous_target"
        else:
            reason = "no_target"
        pending_id = self._stable_pending_id(
            namespace=ns,
            from_node_id=from_id,
            relation=rel,
            target_name=tname,
            path_hint=ph,
        )
        cj = json.dumps(dict(claim), ensure_ascii=False, sort_keys=True)
        store.insert_pending_link_claim(
            namespace=ns,
            pending_id=pending_id,
            from_node_id=from_id,
            relation=rel,
            target_name=tname,
            target_kind=tkind,
            path_hint=ph,
            language=lang,
            confidence=conf,
            claim_json=cj,
        )
        return LinkResolveResult(
            path="pending",
            reason=reason,
            pending_id=pending_id,
        )

    def apply_link_claims(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        claims: Sequence[Mapping[str, Any]],
    ) -> list[LinkResolveResult]:
        """Список claims из extractor; затем resolve pending (новые C)."""
        out: list[LinkResolveResult] = []
        for c in claims:
            if not isinstance(c, dict):
                out.append(
                    LinkResolveResult(
                        path="skipped",
                        reason="not_a_dict",
                    ),
                )
                continue
            out.append(
                self.process_claim_dict(
                    store,
                    namespace=namespace,
                    claim=c,
                ),
            )
        self.resolve_all_pending(
            store,
            namespace=namespace,
        )
        return out

    def resolve_all_pending(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        max_passes: int = 12,
    ) -> int:
        """Повторно проверяет `pag_pending_edges` (п.6 G12.8)."""
        ns = str(namespace or "").strip()
        if not ns:
            return 0
        total_resolved = 0
        for _ in range(max(1, int(max_passes))):
            rows = store.list_pending_link_claims(namespace=ns)
            if not rows:
                break
            progress = 0
            for row in rows:
                ok, eid = self._try_resolve_one(
                    store,
                    namespace=ns,
                    from_node_id=row.from_node_id,
                    relation=row.relation,
                    path_hint=row.path_hint,
                    target_name=row.target_name,
                    target_kind=row.target_kind,
                    confidence=row.confidence,
                )
                if ok and eid:
                    store.delete_pending_link_claim(
                        namespace=ns,
                        pending_id=row.pending_id,
                    )
                    total_resolved += 1
                    progress += 1
            if progress == 0:
                break
        return total_resolved

    def rehydrate_from_pending_row(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        row: PagPendingLinkClaim,
    ) -> bool:
        """Публичный helper: resolve одной pending-строки (тесты)."""
        ok, eid = self._try_resolve_one(
            store,
            namespace=namespace,
            from_node_id=row.from_node_id,
            relation=row.relation,
            path_hint=row.path_hint,
            target_name=row.target_name,
            target_kind=row.target_kind,
            confidence=row.confidence,
        )
        if ok and eid:
            store.delete_pending_link_claim(
                namespace=namespace,
                pending_id=row.pending_id,
            )
        return bool(ok and eid)
