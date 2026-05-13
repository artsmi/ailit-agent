"""MemoryGrant enforcement for code-read tools (G8.5).

Policy:
- Grants are always path-scoped and line-range-scoped.
- Reading without a matching grant is blocked with `memory_grant_required`.
- `whole_file=True` grants are required for requests that omit `limit`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ailit_runtime.models import MemoryGrant


@dataclass(frozen=True, slots=True)
class MemoryGrantCheckResult:
    """Результат проверки grant-ов."""

    ok: bool
    error_code: str | None
    error_message: str | None


class MemoryGrantChecker:
    """Проверка доступа к чтению файла по активным grants."""

    def __init__(self, grants: Iterable[MemoryGrant]) -> None:
        self._grants = tuple(grants)

    def check_read_file(
        self,
        *,
        path: str,
        offset_line: int,
        limit_line: int | None,
    ) -> MemoryGrantCheckResult:
        """Проверить read_file(path, offset, limit)."""
        requested_whole = limit_line is None
        if offset_line < 1:
            return MemoryGrantCheckResult(
                ok=False,
                error_code="invalid_args",
                error_message="offset must be >= 1",
            )
        if limit_line is not None and limit_line < 1:
            return MemoryGrantCheckResult(
                ok=False,
                error_code="invalid_args",
                error_message="limit must be >= 1",
            )
        requested_end = (
            offset_line if limit_line is None else offset_line + limit_line - 1
        )
        for g in self._grants:
            if str(g.path) != str(path):
                continue
            if requested_whole and not bool(g.whole_file):
                continue
            if bool(g.whole_file):
                return MemoryGrantCheckResult(
                    ok=True,
                    error_code=None,
                    error_message=None,
                )
            for r in g.ranges:
                if offset_line >= r.start_line and requested_end <= r.end_line:
                    return MemoryGrantCheckResult(
                        ok=True, error_code=None, error_message=None
                    )
        return MemoryGrantCheckResult(
            ok=False,
            error_code="memory_grant_required",
            error_message="read requires MemoryGrant(path+lines)",
        )
