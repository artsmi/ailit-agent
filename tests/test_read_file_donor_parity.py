# flake8: noqa: E501
"""read-6 follow-up: read meta, large file stream, @path#Lx-y."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.tool_runtime.builtins import builtin_read_file
from agent_core.tool_runtime.read_file_envelope import (
    format_read_file_with_meta,
    split_read_file_tool_output,
)
from agent_core.tool_runtime.workdir_paths import MAX_READ_BYTES, read_file_slice
from ailit.user_mention_read_hint import parse_user_at_file_line_refs


def test_split_read_meta_roundtrip() -> None:
    s = format_read_file_with_meta(
        relative_path="a/b.py",
        body="x\ny\n",
        from_line=1,
        to_line=2,
        total_lines=10,
        source="buffer",
    )
    pay = split_read_file_tool_output(s)
    assert pay.meta is not None
    assert int(pay.meta.get("total_lines", 0)) == 10
    assert pay.body_line_count == 2


def test_parse_at_file_line_ref() -> None:
    refs = parse_user_at_file_line_refs(
        "see @src/m.py#L10-12 and @x.txt",
    )
    assert len(refs) == 2
    assert refs[0].path == "src/m.py"
    assert refs[0].start_line == 10
    assert refs[0].end_line == 12
    assert refs[1].path == "x.txt"


def test_read_file_streaming_large_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path.resolve()
    p = root / "big.txt"
    # больше MAX_READ_BYTES, но с range — stream
    p.write_bytes(b"line\n" * (120_000))
    monkeypatch.setenv("AILIT_WORK_ROOT", str(root))
    res = read_file_slice(
        p,
        max_bytes=MAX_READ_BYTES,
        offset_line=2,
        limit_line=3,
    )
    assert res.source == "stream"
    assert res.total_lines > 2
    assert "line" in res.body


def test_builtin_read_file_includes_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    (root / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    monkeypatch.setenv("AILIT_WORK_ROOT", str(root))
    out = builtin_read_file({"path": "a.txt", "offset": 1, "limit": 1})
    assert "ailit:read_meta" in out
    assert "one" in out
