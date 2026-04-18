"""Единая точка для retry с экспоненциальной задержкой."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from agent_core.models import RetryPolicy
from agent_core.transport.errors import TransportHttpError

T = TypeVar("T")


def run_with_retry(
    operation: Callable[[], T],
    policy: RetryPolicy,
    *,
    retry_on_status: frozenset[int] = frozenset({429, 500, 502, 503, 504}),
) -> T:
    """Выполнить операцию с повторами при временных HTTP сбоях."""
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except TransportHttpError as exc:
            last_exc = exc
            code = exc.status_code
            if code is None or code not in retry_on_status:
                raise
            if attempt >= policy.max_attempts:
                raise
            sleep_for = policy.backoff_base_seconds * (2 ** (attempt - 1))
            sleep_for += random.random() * 0.1
            time.sleep(sleep_for)
    assert last_exc is not None
    raise RuntimeError("unreachable") from last_exc
