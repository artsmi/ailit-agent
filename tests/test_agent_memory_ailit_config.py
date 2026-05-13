"""Резолв AgentMemory: глобальный ailit config (agent_memory / default)."""

from __future__ import annotations

from dataclasses import replace

from agent_memory.agent_memory_ailit_config import (
    build_chat_provider_for_agent_memory,
    resolve_memory_llm_optimization,
)
from agent_memory.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)


def test_resolve_model_prefers_agent_memory_then_default() -> None:
    base: MemoryLlmOptimizationPolicy = replace(
        MemoryLlmOptimizationPolicy.default(),
        model="from-am-yaml",
    )
    m1 = resolve_memory_llm_optimization(
        {
            "default": {"provider": "mock", "model": "default-m"},
            "agent_memory": {"provider": "", "model": "mem-m"},
        },
        base,
    )
    assert m1.model == "mem-m"
    m2 = resolve_memory_llm_optimization(
        {
            "default": {"provider": "mock", "model": "only-default"},
            "agent_memory": {"provider": "", "model": ""},
        },
        base,
    )
    assert m2.model == "only-default"
    m3 = resolve_memory_llm_optimization(
        {"default": {"provider": "mock", "model": ""}, "agent_memory": {}},
        base,
    )
    assert m3.model == "from-am-yaml"


def test_build_provider_mock_and_deepseek() -> None:
    p0 = build_chat_provider_for_agent_memory(
        {
            "default": {"provider": "mock", "model": ""},
            "agent_memory": {"provider": "", "model": ""},
        },
    )
    assert p0.provider_id == "mock"

    p1 = build_chat_provider_for_agent_memory(
        {
            "default": {"provider": "mock", "model": ""},
            "agent_memory": {"provider": "deepseek", "model": "x"},
            "deepseek": {
                "api_key": "sk-test-dummy",
                "base_url": "https://api.deepseek.com/v1",
            },
        },
    )
    assert p1.provider_id == "deepseek"

    p2 = build_chat_provider_for_agent_memory(
        {
            "default": {"provider": "deepseek", "model": ""},
            "agent_memory": {"provider": "", "model": ""},
            "deepseek": {"api_key": "sk-y"},
        },
    )
    assert p2.provider_id == "deepseek"

    p3 = build_chat_provider_for_agent_memory(
        {
            "default": {"provider": "deepseek", "model": ""},
            "agent_memory": {"provider": "", "model": ""},
            "deepseek": {},
        },
    )
    assert p3.provider_id == "mock"
