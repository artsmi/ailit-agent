"""AgentWork subprocess worker.

Цель: `work.handle_user_prompt` исполняется через `SessionRunner` и эмитит
UI-события в runtime trace (через `topic.publish`), чтобы desktop UI мог
показывать streaming-ответы, tool-логи и bash output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Mapping, MutableMapping, Optional

from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.factory import ProviderFactory, ProviderKind
from agent_core.providers.mock_provider import MockProvider
from agent_core.providers.protocol import ChatProvider
from agent_core.session.event_contract import SessionEvent
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.perm_tool_mode import normalize_perm_tool_mode
from agent_core.session.perm_turn import (
    PermModeTurnCoordinator,
    build_mode_kb_namespace,
    memory_namespace_from_cfg,
)
from agent_core.session.d_level_compact import DLevelCompactService
from agent_core.session.context_ledger import (
    ContextProjectRef,
    memory_injected_v2_payload,
)
from agent_core.session.repo_context import (
    detect_repo_context,
    namespace_for_repo,
)
from agent_core.runtime.agent_memory_ailit_config import (
    agent_memory_rpc_timeout_s,
    load_merged_ailit_config_for_memory,
    max_memory_queries_per_user_turn,
)
from agent_core.runtime.agent_memory_result_v1 import FIX_MEMORY_LLM_JSON_STEP
from agent_core.runtime.models import (
    AGENT_WORK_MEMORY_QUERY_V1,
    CONTRACT_VERSION,
    RuntimeRequestEnvelope,
    RuntimeIdentity,
    TopicEvent,
    make_request_envelope,
    make_response_envelope,
)
from agent_core.system_style_defaults import merge_with_base_system
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.bash_tools import bash_tool_registry
from agent_core.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_core.tool_runtime.registry import (
    ToolRegistry,
    default_builtin_registry,
)
from agent_core.runtime.subprocess_agents.work_orchestrator import (
    AgentWorkProfile,
    WorkTaskOrchestrator,
    WorkTaskRequest,
)

from ailit.agent_provider_config import AgentRunProviderConfigBuilder
from ailit.tool_system_hints import (
    inject_tool_hints_before_first_user,
    memory_kb_first_enabled,
)


@dataclass(frozen=True, slots=True)
class WorkAgentConfig:
    """Конфиг AgentWork."""

    chat_id: str
    broker_id: str
    namespace: str
    broker_socket_path: str = ""


@dataclass(frozen=True, slots=True)
class _Workspace:
    namespace: str
    project_root: Path
    project_roots: tuple[Path, ...] = field(default_factory=tuple)


_MEMORY_RPC_FAILED_ADVISORY: str = (
    "AgentMemory RPC failed or timed out. This turn does not have a complete "
    "memory result. Tell the user; do not use glob_file, read_file, or "
    "run_shell as a substitute for the missing AgentMemory result."
)

_MEMORY_CONTINUATION_CAP_ADVISORY: str = (
    "AgentMemory returned partial with a continuation subgoal, but "
    "max_memory_queries_per_user_turn was reached. Summarize injected memory "
    "only; suggest continuing in a follow-up message if needed."
)


def _collect_refs_from_agent_memory_result(
    amr: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    paths: set[str] = set()
    nids: set[str] = set()
    raw = amr.get("results")
    if isinstance(raw, list):
        for it in raw:
            if not isinstance(it, Mapping):
                continue
            p = str(it.get("path") or "").strip()
            if p:
                paths.add(p)
            cid = it.get("c_node_id")
            if cid is not None and str(cid).strip():
                nids.add(str(cid).strip())
            nid = it.get("node_id")
            if nid is not None and str(nid).strip():
                nids.add(str(nid).strip())
    return sorted(paths), sorted(nids)


def _partial_reasons_signal_continuation(amr: Mapping[str, Any]) -> bool:
    rt = amr.get("runtime_trace")
    if not isinstance(rt, Mapping):
        return False
    pr = rt.get("partial_reasons")
    if not isinstance(pr, list):
        return False
    for item in pr:
        if "continuation" in str(item).lower():
            return True
    return False


_MEMORY_RNS_GENERIC_NO_FOLLOWUP_LOWER: Final[frozenset[str]] = frozenset(
    (
        "read selected context",
        "provide more specific memory goal",
    ),
)


def _recommended_next_step_implies_no_memory_followup(rns_raw: object) -> bool:
    rns = str(rns_raw or "").strip()
    if not rns:
        return True
    return rns.lower() in _MEMORY_RNS_GENERIC_NO_FOLLOWUP_LOWER


def _memory_path_refs_strictly_expand(
    amr: Mapping[str, Any],
    *,
    paths_before: frozenset[str],
    nids_before: frozenset[str],
) -> bool:
    p2, n2 = _collect_refs_from_agent_memory_result(amr)
    return bool((set(p2) - paths_before) | (set(n2) - nids_before))


def _memory_path_partial_terminal(sot: _AgentMemoryPathSoT) -> bool:
    amr = sot.agent_memory_result
    rns = str(amr.get("recommended_next_step") or "").strip()
    if rns == FIX_MEMORY_LLM_JSON_STEP:
        return True
    ms = sot.memory_slice
    if isinstance(ms, Mapping) and bool(ms.get("w14_contract_failure")):
        return True
    return False


def _memory_path_should_continue_loop(
    sot: _AgentMemoryPathSoT,
    *,
    paths_before: frozenset[str],
    nids_before: frozenset[str],
) -> bool:
    amr = sot.agent_memory_result
    if str(amr.get("status") or "").strip().lower() != "partial":
        return False
    if amr.get("memory_continuation_required") is True:
        return True
    if _partial_reasons_signal_continuation(amr):
        return True
    if _recommended_next_step_implies_no_memory_followup(
        amr.get("recommended_next_step"),
    ):
        return False
    return _memory_path_refs_strictly_expand(
        amr,
        paths_before=paths_before,
        nids_before=nids_before,
    )


@dataclass(frozen=True, slots=True)
class _AgentMemoryPathSoT:
    """Распарсенный SoT memory-path из payload ответа broker."""

    agent_memory_result: Mapping[str, Any]
    memory_slice: dict[str, Any] | None


class _AgentMemoryPathSoTParser:
    """Извлечь ``agent_memory_result`` и ``memory_slice`` из payload."""

    @staticmethod
    def parse_payload(
        payload: Mapping[str, Any],
    ) -> _AgentMemoryPathSoT | None:
        raw = payload.get("agent_memory_result")
        if not isinstance(raw, Mapping):
            return None
        ms = payload.get("memory_slice")
        ms_d = ms if isinstance(ms, dict) else None
        return _AgentMemoryPathSoT(
            agent_memory_result=raw,
            memory_slice=ms_d,
        )


class _MemoryPathTurnClassifier:
    """Классификация исхода одного ответа AM по SoT (W14)."""

    @staticmethod
    def outcome_kind(
        sot: _AgentMemoryPathSoT,
        *,
        paths_before: frozenset[str],
        nids_before: frozenset[str],
    ) -> Literal["continue", "finish_inject", "finish_silent"]:
        amr = sot.agent_memory_result
        st = str(amr.get("status") or "").strip().lower()
        if st == "blocked":
            return "finish_silent"
        if st == "complete":
            return "finish_inject"
        if st == "partial":
            if _memory_path_partial_terminal(sot):
                return "finish_inject"
            if _memory_path_should_continue_loop(
                sot,
                paths_before=paths_before,
                nids_before=nids_before,
            ):
                return "continue"
            return "finish_inject"
        if st:
            return "finish_inject"
        return "finish_silent"


def _work_agent_perm_mode_enabled() -> bool:
    """Включение perm-5 + классификатор (Desktop: UI; выкл. через env)."""
    raw = os.environ.get("AILIT_WORK_AGENT_PERM", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


class _ProviderAssembler:
    """Выбрать провайдера из merged-конфига или fallback на mock."""

    def build(self, *, project_root: Path) -> tuple[ChatProvider, str]:
        try:
            cfg = AgentRunProviderConfigBuilder().build(
                project_root.resolve(),
                use_dev_repo_yaml=True,
            )
        except Exception:
            return MockProvider(), "mock"  # type: ignore[return-value]
        ds = cfg.get("deepseek")
        if isinstance(ds, dict):
            key = str(ds.get("api_key") or "").strip()
            if key or os.environ.get("DEEPSEEK_API_KEY", "").strip():
                prov = ProviderFactory.create(
                    ProviderKind.DEEPSEEK,
                    config=cfg,
                )
                model = str(ds.get("model") or "deepseek-chat")
                return prov, model  # type: ignore[return-value]
        km = cfg.get("kimi")
        if isinstance(km, dict):
            key = str(km.get("api_key") or "").strip()
            has_key = bool(key)
            has_env = bool(os.environ.get("KIMI_API_KEY", "").strip()) or bool(
                os.environ.get("MOONSHOT_API_KEY", "").strip(),
            )
            if has_key or has_env:
                prov = ProviderFactory.create(ProviderKind.KIMI, config=cfg)
                model = str(km.get("model") or "moonshot-v1-8k")
                return prov, model  # type: ignore[return-value]
        return MockProvider(), "mock"  # type: ignore[return-value]


class _RegistryAssembler:
    """Собрать tool registry для AgentWork."""

    def build(
        self,
        *,
        project_root: Path,
        project_roots: tuple[Path, ...] | None = None,
    ) -> ToolRegistry:
        roots = project_roots if project_roots else (project_root.resolve(),)
        os.environ["AILIT_WORK_ROOTS"] = json.dumps(
            [str(p.resolve()) for p in roots],
        )
        os.environ["AILIT_WORK_ROOT"] = str(roots[0].resolve())
        reg = default_builtin_registry().merge(bash_tool_registry())

        try:
            cfg = AgentRunProviderConfigBuilder().build(
                project_root.resolve(),
                use_dev_repo_yaml=True,
            )
        except Exception:
            return reg
        mem = cfg.get("memory")
        if isinstance(mem, dict) and bool(mem.get("enabled", False)):
            ns = str(mem.get("namespace") or "").strip() or "default"
            os.environ["AILIT_KB_NAMESPACE"] = ns
            from agent_core.memory.kb_tools import (  # local import
                build_kb_tool_registry,
                kb_tools_config_from_env,
            )

            reg = reg.merge(build_kb_tool_registry(kb_tools_config_from_env()))
        return reg


class _RuntimeEventEmitter:
    """Эмитить topic.publish события в stdout для broker trace."""

    def __init__(
        self,
        *,
        identity: RuntimeIdentity,
        parent_message_id: str,
    ) -> None:
        self._identity = identity
        self._parent_message_id = parent_message_id
        self._lock = None

    def with_lock(self, lock: Any) -> _RuntimeEventEmitter:
        self._lock = lock
        return self

    def publish(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        msg_id = f"evt-{time.time_ns()}"
        topic = TopicEvent(
            topic="chat",
            event_name=str(event_type),
            payload=payload,
        )
        env = make_request_envelope(
            identity=self._identity,
            message_id=msg_id,
            parent_message_id=self._parent_message_id,
            from_agent=f"AgentWork:{self._identity.chat_id}",
            to_agent=None,
            msg_type="topic.publish",
            payload=topic.to_payload(),
        )
        line = json.dumps(
            env.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if self._lock is not None:
            with self._lock:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            return
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


_MEMORY_QUERY_TIMEOUT_EVENT: Final[str] = "memory.query.timeout"
_MEMORY_QUERY_CONTINUATION_EVENT: Final[str] = (
    "memory.query_context.continuation"
)
_MEMORY_QUERY_CONTINUATION_REASON: Final[str] = "continuation"


def _publish_memory_query_timeout(
    emitter: _RuntimeEventEmitter,
    *,
    query_id: str,
    user_turn_id: str,
    timeout_s: float,
    code: str,
) -> None:
    emitter.publish(
        event_type=_MEMORY_QUERY_TIMEOUT_EVENT,
        payload={
            "query_id": query_id,
            "user_turn_id": user_turn_id,
            "timeout_s": float(timeout_s),
            "code": str(code),
        },
    )


class _BrokerServiceClient:
    """Синхронный локальный клиент AgentWork -> Broker services."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = str(socket_path or "").strip()

    @property
    def available(self) -> bool:
        return bool(self._socket_path)

    def request(
        self,
        *,
        identity: RuntimeIdentity,
        parent_message_id: str,
        to_agent: str,
        payload: Mapping[str, Any],
        timeout_s: float = 15.0,
    ) -> Mapping[str, Any]:
        """Send one service.request through the broker Unix socket."""
        if not self._socket_path:
            raise RuntimeError("broker_socket_path is not configured")
        env = make_request_envelope(
            identity=identity,
            message_id=f"svc-{time.time_ns()}",
            parent_message_id=parent_message_id,
            from_agent=f"AgentWork:{identity.chat_id}",
            to_agent=to_agent,
            msg_type="service.request",
            payload=payload,
        )
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout_s)
            sock.connect(self._socket_path)
            sock.sendall(env.to_json_line().encode("utf-8") + b"\n")
            data = sock.recv(2_000_000)
        finally:
            try:
                sock.close()
            except OSError:
                pass
        raw = data.decode("utf-8", errors="replace").strip()
        if not raw:
            raise RuntimeError("empty broker response")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("invalid broker response")
        return parsed


