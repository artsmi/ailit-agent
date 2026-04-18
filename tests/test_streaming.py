"""Streaming: SSE → StreamDone."""

from __future__ import annotations

from agent_core.models import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    StreamDone,
)
from agent_core.normalization.stream_assembler import iter_stream_events_from_sse_lines
from agent_core.providers.deepseek import DeepSeekAdapter
from agent_core.transport.httpx_transport import HttpxJsonTransport


class _SseOnlyTransport(HttpxJsonTransport):
    """Транспорт, возвращающий фиксированные строки SSE."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self._lines = lines

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> dict[str, object]:
        raise AssertionError("post_json must not be used in stream test")

    def post_sse_lines(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
    ):
        yield from iter(self._lines)


def test_sse_lines_end_with_done() -> None:
    """Две дельты контента и [DONE] дают итоговый нормализованный ответ."""
    lines = iter(
        [
            'data: {"choices":[{"delta":{"content":"hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "data: [DONE]",
        ]
    )
    events = list(iter_stream_events_from_sse_lines(lines, provider_id="deepseek"))
    assert isinstance(events[-1], StreamDone)
    assert events[-1].response.text_parts == ("hello",)


def test_deepseek_stream_injects_transport() -> None:
    """OpenAICompatProvider.stream использует инжектированный транспорт."""
    sse = _SseOnlyTransport(
        [
            'data: {"choices":[{"delta":{"content":"x"}}]}',
            "data: [DONE]",
        ]
    )
    adapter = DeepSeekAdapter("k", transport=sse)
    req = ChatRequest(
        messages=(ChatMessage(role=MessageRole.USER, content="ping"),),
        model="deepseek-chat",
    )
    events = list(adapter.stream(req))
    assert isinstance(events[-1], StreamDone)
