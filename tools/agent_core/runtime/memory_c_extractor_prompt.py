"""LLM-extractor prompt для C-нод: G13.4, D13.5, JSON-only, bounded."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from agent_core.runtime.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)
from agent_core.runtime.semantic_c_extraction import (
    C_NODE_FULL_B_MAX_CHARS,
    clamp_b_text_for_policy,
)

EXTRACTOR_SYSTEM_PROMPT: str = "\n".join(
    (
        "You extract semantic C-level nodes for a single source file (B).",
        "Return ONLY one JSON object. No markdown fences. No CoT.",
        "Schema: agent_memory.extractor_result.v1",
        'Each node: level "C", stable_key, semantic_locator (structural).',
        "Do not use line numbers, byte offsets, or line_hint as identity.",
        "Respect excluded_nodes; no C nodes for those chunk_ids/paths.",
        "Artifact or cache: nodes [] and short decision.",
    ),
)


class MemoryExtractorPromptBuilder:
    """user/system payload с caps MemoryLlmOptimizationPolicy."""

    @staticmethod
    def system_prompt() -> str:
        return EXTRACTOR_SYSTEM_PROMPT

    @classmethod
    def build_user_payload(
        cls,
        *,
        b_path: str,
        b_fingerprint: str,
        b_text: str,
        full_b: bool,
        chunk_catalog: Sequence[Mapping[str, Any]],
        excluded_nodes: Sequence[str],
        policy: MemoryLlmOptimizationPolicy,
        namespace: str = "",
    ) -> dict[str, Any]:
        """Только bounded excerpts; весь B выше cap не передаётся."""
        if full_b and len(b_text) > C_NODE_FULL_B_MAX_CHARS:
            full_b = False
        if full_b:
            text_out = clamp_b_text_for_policy(
                b_text,
                policy,
                phase="extractor",
            )
        else:
            text_out = ""
        max_cat = int(policy.extractor_max_candidates)
        cat = [dict(x) for x in chunk_catalog[: max(0, max_cat)]]
        excl = [str(x) for x in excluded_nodes[:200]]
        base: dict[str, Any] = {
            "schema": "agent_memory.extractor_user.v1",
            "namespace": namespace,
            "b_path": b_path,
            "b_fingerprint": b_fingerprint,
            "full_b": bool(full_b and len(b_text) <= C_NODE_FULL_B_MAX_CHARS),
            "chunk_catalog": cat,
            "excluded_nodes": excl,
            "policy_hint": {
                "max_excerpt_chars": int(policy.extractor_max_excerpt_chars),
                "max_output_tokens": int(policy.extractor_max_output_tokens),
                "thinking": False,
                "json_only": True,
            },
        }
        if base["full_b"]:
            base["b_text"] = text_out
        else:
            base["b_text_omitted"] = (
                "<omitted — use chunk_catalog; excerpts capped>"
            )
        return base

    @classmethod
    def build_user_json(
        cls,
        *,
        b_path: str,
        b_fingerprint: str,
        b_text: str,
        full_b: bool,
        chunk_catalog: Sequence[Mapping[str, Any]],
        excluded_nodes: Sequence[str],
        policy: MemoryLlmOptimizationPolicy,
        namespace: str = "",
    ) -> str:
        p = cls.build_user_payload(
            b_path=b_path,
            b_fingerprint=b_fingerprint,
            b_text=b_text,
            full_b=full_b,
            chunk_catalog=chunk_catalog,
            excluded_nodes=excluded_nodes,
            policy=policy,
            namespace=namespace,
        )
        return json.dumps(p, ensure_ascii=False)
