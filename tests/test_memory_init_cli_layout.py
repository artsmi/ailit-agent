"""Gate-тесты layout / VERIFY для ``memory init``.

Расширение сценариев — task_4_1 (T-M01–T-M05).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_core.runtime.agent_memory_chat_log import (
    COMPACT_LOG_FILE_NAME,
    AgentMemoryChatDebugLog,
)
from agent_core.runtime.agent_memory_config import (
    AgentMemoryFileConfig,
    MemoryDebugSubConfig,
)
from agent_core.runtime.compact_observability_sink import (
    CompactObservabilitySink,
)
from agent_core.runtime.memory_init_orchestrator import (
    count_compact_d4_summary_lines,
    verify_memory_init_journal_complete_marker,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_E2E_DIR = _REPO_ROOT / "tests" / "e2e"
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from cli_runner import AilitCliRunner  # noqa: E402


def _verbose_cfg() -> AgentMemoryFileConfig:
    base: AgentMemoryFileConfig = AgentMemoryFileConfig()
    return replace(
        base,
        memory=replace(
            base.memory,
            debug=MemoryDebugSubConfig(verbose=1),
        ),
    )


def test_memory_init_cli_layout_legacy_dir_multiline_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-M01: ``ailit-cli-*`` + ``legacy.log`` с multiline JSON в блоке."""
    log_root: Path = tmp_path / "chat_logs"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_root))
    chat_id: str = "mem-init-layout-chat"
    dbg = AgentMemoryChatDebugLog(
        _verbose_cfg(),
        session_log_mode="cli_init",
    )
    dbg.log_audit(
        raw_chat_id=chat_id,
        event="memory.init.layout",
        request_id="req-tm01",
        topic="tm01",
        body={"nested": {"inner": 7}},
    )
    cli_dirs: list[Path] = sorted(log_root.glob("ailit-cli-*"))
    assert len(cli_dirs) == 1
    assert cli_dirs[0].name.startswith("ailit-cli-")
    legacy: Path = cli_dirs[0] / "legacy.log"
    assert legacy.is_file()
    text: str = legacy.read_text(encoding="utf-8")
    msg = "multiline JSON: перевод строки после открывающей скобки"
    assert re.search(r"\{\n\s+\"", text), msg


def test_memory_init_compact_log_single_line_records(
    tmp_path: Path,
) -> None:
    """T-M02: single-line ``compact.log``; запрет multiline JSON ``{`` + NL."""
    compact: Path = tmp_path / COMPACT_LOG_FILE_NAME
    sink = CompactObservabilitySink(
        compact_file=compact,
        init_session_id="00000000-0000-4000-8000-000000000002",
        tee_stderr=False,
    )
    sink.emit(
        req=None,
        chat_id="c-tm02",
        event="orch_memory_init_phase",
        fields={"phase": "prepare", "note": "a\nb"},
    )
    sink.emit_memory_result_complete_marker(
        req=None,
        chat_id="c-tm02",
        request_id="r2",
    )
    raw: str = compact.read_text(encoding="utf-8")
    assert "{\n" not in raw
    for line in raw.splitlines():
        stripped: str = line.rstrip("\n")
        if not stripped:
            continue
        assert "\n" not in stripped


def test_memory_init_compact_fixture_d4_summary_three_counters(
    tmp_path: Path,
) -> None:
    """T-M03: три счётчика D4 на fixture ``compact.log``."""
    compact_path: Path = tmp_path / "compact.log"
    lines: list[str] = [
        (
            "timestamp=2026-05-01T10:00:00+00:00 init_session_id=s "
            "chat_id=c event=memory.why_llm"
        ),
        (
            "timestamp=2026-05-01T10:00:01+00:00 init_session_id=s "
            "chat_id=c event=memory.why_llm"
        ),
        (
            "timestamp=2026-05-01T10:00:02+00:00 event=memory.pag_graph "
            "op=node rev=1 ns=n subject=p#L:x"
        ),
        (
            "timestamp=2026-05-01T10:00:03+00:00 "
            "event=memory.w14_graph_highlight query_id=q w14_command=x "
            "n_node=0 n_edge=0"
        ),
        (
            "timestamp=2026-05-01T10:00:04+00:00 "
            "event=memory.w14_graph_highlight query_id=q w14_command=x "
            "n_node=0 n_edge=0"
        ),
        (
            "timestamp=2026-05-01T10:00:05+00:00 "
            "event=memory.w14_graph_highlight query_id=q w14_command=x "
            "n_node=0 n_edge=0"
        ),
    ]
    compact_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    got: tuple[int, int, int] = count_compact_d4_summary_lines(compact_path)
    assert got == (2, 1, 3)


