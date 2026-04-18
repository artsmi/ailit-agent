"""Ошибки транспорта и malformed ответов."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_core.models import ChatMessage, ChatRequest, MessageRole, RetryPolicy, TimeoutPolicy
from agent_core.providers.deepseek import DeepSeekAdapter
from agent_core.transport.errors import MalformedProviderResponseError, TransportHttpError
from agent_core.transport.httpx_transport import HttpxJsonTransport
from agent_core.transport.retry_runner import run_with_retry


def test_post_json_malformed_body_raises() -> None:
    """Невалидный JSON в ответе."""
    transport = HttpxJsonTransport()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = json.JSONDecodeError("bad json", "", 0)

    with patch("httpx.Client") as client_cls:
        inst = MagicMock()
        client_cls.return_value.__enter__.return_value = inst
        inst.post.return_value = mock_response
        with pytest.raises(MalformedProviderResponseError):
            transport.post_json("http://example.com", headers={}, body={})


def test_post_json_http_error_raises() -> None:
    """HTTP 500 с TransportHttpError."""
    transport = HttpxJsonTransport()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "err"

    with patch("httpx.Client") as client_cls:
        inst = MagicMock()
        client_cls.return_value.__enter__.return_value = inst
        inst.post.return_value = mock_response
        with pytest.raises(TransportHttpError) as exc:
            transport.post_json("http://example.com", headers={}, body={})
        assert exc.value.status_code == 500


def test_retry_runner_retries_429() -> None:
    """Повтор при 429."""
    calls: list[int] = []

    def op() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise TransportHttpError("rate", status_code=429)
        return "ok"

    out = run_with_retry(op, RetryPolicy(max_attempts=3, backoff_base_seconds=0.01))
    assert out == "ok"
    assert len(calls) == 2


def test_deepseek_complete_surfaces_transport_error() -> None:
    """Адаптер пробрасывает HTTP ошибку транспорта."""
    transport = HttpxJsonTransport()
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "forbidden"

    with patch("httpx.Client") as client_cls:
        inst = MagicMock()
        client_cls.return_value.__enter__.return_value = inst
        inst.post.return_value = mock_response
        adapter = DeepSeekAdapter("fake-key", transport=transport)
        req = ChatRequest(
            messages=(ChatMessage(role=MessageRole.USER, content="hi"),),
            model="deepseek-chat",
            timeout=TimeoutPolicy(read_seconds=1.0),
        )
        with pytest.raises(TransportHttpError):
            adapter.complete(req)
