"""C↔C link claims → реальные pag_edges или pending (G12.8, G13.5, D13.7)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from agent_memory.storage.sqlite_pag import (
    PagNode,
    PagPendingLinkClaim,
    SqlitePagStore,
)
from agent_memory.contracts.agent_memory_contracts import SemanticLinkClaim
from agent_memory.pag.pag_graph_write_service import PagGraphWriteService

SEMANTIC_LINK_RELATION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "calls",
        "imports",
        "implements",
        "configures",
        "reads",
        "writes",
        "tests",
        "documents",
        "depends_on",
        "summarizes",
        "related_to",
    },
)

LINK_RELATION_LEGACY_ALIASES: Final[dict[str, str]] = {
    "imports_symbol": "imports",
    "references": "related_to",
    "cross_link": "related_to",
}

MVP_LINK_RELATIONS: Final[frozenset[str]] = SEMANTIC_LINK_RELATION_TYPES

SOURCE_CONTRACT: Final[str] = "ailit_semantic_link_claim_v1"
EDGE_CLASS_SEMANTIC: Final[str] = "semantic"


def normalize_semantic_link_relation_type(raw: object) -> str:
    """
    LLM-строка → один enum.

    Пусто → ``""``; неизвестное непустое → ``related_to``.
    """
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    aliased = LINK_RELATION_LEGACY_ALIASES.get(s)
    if aliased is not None:
        return aliased
    if s in SEMANTIC_LINK_RELATION_TYPES:
        return s
    return "related_to"


@dataclass(frozen=True, slots=True)
class LinkResolveResult:
    """Итог обработки одного claim (тесты и логи)."""

    path: str
    reason: str
    edge_id: str = ""
    pending_id: str = ""


class LinkClaimResolver:
    """``link_claims`` → ``pag_edges`` или ``pag_pending_edges``."""

    def _norm_path(self, raw: str) -> str:
        s = str(raw or "").replace("\\", "/").strip().lstrip("./")
        return s

    def _norm_name(self, raw: str) -> str:
        return str(raw or "").strip()

    def _edge_id(self, relation: str, from_id: str, to_id: str) -> str:
        rel = str(relation or "related_to").strip() or "related_to"
        base = f"link:{rel}:{from_id}->{to_id}"
        if len(base) <= 220:
            return base
        h = hashlib.sha256(
            base.encode("utf-8", errors="replace"),
        ).hexdigest()[:40]
        return f"link:{rel}:{h}"

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

    def _parse_confidence(self, claim: Mapping[str, Any]) -> float:
        try:
            return float(claim.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _semantic_dto(
        self,
        claim: Mapping[str, Any],
        *,
        relation: str,
        from_node_id: str,
    ) -> SemanticLinkClaim:
        f_sk = str(claim.get("from_stable_key", "") or "").strip()
        t_sk = str(claim.get("to_stable_key", "") or "").strip()
        f_nid = str(claim.get("from_node_id", "") or "").strip()
        t_nid = str(claim.get("to_node_id", "") or "").strip()
        raw_from: Any = claim.get("from")
        if isinstance(raw_from, dict):
            f_sk = f_sk or str(raw_from.get("stable_key", "") or "").strip()
            f_nid = f_nid or str(raw_from.get("node_id", "") or "").strip()
        if not f_nid:
            f_nid = from_node_id
        ev = str(claim.get("evidence_summary", "") or "")[:2_000]
        sreq = str(claim.get("source_request_id", "") or "")[:512]
        return SemanticLinkClaim(
            from_stable_key=f_sk,
            from_node_id=f_nid,
            to_stable_key=t_sk,
            to_node_id=t_nid,
            relation_type=relation,
            confidence=self._parse_confidence(claim),
            evidence_summary=ev,
            source_request_id=sreq,
        )

    def _resolve_from_c(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        claim: Mapping[str, Any],
    ) -> tuple[PagNode | None, str]:
        from_id = str(claim.get("from_node_id", "") or "").strip()
        from_sk = str(claim.get("from_stable_key", "") or "").strip()
        raw_from: Any = claim.get("from")
        if isinstance(raw_from, dict):
            from_id = from_id or str(
                raw_from.get("node_id", "") or "",
            ).strip()
            from_sk = from_sk or str(
                raw_from.get("stable_key", "") or "",
            ).strip()

        if from_id:
            src = store.fetch_node(namespace=namespace, node_id=from_id)
            if src is None:
                return None, "missing_from_node"
            if str(src.level) != "C":
                return None, "from_not_c_level"
            return src, ""
        if from_sk:
            cands = store.list_c_nodes_by_stable_key(
                namespace=namespace,
                stable_key=from_sk,
            )
            if len(cands) == 1:
                return cands[0], ""
            if not cands:
                return None, "missing_from_node"
            return None, "ambiguous_from"
        return None, "missing_from_node"

    def _find_target_nodes(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        path_hint: str,
        target_name: str,
        target_kind: str,
    ) -> list[PagNode]:
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
            if out:
                return out
        return store.list_c_nodes_by_kind_title(
            namespace=namespace,
            kind=target_kind,
            title=name,
            limit=50,
        )

    def _upsert_semantic_edge(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        relation: str,
        from_node_id: str,
        to_id: str,
        confidence: float,
    ) -> str:
        eid = self._edge_id(relation, from_node_id, to_id)
        pag.upsert_edge(
            namespace=namespace,
            edge_id=eid,
            edge_class=EDGE_CLASS_SEMANTIC,
            edge_type=str(relation),
            from_node_id=from_node_id,
            to_node_id=to_id,
            confidence=float(max(0.0, min(1.0, confidence))),
            source_contract=SOURCE_CONTRACT,
        )
        return eid

    def _try_target_search(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        from_node_id: str,
        relation: str,
        path_hint: str,
        target_name: str,
        target_kind: str,
        confidence: float,
    ) -> str | None:
        to_nodes = self._find_target_nodes(
            pag.store,
            namespace=namespace,
            path_hint=path_hint,
            target_name=target_name,
            target_kind=target_kind,
        )
        if len(to_nodes) == 1:
            return self._upsert_semantic_edge(
                pag,
                namespace=namespace,
                relation=relation,
                from_node_id=from_node_id,
                to_id=to_nodes[0].node_id,
                confidence=confidence,
            )
        return None

    def _insert_pending(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        pending_id: str,
        from_node_id: str,
        relation: str,
        target_name: str,
        target_kind: str,
        path_hint: str,
        language: str,
        confidence: float,
        claim: Mapping[str, Any],
    ) -> None:
        cj = json.dumps(dict(claim), ensure_ascii=False, sort_keys=True)
        store.insert_pending_link_claim(
            namespace=namespace,
            pending_id=pending_id,
            from_node_id=from_node_id,
            relation=relation,
            target_name=target_name,
            target_kind=target_kind,
            path_hint=path_hint,
            language=language,
            confidence=confidence,
            claim_json=cj,
        )

    def process_claim_dict(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        claim: Mapping[str, Any],
    ) -> LinkResolveResult:
        """Один элемент ``link_claims[]`` (сырой dict)."""
        ns = str(namespace or "").strip()
        if not ns:
            return LinkResolveResult(path="skipped", reason="empty_namespace")

        raw_rel = (
            claim.get("relation_type")
            if claim.get("relation_type") is not None
            else claim.get("relation", "")
        )
        rel = normalize_semantic_link_relation_type(raw_rel)
        if not rel:
            return LinkResolveResult(path="skipped", reason="empty_relation")

        store = pag.store
        from_src, from_err = self._resolve_from_c(
            store,
            namespace=ns,
            claim=claim,
        )
        if from_src is None:
            r = "missing_from_node"
            if from_err in ("from_not_c_level", "ambiguous_from"):
                r = from_err
            return LinkResolveResult(path="skipped", reason=r)
        from_id = from_src.node_id
        _ = self._semantic_dto(claim, relation=rel, from_node_id=from_id)
        conf = self._parse_confidence(claim)

        to_id_raw = str(claim.get("to_node_id", "") or "").strip()
        if to_id_raw:
            to = store.fetch_node(namespace=ns, node_id=to_id_raw)
            if to is not None and str(to.level) == "C":
                eid = self._upsert_semantic_edge(
                    pag,
                    namespace=ns,
                    relation=rel,
                    from_node_id=from_id,
                    to_id=to_id_raw,
                    confidence=conf,
                )
                return LinkResolveResult(
                    path="resolved",
                    reason="explicit_to",
                    edge_id=eid,
                )
        to_sk = str(claim.get("to_stable_key", "") or "").strip()
        if to_sk:
            t_nodes = store.list_c_nodes_by_stable_key(
                namespace=ns,
                stable_key=to_sk,
            )
            if len(t_nodes) == 1:
                eid = self._upsert_semantic_edge(
                    pag,
                    namespace=ns,
                    relation=rel,
                    from_node_id=from_id,
                    to_id=t_nodes[0].node_id,
                    confidence=conf,
                )
                return LinkResolveResult(
                    path="resolved",
                    reason="resolved_by_to_stable_key",
                    edge_id=eid,
                )
            if len(t_nodes) > 1:
                tr: Any = claim.get("target", {})
                tname, tkind, ph, lang = _pending_tuple_from_target(tr, claim)
                pid = self._stable_pending_id(
                    namespace=ns,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    path_hint=ph,
                )
                self._insert_pending(
                    store,
                    namespace=ns,
                    pending_id=pid,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    target_kind=tkind,
                    path_hint=ph,
                    language=lang,
                    confidence=conf,
                    claim=claim,
                )
                return LinkResolveResult(
                    path="pending",
                    reason="ambiguous_target",
                    pending_id=pid,
                )
            # to_sk, 0 matches — target search
        traw: Any = claim.get("target", {})
        if not isinstance(traw, dict) and to_id_raw:
            tname, tkind, ph, lang = _pending_tuple_missing_explicit_to()
            if to_id_raw:
                pid = self._stable_pending_id(
                    namespace=ns,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    path_hint=ph,
                )
                self._insert_pending(
                    store,
                    namespace=ns,
                    pending_id=pid,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    target_kind=tkind,
                    path_hint=ph,
                    language=lang,
                    confidence=conf,
                    claim=claim,
                )
                return LinkResolveResult(
                    path="pending",
                    reason="no_target",
                    pending_id=pid,
                )
            return LinkResolveResult(
                path="skipped",
                reason="bad_target",
            )
        if not isinstance(traw, dict):
            return LinkResolveResult(
                path="skipped",
                reason="bad_target",
            )
        tname = str(traw.get("name", "") or "").strip()
        tkind = str(traw.get("kind", "") or "").strip()
        ph = str(traw.get("path_hint", "") or "").strip()
        lang = str(traw.get("language", "") or "").strip()
        if not tname or not tkind:
            if to_id_raw:
                tname, tkind, ph, lang = _pending_tuple_missing_explicit_to()
                pending_id = self._stable_pending_id(
                    namespace=ns,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    path_hint=ph,
                )
                self._insert_pending(
                    store,
                    namespace=ns,
                    pending_id=pending_id,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    target_kind=tkind,
                    path_hint=ph,
                    language=lang,
                    confidence=conf,
                    claim=claim,
                )
                return LinkResolveResult(
                    path="pending",
                    reason="no_target",
                    pending_id=pending_id,
                )
            return LinkResolveResult(
                path="skipped",
                reason="missing_target_name_or_kind",
            )
        eid2 = self._try_target_search(
            pag,
            namespace=ns,
            from_node_id=from_id,
            relation=rel,
            path_hint=ph,
            target_name=tname,
            target_kind=tkind,
            confidence=conf,
        )
        if eid2:
            return LinkResolveResult(
                path="resolved",
                reason="unique_target",
                edge_id=eid2,
            )
        cands = self._find_target_nodes(
            store,
            namespace=ns,
            path_hint=ph,
            target_name=tname,
            target_kind=tkind,
        )
        reason = "ambiguous_target" if len(cands) > 1 else "no_target"
        pending_id = self._stable_pending_id(
            namespace=ns,
            from_node_id=from_id,
            relation=rel,
            target_name=tname,
            path_hint=ph,
        )
        self._insert_pending(
            store,
            namespace=ns,
            pending_id=pending_id,
            from_node_id=from_id,
            relation=rel,
            target_name=tname,
            target_kind=tkind,
            path_hint=ph,
            language=lang,
            confidence=conf,
            claim=claim,
        )
        return LinkResolveResult(
            path="pending",
            reason=reason,
            pending_id=pending_id,
        )

    def apply_link_claims(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        claims: Sequence[Mapping[str, Any]],
    ) -> list[LinkResolveResult]:
        """
        Список claims: batch resolved edges, затем ``resolve_all_pending``.
        """
        out: list[LinkResolveResult] = []
        batch_edges: list[Mapping[str, Any]] = []
        ns = str(namespace or "").strip()
        for c in claims:
            if not isinstance(c, dict):
                out.append(
                    LinkResolveResult(
                        path="skipped",
                        reason="not_a_dict",
                    ),
                )
                continue
            res, edge = self._process_claim_collect_edge(
                pag,
                namespace=ns,
                claim=c,
            )
            out.append(res)
            if edge is not None:
                batch_edges.append(edge)
        if batch_edges:
            pag.upsert_edges_batch(namespace=ns, edges=batch_edges)
        self.resolve_all_pending(
            pag,
            namespace=namespace,
        )
        return out

    def _process_claim_collect_edge(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        claim: Mapping[str, Any],
    ) -> tuple[LinkResolveResult, dict[str, Any] | None]:
        """
        Как ``process_claim_dict``, но с записью в БД Только pending/skip
        (resolved edge возвращается снаружи для batch).
        """
        ns = str(namespace or "").strip()
        if not ns:
            return (
                LinkResolveResult(path="skipped", reason="empty_namespace"),
                None,
            )
        raw_rel = (
            claim.get("relation_type")
            if claim.get("relation_type") is not None
            else claim.get("relation", "")
        )
        rel = normalize_semantic_link_relation_type(raw_rel)
        if not rel:
            return (
                LinkResolveResult(path="skipped", reason="empty_relation"),
                None,
            )
        store = pag.store
        from_src, from_err = self._resolve_from_c(
            store,
            namespace=ns,
            claim=claim,
        )
        if from_src is None:
            r = "missing_from_node"
            if from_err in ("from_not_c_level", "ambiguous_from"):
                r = from_err
            return (LinkResolveResult(path="skipped", reason=r), None)
        from_id = from_src.node_id
        _ = self._semantic_dto(claim, relation=rel, from_node_id=from_id)
        conf = self._parse_confidence(claim)

        def edge_row(
            *,
            to_id: str,
        ) -> dict[str, Any]:
            eid = self._edge_id(rel, from_id, to_id)
            return {
                "edge_id": eid,
                "edge_class": EDGE_CLASS_SEMANTIC,
                "edge_type": str(rel),
                "from_node_id": from_id,
                "to_node_id": to_id,
                "confidence": float(max(0.0, min(1.0, conf))),
                "source_contract": SOURCE_CONTRACT,
            }

        to_id_raw = str(claim.get("to_node_id", "") or "").strip()
        if to_id_raw:
            to = store.fetch_node(namespace=ns, node_id=to_id_raw)
            if to is not None and str(to.level) == "C":
                er = edge_row(to_id=to_id_raw)
                eid = str(er.get("edge_id", "") or "")
                return (
                    LinkResolveResult(
                        path="resolved",
                        reason="explicit_to",
                        edge_id=eid,
                    ),
                    er,
                )
        to_sk = str(claim.get("to_stable_key", "") or "").strip()
        if to_sk:
            t_nodes = store.list_c_nodes_by_stable_key(
                namespace=ns,
                stable_key=to_sk,
            )
            if len(t_nodes) == 1:
                er = edge_row(to_id=t_nodes[0].node_id)
                eid = str(er.get("edge_id", "") or "")
                return (
                    LinkResolveResult(
                        path="resolved",
                        reason="resolved_by_to_stable_key",
                        edge_id=eid,
                    ),
                    er,
                )
            if len(t_nodes) > 1:
                tr2: Any = claim.get("target", {})
                tname, tkind, ph, lang = _pending_tuple_from_target(tr2, claim)
                pid = self._stable_pending_id(
                    namespace=ns,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    path_hint=ph,
                )
                self._insert_pending(
                    store,
                    namespace=ns,
                    pending_id=pid,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    target_kind=tkind,
                    path_hint=ph,
                    language=lang,
                    confidence=conf,
                    claim=claim,
                )
                return (
                    LinkResolveResult(
                        path="pending",
                        reason="ambiguous_target",
                        pending_id=pid,
                    ),
                    None,
                )
        traw2: Any = claim.get("target", {})
        if not isinstance(traw2, dict) and to_id_raw:
            tname, tkind, ph, lang = _pending_tuple_missing_explicit_to()
            if to_id_raw:
                pid = self._stable_pending_id(
                    namespace=ns,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    path_hint=ph,
                )
                self._insert_pending(
                    store,
                    namespace=ns,
                    pending_id=pid,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    target_kind=tkind,
                    path_hint=ph,
                    language=lang,
                    confidence=conf,
                    claim=claim,
                )
                return (
                    LinkResolveResult(
                        path="pending",
                        reason="no_target",
                        pending_id=pid,
                    ),
                    None,
                )
            return (
                LinkResolveResult(path="skipped", reason="bad_target"),
                None,
            )
        if not isinstance(traw2, dict):
            return (
                LinkResolveResult(path="skipped", reason="bad_target"),
                None,
            )
        tname2 = str(traw2.get("name", "") or "").strip()
        tkind2 = str(traw2.get("kind", "") or "").strip()
        ph2 = str(traw2.get("path_hint", "") or "").strip()
        lang2 = str(traw2.get("language", "") or "").strip()
        if not tname2 or not tkind2:
            if to_id_raw:
                tname, tkind, ph, lang = _pending_tuple_missing_explicit_to()
                pending_id2 = self._stable_pending_id(
                    namespace=ns,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    path_hint=ph,
                )
                self._insert_pending(
                    store,
                    namespace=ns,
                    pending_id=pending_id2,
                    from_node_id=from_id,
                    relation=rel,
                    target_name=tname,
                    target_kind=tkind,
                    path_hint=ph,
                    language=lang,
                    confidence=conf,
                    claim=claim,
                )
                return (
                    LinkResolveResult(
                        path="pending",
                        reason="no_target",
                        pending_id=pending_id2,
                    ),
                    None,
                )
            return (
                LinkResolveResult(
                    path="skipped",
                    reason="missing_target_name_or_kind",
                ),
                None,
            )
        to_cands2 = self._find_target_nodes(
            store,
            namespace=ns,
            path_hint=ph2,
            target_name=tname2,
            target_kind=tkind2,
        )
        if len(to_cands2) == 1:
            er2 = edge_row(to_id=to_cands2[0].node_id)
            eid2 = str(er2.get("edge_id", "") or "")
            return (
                LinkResolveResult(
                    path="resolved",
                    reason="unique_target",
                    edge_id=eid2,
                ),
                er2,
            )
        reas = "ambiguous_target" if len(to_cands2) > 1 else "no_target"
        pid2 = self._stable_pending_id(
            namespace=ns,
            from_node_id=from_id,
            relation=rel,
            target_name=tname2,
            path_hint=ph2,
        )
        self._insert_pending(
            store,
            namespace=ns,
            pending_id=pid2,
            from_node_id=from_id,
            relation=rel,
            target_name=tname2,
            target_kind=tkind2,
            path_hint=ph2,
            language=lang2,
            confidence=conf,
            claim=claim,
        )
        return (
            LinkResolveResult(
                path="pending",
                reason=reas,
                pending_id=pid2,
            ),
            None,
        )

    def resolve_all_pending(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        max_passes: int = 12,
    ) -> int:
        """Скан pending; batch ``upsert_edges`` при разрешимых целях."""
        ns = str(namespace or "").strip()
        if not ns:
            return 0
        store = pag.store
        total_resolved = 0
        for _ in range(max(1, int(max_passes))):
            rows = store.list_pending_link_claims(namespace=ns)
            if not rows:
                break
            to_apply: list[Mapping[str, Any]] = []
            pids: list[str] = []
            for row in rows:
                ok, er = self._pending_to_edge(
                    store,
                    namespace=ns,
                    row=row,
                )
                if ok and er is not None:
                    to_apply.append(er)
                    pids.append(row.pending_id)
            if not to_apply:
                break
            pag.upsert_edges_batch(namespace=ns, edges=to_apply)
            for p in pids:
                store.delete_pending_link_claim(
                    namespace=ns,
                    pending_id=p,
                )
            total_resolved += len(pids)
        return total_resolved

    def _pending_to_edge(
        self,
        store: SqlitePagStore,
        *,
        namespace: str,
        row: PagPendingLinkClaim,
    ) -> tuple[bool, dict[str, Any] | None]:
        rel = normalize_semantic_link_relation_type(row.relation)
        to_nodes = self._find_target_nodes(
            store,
            namespace=namespace,
            path_hint=row.path_hint,
            target_name=row.target_name,
            target_kind=row.target_kind,
        )
        if len(to_nodes) != 1:
            return False, None
        eid = self._edge_id(rel, row.from_node_id, to_nodes[0].node_id)
        return True, {
            "edge_id": eid,
            "edge_class": EDGE_CLASS_SEMANTIC,
            "edge_type": str(rel),
            "from_node_id": row.from_node_id,
            "to_node_id": to_nodes[0].node_id,
            "confidence": float(
                max(0.0, min(1.0, float(row.confidence or 0.0))),
            ),
            "source_contract": SOURCE_CONTRACT,
        }

    def rehydrate_from_pending_row(
        self,
        pag: PagGraphWriteService,
        *,
        namespace: str,
        row: PagPendingLinkClaim,
    ) -> bool:
        """Публичный helper: resolve одной pending-строки (тесты)."""
        store = pag.store
        ok, er = self._pending_to_edge(
            store,
            namespace=namespace,
            row=row,
        )
        if not ok or er is None:
            return False
        pag.upsert_edges_batch(namespace=namespace, edges=[er])
        store.delete_pending_link_claim(
            namespace=namespace,
            pending_id=row.pending_id,
        )
        return True


def _pending_tuple_from_target(
    tr: object,
    claim: Mapping[str, Any],
) -> tuple[str, str, str, str]:
    if isinstance(tr, dict):
        tname = str(tr.get("name", "") or "").strip() or "_"
        tkind = str(tr.get("kind", "") or "").strip() or "_"
        ph = str(tr.get("path_hint", "") or "").strip()
        lang = str(tr.get("language", "") or "").strip()
        return tname, tkind, ph, lang
    _ = claim
    return _pending_tuple_missing_explicit_to()


def _pending_tuple_missing_explicit_to() -> tuple[str, str, str, str]:
    return (
        "(pending_to)",
        "unresolved",
        "",
        "",
    )
