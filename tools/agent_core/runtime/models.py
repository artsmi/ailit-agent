"""Модели runtime contract `ailit_agent_runtime_v1` (G8.1.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from agent_core.runtime.errors import RuntimeProtocolError


CONTRACT_VERSION: str = "ailit_agent_runtime_v1"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class RuntimeNow:
    """Clock abstraction for runtime envelopes (test-friendly)."""

    def iso(self) -> str:
        """Текущее время в ISO-формате UTC."""
        return _iso_now()


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """Идентичность runtime и контекст маршрутизации."""

    runtime_id: str
    chat_id: str
    broker_id: str
    trace_id: str
    goal_id: str
    namespace: str


@dataclass(frozen=True, slots=True)
class AgentId:
    """Уникальный идентификатор агента внутри runtime."""

    value: str


@dataclass(frozen=True, slots=True)
class MessageId:
    """Идентификатор сообщения (request/response/event)."""

    value: str


@dataclass(frozen=True, slots=True)
class TraceId:
    """Идентификатор trace."""

    value: str


@dataclass(frozen=True, slots=True)
class BrokerId:
    """Идентификатор broker-а."""

    value: str


@dataclass(frozen=True, slots=True)
class RuntimeEnvelopeBase:
    """Общие поля для сообщений и событий."""

    contract_version: str
    runtime_id: str
    chat_id: str
    broker_id: str
    trace_id: str
    message_id: str
    parent_message_id: str | None
    goal_id: str
    namespace: str
    from_agent: str
    to_agent: str | None
    created_at: str

    def validate(self) -> None:
        """Базовая валидация обязательных полей."""
        if self.contract_version != CONTRACT_VERSION:
            raise RuntimeProtocolError(
                code="contract_version_mismatch",
                message=(
                    f"expected {CONTRACT_VERSION}, "
                    f"got {self.contract_version!r}"
                ),
            )
        required = {
            "runtime_id": self.runtime_id,
            "chat_id": self.chat_id,
            "broker_id": self.broker_id,
            "trace_id": self.trace_id,
            "message_id": self.message_id,
            "goal_id": self.goal_id,
            "namespace": self.namespace,
            "from_agent": self.from_agent,
            "created_at": self.created_at,
        }
        missing = [k for k, v in required.items() if not str(v).strip()]
        if missing:
            raise RuntimeProtocolError(
                code="missing_fields",
                message=f"missing required fields: {', '.join(missing)}",
            )


def _expect_dict(value: Any, *, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeProtocolError(
            code="invalid_shape",
            message=f"{where} must be dict",
        )
    return value


def _expect_str(value: Any, *, where: str) -> str:
    if not isinstance(value, str):
        raise RuntimeProtocolError(
            code="invalid_shape",
            message=f"{where} must be str",
        )
    return value


def _expect_optional_str(value: Any, *, where: str) -> str | None:
    if value is None:
        return None
    return _expect_str(value, where=where)


@dataclass(frozen=True, slots=True)
class RuntimeRequestEnvelope(RuntimeEnvelopeBase):
    """Общий request envelope."""

    type: str
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "contract_version": self.contract_version,
            "runtime_id": self.runtime_id,
            "chat_id": self.chat_id,
            "broker_id": self.broker_id,
            "trace_id": self.trace_id,
            "message_id": self.message_id,
            "parent_message_id": self.parent_message_id,
            "goal_id": self.goal_id,
            "namespace": self.namespace,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "created_at": self.created_at,
            "type": self.type,
            "payload": dict(self.payload),
        }

    def to_json_line(self) -> str:
        """Сериализация для JSON-lines транспорта."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> RuntimeRequestEnvelope:
        data = _expect_dict(raw, where="envelope")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeProtocolError(
                code="invalid_shape",
                message="payload must be dict",
            )
        env = RuntimeRequestEnvelope(
            contract_version=_expect_str(
                data.get("contract_version"),
                where="contract_version",
            ),
            runtime_id=_expect_str(data.get("runtime_id"), where="runtime_id"),
            chat_id=_expect_str(data.get("chat_id"), where="chat_id"),
            broker_id=_expect_str(data.get("broker_id"), where="broker_id"),
            trace_id=_expect_str(data.get("trace_id"), where="trace_id"),
            message_id=_expect_str(data.get("message_id"), where="message_id"),
            parent_message_id=_expect_optional_str(
                data.get("parent_message_id"),
                where="parent_message_id",
            ),
            goal_id=_expect_str(data.get("goal_id"), where="goal_id"),
            namespace=_expect_str(data.get("namespace"), where="namespace"),
            from_agent=_expect_str(data.get("from_agent"), where="from_agent"),
            to_agent=_expect_optional_str(
                data.get("to_agent"),
                where="to_agent",
            ),
            created_at=_expect_str(data.get("created_at"), where="created_at"),
            type=_expect_str(data.get("type"), where="type"),
            payload=payload,
        )
        env.validate()
        return env

    @staticmethod
    def from_json_line(line: str) -> RuntimeRequestEnvelope:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            raise RuntimeProtocolError(
                code="json_decode_error",
                message=str(e),
            ) from e
        return RuntimeRequestEnvelope.from_dict(raw)


