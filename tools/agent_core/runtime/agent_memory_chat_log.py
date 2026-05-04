"""
Логи отладки AgentMemory при memory.debug.verbose = 1.

Режим **desktop**: один файл ``…/chat_logs/<safe_chat_id>.log`` (как
``agentMemoryChatLogFileName`` в desktop ``tracePaths.ts``).

Режим **cli_init**: каталог ``…/chat_logs/ailit-cli-<suffix>/`` и внутри
append-only ``legacy.log`` (тот же формат блоков и JSON, что раньше в
плоском файле).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal, Mapping, TypeAlias

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

LEGACY_LOG_FILE_NAME: Final[str] = "legacy.log"
COMPACT_LOG_FILE_NAME: Final[str] = "compact.log"
# Compact sink (CLI): ``memory.command.requested`` — только stats в kv,
# без raw_prompt / goal (см. ``log_memory_w14_command_requested``).
CLI_SESSION_DIR_PREFIX: Final[str] = "ailit-cli-"

SessionLogMode: TypeAlias = Literal["desktop", "cli_init"]

# Единая блокировка append в процессе AgentMemory (последовательная запись).
_write_lock: threading.Lock = threading.Lock()

# Стабильные ID для сценария «зачем вызван / не вызван LLM» (whitelist).
MEMORY_AUDIT_A1_POLICY_LLM_OFF: Final[str] = "A1"
MEMORY_AUDIT_A2_MECHANICAL_SLICE: Final[str] = "A2"
MEMORY_AUDIT_A3_NO_PROJECT_ROOT: Final[str] = "A3"
MEMORY_AUDIT_A4_PLANNER_JSON_INVALID: Final[str] = "A4"
MEMORY_AUDIT_A5_LLM_PLANNER: Final[str] = "A5"
MEMORY_AUDIT_A6_W14_COMMAND_REJECTED: Final[str] = "A6"
MEMORY_AUDIT_WHY: Final[dict[str, str]] = {
    MEMORY_AUDIT_A1_POLICY_LLM_OFF: (
        "Memory LLM policy disabled: heuristic PAG only, no provider call"
    ),
    MEMORY_AUDIT_A2_MECHANICAL_SLICE: (
        "Mechanical PAG slice cache hit: fresh slice without LLM"
    ),
    MEMORY_AUDIT_A3_NO_PROJECT_ROOT: (
        "Empty project_root: cannot run planner, heuristic fallback"
    ),
    MEMORY_AUDIT_A4_PLANNER_JSON_INVALID: (
        "Planner response not valid JSON: partial without PAG writes"
    ),
    MEMORY_AUDIT_A5_LLM_PLANNER: (
        "Invoke AgentMemory W14 LLM (plan_traversal, finish_decision)"
    ),
    MEMORY_AUDIT_A6_W14_COMMAND_REJECTED: (
        "W14 agent_memory_command_output.v1 rejected "
        "(strict JSON/schema)"
    ),
}


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


def agent_memory_chat_log_file_name(raw_chat_id: str) -> str:
    """Имя файла: ``agentMemoryChatLogFileName`` (desktop ``tracePaths``)."""
    safe: str = safe_chat_id_for_log_file(raw_chat_id)
    return f"{safe}.log"


def log_file_path_for_chat(raw_chat_id: str) -> Path:
    """Путь `…/chat_logs/<safe_id>.log` (только режим desktop)."""
    return default_chat_logs_dir() / agent_memory_chat_log_file_name(
        raw_chat_id,
    )


def create_unique_cli_session_dir(parent: Path | None = None) -> Path:
    """
    Создать каталог сессии CLI ``ailit-cli-<ms>_<hex>`` под ``parent``.

    ``parent`` по умолчанию — ``default_chat_logs_dir()``. Без молчаливого
    игнорирования ошибок прав доступа.
    """
    base: Path = parent if parent is not None else default_chat_logs_dir()
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(32):
        suffix: str = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:10]}"
        candidate: Path = base / f"{CLI_SESSION_DIR_PREFIX}{suffix}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate.resolve()
        except FileExistsError:
            continue
    raise OSError(
        "failed to allocate unique cli session directory under "
        f"{base!s}",
    )


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


def audit_jsonable(x: Any) -> Any:  # noqa: ANN401
    """Сериализация значений для audit-блоков (PAG graph, вложенные DTO)."""
    return _jsonable(x)


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


_AUDIT_SEP: Final[str] = "=" * 80


class AgentMemoryChatDebugLog:
    """
    Пишет append-only при verbose=1: desktop — плоский ``<safe>.log``;
    cli_init — ``…/ailit-cli-*/legacy.log``.
    """

    def __init__(
        self,
        file_cfg: AgentMemoryFileConfig,
        *,
        session_log_mode: SessionLogMode = "desktop",
        cli_session_dir: Path | None = None,
    ) -> None:
        self._file_cfg: AgentMemoryFileConfig = file_cfg
        self._session_log_mode: SessionLogMode = session_log_mode
        self._cli_session_dir_arg: Path | None = (
            cli_session_dir.expanduser().resolve()
            if cli_session_dir is not None
            else None
        )
        self._cli_session_root_resolved: Path | None = None

    @property
    def enabled(self) -> bool:
        v: int = int(self._file_cfg.memory.debug.verbose)
        return v == 1

    def _ensure_cli_session_root_locked(self) -> Path:
        if self._session_log_mode != "cli_init":
            raise RuntimeError("cli session root only for cli_init mode")
        if self._cli_session_root_resolved is not None:
            return self._cli_session_root_resolved
        if self._cli_session_dir_arg is not None:
            root: Path = self._cli_session_dir_arg
            root.mkdir(parents=True, exist_ok=True)
            self._cli_session_root_resolved = root
            return root
        created: Path = create_unique_cli_session_dir()
        self._cli_session_root_resolved = created
        return created

    def _legacy_log_path_for_write(self, raw_chat_id: str) -> Path:
        if self._session_log_mode == "desktop":
            return log_file_path_for_chat(raw_chat_id)
        root: Path = self._ensure_cli_session_root_locked()
        return root / LEGACY_LOG_FILE_NAME

    def compact_log_path_for_write(self) -> Path | None:
        """Путь ``compact.log`` в каталоге CLI-сессии; в desktop — ``None``."""
        if self._session_log_mode != "cli_init":
            return None
        root: Path = self._ensure_cli_session_root_locked()
        return root / COMPACT_LOG_FILE_NAME

    @staticmethod
    def _dumps_pretty(data: Mapping[str, Any]) -> str:
        return json.dumps(
            dict(data),
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )

    def _write_pretty_block(
        self,
        raw_chat_id: str,
        header_line: str,
        record: dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        text: str = (
            f"{_AUDIT_SEP}\n"
            f"{header_line}\n"
            f"{self._dumps_pretty(record)}\n"
        )
        with _write_lock:
            p: Path = self._legacy_log_path_for_write(raw_chat_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(text + "\n")

    def log_audit(
        self,
        *,
        raw_chat_id: str,
        event: str,
        request_id: str,
        topic: str,
        body: Mapping[str, Any],
        service: str | None = None,
        change_batch_id: str | None = None,
    ) -> None:
        """Семантическое событие аудита (вход, рантайм, ответ work)."""
        if not self.enabled:
            return
        corr: dict[str, Any] = {"request_id": request_id}
        if service is not None and str(service).strip():
            corr["service"] = str(service).strip()
        if change_batch_id is not None and str(change_batch_id).strip():
            corr["change_batch_id"] = str(change_batch_id).strip()
        record: dict[str, Any] = {
            "event": event,
            "request_id": request_id,
            "topic": topic,
            "correlation": corr,
            **dict(body),
        }
        h_svc = f"  service={corr.get('service', '')}" if corr.get(
            "service",
        ) else ""
        h_b = (
            f"  change_batch_id={corr['change_batch_id']}"
            if corr.get("change_batch_id")
            else ""
        )
        header: str = (
            f"{_now_local_iso()}  event={event}  "
            f"request_id={request_id}  topic={topic}{h_svc}{h_b}"
        )
        self._write_pretty_block(raw_chat_id, header, record)

    def log_llm(
        self,
        *,
        raw_chat_id: str,
        request_id: str,
        phase: str,
        request: ChatRequest,
        response: NormalizedChatResponse | None,
        error: str | None = None,
        service: str | None = None,
        change_batch_id: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        corr: dict[str, Any] = {"request_id": request_id}
        if service is not None and str(service).strip():
            corr["service"] = str(service).strip()
        if change_batch_id is not None and str(change_batch_id).strip():
            corr["change_batch_id"] = str(change_batch_id).strip()
        record: dict[str, Any] = {
            "event": "llm",
            "request_id": request_id,
            "phase": phase,
            "correlation": corr,
            "request": chat_request_to_log_dict(request),
        }
        if error is not None:
            record["error"] = error
        if response is not None:
            record["response"] = chat_response_to_log_dict(response)
        h_svc = f"  service={corr['service']}" if corr.get("service") else ""
        h_b = (
            f"  change_batch_id={corr['change_batch_id']}"
            if corr.get("change_batch_id")
            else ""
        )
        header: str = (
            f"{_now_local_iso()}  event=llm  "
            f"request_id={request_id}  topic={phase}{h_svc}{h_b}"
        )
        self._write_pretty_block(raw_chat_id, header, record)
