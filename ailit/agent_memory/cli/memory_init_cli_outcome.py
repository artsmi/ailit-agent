"""Единый маппинг итогового статуса CLI ``memory init`` и кода выхода (S4)."""

from __future__ import annotations

from typing import Any, Final, Literal, Mapping

MemoryInitTerminalStatus = Literal["complete", "partial", "blocked"]

_EXIT_SUCCESS: Final[int] = 0
_EXIT_GATE_NON_COMPLETE: Final[int] = 1
_EXIT_RUNTIME: Final[int] = 2
_EXIT_INTERRUPT: Final[int] = 130

_FINAL_AM_STATUSES: Final[frozenset[str]] = frozenset(
    {"complete", "partial", "blocked"},
)


def memory_init_exit_code(
    status: MemoryInitTerminalStatus,
    *,
    abort_class: Literal["none", "interrupt", "infrastructure"] = "none",
) -> int:
    """Код выхода: complete→0; partial/blocked→1; SIGINT→130; infra→2."""
    if abort_class == "interrupt":
        return _EXIT_INTERRUPT
    if abort_class == "infrastructure":
        return _EXIT_RUNTIME
    if status == "complete":
        return _EXIT_SUCCESS
    return _EXIT_GATE_NON_COMPLETE


def normalize_terminal_status(raw: str | None) -> MemoryInitTerminalStatus:
    """Приводит произвольную строку к одному из трёх канонических статусов."""
    s = str(raw or "").strip()
    if s == "complete":
        return "complete"
    if s == "blocked":
        return "blocked"
    return "partial"


def agent_memory_v1_status_from_envelope(
    out: Mapping[str, Any] | None,
) -> str | None:
    """``agent_memory_result.status`` при ``ok: true``, иначе ``None``."""
    if not isinstance(out, dict) or out.get("ok") is not True:
        return None
    pl = out.get("payload")
    if not isinstance(pl, dict):
        return None
    amr = pl.get("agent_memory_result")
    if not isinstance(amr, dict):
        return None
    st = str(amr.get("status") or "").strip()
    if st in _FINAL_AM_STATUSES:
        return st
    return None


def terminal_status_worker_not_ok(
    out: Mapping[str, Any] | None,
) -> MemoryInitTerminalStatus:
    """
    Статус при ``ok: false`` от worker.

    Не подменяет канонический ``blocked`` через legacy ``aborted`` UX:
    явные коды ошибок провайдера/LLM трактуются как ``blocked``.
    """
    if not isinstance(out, dict):
        return "partial"
    err = out.get("error")
    if not isinstance(err, dict):
        return "partial"
    code = str(err.get("code") or "").strip().lower()
    if code in (
        "memory_llm_unavailable",
        "llm_unavailable",
        "memory_query_llm_error",
        "provider_error",
        "memory_provider_error",
    ):
        return "blocked"
    msg = str(err.get("message") or "").strip().lower()
    if "llm" in msg and "unavailable" in msg:
        return "blocked"
    return "partial"
