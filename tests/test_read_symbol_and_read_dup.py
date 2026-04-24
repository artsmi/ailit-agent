"""read-6 R1.2 и R2: дубликаты read_file в агрегатах, read_symbol для .py."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ailit.token_economy_aggregates import (
    empty_cumulative,
    merge_events_into_cumulative,
)
from agent_core.tool_runtime.python_read_symbol import builtin_read_symbol


def test_merge_fs_duplicate_stub_count() -> None:
    acc = empty_cumulative()
    acc = merge_events_into_cumulative(
        acc,
        (
            {
                "event_type": "fs.read_file.completed",
                "unchanged_stub": True,
                "range_read": True,
            },
        ),
    )
    assert int(acc.get("fs_read_file_calls", 0) or 0) == 1
    assert int(acc.get("fs_read_file_range_calls", 0) or 0) == 1
    assert int(acc.get("fs_read_file_duplicate_calls", 0) or 0) == 1


def test_read_symbol_top_level_function(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    p = root / "mod.py"
    p.write_text("def bar():\n    return 42\n", encoding="utf-8")
    old = os.environ.get("AILIT_WORK_ROOT")
    try:
        os.environ["AILIT_WORK_ROOT"] = str(root)
        out = builtin_read_symbol({"path": "mod.py", "symbol": "bar"})
    finally:
        if old is None:
            os.environ.pop("AILIT_WORK_ROOT", None)
        else:
            os.environ["AILIT_WORK_ROOT"] = old
    data = json.loads(out)
    assert data.get("ok") is True
    assert data.get("name") == "bar"
    assert int(data.get("start_line", 0)) == 1


def test_read_symbol_not_found(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    p = root / "a.py"
    p.write_text("x = 1\n", encoding="utf-8")
    old = os.environ.get("AILIT_WORK_ROOT")
    try:
        os.environ["AILIT_WORK_ROOT"] = str(root)
        out = builtin_read_symbol({"path": "a.py", "symbol": "missing_fn"})
    finally:
        if old is None:
            os.environ.pop("AILIT_WORK_ROOT", None)
        else:
            os.environ["AILIT_WORK_ROOT"] = old
    data = json.loads(out)
    assert data.get("ok") is False
