from __future__ import annotations

from ailit_runtime.models import MemoryGrant, MemoryGrantRange
from agent_work.tool_runtime.memory_grants import MemoryGrantChecker


def test_grant_blocks_without_grant() -> None:
    checker = MemoryGrantChecker(())
    res = checker.check_read_file(path="a.py", offset_line=1, limit_line=10)
    assert res.ok is False
    assert res.error_code == "memory_grant_required"


def test_grant_allows_in_range() -> None:
    g = MemoryGrant(
        grant_id="g1",
        issued_by="AgentMemory:x",
        issued_to="AgentWork:x",
        namespace="ns",
        path="a.py",
        ranges=(MemoryGrantRange(start_line=1, end_line=20),),
        whole_file=False,
        reason="test",
        expires_at="2099-01-01T00:00:00Z",
    )
    checker = MemoryGrantChecker((g,))
    res = checker.check_read_file(path="a.py", offset_line=5, limit_line=10)
    assert res.ok is True


def test_grant_blocks_out_of_range() -> None:
    g = MemoryGrant(
        grant_id="g1",
        issued_by="AgentMemory:x",
        issued_to="AgentWork:x",
        namespace="ns",
        path="a.py",
        ranges=(MemoryGrantRange(start_line=1, end_line=20),),
        whole_file=False,
        reason="test",
        expires_at="2099-01-01T00:00:00Z",
    )
    checker = MemoryGrantChecker((g,))
    res = checker.check_read_file(path="a.py", offset_line=21, limit_line=1)
    assert res.ok is False


def test_whole_file_requires_explicit_whole_file_grant() -> None:
    g = MemoryGrant(
        grant_id="g1",
        issued_by="AgentMemory:x",
        issued_to="AgentWork:x",
        namespace="ns",
        path="a.py",
        ranges=(MemoryGrantRange(start_line=1, end_line=9999),),
        whole_file=False,
        reason="test",
        expires_at="2099-01-01T00:00:00Z",
    )
    checker = MemoryGrantChecker((g,))
    res1 = checker.check_read_file(path="a.py", offset_line=1, limit_line=None)
    assert res1.ok is False

    g2 = MemoryGrant(
        grant_id="g2",
        issued_by="AgentMemory:x",
        issued_to="AgentWork:x",
        namespace="ns",
        path="a.py",
        ranges=(MemoryGrantRange(start_line=1, end_line=9999),),
        whole_file=True,
        reason="test",
        expires_at="2099-01-01T00:00:00Z",
    )
    checker2 = MemoryGrantChecker((g2,))
    res2 = checker2.check_read_file(
        path="a.py",
        offset_line=1,
        limit_line=None,
    )
    assert res2.ok is True
