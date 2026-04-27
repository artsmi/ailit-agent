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
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.factory import ProviderFactory, ProviderKind
from agent_core.providers.mock_provider import MockProvider
from agent_core.providers.protocol import ChatProvider
from agent_core.session.event_contract import SessionEvent
from agent_core.session.loop import SessionOutcome, SessionRunner, SessionSettings
from agent_core.session.perm_tool_mode import normalize_perm_tool_mode
from agent_core.session.perm_turn import (
    PermModeTurnCoordinator,
    build_mode_kb_namespace,
    memory_namespace_from_cfg,
)
from agent_core.session.repo_context import detect_repo_context
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
    project_roots: tuple[Path, ...] = field(default_factory=tuple)


def _work_agent_perm_mode_enabled() -> bool:
    """Включение perm-5 + классификатор (Desktop: UI; выкл. через env)."""
    raw = os.environ.get("AILIT_WORK_AGENT_PERM", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _session_end_user_message(
    *,
    state: SessionState,
    reason: str | None,
) -> str:
    """Человекочитаемый текст, если сессия завершилась не FINISHED."""
    r = (reason or "").strip()
    if state is SessionState.WAITING_APPROVAL and r == "approval_pending":
        return (
            "Выполнение остановилось: нужно подтверждение (ASK) вызова "
            "инструмента, а в фоновом воркере нет UI. "
            "Perm-5 для worker по умолчанию выключен; иначе пользуйтесь "
            "`ailit chat`."
        )
    if state is SessionState.ERROR and r:
        return f"Ошибка сессии: {r}"
    if r:
        return f"Сессия завершена ({state.value}): {r}"
    return f"Сессия завершена: {state.value}"


def _waiting_approval_call_id(events: tuple[dict[str, Any], ...]) -> str | None:
    """``call_id`` из последнего ``session.waiting_approval``."""
    for ev in reversed(events):
        if ev.get("event_type") == "session.waiting_approval":
            cid = ev.get("call_id")
            if isinstance(cid, str) and cid:
                return cid
    return None


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
        identity: RuntimeIdentity,
        worker: "AgentWorkWorker",
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

        pr_roots = (
            workspace.project_roots
            if workspace.project_roots
            else (workspace.project_root.resolve(),)
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
        runner = SessionRunner(provider_obj, reg, permission_engine=perm_base)
        assistant_mid = f"asst-{uuid.uuid4()}"
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
                    worker._perm_user_intent = text  # type: ignore[attr-defined]
                    worker._perm_coord = coord  # type: ignore[attr-defined]
                    worker._perm_chosen_mode = None  # type: ignore[attr-defined]
                    worker._perm_event = threading.Event()  # type: ignore[attr-defined]
                    worker._perm_gate_id = gate_id  # type: ignore[attr-defined]
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
                    chosen = worker._perm_chosen_mode  # type: ignore[attr-defined]
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
        )
        out: SessionOutcome | None = None
        while True:
            out = runner.run(
                list(self._messages),
                worker._approval,  # type: ignore[attr-defined]
                settings,
                diag_sink=None,
                event_sink=sink,  # type: ignore[arg-type]
            )
            self._messages = list(out.messages)
            if out.state is SessionState.WAITING_APPROVAL:
                call_id = _waiting_approval_call_id(out.events)
                if not call_id:
                    break
                with worker._state_lock:  # type: ignore[attr-defined]
                    worker._appr_event = threading.Event()  # type: ignore[attr-defined]
                    worker._appr_call_id = call_id  # type: ignore[attr-defined]
                ev_a = worker._appr_event  # type: ignore[attr-defined]
                ev_a.wait(timeout=3600.0)  # type: ignore[union-attr]
                with worker._state_lock:  # type: ignore[attr-defined]
                    worker._appr_event = None  # type: ignore[attr-defined]
                    worker._appr_call_id = ""  # type: ignore[attr-defined]
                continue
            break
        assert out is not None
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
                "text": _session_end_user_message(
                    state=out.state,
                    reason=out.reason,
                ),
            },
        )
        return {"ok": False, "error": out.reason or out.state.value}


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
                            project_roots.append(Path(r).expanduser().resolve())
            if not project_roots:
                project_roots = [Path.cwd().resolve()]
            project_root = project_roots[0]
            proot_t = tuple(project_roots)
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
