"""Тест этапа 3: одинаковый сырой ответ → одинаковая нормализация у адаптеров."""

from __future__ import annotations

from ailit_base.models import ChatMessage, ChatRequest, MessageRole, NormalizedChatResponse
from ailit_base.providers.deepseek import DeepSeekAdapter
from ailit_base.providers.kimi import KimiAdapter
from ailit_base.providers.mock_provider import MockProvider
from ailit_base.transport.httpx_transport import HttpxJsonTransport


class _FixedJsonTransport(HttpxJsonTransport):
    """Всегда возвращает один и тот же JSON completion."""

    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__()
        self._payload = payload

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> dict[str, object]:
        return dict(self._payload)

    def post_sse_lines(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
    ):
        raise AssertionError("stream not used in gate test")


SHARED_PAYLOAD: dict[str, object] = {
    "id": "chatcmpl-gate",
    "object": "chat.completion",
    "model": "parity-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "same-body"},
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
}


def _semantic_core(resp: NormalizedChatResponse) -> tuple:
    """Сравнение без provider-specific metadata и raw payload."""
    tcs = tuple((tc.tool_name, tc.arguments_json, tc.stream_index) for tc in resp.tool_calls)
    return (resp.text_parts, tcs, resp.finish_reason, resp.usage)


def test_mock_baseline_distinct_from_http_shape() -> None:
    """Mock даёт свой фиксированный профиль (контракт отдельно проверен)."""
    p = MockProvider()
    req = ChatRequest(
        messages=(ChatMessage(role=MessageRole.USER, content="x"),),
        model="any",
    )
    out = p.complete(req)
    assert out.text_parts == ("mock-ok",)


def test_kimi_and_deepseek_normalize_identically_for_shared_payload() -> None:
    """Один HTTP JSON → одинаковая семантика нормализации (различается только meta)."""
    tx = _FixedJsonTransport(SHARED_PAYLOAD)
    ds = DeepSeekAdapter("key-ds", transport=tx)
    km = KimiAdapter("key-km", transport=tx)
    req = ChatRequest(
        messages=(ChatMessage(role=MessageRole.USER, content="hi"),),
        model="parity-model",
    )
    a = ds.complete(req)
    b = km.complete(req)
    assert _semantic_core(a) == _semantic_core(b)
    assert a.provider_metadata["provider_id"] == "deepseek"
    assert b.provider_metadata["provider_id"] == "kimi"
