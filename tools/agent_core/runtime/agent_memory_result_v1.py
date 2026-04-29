"""agent_memory_result.v1 — envelope для payload.agent_memory_result.

План: plan/14-agent-memory-runtime.md §1.3, C14R.1a. Источник истины для
AgentWork — это поле; memory_slice — compatibility projection.
"""

from __future__ import annotations

from typing import Any, Mapping

AGENT_MEMORY_RESULT_V1: str = "agent_memory_result.v1"


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
            return t0, node_ids[0] if node_ids else None
    return ".", node_ids[0] if node_ids else None


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
) -> dict[str, Any]:
    """Собрать объект `agent_memory_result.v1` (§1.3) из текущего среза.

    W14G14R.0: минимальная мапа без полного B/C state machine; поле обязательно
    в ответе рядом с memory_slice.

    G14R.7: если задан ``explicit_results`` (в т.ч. пустой список), контракт
    берётся из ``finish_decision`` / сборщика, а не из грубой проекции
    ``injected_text`` в ``c_summary``.
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
    return {
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
            "partial_reasons": (
                (["query_pipeline_partial"] if partial else [])
                + pr_extra
            ),
        },
    }
