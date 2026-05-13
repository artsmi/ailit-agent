"""LLM-классификатор perm-режима: отдельный вызов без tool-calling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ailit_base.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
)
from ailit_base.providers.protocol import ChatProvider
from agent_work.session.perm_tool_mode import PermToolMode


CLASSIFIER_PROMPT_MARKER = "[AILIT_PERM_MODE_CLASSIFIER_V1]"

VALID_MODES = frozenset(m.value for m in PermToolMode) | {"not_sure"}


@dataclass(frozen=True, slots=True)
class ClassifierModelOutput:
    """Строгий JSON-ответ классификатора."""

    mode: str
    confidence: float
    reason: str


class ClassifierJsonParser:
    """Разбор JSON из текста модели (включая markdown fence)."""

    def parse(self, text: str) -> ClassifierModelOutput | None:
        """Извлечь объект или None при ошибке."""
        raw = (text or "").strip()
        if not raw:
            return None
        raw = self._strip_fence(raw)
        try:
            obj: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if not m:
                return None
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        if not isinstance(obj, dict):
            return None
        mode = str(obj.get("mode") or "").strip().lower()
        if mode not in VALID_MODES:
            return None
        conf_raw = obj.get("confidence")
        try:
            conf = float(conf_raw)
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        reason = str(obj.get("reason") or "").strip()
        if not reason:
            reason = "(no reason)"
        return ClassifierModelOutput(mode=mode, confidence=conf, reason=reason)

    @staticmethod
    def _strip_fence(text: str) -> str:
        s = text.strip()
        if s.startswith("```"):
            lines = s.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                inner = "\n".join(lines[1:])
                if inner.rstrip().endswith("```"):
                    inner = inner.rstrip()[:-3]
                return inner.strip()
        return s


class LlmPermModeClassifier:
    """Один вызов complete/stream=False без инструментов."""

    def __init__(self, provider: ChatProvider) -> None:
        """Запомнить провайдера."""
        self._provider = provider

    def classify(
        self,
        *,
        model: str,
        temperature: float,
        user_intent: str,
        history_block: str,
        max_tokens: int = 256,
    ) -> ClassifierModelOutput | None:
        """Вернуть разобранный ответ или None."""
        system = self._system_prompt(history_block)
        req = ChatRequest(
            messages=(
                ChatMessage(role=MessageRole.SYSTEM, content=system),
                ChatMessage(
                    role=MessageRole.USER,
                    content=f"User request:\n{user_intent.strip()[:4000]}",
                ),
            ),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=(),
            tool_choice=None,
            stream=False,
        )
        resp = self._provider.complete(req)
        if resp.finish_reason is FinishReason.TOOL_CALLS and resp.tool_calls:
            return None
        text = "".join(resp.text_parts)
        return ClassifierJsonParser().parse(text)

    @staticmethod
    def _system_prompt(history_block: str) -> str:
        """Системный промпт: только JSON, без инструментов."""
        modes = "|".join(sorted(VALID_MODES))
        return (
            f"{CLASSIFIER_PROMPT_MARKER}\n"
            "You are a mode classifier. Output a single JSON object only, "
            "no markdown, no prose.\n"
            "Schema:\n"
            '  {"mode": "<'
            f"{modes}"
            '>", "confidence": <float 0..1>, "reason": "<short string>"}\n'
            "Modes:\n"
            "- read: read-only filesystem + KB tools only\n"
            "- read_plan: read + creating safe non-executable docs under "
            "workdir\n"
            "- explore: read + shell (some safe commands auto-allowed)\n"
            "- edit: full coding agent tools\n"
            "- not_sure: cannot decide; user must choose\n"
            "Recent structured decisions (newest last):\n"
            f"{history_block}\n"
        )
