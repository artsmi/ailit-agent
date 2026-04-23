"""Агрегаты token-economy из событий session (JSONL / Streamlit)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_BYTES_TO_PSEUDO_TOKENS = 4

# E2E-M3-02: «one source»; ориентир: context-mode FullReport.
SESSION_SUMMARY_CONTRACT = "ailit_session_summary_v1"


def read_jsonl_session_log(
    path: Path,
    *,
    max_bytes: int = 50_000_000,
) -> list[dict[str, Any]]:
    """Прочитать JSONL-лог сессии (тот же формат, что и CLI session usage)."""
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raw = raw[-max_bytes:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


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
        "memory_promotion_applied": 0,
        "memory_promotion_denied": 0,
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
        elif et == "memory.promotion.applied":
            acc["memory_promotion_applied"] = int(
                acc.get("memory_promotion_applied", 0),
            ) + 1
        elif et == "memory.promotion.denied":
            acc["memory_promotion_denied"] = int(
                acc.get("memory_promotion_denied", 0),
            ) + 1
    return acc


def compute_resume_signals(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Эвристика «можно продолжать сессию» по JSONL (M3 continuity)."""
    cancelled = False
    n_model_ok = 0
    n_model_err = 0
    n_mem = 0
    last_sig: str | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        et = row.get("event_type")
        if not isinstance(et, str) or not et:
            continue
        if et == "session.cancelled":
            cancelled = True
        if et == "model.response":
            n_model_ok += 1
        if et == "model.error":
            n_model_err += 1
        if et == "memory.access":
            n_mem += 1
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        et = row.get("event_type")
        if isinstance(et, str) and et:
            last_sig = et
            break
    trailing_error = last_sig == "model.error"
    resume_ready = (
        n_model_ok > 0
        and not cancelled
        and not trailing_error
    )
    notes: list[str] = []
    if cancelled:
        notes.append("в логе есть session.cancelled")
    if trailing_error:
        notes.append("последнее событие: model.error")
    if n_model_ok == 0:
        notes.append("нет model.response")
    return {
        "resume_ready": resume_ready,
        "last_event_type": last_sig,
        "cancelled": cancelled,
        "model_response_n": n_model_ok,
        "model_error_n": n_model_err,
        "memory_access_n": n_mem,
        "trailing_error": trailing_error,
        "notes": notes,
    }


def build_subsystems_block(
    *,
    usage: Mapping[str, Any],
    cumulative: Mapping[str, Any],
    resume: Mapping[str, Any],
) -> dict[str, Any]:
    """Срез подсистем; то же, что отдельные команды `session usage <sub>`."""
    return {
        "usage": {
            "input_tokens": _i(usage, "input_tokens"),
            "output_tokens": _i(usage, "output_tokens"),
            "cache_read_tokens": _i(usage, "cache_read_tokens"),
            "cache_write_tokens": _i(usage, "cache_write_tokens"),
        },
        "pager": {
            "page_created": int(cumulative.get("pager_page_created", 0) or 0),
            "page_used": int(cumulative.get("pager_page_used", 0) or 0),
        },
        "budget": {
            "events": int(cumulative.get("budget_events", 0) or 0),
            "saved_chars": int(cumulative.get("budget_chars_saved", 0) or 0),
        },
        "prune": {
            "passes": int(cumulative.get("prune_passes", 0) or 0),
            "tools": int(cumulative.get("prune_tools", 0) or 0),
            "bytes_freed": int(cumulative.get("prune_bytes_freed", 0) or 0),
        },
        "compaction": {
            "restored_files": int(
                cumulative.get("compaction_restore_files", 0) or 0,
            ),
            "injected_chars": int(
                cumulative.get("compaction_restore_injected_chars", 0) or 0,
            ),
        },
        "tool_exposure": {
            "applied": int(
                cumulative.get("tool_exposure_applied", 0) or 0,
            ),
            "schema_chars_sum": int(
                cumulative.get("tool_exposure_schema_chars_sum", 0) or 0,
            ),
        },
        "memory": {
            "access_n": int(resume.get("memory_access_n", 0) or 0),
            "promotion_applied": int(
                cumulative.get("memory_promotion_applied", 0) or 0,
            ),
            "promotion_denied": int(
                cumulative.get("memory_promotion_denied", 0) or 0,
            ),
        },
    }


def build_session_summary(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Единый отчёт: usage, TE, resume, subsystems (один проход, E2E-M3-02)."""
    base = analyze_log_rows(rows)
    resume = compute_resume_signals(rows)
    c = base.get("cumulative")
    c_dict: dict[str, Any] = dict(c) if isinstance(c, dict) else {}
    u = base.get("usage")
    u_dict: dict[str, Any] = dict(u) if isinstance(u, dict) else {}
    s = base.get("synthetic_est")
    s_dict: dict[str, Any] = dict(s) if isinstance(s, dict) else {}
    r_dict: dict[str, Any] = (
        dict(resume) if isinstance(resume, dict) else {}
    )
    sub = build_subsystems_block(
        usage=u_dict,
        cumulative=c_dict,
        resume=r_dict,
    )
    return {
        "contract": SESSION_SUMMARY_CONTRACT,
        "log_start": base.get("log_start"),
        "model_response_n": base.get("model_response_n"),
        "usage": u_dict,
        "cumulative": c_dict,
        "synthetic_est": s_dict,
        "resume": r_dict,
        "subsystems": sub,
    }


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
