"""
Каноническое извлечение C-нод (G13.4, D13.6, D13.5). G14R.6: quarantine.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Final

from agent_memory.contracts.agent_memory_contracts import (
    EXTRACTION_CONTRACT_VERSION,
    MemoryLineHintV1,
    MemorySemanticLocatorV1,
)
from agent_memory.services.memory_c_size_limits import (
    C_NODE_EXCERPT_MAX_CHARS,
    C_NODE_FULL_B_MAX_CHARS,
    C_NODE_REMAP_MAX_EXCERPT_CHARS,
)
from agent_memory.services.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)


@dataclass(frozen=True, slots=True)
class SemanticCNodeCandidate:
    """
    DTO: identity только через stable_key + semantic_locator (G13.4).

    line_hint / line ranges / byte offsets — не identity.
    """

    stable_key: str
    semantic_locator: MemorySemanticLocatorV1
    level: str
    kind: str
    title: str
    summary: str
    line_hint: MemoryLineHintV1 | None
    content_fingerprint: str
    summary_fingerprint: str
    confidence: float
    source_boundary_decision: str
    b_node_id: str
    b_fingerprint: str
    extraction_contract_version: str = EXTRACTION_CONTRACT_VERSION
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if str(self.level or "").upper() != "C":
            raise ValueError("SemanticCNodeCandidate.level must be C")
        if not (self.stable_key or "").strip():
            raise ValueError("stable_key is required")
        if not (self.b_node_id or "").strip():
            raise ValueError("b_node_id is required")

    def to_pag_attrs(self) -> dict[str, Any]:
        loc = self.semantic_locator.to_json_dict()
        lh = self.line_hint.to_json_dict() if self.line_hint else None
        return {
            "stable_key": self.stable_key,
            "semantic_locator": loc,
            "line_hint": lh,
            "content_fingerprint": self.content_fingerprint,
            "summary_fingerprint": self.summary_fingerprint,
            "b_fingerprint": self.b_fingerprint,
            "b_node_id": self.b_node_id,
            "confidence": float(self.confidence),
            "source_boundary_decision": str(
                self.source_boundary_decision or "",
            ),
            "extraction_contract_version": self.extraction_contract_version,
            "aliases": list(self.aliases),
        }


class StableKeyNormalizer:
    """Runtime: валидация, нормализация, dedupe stable_key (G13.4)."""

    _unsafe: Final[re.Pattern[str]] = re.compile(
        r"[^a-z0-9._:-]+",
        re.IGNORECASE,
    )

    @classmethod
    def normalize(cls, proposed: str) -> str:
        s = str(proposed or "").strip()
        s = cls._unsafe.sub("_", s)
        s = re.sub(r"_+", "_", s).strip("_")
        return s[:512] if s else "c:unnamed"

    @classmethod
    def with_conflict_suffix(cls, base: str, existing: set[str]) -> str:
        b = cls.normalize(base)
        if b not in existing:
            return b
        h = hashlib.sha256(b.encode("utf-8", errors="replace")).hexdigest()[:8]
        candidate = f"{b}#{h}"
        n = 1
        while candidate in existing:
            candidate = f"{b}#{h}{n}"
            n += 1
        return candidate


class SignatureNormalizer:
    """Удаление шумовых whitespace/comments в сигнатурах (best-effort)."""

    @staticmethod
    def normalize_code_signature(sig: str) -> str:
        s = str(sig or "")
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
        s = re.sub(r"//.*?$", "", s, flags=re.MULTILINE)
        s = re.sub(r"#[^\n]*", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s[:4_000]


class SemanticLocatorNormalizer:
    """
    Нормализация semantic_locator по типу B (структурный, не string offset).
    """

    @classmethod
    def normalize(
        cls,
        loc: MemorySemanticLocatorV1,
        *,
        module_path: str = "",
    ) -> MemorySemanticLocatorV1:
        k = str(loc.kind or "").strip().lower() or "opaque"
        raw = dict(loc.raw)
        if k in ("function", "class", "method", "py_def", "ts_function"):
            name = str(raw.get("name", "") or "").strip()
            sig = SignatureNormalizer.normalize_code_signature(
                str(raw.get("signature", "") or ""),
            )
            par = raw.get("parent")
            parent_s = str(par).strip() if par is not None else ""
            mp = str(raw.get("module_path", "") or module_path or "").strip()
            return MemorySemanticLocatorV1(
                kind=k,
                raw={
                    "name": name,
                    "signature": sig,
                    "parent": parent_s or None,
                    "module_path": mp,
                },
            )
        if k in ("md_heading", "markdown"):
            hp = raw.get("heading_path")
            if isinstance(hp, list):
                hps = [str(x).strip() for x in hp if str(x).strip()]
            else:
                hps = []
            title0 = raw.get("title", "")
            title = str(
                (title0 or (hps[-1] if hps else "")) or "",
            ).strip()
            hl = int(raw.get("heading_level", 0) or 0)
            return MemorySemanticLocatorV1(
                kind="md_heading",
                raw={
                    "heading_path": hps,
                    "heading_level": hl,
                    "title": title,
                },
            )
        if "pointer" in raw or k in ("json", "yaml", "toml", "config"):
            ptr = str(
                raw.get("pointer", "") or raw.get("key_path", "") or "",
            ).strip()
            return MemorySemanticLocatorV1(
                kind="config_pointer",
                raw={"pointer": ptr},
            )
        if k in ("xml", "urdf", "launch", "element"):
            return MemorySemanticLocatorV1(
                kind="markup_element",
                raw={
                    "element_path": str(raw.get("element_path", "") or ""),
                    "tag": str(raw.get("tag", "") or ""),
                    "key_attributes": dict(raw.get("key_attributes", {}))
                    if isinstance(raw.get("key_attributes"), dict)
                    else {},
                },
            )
        if "cell" in k or "notebook" in k:
            return MemorySemanticLocatorV1(
                kind="notebook_cell",
                raw={
                    "cell_id": str(raw.get("cell_id", "") or ""),
                    "cell_index": int(raw.get("cell_index", -1) or -1),
                    "cell_kind": str(raw.get("cell_kind", "") or ""),
                },
            )
        if k in ("text_chunk", "chunk", "fallback"):
            return MemorySemanticLocatorV1(
                kind="text_chunk",
                raw={
                    "chunk_kind": str(
                        raw.get("chunk_kind", "") or "line_window",
                    ),
                    "anchor_text": str(
                        raw.get("anchor_text", "") or "",
                    )[:2_000],
                    "chunk_fingerprint": str(
                        raw.get("chunk_fingerprint", "") or "",
                    ),
                },
            )
        return loc


class SemanticCNodeValidator:
    """Проверки до записи / после LLM (G13.4)."""

    def __init__(self, *, max_summary_chars: int = 2_000) -> None:
        self._max_summary: int = max(64, int(max_summary_chars))

    def validate(
        self,
        cand: SemanticCNodeCandidate,
        *,
        b_path: str,
        n_lines: int,
    ) -> tuple[bool, str]:
        rel_b = str(b_path or "").replace("\\", "/").strip()
        if not rel_b:
            return False, "empty b_path"
        if n_lines < 1:
            return False, "empty file"
        if len(cand.summary) > self._max_summary:
            return False, "summary too long"
        lh = cand.line_hint
        if lh is not None:
            oob = (
                lh.start < 1
                or lh.end < 1
                or lh.start > n_lines
                or lh.end > n_lines
            )
            if oob:
                return False, "line_hint out of bounds"
        return True, "ok"

    @staticmethod
    def c_path_must_be_under_b(
        c_path: str,
        b_path: str,
    ) -> bool:
        """C.node path должен совпадать с B file path (MVP)."""
        a = str(c_path or "").replace("\\", "/").strip()
        b = str(b_path or "").replace("\\", "/").strip()
        return bool(a) and bool(b) and a == b


def clamp_b_text_for_policy(
    b_text: str,
    policy: MemoryLlmOptimizationPolicy,
    *,
    phase: str = "extractor",
) -> str:
    """
    LLM — только bounded excerpt; full B выше cap нельзя (G13.4).

    phase: extractor | remap.
    """
    if phase == "remap":
        cap = min(
            C_NODE_REMAP_MAX_EXCERPT_CHARS,
            int(policy.remap_max_excerpt_chars),
            C_NODE_FULL_B_MAX_CHARS,
        )
    else:
        cap = min(
            C_NODE_EXCERPT_MAX_CHARS,
            int(policy.extractor_max_excerpt_chars),
            C_NODE_FULL_B_MAX_CHARS,
        )
    return policy.clamp_utf8(b_text, cap)
