"""
W14: DTO runtime_step, реестр LLM-команд и строгий разбор
agent_memory_command_output.v1 (G14R.2, C14R.3–4, C14R.8, C14R.10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Mapping

# --- schema versions (C14R.3, C14R.8) --------------------------------------

AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA: Final[str] = (
    "agent_memory_command_output.v1"
)
AGENT_MEMORY_COMMAND_INPUT_SCHEMA: Final[str] = (
    "agent_memory_command_input.v1"
)
AGENT_MEMORY_RUNTIME_STEP_SCHEMA: Final[str] = "agent_memory_runtime_step.v1"

# --- commands (C14R.4 matrices) --------------------------------------------


class AgentMemoryCommandName(str, Enum):
    """Реестр имён LLM-команд AgentMemory (единственный whitelist)."""

    PLAN_TRAVERSAL = "plan_traversal"
    SUMMARIZE_C = "summarize_c"
    SUMMARIZE_B = "summarize_b"
    FINISH_DECISION = "finish_decision"


class UnknownAgentMemoryCommandError(ValueError):
    """command отсутствует в ``AgentMemoryCommandName`` (unknown_command)."""


class W14CommandParseError(ValueError):
    """Невалидный JSON, prose вокруг JSON, лишние поля (strict W14)."""


class UnknownRuntimeStateError(ValueError):
    """state не из контракта C14R.8."""


class InvalidRuntimeTransitionError(ValueError):
    """Переход не из таблицы C14R.8."""


# C14R.8 — разрешённые значения state
RUNTIME_STATES: Final[tuple[str, ...]] = (
    "start",
    "list_frontier",
    "plan_traversal",
    "materialize_b",
    "decompose_b_to_c",
    "summarize_c",
    "summarize_b",
    "collect_result",
    "finish_decision",
    "finish",
    "blocked",
)
_RUNTIME_STATE_SET: Final[frozenset[str]] = frozenset(RUNTIME_STATES)

# Таблица переходов: (from_state, to_state) — C14R.8, строки 728–745
_RUNTIME_EDGES: Final[tuple[tuple[str, str], ...]] = (
    ("start", "list_frontier"),
    ("list_frontier", "plan_traversal"),
    ("plan_traversal", "materialize_b"),
    ("plan_traversal", "decompose_b_to_c"),
    ("plan_traversal", "summarize_b"),
    ("plan_traversal", "finish_decision"),
    ("materialize_b", "list_frontier"),
    ("decompose_b_to_c", "summarize_c"),
    ("summarize_c", "collect_result"),
    ("summarize_b", "collect_result"),
    ("collect_result", "plan_traversal"),
    ("collect_result", "finish_decision"),
    ("finish_decision", "finish"),
)
_ALLOW_DIRECT: Final[frozenset[tuple[str, str]]] = frozenset(
    _RUNTIME_EDGES,
)


@dataclass(frozen=True, slots=True)
class AgentMemoryCommandRegistry:
    """Реестр команд: только зарегистрированные имена (C14R.4, A14R.10)."""

    _known: ClassVar[frozenset[str]] = frozenset(
        m.value for m in AgentMemoryCommandName
    )

    @classmethod
    def is_registered(cls, name: str) -> bool:
        n = (name or "").strip()
        return n in cls._known

    @classmethod
    def resolve(cls, name: str) -> AgentMemoryCommandName:
        s = (name or "").strip()
        try:
            return AgentMemoryCommandName(s)
        except ValueError as err:
            raise UnknownAgentMemoryCommandError(
                f"unknown_command:{s!r}",
            ) from err

    @classmethod
    def registered_names(cls) -> tuple[str, ...]:
        return tuple(sorted(cls._known))


AGENT_MEMORY_COMMAND_REGISTRY: type[AgentMemoryCommandRegistry] = (
    AgentMemoryCommandRegistry
)


@dataclass(frozen=True, slots=True)
class AgentMemoryRuntimeStepV1:
    """C14R.8 — DTO ``runtime_step`` (минимальный валидируемый срез)."""

    step_id: str
    query_id: str
    state: str
    next_state: str = ""

    @staticmethod
    def _validate_state_key(label: str, value: str) -> str:
        s = (value or "").strip()
        if s not in _RUNTIME_STATE_SET:
            msg = f"invalid_runtime_state:{label}:{s!r}"
            raise UnknownRuntimeStateError(msg)
        return s

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
    ) -> AgentMemoryRuntimeStepV1:
        ver = str(raw.get("schema_version", "") or "").strip()
        if ver and ver != AGENT_MEMORY_RUNTIME_STEP_SCHEMA:
            msg = f"invalid_runtime_step_schema_version:{ver!r}"
            raise ValueError(msg)
        sid = str(raw.get("step_id", "") or "").strip()
        if not sid:
            raise ValueError("runtime_step.step_id required")
        qid = str(raw.get("query_id", "") or "").strip()
        st = cls._validate_state_key("state", str(raw.get("state", "") or ""))
        tr = raw.get("transition")
        next_s = ""
        if isinstance(tr, dict):
            next_s = str(tr.get("next_state", "") or "").strip()
        ns = ""
        if next_s:
            ns = cls._validate_state_key("next_state", next_s)
        return cls(
            step_id=sid,
            query_id=qid,
            state=st,
            next_state=ns,
        )

    @classmethod
    def from_runtime_step_value(
        cls,
        value: Any,
    ) -> AgentMemoryRuntimeStepV1:
        if not isinstance(value, dict):
            raise TypeError("runtime_step must be an object")
        return cls.from_mapping(value)

    @classmethod
    def from_command_input_envelope(
        cls,
        raw: Mapping[str, Any],
    ) -> AgentMemoryRuntimeStepV1 | None:
        rs = raw.get("runtime_step")
        if rs is None:
            return None
        if not isinstance(rs, dict):
            raise TypeError("runtime_step must be an object")
        return cls.from_mapping(rs)


def assert_runtime_state_transition(
    from_state: str,
    to_state: str,
) -> None:
    """
    Проверка по таблице C14R.8. Явные рёбра; дополнительно любой переход
    в ``blocked``, кроме исходного состояния ``finish`` (C14R.8).
    """
    fs = from_state.strip()
    ts = to_state.strip()
    for x in (fs, ts):
        if x not in _RUNTIME_STATE_SET:
            raise UnknownRuntimeStateError(
                f"invalid_runtime_state:{x!r}",
            )
    if (fs, ts) in _ALLOW_DIRECT:
        return
    if ts == "blocked" and fs != "finish":
        return
    raise InvalidRuntimeTransitionError(
        f"forbidden_runtime_transition:{fs!r}->{ts!r}",
    )


# --- W14 command output: envelope (C14R.3) -----------------------------------

_W14_COMMAND_OUTPUT_KEYS: Final[frozenset[str]] = frozenset(
    (
        "schema_version",
        "command",
        "command_id",
        "status",
        "payload",
        "decision_summary",
        "violations",
    )
)


def _is_w14_command_envelope_object(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    return (
        str(obj.get("schema_version", "") or "").strip()
        == AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA
    )


def validate_w14_command_envelope_object(
    obj: Mapping[str, Any],
) -> dict[str, Any]:
    if not _is_w14_command_envelope_object(obj):
        raise W14CommandParseError("not agent_memory_command_output.v1")
    extra = [k for k in obj if k not in _W14_COMMAND_OUTPUT_KEYS]
    if extra:
        extra_s = ", ".join(sorted(extra))
        raise W14CommandParseError(f"unknown_fields: {extra_s}")
    for k in (
        "schema_version",
        "command",
        "command_id",
        "status",
        "payload",
        "decision_summary",
        "violations",
    ):
        if k not in obj:
            raise W14CommandParseError(f"missing_field: {k}")
    cmd = str(obj.get("command", "") or "")
    AgentMemoryCommandRegistry.resolve(cmd)
    p = obj.get("payload", {})
    if not isinstance(p, dict):
        raise W14CommandParseError("payload must be an object")
    dsum: Any = obj.get("decision_summary")
    if not isinstance(dsum, str):
        raise W14CommandParseError("decision_summary must be a string")
    vio: Any = obj.get("violations")
    if not isinstance(vio, list):
        raise W14CommandParseError("violations must be an array")
    return {str(x): y for x, y in obj.items()}


def _json_extract_object(text: str) -> str | None:
    t = text or ""
    if "{" not in t:
        return None
    start: int = t.find("{")
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    return None


def parse_memory_query_pipeline_llm_text(
    text: str,
) -> dict[str, Any]:
    """
    Парсинг ответа memory planner/LLM для `AgentMemoryQueryPipeline`.

    - Legacy planner (G13) и произвольный JSON: разрешён fallback `{...}` как
      в `parse_memory_json_with_retry` **только если** это не W14 envelope.
    - ``agent_memory_command_output.v1``: **только** сырой JSON, без прозы
      вокруг и без «тихой» обрезки, строгий набор top-level полей; команда
      валидируется реестром.
    """
    raw: str = (text or "").strip()
    try:
        o = json.loads(raw)
    except json.JSONDecodeError as exc0:
        sub: str | None = _json_extract_object(raw)
        if sub is None:
            raise ValueError(f"invalid memory json: {exc0}") from exc0
        try:
            o2 = json.loads(sub)
        except json.JSONDecodeError as exc1:
            raise ValueError(
                f"invalid memory json: {exc1}",
            ) from exc1
        if not isinstance(o2, dict):
            raise ValueError("memory json must be an object")
        if _is_w14_command_envelope_object(o2):
            raise W14CommandParseError(
                "w14 command output must be only JSON, no prose or "
                "extracted substrings",
            )
        return o2
    if not isinstance(o, dict):
        raise ValueError("memory json must be an object")
    if _is_w14_command_envelope_object(o):
        return validate_w14_command_envelope_object(o)
    return o


def parse_w14_command_output_text_strict(
    text: str,
) -> dict[str, Any]:
    """
    W14: только ``json.loads`` на всю строку + строгий envelope (C14R.3).
    """
    t = (text or "").strip()
    if not t:
        raise W14CommandParseError("empty")
    try:
        o = json.loads(t)
    except json.JSONDecodeError as exc:
        raise W14CommandParseError("invalid json") from exc
    if not isinstance(o, dict):
        raise W14CommandParseError("envelope must be an object")
    return validate_w14_command_envelope_object(o)
