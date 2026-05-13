"""Тесты ShellInvocationRecord (этап A.2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_work.bash_runner import BashRunOutcome
from ailit_base.shell_invocation_record import (
    ShellInvocationRecord,
    build_shell_invocation_record,
)


def test_shell_invocation_record_roundtrip() -> None:
    rec = ShellInvocationRecord(
        call_id="c1",
        command="echo x",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        exit_code=0,
        combined_output="x",
        truncated=False,
        detached_recommended=False,
    )
    back = ShellInvocationRecord.from_dict(rec.to_dict())
    assert back == rec


def test_build_shell_invocation_record_detached() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=10)
    outcome = BashRunOutcome(
        exit_code=0,
        stdout="a\n" * 50,
        stderr="",
        timed_out=False,
        truncated=False,
        spill_path=None,
    )
    rec = build_shell_invocation_record(
        call_id="id",
        command="x",
        started_at=t0,
        finished_at=t1,
        outcome=outcome,
    )
    assert rec.detached_recommended is True
    assert rec.exit_code == 0
