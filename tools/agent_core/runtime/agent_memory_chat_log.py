"""
Логи отладки AgentMemory: ~/.ailit/agent-memory/chat_logs/<chat_id>.log
при memory.debug.verbose = 1. Строка = системное время + JSON-событие.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping

from agent_core.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    NormalizedUsage,
    ToolCallNormalized,
    ToolDefinition,
)

from agent_core.runtime.agent_memory_config import AgentMemoryFileConfig

_SAFE_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]")

# Единая блокировка append в процессе AgentMemory (последовательная запись).
_write_lock: threading.Lock = threading.Lock()


def safe_chat_id_for_log_file(raw_chat_id: str) -> str:
    """
    Согласовано с desktop `safeChatIdForTraceFile`: только [A-Za-z0-9_-].
    Пустой результат — стабильный идентификатор `unknown-…`.
    """
    s = _SAFE_RE.findall(str(raw_chat_id or ""))
    out = "".join(s)
    if out:
        return out
    raw_b = str(raw_chat_id).encode("utf-8", errors="replace")
    h16 = hashlib.sha256(raw_b).hexdigest()[:16]
    return f"unknown-{h16}"


def default_chat_logs_dir() -> Path:
    """
    `~/.ailit/agent-memory/chat_logs` либо `AILIT_AGENT_MEMORY_CHAT_LOG_DIR`.
    """
    ex: str = os.environ.get("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", "").strip()
    if ex:
        return Path(ex).expanduser().resolve()
    return (Path.home() / ".ailit" / "agent-memory" / "chat_logs").resolve()


def log_file_path_for_chat(raw_chat_id: str) -> Path:
    """Путь `…/chat_logs/<safe_id>.log`."""
    safe: str = safe_chat_id_for_log_file(raw_chat_id)
    return default_chat_logs_dir() / f"{safe}.log"


def _now_local_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _message_to_dict(m: ChatMessage) -> dict[str, Any]:
    o: dict[str, Any] = {
        "role": m.role.value
        if isinstance(m.role, MessageRole)
        else str(m.role),
        "content": m.content,
    }
    if m.name:
        o["name"] = m.name
    if m.tool_call_id:
        o["tool_call_id"] = m.tool_call_id
    if m.tool_calls:
        o["tool_calls"] = [_tc_to_dict(t) for t in m.tool_calls]
    return o


def _tc_to_dict(t: ToolCallNormalized) -> dict[str, Any]:
    return {
        "call_id": t.call_id,
        "tool_name": t.tool_name,
        "arguments_json": t.arguments_json,
        "stream_index": t.stream_index,
        "provider_name": t.provider_name,
        "is_complete": t.is_complete,
    }


def _tool_def_to_dict(t: ToolDefinition) -> dict[str, Any]:
    return {
        "name": t.name,
        "description": t.description,
        "parameters": dict(t.parameters),
    }


def _jsonable(x: Any) -> Any:  # noqa: ANN401
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, Mapping) and not is_dataclass(x):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if is_dataclass(x):
        return _jsonable(asdict(x))
    if isinstance(x, MessageRole):
        return x.value
    return str(x)


def chat_request_to_log_dict(req: ChatRequest) -> dict[str, Any]:
    return {
        "model": req.model,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "stream": req.stream,
        "strict_json_schema": req.strict_json_schema,
        "messages": [_message_to_dict(m) for m in req.messages],
        "tools": (
            [_tool_def_to_dict(t) for t in req.tools] if req.tools else []
        ),
        "tool_choice": asdict(req.tool_choice) if req.tool_choice else None,
        "timeout": asdict(req.timeout) if is_dataclass(req.timeout) else {},
        "retry": asdict(req.retry) if is_dataclass(req.retry) else {},
        "extra": _jsonable(req.extra) if req.extra else {},
    }


def chat_response_to_log_dict(resp: NormalizedChatResponse) -> dict[str, Any]:
    usage: NormalizedUsage = resp.usage
    return {
        "text_parts": list(resp.text_parts),
        "text_joined": "".join(resp.text_parts),
        "tool_calls": [_jsonable(t) for t in resp.tool_calls]
        if resp.tool_calls
        else [],
        "finish_reason": (
            resp.finish_reason.value
            if isinstance(resp.finish_reason, FinishReason)
            else str(resp.finish_reason)
        ),
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "cached_tokens": usage.cached_tokens,
        },
        "provider_metadata": _jsonable(resp.provider_metadata),
        "raw_debug_payload": _jsonable(resp.raw_debug_payload)
        if resp.raw_debug_payload
        else None,
    }


class AgentMemoryChatDebugLog:
    """
    Пишет append-only в `log_file_path_for_chat(chat_id)` при verbose=1.
    Все записи в одной строке: `ISO-время {"event":…}`.
    """

    def __init__(self, file_cfg: AgentMemoryFileConfig) -> None:
        self._file_cfg: AgentMemoryFileConfig = file_cfg

    @property
    def enabled(self) -> bool:
        v: int = int(self._file_cfg.memory.debug.verbose)
        return v == 1

    def _append(
        self,
        raw_chat_id: str,
        event: str,
        data: dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        p: Path = log_file_path_for_chat(raw_chat_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec: dict[str, Any] = {"event": event, **data}
        j = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        line: str = f"{_now_local_iso()} {j}"
        with _write_lock:
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def log_llm(
        self,
        *,
        raw_chat_id: str,
        request_id: str,
        phase: str,
        request: ChatRequest,
        response: NormalizedChatResponse | None,
        error: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload: dict[str, Any] = {
            "request_id": request_id,
            "phase": phase,
            "request": chat_request_to_log_dict(request),
        }
        if error is not None:
            payload["error"] = error
        if response is not None:
            payload["response"] = chat_response_to_log_dict(response)
        self._append(raw_chat_id, "llm", payload)