def test_memory_init_journal_verify_requires_complete_marker(
    tmp_path: Path,
) -> None:
    """TC-2_2-MARKER-VERIFY, T-M04: journal gate и дубль в compact."""
    chat_id = "mem-verify-chat-1"
    journal = tmp_path / "journal.jsonl"
    verify = verify_memory_init_journal_complete_marker
    assert verify(journal, chat_id) is False

    other_chat_row = {
        "schema": "ailit_memory_journal_v1",
        "created_at": "2026-05-01T11:00:00+00:00",
        "chat_id": "other-chat",
        "request_id": "r0",
        "namespace": "ns",
        "project_id": "p",
        "event_name": "memory.result.returned",
        "summary": "x",
        "node_ids": [],
        "edge_ids": [],
        "payload": {"status": "complete", "query_id": "q0"},
    }
    dumped = json.dumps(
        other_chat_row,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    journal.write_text(dumped + "\n", encoding="utf-8")
    assert verify(journal, chat_id) is False

    wrong_event = {
        "schema": "ailit_memory_journal_v1",
        "created_at": "2026-05-01T11:30:00+00:00",
        "chat_id": chat_id,
        "request_id": "r-bad",
        "namespace": "ns",
        "project_id": "p",
        "event_name": "memory.other",
        "summary": "x",
        "node_ids": [],
        "edge_ids": [],
        "payload": {"status": "complete", "query_id": "qb"},
    }
    dumped_wrong = json.dumps(
        wrong_event,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    journal.write_text(dumped_wrong + "\n", encoding="utf-8")
    assert verify(journal, chat_id) is False

    incomplete = {
        "schema": "ailit_memory_journal_v1",
        "created_at": "2026-05-01T11:45:00+00:00",
        "chat_id": chat_id,
        "request_id": "r-inc",
        "namespace": "ns",
        "project_id": "p",
        "event_name": "memory.result.returned",
        "summary": "x",
        "node_ids": [],
        "edge_ids": [],
        "payload": {"status": "pending", "query_id": "qi"},
    }
    dumped_inc = json.dumps(
        incomplete,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    journal.write_text(dumped_inc + "\n", encoding="utf-8")
    assert verify(journal, chat_id) is False

    row = {
        "schema": "ailit_memory_journal_v1",
        "created_at": "2026-05-01T12:00:00+00:00",
        "chat_id": chat_id,
        "request_id": "r1",
        "namespace": "ns",
        "project_id": "p",
        "event_name": "memory.result.returned",
        "summary": "x",
        "node_ids": [],
        "edge_ids": [],
        "payload": {"status": "complete", "query_id": "q1"},
    }
    dumped_ok = json.dumps(
        row,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    journal.write_text(dumped_ok + "\n", encoding="utf-8")
    assert row["event_name"] == "memory.result.returned"
    assert row["payload"]["status"] == "complete"
    assert verify(journal, chat_id) is True

    compact = tmp_path / COMPACT_LOG_FILE_NAME
    sink = CompactObservabilitySink(
        compact_file=compact,
        init_session_id="00000000-0000-4000-8000-000000000001",
        tee_stderr=False,
    )
    sink.emit_memory_result_complete_marker(
        req=None,
        chat_id=chat_id,
        request_id="r1",
    )
    text = compact.read_text(encoding="utf-8")
    assert "event=memory.result.returned" in text
    assert "status=complete" in text
    assert chat_id in text


def test_memory_init_subprocess_python_m_invalid_path_nonzero(
    tmp_path: Path,
) -> None:
    """T-M05: ``python -m ailit.cli memory init`` на несуществующем path."""
    runner = AilitCliRunner(_REPO_ROOT)
    missing = tmp_path / "not_a_real_project_dir"
    cmd: list[str] = [
        runner._python(),
        "-m",
        "ailit.cli",
        "memory",
        "init",
        str(missing),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        env=runner._env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode != 0
    err = (proc.stderr or "") + (proc.stdout or "")
    assert "memory_init_root_missing" in err or "does not exist" in err