class _WorkChatSession:
    """Сессия AgentWork (хранит историю сообщений между prompt-ами)."""

    def __init__(self) -> None:
        self._messages: list[ChatMessage] = [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=merge_with_base_system(
                    "You are a helpful concise assistant.",
                ),
            ),
        ]
        self._user_turns: int = 0
        self._restored_d_node_ids: set[str] = set()
        self._user_turn_id: str = ""
        self._memory_queries_in_turn: int = 0

    @staticmethod
    def _memory_slice_message(
        memory_slice: Mapping[str, Any],
    ) -> ChatMessage | None:
        injected = str(memory_slice.get("injected_text") or "").strip()
        if not injected:
            return None
        return ChatMessage(
            role=MessageRole.SYSTEM,
            name="agent_memory_slice",
            content=(
                "AgentMemory context slice. Treat this as selected project "
                "memory for the current user turn only.\n\n"
                f"{injected}"
            ),
        )

    @staticmethod
    def _strip_transient_memory(
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        return [m for m in messages if m.name != "agent_memory_slice"]

    def _request_memory_slice(
        self,
        *,
        text: str,
        workspace: _Workspace,
        emitter: _RuntimeEventEmitter,
        identity: RuntimeIdentity,
        parent_message_id: str,
        worker: "AgentWorkWorker",
    ) -> ChatMessage | None:
        """Запросить slice у AgentMemory.

        SoT решений — ``payload.agent_memory_result`` (W14).
        """
        client = _BrokerServiceClient(  # noqa: SLF001
            worker._cfg.broker_socket_path,
        )
        if not client.available:
            emitter.publish(
                event_type="memory.actor_unavailable",
                payload={
                    "reason": "broker_socket_path_missing",
                    "fallback": "none",
                },
            )
            return None
        try:
            merged_mem = load_merged_ailit_config_for_memory()
        except Exception:  # noqa: BLE001
            merged_mem = {}
        mem_cap = max_memory_queries_per_user_turn(merged_mem)
        ns = str(identity.namespace or "").strip() or "default"
        rpc_to = float(agent_memory_rpc_timeout_s(merged_mem))
        root = str(workspace.project_root.resolve())
        known_paths: list[str] = []
        known_node_ids: list[str] = []
        subgoal = (text or "").strip() or "task"

        while True:
            paths_before = frozenset(known_paths)
            nids_before = frozenset(known_node_ids)
            if self._memory_queries_in_turn >= mem_cap:
                emitter.publish(
                    event_type="memory.query.budget_exceeded",
                    payload={
                        "code": "too_many_memory_queries",
                        "cap": int(mem_cap),
                        "user_turn_id": self._user_turn_id,
                    },
                )
                return None
            next_idx = int(self._memory_queries_in_turn) + 1
            qid = f"mq-{self._user_turn_id}-{next_idx}"
            payload: dict[str, Any] = {
                "service": "memory.query_context",
                "schema_version": AGENT_WORK_MEMORY_QUERY_V1,
                "user_turn_id": self._user_turn_id,
                "query_id": qid,
                "subgoal": subgoal,
                "expected_result_kind": "mixed",
                "query_kind": "task",
                "level": "B",
                "project_root": root,
                "namespace": ns,
                "known_paths": list(known_paths),
                "known_node_ids": list(known_node_ids),
                "stop_condition": {
                    "max_runtime_steps": 12,
                    "max_llm_commands": 20,
                    "must_finish_explicitly": True,
                },
            }
            try:
                resp = client.request(
                    identity=identity,
                    parent_message_id=parent_message_id,
                    to_agent="AgentMemory:global",
                    payload=payload,
                    timeout_s=rpc_to,
                )
            except TimeoutError:
                _publish_memory_query_timeout(
                    emitter,
                    query_id=qid,
                    user_turn_id=self._user_turn_id,
                    timeout_s=rpc_to,
                    code="runtime_timeout",
                )
                return None
            except Exception as exc:  # noqa: BLE001
                emitter.publish(
                    event_type="memory.actor_unavailable",
                    payload={
                        "reason": "broker_request_failed",
                        "error": str(exc),
                        "fallback": "none",
                    },
                )
                return None
            ok = bool(resp.get("ok", False))
            if not ok:
                err_raw = resp.get("error")
                err_code = ""
                if isinstance(err_raw, Mapping):
                    err_code = str(err_raw.get("code") or "")
                if err_code == "runtime_timeout":
                    _publish_memory_query_timeout(
                        emitter,
                        query_id=qid,
                        user_turn_id=self._user_turn_id,
                        timeout_s=rpc_to,
                        code="runtime_timeout",
                    )
                    return None
                emitter.publish(
                    event_type="memory.actor_unavailable",
                    payload={
                        "reason": "memory_query_failed",
                        "error": resp.get("error"),
                        "fallback": "none",
                    },
                )
                return None
            pl_any = resp.get("payload")
            pl = pl_any if isinstance(pl_any, dict) else {}
            sot = _AgentMemoryPathSoTParser.parse_payload(pl)
            if sot is None:
                emitter.publish(
                    event_type="memory.actor_unavailable",
                    payload={
                        "reason": "agent_memory_result_missing",
                        "fallback": "none",
                    },
                )
                return None
            outcome = _MemoryPathTurnClassifier.outcome_kind(
                sot,
                paths_before=paths_before,
                nids_before=nids_before,
            )
            self._memory_queries_in_turn += 1

            if outcome == "continue":
                next_qid = (
                    f"mq-{self._user_turn_id}-"
                    f"{int(self._memory_queries_in_turn) + 1}"
                )
                emitter.publish(
                    event_type=_MEMORY_QUERY_CONTINUATION_EVENT,
                    payload={
                        "user_turn_id": self._user_turn_id,
                        "previous_query_id": qid,
                        "next_query_id": next_qid,
                        "reason": _MEMORY_QUERY_CONTINUATION_REASON,
                    },
                )
                p2, n2 = _collect_refs_from_agent_memory_result(
                    sot.agent_memory_result,
                )
                known_paths = sorted(set(known_paths) | set(p2))
                known_node_ids = sorted(set(known_node_ids) | set(n2))
                rns = str(
                    sot.agent_memory_result.get("recommended_next_step")
                    or "",
                ).strip()
                if rns:
                    subgoal = rns
                continue

            if outcome == "finish_silent":
                return None

            memory_slice = sot.memory_slice
            if not isinstance(memory_slice, dict):
                emitter.publish(
                    event_type="memory.actor_unavailable",
                    payload={
                        "reason": "memory_query_failed",
                        "error": resp.get("error"),
                        "fallback": "none",
                    },
                )
                return None
            msg = self._memory_slice_message(memory_slice)
            if msg is None:
                emitter.publish(
                    event_type="memory.actor_slice_skipped",
                    payload={
                        "reason": str(memory_slice.get("reason") or ""),
                        "staleness": str(
                            memory_slice.get("staleness") or "",
                        ),
                    },
                )
                return None
            emitter.publish(
                event_type="memory.actor_slice_used",
                payload={
                    "level": str(memory_slice.get("level") or ""),
                    "node_ids": list(memory_slice.get("node_ids") or []),
                    "edge_ids": list(memory_slice.get("edge_ids") or []),
                    "estimated_tokens": int(
                        memory_slice.get("estimated_tokens") or 0,
                    ),
                    "staleness": str(memory_slice.get("staleness") or ""),
                    "reason": str(memory_slice.get("reason") or ""),
                },
            )
            emitter.publish(
                event_type="context.memory_injected",
                payload=self._memory_injected_payload(
                    identity=identity,
                    parent_message_id=parent_message_id,
                    memory_slice=memory_slice,
                    response_payload=pl,
                ),
            )
            return msg

    @staticmethod
    def _memory_injected_payload(
        *,
        identity: RuntimeIdentity,
        parent_message_id: str,
        memory_slice: Mapping[str, Any],
        response_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        refs_raw = response_payload.get("project_refs")
        project_refs: list[ContextProjectRef] = []
        if isinstance(refs_raw, list):
            for raw in refs_raw:
                if not isinstance(raw, Mapping):
                    continue
                project_refs.append(
                    ContextProjectRef(
                        project_id=str(raw.get("project_id") or ""),
                        namespace=str(
                            raw.get("namespace") or identity.namespace,
                        ),
                        node_ids=tuple(
                            str(x)
                            for x in raw.get("node_ids", [])
                            if str(x).strip()
                        )
                        if isinstance(raw.get("node_ids"), list)
                        else (),
                        edge_ids=tuple(
                            str(x)
                            for x in raw.get("edge_ids", [])
                            if str(x).strip()
                        )
                        if isinstance(raw.get("edge_ids"), list)
                        else (),
                    ),
                )
        if not project_refs:
            project_refs = [
                ContextProjectRef(
                    project_id="",
                    namespace=identity.namespace,
                    node_ids=tuple(
                        str(x)
                        for x in memory_slice.get("node_ids", [])
                        if str(x).strip()
                    )
                    if isinstance(memory_slice.get("node_ids"), list)
                    else (),
                    edge_ids=tuple(
                        str(x)
                        for x in memory_slice.get("edge_ids", [])
                        if str(x).strip()
                    )
                    if isinstance(memory_slice.get("edge_ids"), list)
                    else (),
                ),
            ]
        amr_raw = response_payload.get("agent_memory_result")
        amr_ds = ""
        amr_rns = ""
        if isinstance(amr_raw, Mapping):
            amr_ds = str(amr_raw.get("decision_summary") or "").strip()
            amr_rns = str(amr_raw.get("recommended_next_step") or "").strip()
        top_ds = str(response_payload.get("decision_summary") or "").strip()
        top_rns = str(
            response_payload.get("recommended_next_step") or "",
        ).strip()
        return memory_injected_v2_payload(
            chat_id=identity.chat_id,
            turn_id=parent_message_id,
            source_agent="AgentMemory:global",
            project_refs=project_refs,
            estimated_tokens=int(memory_slice.get("estimated_tokens") or 0),
            prompt_section="memory",
            decision_summary=str(
                top_ds or amr_ds or memory_slice.get("reason") or "",
            ),
            recommended_next_step=str(top_rns or amr_rns or ""),
        )

    def _restore_d_context(
        self,
        *,
        workspace: _Workspace,
        emitter: _RuntimeEventEmitter,
    ) -> ChatMessage | None:
        """Restore latest D-level compact summary for reopened chats."""
        try:
            rc = detect_repo_context(workspace.project_root.resolve())
            namespace = namespace_for_repo(
                repo_uri=rc.repo_uri,
                repo_path=rc.repo_path,
                branch=rc.branch,
            )
            restored = DLevelCompactService.default().restore_latest(
                namespace=namespace,
            )
        except Exception as exc:  # noqa: BLE001
            emitter.publish(
                event_type="context.restore_failed",
                payload={
                    "schema": "context.restore_failed.v1",
                    "reason": f"{type(exc).__name__}:{exc}",
                },
            )
            return None
        if restored is None:
            return None
        if restored.d_node_id in self._restored_d_node_ids:
            return None
        self._restored_d_node_ids.add(restored.d_node_id)
        emitter.publish(
            event_type="context.restored",
            payload=restored.to_event_payload(),
        )
        return restored.message

    def run_user_prompt(
        self,
        *,
        text: str,
        workspace: _Workspace,
        emitter: _RuntimeEventEmitter,
        identity: RuntimeIdentity,
        worker: "AgentWorkWorker",
    ) -> Mapping[str, Any]:
        self._messages.append(ChatMessage(role=MessageRole.USER, content=text))
        self._user_turns += 1
        self._user_turn_id = f"ut-{uuid.uuid4().hex[:20]}"
        self._memory_queries_in_turn = 0
        if self._user_turns == 1:
            try:
                cfg = AgentRunProviderConfigBuilder().build(
                    workspace.project_root.resolve(),
                    use_dev_repo_yaml=True,
                )
            except Exception:
                cfg = None
            inject_tool_hints_before_first_user(
                self._messages,
                include_kb_first=(
                    memory_kb_first_enabled(cfg)
                    if isinstance(cfg, dict)
                    else False
                ),
            )

        pr_roots = (
            workspace.project_roots
            if workspace.project_roots
            else (workspace.project_root.resolve(),)
        )
        assistant_mid = f"asst-{uuid.uuid4()}"
        restored_d_msg = self._restore_d_context(
            workspace=workspace,
            emitter=emitter,
        )
        memory_slice_msg = self._request_memory_slice(
            text=text,
            workspace=workspace,
            emitter=emitter,
            identity=identity,
            parent_message_id=assistant_mid,
            worker=worker,
        )
        provider_obj, model_eff = _ProviderAssembler().build(
            project_root=workspace.project_root,
        )
        reg = _RegistryAssembler().build(
            project_root=workspace.project_root,
            project_roots=pr_roots,
        )
        perm_base = PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
            network_default=PermissionDecision.ALLOW,
        )

        def _file_changed_notifier(info: dict[str, Any]) -> None:
            """
            G13.3: `memory.change_feedback` с fingerprint и tool ids
            (заменяет bare `memory.file_changed` с AgentWork).
            """
            root = workspace.project_root.resolve()
            paths = info.get("written_paths") or ()
            items_any: list[Any] = list(info.get("written_items") or [])
            if not items_any and paths:
                items_any = [
                    {
                        "path": str(p),
                        "call_id": f"w-{i}",
                        "tool": "write_file",
                    }
                    for i, p in enumerate(paths)
                ]
            if not items_any:
                return
            sock = str(worker._cfg.broker_socket_path or "").strip()
            if not sock:
                return
            ns0 = str(info.get("namespace") or "").strip()
            if not ns0:
                ns0 = identity.namespace
            ns = ns0
            if not ns:
                try:
                    rc = detect_repo_context(root)
                    ns = namespace_for_repo(
                        repo_uri=rc.repo_uri,
                        repo_path=rc.repo_path,
                        branch=rc.branch,
                    )
                except OSError:
                    ns = "default"
            client = _BrokerServiceClient(
                worker._cfg.broker_socket_path,
            )
            changed_files: list[dict[str, Any]] = []
            for it in items_any:
                if not isinstance(it, dict):
                    continue
                rel_path = str(it.get("path", "") or "").strip()
                if not rel_path:
                    continue
                ab = (root / rel_path).resolve()
                try:
                    if ab.is_file():
                        h = hashlib.sha256()
                        h.update(ab.read_bytes())
                        after_fp = f"sha256:{h.hexdigest()}"
                    else:
                        after_fp = "sha256:missing"
                except OSError:
                    after_fp = "sha256:unreadable"
                tool_name = str(it.get("tool", "") or "write_file")
                call_id = str(it.get("call_id", "") or "tc")
                changed_files.append(
                    {
                        "path": rel_path,
                        "operation": "modify",
                        "old_path": None,
                        "tool_call_id": call_id,
                        "message_id": assistant_mid,
                        "content_before_fingerprint": None,
                        "content_after_fingerprint": after_fp,
                        "line_ranges_touched": [],
                        "symbol_hints": [],
                        "change_summary": f"{tool_name} commit",
                        "requires_llm_review": False,
                    },
                )
            if not changed_files:
                return
            key_obj = {
                "turn": assistant_mid,
                "items": sorted(
                    [
                        {"p": str(x["path"]), "c": str(x["tool_call_id"])}
                        for x in changed_files
                    ],
                    key=lambda z: str(z["p"]),
                ),
            }
            key_json = json.dumps(
                key_obj,
                sort_keys=True,
                ensure_ascii=False,
            )
            dig = hashlib.sha256(
                key_json.encode("utf-8"),
            ).hexdigest()[:24]
            batch_id = f"cb-{dig}"
            user_snip = (text or "")[:4000]
            payload = {
                "service": "memory.change_feedback",
                "request_id": f"cf-{time.time_ns()}",
                "schema": "memory.change_feedback.v1",
                "chat_id": identity.chat_id,
                "turn_id": assistant_mid,
                "namespace": ns,
                "project_root": str(root),
                "source": "AgentWork",
                "change_batch_id": batch_id,
                "user_intent_summary": user_snip,
                "goal": user_snip,
                "changed_files": changed_files,
            }
            try:
                client.request(
                    identity=identity,
                    parent_message_id=assistant_mid,
                    to_agent="AgentMemory:global",
                    payload=payload,
                )
            except Exception:  # noqa: BLE001
                return

        runner = SessionRunner(
            provider_obj,
            reg,
            permission_engine=perm_base,
            file_changed_notifier=_file_changed_notifier,
        )
        pm_en = _work_agent_perm_mode_enabled()
        perm_tool_mode = "explore"
        perm_bypass = bool(
            os.environ.get("AILIT_MULTI_AGENT", "").strip().lower()
            in ("1", "true", "yes", "on"),
        )
        forced = os.environ.get("AILIT_PERM_TOOL_MODE", "").strip() or None
        if pm_en and not perm_bypass:
            try:
                rc = detect_repo_context(workspace.project_root.resolve())
                repo_pl = rc.to_event_payload()
            except OSError:
                repo_pl = None
            try:
                _cfg0 = AgentRunProviderConfigBuilder().build(
                    workspace.project_root.resolve(),
                    use_dev_repo_yaml=True,
                )
            except Exception:
                _cfg0 = {}
            mns = (
                memory_namespace_from_cfg(_cfg0)
                if isinstance(_cfg0, dict)
                else "default"
            )
            kb_ns = build_mode_kb_namespace(
                memory_namespace=mns,
                project_root=workspace.project_root,
            )
            coord = PermModeTurnCoordinator(
                kb_namespace=kb_ns,
                history_max=8,
                repo_payload=repo_pl,
            )
            res = coord.resolve_turn(
                provider=provider_obj,
                model=model_eff,
                temperature=0.3,
                user_intent=text,
                classifier_bypass=perm_bypass,
                forced_mode=forced,
                diag_sink=None,
            )
            user_resolved_perm = False
            if res.not_sure:
                gate_id = uuid.uuid4().hex
                with worker._state_lock:  # type: ignore[attr-defined]
                    worker._perm_user_intent = text
                    worker._perm_coord = coord  # type: ignore[attr-defined]
                    worker._perm_chosen_mode = None  # type: ignore[attr-defined]  # noqa: E501
                    worker._perm_event = threading.Event()  # type: ignore[attr-defined]  # noqa: E501
                    worker._perm_gate_id = gate_id
                emitter.publish(
                    event_type="session.perm_mode.need_user_choice",
                    payload={
                        "chat_id": identity.chat_id,
                        "gate_id": gate_id,
                    },
                )
                ev = worker._perm_event  # type: ignore[attr-defined]
                ev.wait(timeout=600.0)  # type: ignore[union-attr]
                with worker._state_lock:  # type: ignore[attr-defined]
                    chosen = worker._perm_chosen_mode  # type: ignore[attr-defined]  # noqa: E501
                    worker._clear_perm_wait()  # type: ignore[attr-defined]
                if not chosen:
                    return {"ok": False, "error": "perm_mode_choice_timeout"}
                perm_tool_mode = str(chosen)
                user_resolved_perm = True
            else:
                perm_tool_mode = res.final_mode
            clsf = res.classification
            emitter.publish(
                event_type="session.perm_mode.settled",
                payload={
                    "chat_id": identity.chat_id,
                    "perm_mode": perm_tool_mode,
                    "not_sure": False,
                    "confidence": (
                        clsf.confidence
                        if clsf and not user_resolved_perm
                        else None
                    ),
                    "reason": (
                        clsf.reason
                        if clsf and not user_resolved_perm
                        else None
                    ),
                },
            )
        else:
            perm_tool_mode = normalize_perm_tool_mode(
                os.environ.get("AILIT_PERM_TOOL_MODE", "explore").strip()
                or "explore",
            )
            if pm_en and perm_bypass:
                perm_tool_mode = normalize_perm_tool_mode(
                    os.environ.get("AILIT_PERM_TOOL_MODE", "edit").strip()
                    or "edit",
                )

        def sink(ev: SessionEvent) -> None:
            p: MutableMapping[str, Any] = dict(ev.payload)
            if ev.type.startswith("context."):
                p.setdefault("chat_id", identity.chat_id)
            if ev.type in ("assistant.delta", "assistant.thinking"):
                p["message_id"] = assistant_mid
            if ev.type in ("tool.call_started", "tool.call_finished"):
                p.setdefault("message_id", assistant_mid)
            if ev.type.startswith("bash."):
                p.setdefault("message_id", assistant_mid)
            emitter.publish(event_type=ev.type, payload=p)

        settings = SessionSettings(
            model=model_eff,
            max_turns=10_000,
            temperature=0.3,
            use_stream=True,
            perm_mode_enabled=pm_en,
            perm_tool_mode=perm_tool_mode,
            perm_classifier_bypass=perm_bypass,
            perm_history_max=8,
            pag_runtime_enabled=False,
            compact_to_memory_enabled=True,
        )

        def wait_for_approval(call_id: str) -> None:
            """Wait until Desktop resolves a tool approval request."""
            with worker._state_lock:  # type: ignore[attr-defined]
                worker._appr_event = threading.Event()  # type: ignore[attr-defined]  # noqa: E501
                worker._appr_call_id = call_id  # type: ignore[attr-defined]
            ev_a = worker._appr_event  # type: ignore[attr-defined]
            ev_a.wait(timeout=3600.0)  # type: ignore[union-attr]
            with worker._state_lock:  # type: ignore[attr-defined]
                worker._appr_event = None  # type: ignore[attr-defined]
                worker._appr_call_id = ""  # type: ignore[attr-defined]

        try:
            profile_cfg = AgentRunProviderConfigBuilder().build(
                workspace.project_root.resolve(),
                use_dev_repo_yaml=True,
            )
        except Exception:
            profile_cfg = {}
        profile = AgentWorkProfile.from_config(profile_cfg)
        base_messages = list(self._messages)
        if restored_d_msg is not None:
            base_messages.append(restored_d_msg)
        if memory_slice_msg is not None:
            base_messages.append(memory_slice_msg)
        orchestrator = WorkTaskOrchestrator(
            runner=runner,
            approvals=worker._approval,  # type: ignore[attr-defined]
            settings=settings,
            base_messages=tuple(base_messages),
            event_sink=sink,  # type: ignore[arg-type]
            publisher=emitter,
            wait_for_approval=wait_for_approval,
        )
        result = orchestrator.run(
            WorkTaskRequest(
                user_text=text,
                workspace=workspace.project_root.resolve(),
                chat_id=identity.chat_id,
                assistant_message_id=assistant_mid,
                profile=profile,
            ),
        )
        self._messages = self._strip_transient_memory(list(result.messages))
        emitter.publish(
            event_type="assistant.final",
            payload={
                "message_id": assistant_mid,
                "text": result.final_text,
            },
        )
        if result.ok:
            return {"ok": True, "assistant_message_id": assistant_mid}
        return {"ok": False, "error": result.error or "agent_work_failed"}


class AgentWorkWorker:
    """Worker: выполняет user prompt и стримит UI-события."""

    def __init__(self, cfg: WorkAgentConfig) -> None:
        self._cfg = cfg
        self._session = _WorkChatSession()
        self._threading = threading
        self._emit_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._approval = ApprovalSession()
        self._perm_user_intent: str = ""
        self._perm_coord: PermModeTurnCoordinator | None = None
        self._perm_chosen_mode: str | None = None
        self._perm_event: threading.Event | None = None
        self._perm_gate_id: str = ""
        self._appr_event: threading.Event | None = None
        self._appr_call_id: str = ""
        self._user_prompt_thread: Optional[threading.Thread] = None

    def _clear_perm_wait(self) -> None:
        self._perm_coord = None
        self._perm_event = None
        self._perm_gate_id = ""
        self._perm_chosen_mode = None

    def complete_perm_choice(
        self,
        gate_id: str,
        mode: str,
        *,
        remember_project: bool = False,
    ) -> bool:
        """Снятие perm gate после выбора в UI (Desktop)."""
        with self._state_lock:
            if not gate_id or gate_id != self._perm_gate_id:
                return False
            coord = self._perm_coord
            if coord is None or self._perm_event is None:
                return False
        fm = normalize_perm_tool_mode(mode)
        coord.record_user_choice(
            user_intent=self._perm_user_intent,
            mode=fm,
            remember_project=remember_project,
            diag_sink=None,
        )
        with self._state_lock:
            self._perm_chosen_mode = fm
            if self._perm_event is not None:
                self._perm_event.set()
        return True

    def complete_tool_approval(self, call_id: str, approved: bool) -> bool:
        """ASK на инструмент: approve/reject + разблокировка SessionRunner."""
        with self._state_lock:
            if not call_id or call_id != self._appr_call_id:
                return False
            ev = self._appr_event
        if approved:
            self._approval.approve(call_id)
        else:
            self._approval.reject(call_id)
        if ev is not None:
            ev.set()
        return True

    def handle(self, req: RuntimeRequestEnvelope) -> Mapping[str, Any]:
        if req.type == "service.request":
            action = str(req.payload.get("action", "") or "").strip()
            if action == "work.perm_mode_choice":
                ok = self.complete_perm_choice(
                    str(req.payload.get("gate_id", "") or ""),
                    str(req.payload.get("mode", "") or "explore"),
                    remember_project=bool(
                        req.payload.get("remember_project", False),
                    ),
                )
                return make_response_envelope(
                    request=req,
                    ok=ok,
                    payload={"accepted": ok},
                    error=None
                    if ok
                    else {"code": "bad_gate", "message": "invalid gate_id"},
                ).to_dict()
            if action == "work.approval_resolve":
                call_id = str(req.payload.get("call_id", "") or "")
                approved = bool(req.payload.get("approved", False))
                ok2 = self.complete_tool_approval(call_id, approved)
                return make_response_envelope(
                    request=req,
                    ok=ok2,
                    payload={"accepted": ok2},
                    error=None
                    if ok2
                    else {
                        "code": "bad_call",
                        "message": call_id,
                    },
                ).to_dict()
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "unsupported",
                    "message": action,
                },
            ).to_dict()
        if req.type == "action.start":
            action = str(req.payload.get("action", "") or "")
            if action != "work.handle_user_prompt":
                return make_response_envelope(
                    request=req,
                    ok=False,
                    payload={},
                    error={
                        "code": "unsupported_action",
                        "message": action or "(empty)",
                    },
                ).to_dict()
            prompt = str(req.payload.get("prompt", "") or "").strip()
            ws = req.payload.get("workspace")
            project_roots: list[Path] = []
            if isinstance(ws, dict):
                roots = ws.get("project_roots")
                if roots is None:
                    roots = ws.get("projectRoots")
                if isinstance(roots, list):
                    for r in roots:
                        if isinstance(r, str) and r.strip():
                            resolved = Path(r).expanduser().resolve()
                            project_roots.append(resolved)
            if not project_roots:
                project_roots = [Path.cwd().resolve()]
            project_root = project_roots[0]
            proot_t = tuple(project_roots)
            with self._state_lock:
                busy = (
                    self._user_prompt_thread is not None
                    and self._user_prompt_thread.is_alive()
                )
                if busy:
                    return make_response_envelope(
                        request=req,
                        ok=False,
                        payload={},
                        error={
                            "code": "agent_busy",
                            "message": (
                                "Another work.handle_user_prompt is still "
                                "running "
                                "for this chat."
                            ),
                        },
                    ).to_dict()
            identity = RuntimeIdentity(
                runtime_id=req.runtime_id,
                chat_id=req.chat_id,
                broker_id=req.broker_id,
                trace_id=req.trace_id,
                goal_id=req.goal_id,
                namespace=req.namespace,
            )
            emitter = _RuntimeEventEmitter(
                identity=identity,
                parent_message_id=req.message_id,
            ).with_lock(self._emit_lock)
            action_id = str(uuid.uuid4())
            emitter.publish(
                event_type="action.started",
                payload={"action": action, "action_id": action_id},
            )

            def _run() -> None:
                try:
                    result = self._session.run_user_prompt(
                        text=prompt,
                        workspace=_Workspace(
                            namespace=req.namespace,
                            project_root=project_root,
                            project_roots=proot_t,
                        ),
                        emitter=emitter,
                        identity=identity,
                        worker=self,
                    )
                except Exception as exc:  # noqa: BLE001
                    emitter.publish(
                        event_type="assistant.final",
                        payload={
                            "message_id": f"asst-{uuid.uuid4()}",
                            "text": (
                                "AgentWork error: "
                                f"{type(exc).__name__}: {exc}"
                            ),
                        },
                    )
                    emitter.publish(
                        event_type="action.failed",
                        payload={
                            "action": action,
                            "action_id": action_id,
                            "error": str(exc),
                        },
                    )
                    return
                emitter.publish(
                    event_type="action.completed",
                    payload={
                        "action": action,
                        "action_id": action_id,
                        "result": dict(result),
                    },
                )

            t = self._threading.Thread(target=_run, daemon=True)
            with self._state_lock:
                self._user_prompt_thread = t
            t.start()
            return make_response_envelope(
                request=req,
                ok=True,
                payload={
                    "action": action,
                    "action_id": action_id,
                    "accepted": True,
                },
                error=None,
            ).to_dict()
        return make_response_envelope(
            request=req,
            ok=False,
            payload={},
            error={"code": "unsupported", "message": req.type},
        ).to_dict()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent-work")
    p.add_argument("--chat-id", type=str, required=True)
    p.add_argument("--broker-id", type=str, required=True)
    p.add_argument("--broker-socket-path", type=str, default="")
    p.add_argument("--namespace", type=str, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    cfg = WorkAgentConfig(
        chat_id=str(args.chat_id),
        broker_id=str(args.broker_id),
        namespace=str(args.namespace),
        broker_socket_path=str(args.broker_socket_path),
    )
    worker = AgentWorkWorker(cfg)
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            req = RuntimeRequestEnvelope.from_json_line(raw)
        except Exception:
            continue
        if req.contract_version != CONTRACT_VERSION:
            continue
        out = worker.handle(req)
        sys.stdout.write(
            json.dumps(
                dict(out),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
