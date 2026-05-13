"""Live smoke DeepSeek (small) — только при ключе и явном согласии на live."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ailit_base.config_loader import deepseek_api_key_from_env_or_config, live_run_allowed, load_test_local_yaml
from ailit_base.models import ChatMessage, ChatRequest, MessageRole, TimeoutPolicy
from ailit_base.providers.deepseek import DeepSeekAdapter


def _repo_config() -> dict:
    root = Path(__file__).resolve().parents[1]
    return dict(load_test_local_yaml(root / "config" / "test.local.yaml"))


def _live_gate() -> None:
    cfg = _repo_config()
    key = deepseek_api_key_from_env_or_config(cfg)
    if not key:
        pytest.skip("Нет DEEPSEEK_API_KEY и нет deepseek.api_key в config/test.local.yaml")
    if not live_run_allowed(cfg) and os.environ.get("AILIT_RUN_LIVE", "").strip() != "1":
        pytest.skip("Live выключен: live.run: true в test.local.yaml или AILIT_RUN_LIVE=1")


@pytest.mark.integration
def test_live_deepseek_minimal_completion() -> None:
    """Один короткий запрос к API DeepSeek."""
    _live_gate()
    cfg = _repo_config()
    ds_cfg = cfg.get("deepseek")
    api_root = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
    smoke_timeout = 60.0
    if isinstance(ds_cfg, dict):
        api_root = str(ds_cfg.get("base_url") or api_root).rstrip("/")
        model = str(ds_cfg.get("model") or model)
    tests = cfg.get("tests")
    if isinstance(tests, dict):
        sm = tests.get("smoke")
        if isinstance(sm, dict) and sm.get("timeout_seconds") is not None:
            smoke_timeout = float(sm["timeout_seconds"])

    key = deepseek_api_key_from_env_or_config(cfg)
    adapter = DeepSeekAdapter(key, api_root=api_root)
    req = ChatRequest(
        messages=(
            ChatMessage(role=MessageRole.SYSTEM, content="You reply with one word only."),
            ChatMessage(role=MessageRole.USER, content='Reply exactly: "pong"'),
        ),
        model=model,
        max_tokens=16,
        temperature=0.0,
        timeout=TimeoutPolicy(read_seconds=smoke_timeout),
    )
    out = adapter.complete(req)
    assert out.text_parts
    joined = "".join(out.text_parts).lower()
    assert "pong" in joined
