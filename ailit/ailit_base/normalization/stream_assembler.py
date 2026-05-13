"""Сборка streaming SSE chunks OpenAI-совместимого API в события и итог."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ailit_base.models import (
    FinishReason,
    NormalizedChatResponse,
    StreamDone,
    StreamEvent,
    StreamTextDelta,
    StreamToolDelta,
    ToolCallNormalized,
)
from ailit_base.normalization.openai_normalize import normalize_chat_completion


def _usage_from_chunk(obj: dict[str, Any]) -> dict[str, Any] | None:
    u = obj.get("usage")
    return u if isinstance(u, dict) else None


def iter_stream_events_from_sse_lines(
    lines: Iterator[str],
    *,
    provider_id: str,
) -> Iterator[StreamEvent]:
    """Преобразовать строки SSE в поток StreamEvent, завершая StreamDone."""
    text_buffer: list[str] = []
    tool_acc: dict[int, dict[str, Any]] = {}
    last_usage: dict[str, Any] | None = None
    last_finish: str | None = None
    model: str | None = None
    resp_id: str | None = None

    for line in lines:
        if not line or line.startswith(":"):
            continue
        if line.startswith("data: "):
            data = line.removeprefix("data: ").strip()
        elif line.startswith("data:"):
            data = line.split("data:", 1)[1].strip()
        else:
            continue
        if data == "[DONE]":
            synthetic = _build_synthetic_payload(
                text_buffer,
                tool_acc,
                last_usage,
                last_finish,
                model=model,
                response_id=resp_id,
            )
            normalized = normalize_chat_completion(
                synthetic,
                provider_id=provider_id,
                enable_parser_fallback=True,
            )
            yield StreamDone(response=normalized)
            return
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(chunk, dict):
            continue
        if model is None and isinstance(chunk.get("model"), str):
            model = chunk["model"]
        if resp_id is None and isinstance(chunk.get("id"), str):
            resp_id = chunk["id"]
        u = _usage_from_chunk(chunk)
        if u is not None:
            last_usage = u
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        c0 = choices[0]
        if not isinstance(c0, dict):
            continue
        fr = c0.get("finish_reason")
        if isinstance(fr, str) and fr:
            last_finish = fr
        delta = c0.get("delta")
        if not isinstance(delta, dict):
            continue
        if isinstance(delta.get("content"), str) and delta["content"]:
            text_buffer.append(delta["content"])
            yield StreamTextDelta(text=delta["content"], channel="content")
        rc = delta.get("reasoning_content")
        if not (isinstance(rc, str) and rc):
            alt = delta.get("reasoning")
            if isinstance(alt, str) and alt:
                rc = alt
        if isinstance(rc, str) and rc:
            # Reasoning — отдельные дельты, не в merge content.
            yield StreamTextDelta(text=rc, channel="reasoning")
        tcd = delta.get("tool_calls")
        if isinstance(tcd, list):
            for part in tcd:
                if not isinstance(part, dict):
                    continue
                index = int(part.get("index", 0))
                slot = tool_acc.setdefault(
                    index,
                    {"id": None, "name": None, "args": ""},
                )
                if isinstance(part.get("id"), str):
                    slot["id"] = part["id"]
                func = part.get("function")
                if isinstance(func, dict):
                    if isinstance(func.get("name"), str) and func["name"]:
                        slot["name"] = func["name"]
                    if isinstance(func.get("arguments"), str):
                        slot["args"] += func["arguments"]
                yield StreamToolDelta(
                    index=index,
                    call_id=slot["id"],
                    tool_name=slot["name"],
                    arguments_fragment=slot["args"],
                )

    # Поток оборван без [DONE]
    synthetic = _build_synthetic_payload(
        text_buffer,
        tool_acc,
        last_usage,
        last_finish,
        model=model,
        response_id=resp_id,
    )
    normalized = normalize_chat_completion(
        synthetic,
        provider_id=provider_id,
        enable_parser_fallback=True,
    )
    yield StreamDone(response=normalized)


def _build_synthetic_payload(
    text_buffer: list[str],
    tool_acc: dict[int, dict[str, Any]],
    last_usage: dict[str, Any] | None,
    last_finish: str | None,
    *,
    model: str | None,
    response_id: str | None,
) -> dict[str, Any]:
    """Собрать payload для normalize_chat_completion."""
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_buffer),
    }
    if tool_acc:
        tcs: list[dict[str, Any]] = []
        for idx in sorted(tool_acc):
            slot = tool_acc[idx]
            call_id = slot.get("id") or f"stream_{idx}"
            name = slot.get("name") or ""
            args = slot.get("args") or ""
            tcs.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
            )
        message["tool_calls"] = tcs
    choice: dict[str, Any] = {"index": 0, "message": message}
    if last_finish:
        choice["finish_reason"] = last_finish
    else:
        choice["finish_reason"] = "tool_calls" if tool_acc else "stop"
    payload: dict[str, Any] = {
        "id": response_id or "synthetic",
        "object": "chat.completion",
        "model": model or "",
        "choices": [choice],
    }
    if last_usage:
        payload["usage"] = last_usage
    return payload


def finish_reason_from_stream(
    normalized: NormalizedChatResponse,
) -> FinishReason:
    """Finish reason из нормализованного ответа."""
    return normalized.finish_reason


def tool_calls_from_stream(
    normalized: NormalizedChatResponse,
) -> tuple[ToolCallNormalized, ...]:
    """Tool calls из нормализованного ответа."""
    return normalized.tool_calls
