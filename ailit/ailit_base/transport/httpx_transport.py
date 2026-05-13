"""HTTP-клиент на httpx: JSON POST и SSE stream."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

import httpx

from ailit_base.models import TimeoutPolicy
from ailit_base.transport.errors import MalformedProviderResponseError, TransportHttpError


class HttpxJsonTransport:
    """Минимальный транспорт для OpenAI-совместимых chat completions."""

    def __init__(self, *, timeout_policy: TimeoutPolicy | None = None) -> None:
        """Инициализировать клиент с политикой таймаутов."""
        self._timeout_policy = timeout_policy or TimeoutPolicy()

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._timeout_policy.connect_seconds,
            read=self._timeout_policy.read_seconds,
            write=self._timeout_policy.write_seconds,
            pool=self._timeout_policy.pool_seconds,
        )

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Выполнить POST и вернуть распарсенный JSON объект."""
        with httpx.Client(timeout=self._timeout()) as client:
            response = client.post(url, headers=dict(headers), json=dict(body))
        if response.status_code >= 400:
            snippet = response.text[:512]
            raise TransportHttpError(
                f"HTTP {response.status_code} for {url}",
                status_code=response.status_code,
                body_snippet=snippet,
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise MalformedProviderResponseError("response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise MalformedProviderResponseError("response JSON root must be object")
        return data

    def post_sse_lines(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
    ) -> Iterator[str]:
        """Открыть streaming POST и итерировать сырые строки SSE."""
        with httpx.Client(timeout=self._timeout()) as client:
            with client.stream("POST", url, headers=dict(headers), json=dict(body)) as stream:
                if stream.status_code >= 400:
                    text = stream.read().decode("utf-8", errors="replace")[:512]
                    raise TransportHttpError(
                        f"HTTP {stream.status_code} for {url}",
                        status_code=stream.status_code,
                        body_snippet=text,
                    )
                for line in stream.iter_lines():
                    if line is None:
                        continue
                    yield line
