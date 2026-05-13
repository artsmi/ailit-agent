"""Запись о вызове shell для UI / session_state (этап A.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from agent_work.bash_runner import BashRunOutcome
from ailit_base.shell_output_preview import (
    DetachedViewHeuristic,
    MergedStreamsPreview,
)


def _exit_code_from_dict(data: Mapping[str, Any]) -> int | None:
    raw = data.get("exit_code")
    return int(raw) if raw is not None else None


@dataclass(frozen=True, slots=True)
class ShellInvocationRecord:
    """Сериализуемая запись одного вызова shell/run_shell."""

    call_id: str
    command: str
    started_at: str
    finished_at: str | None
    exit_code: int | None
    combined_output: str
    truncated: bool
    detached_recommended: bool

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для JSON / session_state."""
        return {
            "call_id": self.call_id,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "combined_output": self.combined_output,
            "truncated": self.truncated,
            "detached_recommended": self.detached_recommended,
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> ShellInvocationRecord:
        """Восстановление из dict."""
        return ShellInvocationRecord(
            call_id=str(data["call_id"]),
            command=str(data["command"]),
            started_at=str(data["started_at"]),
            finished_at=(
                str(data["finished_at"]) if data.get("finished_at") else None
            ),
            exit_code=_exit_code_from_dict(data),
            combined_output=str(data.get("combined_output", "")),
            truncated=bool(data.get("truncated", False)),
            detached_recommended=bool(data.get("detached_recommended", False)),
        )


def build_shell_invocation_record(
    *,
    call_id: str,
    command: str,
    started_at: datetime,
    finished_at: datetime,
    outcome: BashRunOutcome,
) -> ShellInvocationRecord:
    """Собрать запись с эвристикой detached view."""
    merged = MergedStreamsPreview.merge(outcome.stdout, outcome.stderr)
    meta_parts: list[str] = []
    if outcome.timed_out:
        meta_parts.append("timed_out=true")
    if outcome.truncated:
        meta_parts.append("truncated=true")
    if outcome.spill_path:
        meta_parts.append(f"spill_path={outcome.spill_path}")
    combined = merged
    if meta_parts:
        combined = merged + "\n" + "\n".join(meta_parts)
    elapsed_ms = int((finished_at - started_at).total_seconds() * 1000)
    line_count = len(combined.splitlines())
    byte_len = len(combined.encode("utf-8"))
    detached = DetachedViewHeuristic.suggest_detached_view(
        elapsed_ms=elapsed_ms,
        byte_len=byte_len,
        line_count=line_count,
    )
    return ShellInvocationRecord(
        call_id=call_id,
        command=command,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        exit_code=outcome.exit_code,
        combined_output=combined,
        truncated=outcome.truncated,
        detached_recommended=detached,
        )
