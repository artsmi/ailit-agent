"""W-TE-2: лимит суммарного размера tool-ответов за один батч (per turn)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from agent_core.session.context_pager import (
    ContextPageStore,
    ContextPagerConfig,
    READ_CONTEXT_PAGE_NAME,
    StoredPage,
    build_preview,
    build_tool_message_for_page,
    locator_from_invocation,
    stable_page_id,
    tool_to_source_key,
)
from agent_core.tool_runtime.executor import ToolInvocation, ToolRunResult

_AGGR_PREVIEW: Final[ContextPagerConfig] = ContextPagerConfig(
    enabled=True,
    min_body_chars=0,
    preview_max_lines=8,
    preview_max_chars=800,
)


@dataclass(frozen=True, slots=True)
class ToolOutputBudgetConfig:
    """Лимит суммарного текста tool-результатов в одном батче."""

    enabled: bool
    max_total_chars: int


def tool_output_budget_config_from_env() -> ToolOutputBudgetConfig:
    """AILIT_TOOL_OUTPUT_BUDGET* (workflow-token-economy W-TE-2)."""
    import os

    raw = os.environ.get("AILIT_TOOL_OUTPUT_BUDGET", "").strip().lower()
    enabled = raw in ("1", "true", "yes", "on")
    max_total = int(
        os.environ.get("AILIT_TOOL_OUTPUT_BUDGET_MAX_CHARS", "48000"),
    )
    return ToolOutputBudgetConfig(
        enabled=enabled,
        max_total_chars=max(2048, min(2_000_000, max_total)),
    )


def _total_len(parts: list[str]) -> int:
    return sum(len(s) for s in parts)


def _pick_shrink(
    out: list[str],
    invs: list[ToolInvocation],
) -> int:
    """Какой элемент сжать: максимальная длина, тогда стабильно по call_id."""
    return max(range(len(out)), key=lambda i: (len(out[i]), invs[i].call_id))


def _force_page(
    inv: ToolInvocation,
    tr: ToolRunResult,
    page_store: ContextPageStore,
) -> tuple[str, dict[str, Any]]:
    """Сжать в страницу с агрессивным preview; dict для event page_created."""
    body = tr.content or ""
    loc = locator_from_invocation(inv.tool_name, inv.arguments_json)
    source = tool_to_source_key(inv.tool_name)
    page_id = stable_page_id(
        content=body,
        call_id=inv.call_id,
        tool_name=inv.tool_name,
    )
    if page_store.get(page_id) is None:
        page_store.put(
            page_id,
            StoredPage(
                full_text=body,
                source=source,
                tool_name=inv.tool_name,
                locator=loc,
            ),
        )
    prev = build_preview(
        body,
        max_lines=_AGGR_PREVIEW.preview_max_lines,
        max_chars=_AGGR_PREVIEW.preview_max_chars,
    )
    text = build_tool_message_for_page(
        page_id=page_id,
        source=source,
        locator=loc,
        full_text=body,
        preview=prev,
        config=_AGGR_PREVIEW,
    )
    b_total = len(body.encode("utf-8"))
    b_prev = len(prev.encode("utf-8"))
    ev: dict[str, Any] = {
        "page_id": page_id,
        "source": source,
        "tool_name": inv.tool_name,
        "locator": loc,
        "bytes_total": b_total,
        "bytes_preview": b_prev,
        "preview_lines": len(prev.splitlines()),
        "reason": "tool_output_budget",
    }
    return text, ev


def apply_tool_output_batch_budget(
    items: list[tuple[ToolInvocation, ToolRunResult, str]],
    *,
    budget: ToolOutputBudgetConfig,
    page_store: ContextPageStore,
) -> tuple[list[str], int, int, int, list[dict[str, Any]]]:
    """Вернуть тела, total до/после, число замен, extra page_created."""
    if not budget.enabled or not items:
        bodies = [t[2] for t in items]
        t0 = _total_len(bodies)
        return bodies, t0, t0, 0, []
    out = [t[2] for t in items]
    invs = [t[0] for t in items]
    t_before = _total_len(out)
    t_after = t_before
    if t_before <= budget.max_total_chars:
        return out, t_before, t_after, 0, []
    extra_pager: list[dict[str, Any]] = []
    replaced = 0
    for _ in range(256):
        if _total_len(out) <= budget.max_total_chars:
            break
        j = _pick_shrink(out, invs)
        if len(out[j]) <= 48:
            break
        inv, tr, _o = items[j]
        if tr.error is not None:
            out[j] = f"[omitted {inv.tool_name} err={tr.error!s}]"[:256]
            replaced += 1
            continue
        if not (tr.content or ""):
            out[j] = f"[omitted {inv.tool_name} empty]"[:200]
            replaced += 1
            continue
        if inv.tool_name == READ_CONTEXT_PAGE_NAME:
            out[j] = f"[omitted deref {inv.call_id}]"[:200]
            replaced += 1
            continue
        s = out[j].lstrip()
        if s.startswith("[Context page"):
            out[j] = (
                f"[Context page: см. {READ_CONTEXT_PAGE_NAME}; "
                f"call_id={inv.call_id}]"[:500]
            )
            replaced += 1
            continue
        new_body, pev = _force_page(inv, tr, page_store)
        out[j] = new_body
        extra_pager.append(pev)
        replaced += 1
    t_after = _total_len(out)
    return out, t_before, t_after, replaced, extra_pager
