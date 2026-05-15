"""G12.5: AgentMemory global config, boundary filter, JSON retry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_memory.config.agent_memory_config import (
    AgentMemoryConfigPaths,
    AgentMemoryFileConfig,
    MemoryDebugSubConfig,
    MemoryPlannerResultV1,
    SourceBoundaryFilter,
    ArtifactsSubConfig,
    load_or_create_agent_memory_config,
    parse_memory_json_with_retry,
)


def test_load_or_create_writes_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg_path: Path = tmp_path / "am" / "config.yaml"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(cfg_path))
    p1: AgentMemoryFileConfig = load_or_create_agent_memory_config()
    assert cfg_path.is_file()
    assert p1.memory.llm.max_full_b_bytes == 32_768
    assert p1.memory.init.max_continuation_rounds == 32
    body = cfg_path.read_text(encoding="utf-8")
    assert "max_continuation_rounds" in body
    p2: AgentMemoryFileConfig = load_or_create_agent_memory_config()
    assert p2.memory.llm.max_full_b_chars == p1.memory.llm.max_full_b_chars


def test_init_max_continuation_rounds_from_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg_path = tmp_path / "am2.yaml"
    cfg_path.write_text(
        "memory:\n"
        "  init:\n"
        "    max_continuation_rounds: 5\n"
        "  llm:\n"
        "    max_turns: 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(cfg_path))
    loaded = AgentMemoryFileConfig.from_mapping(
        yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {},
    )
    assert loaded.memory.init.max_continuation_rounds == 5


def test_init_max_continuation_rounds_root_init_merges_into_memory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Корневой ``init:`` без ``memory.init`` подхватывается в memory.init."""
    cfg_path = tmp_path / "am-root-init.yaml"
    cfg_path.write_text(
        "init:\n"
        "  max_continuation_rounds: 1000\n"
        "memory:\n"
        "  llm:\n"
        "    max_turns: 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(cfg_path))
    loaded = AgentMemoryFileConfig.from_mapping(
        yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {},
    )
    assert loaded.memory.init.max_continuation_rounds == 1000


def test_init_root_init_overridden_by_memory_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``memory.init`` перекрывает совпадающие ключи корневого ``init:``."""
    cfg_path = tmp_path / "am-overlay-init.yaml"
    cfg_path.write_text(
        "init:\n"
        "  max_continuation_rounds: 999\n"
        "memory:\n"
        "  init:\n"
        "    max_continuation_rounds: 7\n"
        "  llm:\n"
        "    max_turns: 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(cfg_path))
    loaded = AgentMemoryFileConfig.from_mapping(
        yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {},
    )
    assert loaded.memory.init.max_continuation_rounds == 7


def test_source_boundary_forbidden_paths() -> None:
    b = SourceBoundaryFilter(ArtifactsSubConfig())
    assert b.is_forbidden_source_path("node_modules/x/foo.js") is True
    assert b.is_forbidden_source_path("src/main.py") is False


def test_parse_memory_json_retry_extracts_object() -> None:
    text: str = 'noise {"a":1,"b":"two"} tail'
    d = parse_memory_json_with_retry(text)
    assert d["a"] == 1


def test_planner_v1_clamps_decision() -> None:
    raw = (
        '{"schema":"agent_memory.planner_result.v1","action":"stop",'
        '"selected":[],"exclude":[],"decision":"'
        + ("x" * 300)
        + '"}'
    )
    p = MemoryPlannerResultV1.parse(raw, max_decision=240)
    assert len(p.decision) <= 241


def test_to_nested_dict_includes_memory_init() -> None:
    nested = AgentMemoryFileConfig().to_nested_dict()
    assert nested["memory"]["init"]["max_continuation_rounds"] == 32


def test_default_file_path_respects_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p = tmp_path / "c.yaml"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(p))
    assert AgentMemoryConfigPaths.default_file_path() == p.resolve()


def test_chat_logs_enabled_from_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg_path = tmp_path / "am_chat_logs.yaml"
    cfg_path.write_text(
        "memory:\n"
        "  debug:\n"
        "    chat_logs_enabled: false\n"
        "    verbose: 1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(cfg_path))
    loaded = AgentMemoryFileConfig.from_mapping(
        yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {},
    )
    assert loaded.memory.debug.chat_logs_enabled is False
    assert loaded.memory.debug.verbose == 1
    nested = loaded.to_nested_dict()
    assert nested["memory"]["debug"]["chat_logs_enabled"] is False


def test_memory_debug_subconfig_defaults() -> None:
    d = MemoryDebugSubConfig()
    assert d.chat_logs_enabled is True
    assert d.verbose == 0
