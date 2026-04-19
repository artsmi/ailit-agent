"""Статические примеры разбора блока ``usage`` (этап O.1)."""

from __future__ import annotations

from agent_core.normalization.usage_fields import (
    normalize_usage_payload,
    usage_to_diag_dict,
)
from agent_core.normalization.openai_normalize import normalize_chat_completion


def test_cache_read_write_anthropic_style() -> None:
    """Поля cache_* как у Anthropic / шлюзов."""
    raw = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 10,
    }
    u = normalize_usage_payload(raw)
    assert u.cache_read_tokens == 30
    assert u.cache_write_tokens == 10
    assert u.usage_missing is False


def test_prompt_tokens_details_cached_maps_to_read() -> None:
    """OpenAI-style prompt_tokens_details.cached_tokens → cache_read."""
    raw = {
        "prompt_tokens": 50,
        "completion_tokens": 5,
        "total_tokens": 55,
        "prompt_tokens_details": {"cached_tokens": 40},
    }
    u = normalize_usage_payload(raw)
    assert u.cache_read_tokens == 40


def test_unknown_top_level_int_preserved() -> None:
    """Неизвестное целочисленное поле попадает в usage_unknown."""
    raw = {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
        "vendor_custom_metric": 99,
    }
    u = normalize_usage_payload(raw)
    assert dict(u.usage_unknown) == {"vendor_custom_metric": 99}


def test_usage_to_diag_roundtrip_shape() -> None:
    """usage_to_diag_dict не теряет известные поля."""
    u = normalize_usage_payload(
        {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
            "reasoning_tokens": 7,
            "cache_read_input_tokens": 4,
            "cache_creation_input_tokens": 5,
        },
    )
    d = usage_to_diag_dict(u)
    assert d["input_tokens"] == 1
    assert d["output_tokens"] == 2
    assert d["reasoning_tokens"] == 7
    assert d["cache_read_tokens"] == 4
    assert d["cache_write_tokens"] == 5


def test_last_usage_pair_from_agent_log_text() -> None:
    """Парсинг хвоста JSONL для CLI ``usage last``."""
    from ailit.agent_usage_cli import last_usage_pair_from_log_text

    log = (
        '{"event_type":"process.start","role":"agent"}\n'
        '{"event_type":"model.response",'
        '"usage":{"input_tokens":2,"output_tokens":1},'
        '"usage_session_totals":{"input_tokens":5,"output_tokens":3}}\n'
    )
    pair = last_usage_pair_from_log_text(log)
    assert pair is not None
    lu, st = pair
    assert lu["input_tokens"] == 2
    assert st["input_tokens"] == 5


def test_normalize_chat_completion_merges_unknown_meta() -> None:
    """provider_metadata получает usage_unknown_tail."""
    payload = {
        "id": "x",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hi"},
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "extra_counter": 42,
        },
    }
    out = normalize_chat_completion(payload, provider_id="mock")
    tail = out.provider_metadata.get("usage_unknown_tail")
    assert tail == {"extra_counter": 42}
