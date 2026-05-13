"""Golden-тесты нормализации ответов."""

from __future__ import annotations

import pytest

from ailit_base.models import FinishReason
from ailit_base.normalization.openai_normalize import normalize_chat_completion


def test_normalize_text_and_usage() -> None:
    """Текст + usage."""
    payload = {
        "id": "x",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hello"},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    out = normalize_chat_completion(payload, provider_id="deepseek")
    assert out.text_parts == ("hello",)
    assert out.finish_reason is FinishReason.STOP
    assert out.usage.input_tokens == 1
    assert out.usage.usage_missing is False


def test_normalize_tool_calls() -> None:
    """Штатные tool_calls."""
    payload = {
        "id": "x",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "fn", "arguments": '{"a":1}'},
                        }
                    ],
                },
            }
        ],
        "usage": {},
    }
    out = normalize_chat_completion(payload, provider_id="kimi")
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].tool_name == "fn"
    assert out.tool_calls[0].arguments_json == '{"a":1}'
    assert out.finish_reason is FinishReason.TOOL_CALLS


def test_normalize_usage_missing() -> None:
    """Нет usage — флаг usage_missing."""
    payload = {
        "id": "x",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "ok"},
            }
        ],
    }
    out = normalize_chat_completion(payload, provider_id="deepseek")
    assert out.usage.usage_missing is True


def test_parser_fallback_json_in_text() -> None:
    """Резервный путь: JSON с tool_calls в тексте."""
    text = '{"tool_calls": [{"id": "1", "name": "x", "arguments": {}}]}'
    payload = {
        "id": "x",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
    }
    out = normalize_chat_completion(payload, provider_id="deepseek", enable_parser_fallback=True)
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].tool_name == "x"


@pytest.mark.parametrize("bad", [{"choices": []}, {"choices": [{}]}])
def test_normalize_invalid_raises(bad: dict) -> None:
    """Невалидная структура — ValueError."""
    with pytest.raises(ValueError):
        normalize_chat_completion(bad, provider_id="mock")