@dataclass(frozen=True, slots=True)
class RuntimeResponseEnvelope(RuntimeEnvelopeBase):
    """Общий response envelope."""

    type: str
    ok: bool
    payload: Mapping[str, Any]
    error: Mapping[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "contract_version": self.contract_version,
            "runtime_id": self.runtime_id,
            "chat_id": self.chat_id,
            "broker_id": self.broker_id,
            "trace_id": self.trace_id,
            "message_id": self.message_id,
            "parent_message_id": self.parent_message_id,
            "goal_id": self.goal_id,
            "namespace": self.namespace,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "created_at": self.created_at,
            "type": self.type,
            "ok": bool(self.ok),
            "payload": dict(self.payload),
            "error": dict(self.error) if self.error is not None else None,
        }

    def to_json_line(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class AgentMessageEnvelope(RuntimeRequestEnvelope):
    """Alias: runtime message between agents (topic/service/action)."""


@dataclass(frozen=True, slots=True)
class TopicEvent:
    """Topic publish: one-to-many event."""

    topic: str
    event_name: str
    payload: Mapping[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "topic.publish",
            "topic": self.topic,
            "event_name": self.event_name,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ServiceRequest:
    """Service request: request/reply (one-to-one)."""

    service: str
    request_id: str
    payload: Mapping[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "service.request",
            "service": self.service,
            "request_id": self.request_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    """Service response."""

    service: str
    request_id: str
    ok: bool
    payload: Mapping[str, Any]
    error: Mapping[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "service.response",
            "service": self.service,
            "request_id": self.request_id,
            "ok": bool(self.ok),
            "payload": dict(self.payload),
            "error": dict(self.error) if self.error is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ActionStarted:
    """Action lifecycle: started."""

    action: str
    action_id: str
    payload: Mapping[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "action.started",
            "action": self.action,
            "action_id": self.action_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ActionFeedback:
    """Action lifecycle: feedback."""

    action: str
    action_id: str
    payload: Mapping[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "action.feedback",
            "action": self.action,
            "action_id": self.action_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ActionCompleted:
    """Action lifecycle: completed."""

    action: str
    action_id: str
    payload: Mapping[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "action.completed",
            "action": self.action,
            "action_id": self.action_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ActionFailed:
    """Action lifecycle: failed."""

    action: str
    action_id: str
    error: Mapping[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "action.failed",
            "action": self.action,
            "action_id": self.action_id,
            "error": dict(self.error),
        }


@dataclass(frozen=True, slots=True)
class MemoryGrantRange:
    """Line-range within a single path."""

    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, int]:
        return {
            "start_line": int(self.start_line),
            "end_line": int(self.end_line),
        }


@dataclass(frozen=True, slots=True)
class MemoryGrant:
    """Контракт разрешения на чтение файлов (G8 MemoryGrant)."""

    grant_id: str
    issued_by: str
    issued_to: str
    namespace: str
    path: str
    ranges: tuple[MemoryGrantRange, ...]
    whole_file: bool
    reason: str
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "issued_by": self.issued_by,
            "issued_to": self.issued_to,
            "namespace": self.namespace,
            "path": self.path,
            "ranges": [r.to_dict() for r in self.ranges],
            "whole_file": bool(self.whole_file),
            "reason": self.reason,
            "expires_at": self.expires_at,
        }

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> MemoryGrant:
        data = _expect_dict(raw, where="memory_grant")
        ranges_raw = data.get("ranges")
        if not isinstance(ranges_raw, list):
            raise RuntimeProtocolError(
                code="invalid_shape",
                message="ranges must be list",
            )
        ranges: list[MemoryGrantRange] = []
        for i, item in enumerate(ranges_raw):
            d = _expect_dict(item, where=f"ranges[{i}]")
            sl = d.get("start_line")
            el = d.get("end_line")
            if not isinstance(sl, int) or not isinstance(el, int):
                raise RuntimeProtocolError(
                    code="invalid_shape",
                    message=f"ranges[{i}] start_line/end_line must be int",
                )
            ranges.append(MemoryGrantRange(start_line=sl, end_line=el))
        whole_file = data.get("whole_file")
        if not isinstance(whole_file, bool):
            raise RuntimeProtocolError(
                code="invalid_shape",
                message="whole_file must be bool",
            )
        return MemoryGrant(
            grant_id=_expect_str(data.get("grant_id"), where="grant_id"),
            issued_by=_expect_str(data.get("issued_by"), where="issued_by"),
            issued_to=_expect_str(data.get("issued_to"), where="issued_to"),
            namespace=_expect_str(data.get("namespace"), where="namespace"),
            path=_expect_str(data.get("path"), where="path"),
            ranges=tuple(ranges),
            whole_file=whole_file,
            reason=_expect_str(data.get("reason"), where="reason"),
            expires_at=_expect_str(data.get("expires_at"), where="expires_at"),
        )


def make_request_envelope(
    *,
    identity: RuntimeIdentity,
    message_id: str,
    parent_message_id: str | None,
    from_agent: str,
    to_agent: str | None,
    msg_type: str,
    payload: Mapping[str, Any],
    now: RuntimeNow | None = None,
) -> RuntimeRequestEnvelope:
    """Удобный конструктор request envelope."""
    clock = now if now is not None else RuntimeNow()
    return RuntimeRequestEnvelope(
        contract_version=CONTRACT_VERSION,
        runtime_id=identity.runtime_id,
        chat_id=identity.chat_id,
        broker_id=identity.broker_id,
        trace_id=identity.trace_id,
        message_id=message_id,
        parent_message_id=parent_message_id,
        goal_id=identity.goal_id,
        namespace=identity.namespace,
        from_agent=from_agent,
        to_agent=to_agent,
        created_at=clock.iso(),
        type=msg_type,
        payload=payload,
    )


def make_response_envelope(
    *,
    request: RuntimeRequestEnvelope,
    ok: bool,
    payload: Mapping[str, Any],
    error: Mapping[str, Any] | None,
    now: RuntimeNow | None = None,
) -> RuntimeResponseEnvelope:
    """Ответ на request envelope."""
    clock = now if now is not None else RuntimeNow()
    return RuntimeResponseEnvelope(
        contract_version=CONTRACT_VERSION,
        runtime_id=request.runtime_id,
        chat_id=request.chat_id,
        broker_id=request.broker_id,
        trace_id=request.trace_id,
        message_id=request.message_id,
        parent_message_id=request.parent_message_id,
        goal_id=request.goal_id,
        namespace=request.namespace,
        from_agent=request.to_agent or request.from_agent,
        to_agent=request.from_agent,
        created_at=clock.iso(),
        type=str(request.type),
        ok=bool(ok),
        payload=payload,
        error=error,
    )


def ensure_json_object(value: Any) -> dict[str, Any]:
    """Привести произвольный payload к JSON-object (dict)."""
    if isinstance(value, dict):
        return dict(value)
    raise RuntimeProtocolError(
        code="invalid_shape",
        message="expected dict payload",
    )


def ensure_json_mapping(value: Any) -> Mapping[str, Any]:
    """Привести произвольный payload к Mapping."""
    if isinstance(value, Mapping):
        return value
    raise RuntimeProtocolError(
        code="invalid_shape",
        message="expected mapping payload",
    )


def ensure_json_list(value: Any) -> Sequence[Any]:
    """Привести произвольный payload к JSON-array."""
    if isinstance(value, list):
        return value
    raise RuntimeProtocolError(
        code="invalid_shape",
        message="expected list payload",
    )
