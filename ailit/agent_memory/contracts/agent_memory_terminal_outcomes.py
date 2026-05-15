"""S5 / OR-013: компактные reason-коды и вывод partial_reasons для W14.

Матрица condition→(status, reason):
``failure-retry-observability.md`` §Failure. Ниже — подключённые коды; прочие
строки матрицы (``llm_unavailable``, ``empty_graph``, …) добавляются по мере
подключения путей, без дублирования веток в CLI/broker.
"""

from __future__ import annotations

from collections.abc import Sequence

REASON_W14_PARSE_FAILED: str = "w14_parse_failed"
REASON_UNKNOWN_NODE_ID: str = "unknown_node_id"
REASON_LINK_REJECTED: str = "link_rejected"
REASON_FILE_MISSING: str = "file_missing"
REASON_CAP_EXCEEDED: str = "cap_exceeded"
REASON_NO_PROGRESS: str = "no_progress"

_ASSEMBLY_CODE_TO_OR013: dict[str, str] = {
    "c_node_not_found": REASON_UNKNOWN_NODE_ID,
    "read_lines_file_not_found": REASON_FILE_MISSING,
}


def w14_intermediate_runtime_partial_reasons(
    *,
    candidate_count: int,
    c_node_count: int,
    cap_exhausted: bool,
) -> tuple[str, ...]:
    """
    FR-no-progress: при нуле usable candidates при ненулевом C-scope без cap —
    ``no_progress``. Caps → ``cap_exceeded`` (D4/OR-013).
    """
    out: list[str] = []
    if cap_exhausted:
        out.append(REASON_CAP_EXCEEDED)
    if candidate_count == 0 and c_node_count > 0 and not cap_exhausted:
        out.append(REASON_NO_PROGRESS)
    return tuple(out)


def or013_reasons_from_assembly_reject_codes(
    codes: Sequence[str],
) -> tuple[str, ...]:
    """Маппинг кодов ``FinishDecisionResultAssembler`` → OR-013 observable."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in codes:
        c = str(raw or "").strip()
        if not c:
            continue
        mapped = _ASSEMBLY_CODE_TO_OR013.get(c)
        if mapped is not None and mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return tuple(out)
