"""agent_memory_result.v1 — envelope для payload.agent_memory_result.

План: plan/14-agent-memory-runtime.md §1.3, C14R.1a. Источник истины для
AgentWork — это поле; memory_slice — compatibility projection.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final, Mapping

AGENT_MEMORY_RESULT_V1: str = "agent_memory_result.v1"

FIX_MEMORY_LLM_JSON_STEP: Final[str] = "fix_memory_llm_json"


def resolve_memory_continuation_required(
    *,
    w14_contract_failure: bool,
    pipeline_recommended_next_step: str,
    am_v1_status: str | None,
    w14_finish: bool,
    final_partial: bool,
) -> bool | None:
    """Вычислить SoT-сигнал UC-04 для ``memory_continuation_required``.

    UC-03 (терминальные диагностические исходы): поле не ``True`` —
    возвращаем ``None`` (поле не попадёт в объект).

    UC-04: ``True`` только при машинном ``am_v1_status == partial`` на пути
    W14 с явным ``explicit_results`` (``w14_finish``), без контрактного
    провала и без терминального ``recommended_next_step`` из pipeline.
    """
    if w14_contract_failure:
        return None
    rns = str(pipeline_recommended_next_step or "").strip()
    if rns == FIX_MEMORY_LLM_JSON_STEP:
        return None
    st = str(am_v1_status or "").strip().lower()
    if st == "blocked":
        return None
    if not final_partial or not w14_finish:
        return None
    if st == "partial":
        return True
    return None


def _first_c_path_from_nodes(
    node_ids: list[str],
    *,
    target_paths: list[str],
) -> tuple[str, str | None]:
    for nid in node_ids:
        if str(nid).strip().upper().startswith("C:") and "B:" not in str(nid):
            # Heuristic: C:<relpath>:... (existing convention in fallback ids)
            parts = str(nid).split(":", 2)
            if len(parts) >= 2 and parts[1].strip():
                return parts[1], nid
    if target_paths:
        t0 = str(target_paths[0] or "").strip()
        if t0:
            return t0, None
    return ".", None


def build_agent_memory_result_v1(
    *,
    query_id: str,
    status: str,
    memory_slice: Mapping[str, Any] | None,
    partial: bool,
    decision_summary: str,
    recommended_next_step: str,
    explicit_results: list[dict[str, Any]] | None = None,
    explicit_status: str | None = None,
    memory_continuation_required: bool | None = None,
    extra_runtime_partial_reasons: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Собрать объект `agent_memory_result.v1` (§1.3) из текущего среза.

    W14G14R.0: минимальная мапа без полного B/C state machine; объект рядом с
    ``memory_slice``. Поле ``memory_continuation_required`` задаётся отдельно
    (см. ``resolve_memory_continuation_required``).

    G14R.7: если задан ``explicit_results`` (в т.ч. пустой список), контракт
    берётся из ``finish_decision`` / сборщика, а не из грубой проекции
    ``injected_text`` в ``c_summary``.

    ``memory_continuation_required``: если не ``None``, добавляет поле в
    объект (машиночитаемый continuation для AgentWork, W14).
    """
    st = str(explicit_status or status or "").strip() or (
        "partial" if partial else "complete"
    )
    if st not in ("complete", "partial", "blocked"):
        st = "partial" if partial else "complete"
    nids: list[str] = []
    tfp: list[str] = []
    if memory_slice and isinstance(memory_slice, Mapping):
        raw = memory_slice.get("node_ids")
        if isinstance(raw, list):
            nids = [str(x) for x in raw if str(x).strip()]
        tfr = memory_slice.get("target_file_paths")
        if isinstance(tfr, list):
            tfp = [str(x) for x in tfr if str(x).strip()]

    results: list[dict[str, Any]] = []
    if explicit_results is not None:
        results = list(explicit_results)
    elif nids or tfp or (
        memory_slice
        and str(memory_slice.get("injected_text") or "").strip()
    ):
        path, cid = _first_c_path_from_nodes(
            nids,
            target_paths=tfp,
        )
        if cid:
            if memory_slice:
                text = str(memory_slice.get("injected_text", "") or "")
            else:
                text = ""
            summary: str | None
            if text.strip():
                cap = 700
                summary = (text[:cap] + "…") if len(text) > cap else text
            else:
                summary = str(memory_slice.get("reason") or "memory slice")
            results.append(
                {
                    "kind": "c_summary",
                    "path": path,
                    "c_node_id": str(cid),
                    "summary": summary,
                    "read_lines": [],
                    "reason": "compat_projection_from_memory_slice",
                },
            )
    pr_extra: list[str] = []
    if explicit_results is not None and not results:
        pr_extra.append("finish_decision_no_valid_results")
    partial_reasons: list[str] = []
    seen_pr: set[str] = set()
    for x in (["query_pipeline_partial"] if partial else []) + pr_extra:
        xs = str(x).strip()
        if xs and xs not in seen_pr:
            seen_pr.add(xs)
            partial_reasons.append(xs)
    for x in extra_runtime_partial_reasons or ():
        xs = str(x).strip()
        if xs and xs not in seen_pr:
            seen_pr.add(xs)
            partial_reasons.append(xs)
    out: dict[str, Any] = {
        "schema_version": AGENT_MEMORY_RESULT_V1,
        "query_id": str(query_id or "").strip() or "mem-unknown",
        "status": st,
        "results": results,
        "decision_summary": str(decision_summary or "").strip() or (
            "memory response"
        ),
        "recommended_next_step": str(recommended_next_step or ""),
        "runtime_trace": {
            "steps_executed": 1,
            "final_step": "finish",
            "partial_reasons": partial_reasons,
        },
    }
    if memory_continuation_required is not None:
        out["memory_continuation_required"] = bool(
            memory_continuation_required,
        )
    return out
