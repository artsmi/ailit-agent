"""G12.5: AgentMemory global config, boundary filter, JSON retry."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.runtime.agent_memory_config import (
    AgentMemoryConfigPaths,
    AgentMemoryFileConfig,
    MemoryPlannerResultV1,
    SourceBoundaryFilter,
    ArtifactsSubConfig,
    load_or_create_agent_memory_config,
    parse_memory_json_with_retry,
)


def test_load_or_create_writes_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg_path: Path = tmp_path / "am" / "config.yaml"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(cfg_path))
    p1: AgentMemoryFileConfig = load_or_create_agent_memory_config()
    assert cfg_path.is_file()
    assert p1.memory.llm.max_full_b_bytes == 32_768
    p2: AgentMemoryFileConfig = load_or_create_agent_memory_config()
    assert p2.memory.llm.max_full_b_chars == p1.memory.llm.max_full_b_chars


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


def test_default_file_path_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(p))
    assert AgentMemoryConfigPaths.default_file_path() == p.resolve()
