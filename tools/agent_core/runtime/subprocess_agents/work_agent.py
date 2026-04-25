"""AgentWork subprocess worker.

Цель: `work.handle_user_prompt` исполняется через `SessionRunner` и эмитит
UI-события в runtime trace (через `topic.publish`), чтобы desktop UI мог
показывать streaming-ответы, tool-логи и bash output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.factory import ProviderFactory, ProviderKind
from agent_core.providers.mock_provider import MockProvider
from agent_core.providers.protocol import ChatProvider
from agent_core.session.event_contract import SessionEvent
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.state import SessionState
from agent_core.runtime.models import (
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

from ailit.agent_provider_config import AgentRunProviderConfigBuilder
from ailit.tool_system_hints import (
    inject_tool_hints_before_first_user,
    memory_kb_first_enabled,
)
from ailit.perm_mode_chat import perm_mode_enabled_from_env


@dataclass(frozen=True, slots=True)
class WorkAgentConfig:
    """Конфиг AgentWork."""

    chat_id: str
    broker_id: str
    namespace: str


@dataclass(frozen=True, slots=True)
class _Workspace:
    namespace: str
    project_root: Path


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

    def build(self, *, project_root: Path) -> ToolRegistry:
        root = project_root.resolve()
        os.environ["AILIT_WORK_ROOT"] = str(root)
        reg = default_builtin_registry().merge(bash_tool_registry())

        try:
            cfg = AgentRunProviderConfigBuilder().build(
                root,
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

    def run_user_prompt(
        self,
        *,
        text: str,
        workspace: _Workspace,
        emitter: _RuntimeEventEmitter,
    ) -> Mapping[str, Any]:
        self._messages.append(ChatMessage(role=MessageRole.USER, content=text))
        self._user_turns += 1
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

        provider_obj, model_eff = _ProviderAssembler().build(
            project_root=workspace.project_root,
        )
        reg = _RegistryAssembler().build(project_root=workspace.project_root)
        perm = PermissionEngine(
            write_default=PermissionDecision.ALLOW,
            shell_default=PermissionDecision.ALLOW,
        )
        runner = SessionRunner(provider_obj, reg, permission_engine=perm)
        assistant_mid = f"asst-{uuid.uuid4()}"

        def sink(ev: SessionEvent) -> None:
            p: MutableMapping[str, Any] = dict(ev.payload)
            if ev.type == "assistant.delta":
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
            perm_mode_enabled=perm_mode_enabled_from_env(),
            perm_tool_mode="explore",
            perm_classifier_bypass=True,
            perm_history_max=8,
        )
        out = runner.run(
            list(self._messages),
            ApprovalSession(),
            settings,
            diag_sink=None,
            event_sink=sink,  # type: ignore[arg-type]
        )
        self._messages = list(out.messages)
        if out.state is SessionState.FINISHED:
            last = self._messages[-1] if self._messages else None
            if last and last.role is MessageRole.ASSISTANT:
                emitter.publish(
                    event_type="assistant.final",
                    payload={
                        "message_id": assistant_mid,
                        "text": last.content or "",
                    },
                )
                return {"ok": True, "assistant_message_id": assistant_mid}
            emitter.publish(
                event_type="assistant.final",
                payload={
                    "message_id": assistant_mid,
                    "text": "(нет ответа ассистента)",
                },
            )
            return {"ok": False, "error": "no_assistant_message"}
        emitter.publish(
            event_type="assistant.final",
            payload={
                "message_id": assistant_mid,
                "text": (
                    f"runtime state={out.state.value} "
                    f"reason={out.reason!r}"
                ),
            },
        )
        return {"ok": False, "error": out.reason or out.state.value}


class AgentWorkWorker:
    """Worker: выполняет user prompt и стримит UI-события."""

    def __init__(self, cfg: WorkAgentConfig) -> None:
        self._cfg = cfg
        self._session = _WorkChatSession()
        import threading

        self._threading = threading
        self._emit_lock = threading.Lock()

    def handle(self, req: RuntimeRequestEnvelope) -> Mapping[str, Any]:
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
            project_root = None
            if isinstance(ws, dict):
                roots = ws.get("projectRoots")
                is_list = isinstance(roots, list)
                has_first = is_list and bool(roots)
                is_str = has_first and isinstance(roots[0], str)
                if is_str:
                    project_root = Path(roots[0]).expanduser()
            if not project_root:
                project_root = Path.cwd().resolve()
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
                        ),
                        emitter=emitter,
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
        if req.type == "service.request":
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "unsupported",
                    "message": "services not implemented",
                },
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
    p.add_argument("--namespace", type=str, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    cfg = WorkAgentConfig(
        chat_id=str(args.chat_id),
        broker_id=str(args.broker_id),
        namespace=str(args.namespace),
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
