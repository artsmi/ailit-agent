"""
AgentMemory + глобальный ``~/.ailit/config/config.yaml`` (пункт A):
провайдер/модель из ``agent_memory`` с fallback на ``default``,
ключи — те же секции ``deepseek`` / ``kimi``, что и у AgentWork.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Final, Mapping, MutableMapping

from ailit_cli.merged_config import load_merged_ailit_config

from ailit_base.config_loader import (
    deepseek_api_key_from_env_or_config,
    kimi_api_key_from_env_or_config,
)
from ailit_base.providers.factory import ProviderFactory, ProviderKind
from ailit_base.providers.protocol import ChatProvider
from agent_memory.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)

_EMPTY: Final[Mapping[str, Any]] = {}


def load_merged_ailit_config_for_memory() -> dict[str, Any]:
    """Только глобальный и env-слой (без project_root)."""
    raw: MutableMapping[str, Any] = dict(load_merged_ailit_config(None))
    return dict(raw)


def max_memory_queries_per_user_turn(merged: Mapping[str, Any]) -> int:
    """C14R.10: cap на число memory.query_context на user turn (default 6)."""
    mem: Any = merged.get("memory")
    if not isinstance(mem, dict):
        return 6
    rt: Any = mem.get("runtime")
    if not isinstance(rt, dict):
        return 6
    raw: Any = rt.get("max_memory_queries_per_user_turn", 6)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 6
    return max(1, min(n, 1_000))


def agent_memory_rpc_timeout_s(merged: Mapping[str, Any]) -> float:
    """Таймаут Unix-RPC AgentWork→AgentMemory (сек); W14 SLA, default 120."""
    mem: Any = merged.get("memory")
    if not isinstance(mem, dict):
        return 120.0
    rt: Any = mem.get("runtime")
    if not isinstance(rt, dict):
        return 120.0
    raw: Any = rt.get("agent_memory_rpc_timeout_s", 120)
    try:
        t = float(raw)
    except (TypeError, ValueError):
        return 120.0
    return max(5.0, min(t, 3_600.0))


def _str_lower(x: object) -> str:
    return str(x or "").strip().lower()


def _effective_memory_provider(
    merged: Mapping[str, Any],
) -> str:
    am: Any = merged.get("agent_memory", _EMPTY)
    p = _str_lower(am.get("provider", "")) if isinstance(am, Mapping) else ""
    if p:
        return p
    d: Any = merged.get("default", _EMPTY)
    if isinstance(d, Mapping):
        return _str_lower(d.get("provider", "mock")) or "mock"
    return "mock"


def resolve_memory_llm_optimization(
    merged: Mapping[str, Any],
    base: MemoryLlmOptimizationPolicy,
) -> MemoryLlmOptimizationPolicy:
    """
    Модель: ``agent_memory.model`` → ``default.model`` → base (am-yaml).
    """
    am: Any = merged.get("agent_memory", _EMPTY)
    m = ""
    if isinstance(am, Mapping):
        m = str(am.get("model", "") or "").strip()
    if not m:
        d: Any = merged.get("default", _EMPTY)
        if isinstance(d, Mapping):
            m = str(d.get("model", "") or "").strip()
    if m:
        return replace(base, model=m)
    return base


def build_chat_provider_for_agent_memory(
    merged: Mapping[str, Any],
) -> ChatProvider:
    """
    Провайдер: ``agent_memory.provider`` → ``default.provider``;
    без ключа deepseek/kimi — мок.
    """
    p = _effective_memory_provider(merged)
    cfg: dict[str, Any] = dict(merged)
    if p in ("mock", "none", "off", ""):
        return ProviderFactory.create(ProviderKind.MOCK, config=cfg)
    if p == "deepseek":
        if not deepseek_api_key_from_env_or_config(cfg):
            return ProviderFactory.create(ProviderKind.MOCK, config=cfg)
        return ProviderFactory.create(ProviderKind.DEEPSEEK, config=cfg)
    if p in ("kimi", "moonshot"):
        if not kimi_api_key_from_env_or_config(cfg):
            return ProviderFactory.create(ProviderKind.MOCK, config=cfg)
        return ProviderFactory.create(ProviderKind.KIMI, config=cfg)
    return ProviderFactory.create(ProviderKind.MOCK, config=cfg)
