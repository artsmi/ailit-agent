"""DTO контрактов AgentMemory: planner / extractor / update / synth (G12.6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from agent_memory.agent_memory_config import parse_memory_json_with_retry

EXTRACTION_CONTRACT_VERSION: str = "agent_memory_c.v1"


@dataclass(frozen=True, slots=True)
class MemoryPlannerInputV1:
    """Вход memory LLM planner: компактные кандидаты + бюджет."""

    namespace: str
    goal: str
    project_roots: tuple[str, ...]
    candidate_b_ids: tuple[str, ...] = ()
    max_selected_b: int = 8

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "schema": "agent_memory.planner_input.v1",
            "namespace": self.namespace,
            "goal": self.goal,
            "project_roots": list(self.project_roots),
            "candidate_b_ids": list(self.candidate_b_ids),
            "max_selected_b": int(self.max_selected_b),
        }


@dataclass(frozen=True, slots=True)
class MemorySemanticLocatorV1:
    """Семантический локатор C (язык-агностичный)."""

    kind: str
    raw: Mapping[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        o: dict[str, Any] = {
            "kind": self.kind,
        }
        o.update(dict(self.raw))
        return o

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any] | None,
    ) -> MemorySemanticLocatorV1 | None:
        if not raw:
            return None
        k = str(raw.get("kind", "") or "").strip()
        if not k and "heading_path" in raw:
            k = "md_heading"
        if not k:
            k = "opaque"
        rest = {str(a): b for a, b in raw.items() if a != "kind"}
        return cls(kind=k, raw=rest)


@dataclass(frozen=True, slots=True)
class MemoryLineHintV1:
    """Кэш диапазона строк; не идентичность."""

    start: int
    end: int

    def to_json_dict(self) -> dict[str, int]:
        return {"start": int(self.start), "end": int(self.end)}

    @classmethod
    def from_json(cls, raw: object) -> MemoryLineHintV1 | None:
        if not isinstance(raw, dict):
            return None
        try:
            a = int(raw.get("start", 0) or 0)
            b = int(raw.get("end", 0) or 0)
        except (TypeError, ValueError):
            return None
        if a < 1 or b < 1:
            return None
        return cls(start=a, end=max(a, b))


@dataclass(frozen=True, slots=True)
class MemoryCNodePayloadV1:
    """C-нода: stable_key + semantic_locator + отпечатки (G12.6, G13.4)."""

    stable_key: str
    semantic_locator: MemorySemanticLocatorV1 | None
    line_hint: MemoryLineHintV1 | None
    kind: str
    title: str
    summary: str
    content_fingerprint: str
    summary_fingerprint: str
    b_fingerprint: str
    confidence: float
    staleness_state: str
    extraction_contract_version: str = EXTRACTION_CONTRACT_VERSION
    b_node_id: str = ""
    source_boundary_decision: str = ""
    aliases: tuple[str, ...] = ()

    def to_pag_attrs(self) -> dict[str, Any]:
        if self.semantic_locator is not None:
            loc = self.semantic_locator.to_json_dict()
        else:
            loc = None
        lh = self.line_hint.to_json_dict() if self.line_hint else None
        o: dict[str, Any] = {
            "stable_key": self.stable_key,
            "semantic_locator": loc,
            "line_hint": lh,
            "content_fingerprint": self.content_fingerprint,
            "summary_fingerprint": self.summary_fingerprint,
            "b_fingerprint": self.b_fingerprint,
            "confidence": float(self.confidence),
            "extraction_contract_version": self.extraction_contract_version,
        }
        if self.b_node_id:
            o["b_node_id"] = self.b_node_id
        if self.source_boundary_decision:
            o["source_boundary_decision"] = self.source_boundary_decision
        if self.aliases:
            o["aliases"] = list(self.aliases)
        return o


@dataclass(frozen=True, slots=True)
class SemanticLinkClaim:
    """
    Утверждение о семантической связи между C-нодами (G13.5, D13.7).
    До resolution хранится в ``pag_pending_edges``, не в ``pag_edges``.
    """

    from_stable_key: str
    from_node_id: str
    to_stable_key: str
    to_node_id: str
    relation_type: str
    confidence: float
    evidence_summary: str
    source_request_id: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema": "agent_memory.semantic_link_claim.v1",
            "from_stable_key": self.from_stable_key,
            "from_node_id": self.from_node_id,
            "to_stable_key": self.to_stable_key,
            "to_node_id": self.to_node_id,
            "relation_type": self.relation_type,
            "confidence": float(self.confidence),
            "evidence_summary": self.evidence_summary,
            "source_request_id": self.source_request_id,
        }


@dataclass(frozen=True, slots=True)
class MemoryExtractorInputV1:
    """Вход extractor: полный B или ссылка на мех. каталог чанков."""

    b_path: str
    b_text: str
    b_fingerprint: str
    full_b: bool
    chunk_catalog: tuple[Mapping[str, Any], ...] = ()
    namespace: str = ""

    def to_prompt_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "schema": "agent_memory.extractor_input.v1",
            "namespace": self.namespace,
            "b_path": self.b_path,
            "b_fingerprint": self.b_fingerprint,
            "full_b": self.full_b,
            "chunk_catalog": [dict(x) for x in self.chunk_catalog],
        }
        if self.full_b:
            base["b_text"] = self.b_text
        else:
            base["b_text_omitted"] = (
                "<omitted — use chunk_catalog chunk_ids>"
            )
        return base


@dataclass(frozen=True, slots=True)
class MemoryExtractorResultV1:
    """Результат extractor: только структурированные C-ноды + claims."""

    source_b_path: str
    nodes: tuple[MemoryCNodePayloadV1, ...]
    link_claims: tuple[Mapping[str, Any], ...]
    decision: str

    @classmethod
    def from_llm_json(
        cls,
        text: str,
    ) -> MemoryExtractorResultV1:
        """Разбор agent_memory.extractor_result.v1 (без сырого reasoning)."""
        raw: dict[str, Any] = parse_memory_json_with_retry(text)
        sch = str(raw.get("schema", "") or "")
        bad_sch = "extractor" not in sch and sch != (
            "agent_memory.extractor_result.v1"
        )
        if sch and bad_sch:
            raise ValueError("unexpected extractor schema id")
        src = str(raw.get("source", "") or raw.get("source_b", "") or "")
        nodes_in: Any = raw.get("nodes", [])
        if not isinstance(nodes_in, list):
            nodes_in = []
        out_nodes: list[MemoryCNodePayloadV1] = []
        for n in nodes_in[:500]:
            if not isinstance(n, dict):
                continue
            if str(n.get("level", "C") or "C") != "C":
                continue
            sk = str(n.get("stable_key", "") or "").strip()
            if not sk:
                continue
            sl = MemorySemanticLocatorV1.from_mapping(
                n.get("semantic_locator")
                if isinstance(n.get("semantic_locator"), dict)
                else None,
            )
            if sl is None:
                continue
            lh = MemoryLineHintV1.from_json(n.get("line_hint", {}))
            ali_raw = n.get("aliases", [])
            aliases_t: tuple[str, ...] = ()
            if isinstance(ali_raw, list):
                aliases_t = tuple(
                    str(x).strip() for x in ali_raw if str(x).strip()
                )[:64]
            cf = str(n.get("content_fingerprint", "") or "")
            sbd = str(n.get("source_boundary_decision", "") or "")[:500]
            out_nodes.append(
                MemoryCNodePayloadV1(
                    stable_key=sk,
                    semantic_locator=sl,
                    line_hint=lh,
                    kind=str(n.get("kind", "") or "chunk"),
                    title=str(n.get("title", "") or sk)[:512],
                    summary=str(n.get("summary", "") or "")[:2000],
                    content_fingerprint=cf,
                    summary_fingerprint=str(
                        n.get("summary_fingerprint", "") or "",
                    ),
                    b_fingerprint=str(n.get("b_fingerprint", "") or ""),
                    confidence=float(n.get("confidence", 0.0) or 0.0),
                    staleness_state=str(
                        n.get("staleness_state", "") or "fresh",
                    ),
                    b_node_id=str(n.get("b_node_id", "") or "")[:512],
                    source_boundary_decision=sbd,
                    aliases=aliases_t,
                ),
            )
        lc: Any = raw.get("link_claims", [])
        lct: tuple[Mapping[str, Any], ...] = (
            tuple(dict(x) for x in lc if isinstance(x, dict))[:200]
            if isinstance(lc, list)
            else ()
        )
        return cls(
            source_b_path=src,
            nodes=tuple(out_nodes),
            link_claims=lct,
            decision=str(raw.get("decision", "") or "")[:2_000],
        )


@dataclass(frozen=True, slots=True)
class MemoryUpdateInputV1:
    """Малый pass remap: старые C + изменённое окно."""

    b_path: str
    old_c: Mapping[str, Any]
    changed_window: str
    namespace: str = ""
    candidates_nearby: tuple[Mapping[str, Any], ...] = ()

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "schema": "agent_memory.update_input.v1",
            "namespace": self.namespace,
            "b_path": self.b_path,
            "old_c": dict(self.old_c),
            "changed_window": self.changed_window,
            "candidates_nearby": [dict(x) for x in self.candidates_nearby],
        }


@dataclass(frozen=True, slots=True)
class MemoryUpdateResultV1:
    """Результат update pass."""

    c_stable_key: str
    new_line_hint: MemoryLineHintV1 | None
    summary: str
    staleness_state: str

    @classmethod
    def from_llm_json(cls, text: str) -> MemoryUpdateResultV1:
        raw: dict[str, Any] = parse_memory_json_with_retry(text)
        k1 = raw.get("c_stable_key", "") or raw.get("stable_key", "") or ""
        sk = str(k1)
        lh = MemoryLineHintV1.from_json(raw.get("line_hint", {}))
        return cls(
            c_stable_key=sk,
            new_line_hint=lh,
            summary=str(raw.get("summary", "") or "")[:2_000],
            staleness_state=str(raw.get("staleness_state", "") or "fresh"),
        )


@dataclass(frozen=True, slots=True)
class MemorySynthInputV1:
    """Синтез D / slice backbone."""

    namespace: str
    goal: str
    node_refs: tuple[str, ...] = field(default_factory=tuple)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "schema": "agent_memory.synth_input.v1",
            "namespace": self.namespace,
            "goal": self.goal,
            "node_refs": list(self.node_refs),
        }


@dataclass(frozen=True, slots=True)
class MemorySynthResultV1:
    """Краткий synth для D-политики (заглушка контракта)."""

    decision: str
    d_candidates: tuple[Mapping[str, Any], ...] = ()


def clamp_nodes_to_config(
    nodes: Sequence[MemoryCNodePayloadV1],
    *,
    max_c: int,
) -> tuple[MemoryCNodePayloadV1, ...]:
    """Усечь число C по YAML лимиту."""
    m = max(0, int(max_c))
    return tuple(nodes[:m])
