"""Агрегаты token-economy из событий session (JSONL / Streamlit)."""

from __future__ import annotations

from typing import Any, Mapping

_BYTES_TO_PSEUDO_TOKENS = 4


def _i(row: Mapping[str, Any], key: str) -> int:
    v = row.get(key)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def empty_cumulative() -> dict[str, Any]:
    """Начальное состояние для накопления в Streamlit."""
    return {
        "pager_page_created": 0,
        "pager_page_used": 0,
        "pager_savings_bytes": 0,
        "budget_events": 0,
        "budget_chars_saved": 0,
        "prune_passes": 0,
        "prune_tools": 0,
        "prune_bytes_freed": 0,
        "compaction_restore_files": 0,
        "compaction_restore_injected_chars": 0,
        "tool_exposure_applied": 0,
        "tool_exposure_schema_chars_sum": 0,
    }


def merge_events_into_cumulative(
    acc: dict[str, Any],
    events: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Добавить к acc счётчики по кортежу событий (один прогон)."""
    for row in events:
        et = row.get("event_type")
        if not isinstance(et, str):
            continue
        if et == "context.pager.page_created":
            pgc = int(acc.get("pager_page_created", 0)) + 1
            acc["pager_page_created"] = pgc
            bt = _i(row, "bytes_total")
            bp = _i(row, "bytes_preview")
            if bt > 0 and bp >= 0:
                acc["pager_savings_bytes"] = int(
                    acc.get("pager_savings_bytes", 0),
                ) + max(0, bt - bp)
        elif et == "context.pager.page_used":
            acc["pager_page_used"] = int(acc.get("pager_page_used", 0)) + 1
        elif et == "tool.output_budget.enforced":
            acc["budget_events"] = int(acc.get("budget_events", 0)) + 1
            t0 = _i(row, "total_before")
            t1 = _i(row, "total_after")
            if t0 >= 0 and t1 >= 0 and t0 >= t1:
                acc["budget_chars_saved"] = int(
                    acc.get("budget_chars_saved", 0),
                ) + (t0 - t1)
        elif et == "tool.output_prune.applied":
            acc["prune_passes"] = int(acc.get("prune_passes", 0)) + 1
            acc["prune_tools"] = int(acc.get("prune_tools", 0)) + _i(
                row, "pruned_tools_count",
            )
            acc["prune_bytes_freed"] = int(
                acc.get("prune_bytes_freed", 0),
            ) + _i(row, "pruned_bytes_estimate")
        elif et == "compaction.restore_files":
            acc["compaction_restore_files"] = int(
                acc.get("compaction_restore_files", 0),
            ) + _i(row, "restored_files")
            acc["compaction_restore_injected_chars"] = int(
                acc.get("compaction_restore_injected_chars", 0),
            ) + _i(row, "injected_chars")
        elif et == "tool.exposure.applied":
            acc["tool_exposure_applied"] = int(
                acc.get("tool_exposure_applied", 0),
            ) + 1
            acc["tool_exposure_schema_chars_sum"] = int(
                acc.get("tool_exposure_schema_chars_sum", 0),
            ) + _i(row, "schema_chars")
    return acc


def analyze_log_rows(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Полный анализ файла лога: usage + token-economy + псевдо-baseline."""
    u_in = 0
    u_out = 0
    u_cr = 0
    u_cw = 0
    n_model = 0
    acc = empty_cumulative()
    log_start: str | None = None
    for row in rows:
        if row.get("event_type") == "process.start":
            ts = row.get("ts")
            if isinstance(ts, str):
                log_start = ts
            elif log_start is None:
                log_start = str(ts) if ts is not None else None
        if row.get("event_type") == "model.response":
            n_model += 1
            u = row.get("usage")
            if isinstance(u, dict):
                u_in += _i(u, "input_tokens")
                u_out += _i(u, "output_tokens")
                u_cr += _i(u, "cache_read_tokens")
                u_cw += _i(u, "cache_write_tokens")
    merge_events_into_cumulative(
        acc,
        tuple(
            r
            for r in rows
            if isinstance(r, Mapping) and "event_type" in r
        ),
    )
    p_bytes = int(acc.get("pager_savings_bytes", 0))
    b_ch = int(acc.get("budget_chars_saved", 0))
    pr_b = int(acc.get("prune_bytes_freed", 0))
    p_tok = p_bytes // _BYTES_TO_PSEUDO_TOKENS
    b_tok = b_ch // _BYTES_TO_PSEUDO_TOKENS
    pr_tok = pr_b // _BYTES_TO_PSEUDO_TOKENS
    synth = p_tok + b_tok + pr_tok
    return {
        "log_start": log_start,
        "model_response_n": n_model,
        "usage": {
            "input_tokens": u_in,
            "output_tokens": u_out,
            "cache_read_tokens": u_cr,
            "cache_write_tokens": u_cw,
        },
        "cumulative": acc,
        "synthetic_est": {
            "pager_bytes": p_bytes,
            "pager_pseudo_tokens": p_tok,
            "budget_chars_saved": b_ch,
            "budget_pseudo_tokens": b_tok,
            "prune_bytes_freed": pr_b,
            "prune_pseudo_tokens": pr_tok,
            "layers_sum_pseudo_tokens": synth,
            "note": "оценка: (bytes|chars)/4 по слоям, без дублирения этапов",
        },
    }


def format_cumulative_caption(
    c: dict[str, Any] | None,
) -> str:
    """Одна строка для st.caption (накопленно в браузерной сессии)."""
    if not isinstance(c, dict) or not c:
        return ""
    a = c
    has_te = any(
        int(a.get(k, 0) or 0)
        for k in (
            "pager_savings_bytes",
            "budget_chars_saved",
            "prune_bytes_freed",
        )
    )
    has_restore = int(a.get("compaction_restore_files", 0) or 0) > 0
    has_exp = int(a.get("tool_exposure_applied", 0) or 0) > 0
    if not (has_te or has_restore or has_exp):
        return ""
    parts = [
        f"pager≈{int(a.get('pager_savings_bytes', 0))} B",
        f"tools∆≈{int(a.get('budget_chars_saved', 0))} ch",
        f"prune≈{int(a.get('prune_bytes_freed', 0))} B",
    ]
    p = int(a.get("pager_savings_bytes", 0)) // _BYTES_TO_PSEUDO_TOKENS
    b = int(a.get("budget_chars_saved", 0)) // _BYTES_TO_PSEUDO_TOKENS
    r = int(a.get("prune_bytes_freed", 0)) // _BYTES_TO_PSEUDO_TOKENS
    parts.append(f"~Σtok≈{p + b + r}")
    if has_restore:
        rf = int(a.get("compaction_restore_files", 0) or 0)
        inj = int(a.get("compaction_restore_injected_chars", 0) or 0)
        parts.append(f"restore={rf}f/{inj}ch")
    if has_exp:
        exn = int(a.get("tool_exposure_applied", 0) or 0)
        sch = int(a.get("tool_exposure_schema_chars_sum", 0) or 0)
        parts.append(f"exposure×{exn} schema≈{sch}ch")
    return "Экономия (накопл.): " + " · ".join(parts)
