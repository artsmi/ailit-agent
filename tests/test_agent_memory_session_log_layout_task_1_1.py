"""TC-1_1: chat_logs layout — CLI dir + legacy.log vs desktop session dir."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from agent_core.runtime.agent_memory_chat_log import (
    AgentMemoryChatDebugLog,
    agent_memory_chat_log_file_name,
    create_unique_cli_session_dir,
    log_file_path_for_chat,
    safe_chat_id_for_log_file,
)
from agent_core.runtime.agent_memory_config import (
    AgentMemoryFileConfig,
    MemoryDebugSubConfig,
)


def _verbose_cfg() -> AgentMemoryFileConfig:
    base: AgentMemoryFileConfig = AgentMemoryFileConfig()
    return replace(
        base,
        memory=replace(
            base.memory,
            debug=MemoryDebugSubConfig(verbose=1),
        ),
    )


def test_agent_memory_cli_session_log_is_directory_with_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-1_1-PATH-CLI.

    Каталог ailit-cli-* + legacy.log; плоского safe.log в корне нет.
    """
    log_root: Path = tmp_path / "chat_logs"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_root))
    chat_id: str = "cli-session-chat-99"
    dbg = AgentMemoryChatDebugLog(
        _verbose_cfg(),
        session_log_mode="cli_init",
    )
    dbg.log_audit(
        raw_chat_id=chat_id,
        event="memory.test.cli_layout",
        request_id="req-tc11",
        topic="tc",
        body={"marker": 1},
    )
    cli_dirs: list[Path] = sorted(log_root.glob("ailit-cli-*"))
    assert len(cli_dirs) == 1
    legacy: Path = cli_dirs[0] / "legacy.log"
    assert legacy.is_file()
    flat: Path = log_root / agent_memory_chat_log_file_name(chat_id)
    assert not flat.is_file()


def test_tc_1_1_path_desktop_session_dir_log_trace_paths_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-1_1-PATH-DESKTOP: каталог ``chat_logs/<safe>/`` и ``<safe>.log``."""
    home: Path = tmp_path / "home_sim"
    log_dir: Path = home / ".ailit" / "agent-memory" / "chat_logs"
    log_dir.mkdir(parents=True)
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_dir))
    chat_id: str = "ailit-desktop-abc_12"
    safe: str = safe_chat_id_for_log_file(chat_id)
    expected: Path = (
        log_dir / safe / agent_memory_chat_log_file_name(chat_id)
    ).resolve()
    resolved: Path = log_file_path_for_chat(chat_id)
    assert resolved == expected
    assert "ailit-cli-" not in str(resolved)
    assert safe in str(resolved)
    flat_legacy: Path = log_dir / agent_memory_chat_log_file_name(chat_id)
    assert not flat_legacy.is_file()
    dbg = AgentMemoryChatDebugLog(_verbose_cfg(), session_log_mode="desktop")
    dbg.log_audit(
        raw_chat_id=chat_id,
        event="memory.test.desktop_layout",
        request_id="req-dsk",
        topic="tc",
        body={},
    )
    assert (log_dir / safe).is_dir()
    assert expected.is_file()
    assert list(log_dir.glob("ailit-cli-*")) == []


def test_agent_memory_legacy_log_json_block_has_indent_newline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-1_1-JSON-LEGACY: вложенный dict, multiline JSON (перевод после {)."""
    log_root: Path = tmp_path / "logs_json"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_root))
    dbg = AgentMemoryChatDebugLog(
        _verbose_cfg(),
        session_log_mode="cli_init",
    )
    dbg.log_audit(
        raw_chat_id="x",
        event="memory.test.json_indent",
        request_id="r-json",
        topic="t",
        body={"nested": {"inner": 42}},
    )
    legacy: Path = next(log_root.glob("ailit-cli-*")) / "legacy.log"
    text: str = legacy.read_text(encoding="utf-8")
    msg = "ожидаем multiline JSON с переводом после {"
    assert re.search(r"\{\n\s+\"", text), msg


def test_create_unique_cli_session_dir_prefix_and_legacy_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Регресс: два вызова — разные ``ailit-cli-*`` под заданным root."""
    base: Path = tmp_path / "cl"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(base))
    a: Path = create_unique_cli_session_dir()
    b: Path = create_unique_cli_session_dir()
    assert a.is_dir() and b.is_dir()
    assert a != b
    assert a.name.startswith("ailit-cli-")
    assert a.parent.resolve() == base.resolve()
    assert b.parent.resolve() == base.resolve()
