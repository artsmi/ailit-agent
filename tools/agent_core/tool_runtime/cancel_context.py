"""Thread-local cancel context for tool handlers.

Tool handlers have a simple `handler(args) -> str` signature, but some
executions (shell) must react immediately to the session cancel event.

This module provides a thread-local accessor so lower layers (bash runner,
session shell) can check for cancellation without changing handler APIs.
"""

from __future__ import annotations

from threading import Event, local

_TLS: local = local()


def set_current_cancel(cancel: Event | None) -> None:
    """Bind cancel event to the current thread for tool execution."""
    _TLS.cancel = cancel


def clear_current_cancel() -> None:
    """Remove cancel event binding from the current thread."""
    _TLS.cancel = None


def current_cancel() -> Event | None:
    """Return current thread cancel event (or None)."""
    ev = getattr(_TLS, "cancel", None)
    return ev if isinstance(ev, Event) else None
