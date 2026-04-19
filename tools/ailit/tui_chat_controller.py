"""Один прогон ``SessionRunner`` для TUI (этап P.3)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_core.config_loader import deepseek_api_key_from_env_or_config
from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.deepseek import DeepSeekAdapter
from agent_core.providers.mock_provider import MockProvider
from agent_core.session.loop import (
    SessionOutcome,
    SessionRunner,
    SessionSettings,
)
from agent_core.session.state import SessionState
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.permission import (
    PermissionDecision,
    PermissionEngine,
)
from agent_core.tool_runtime.registry import default_builtin_registry

from ailit.agent_provider_config import AgentRunProviderConfigBuilder
from ailit.session_outcome_user_copy import (
    MAX_TURNS_EXCEEDED_REASON,
    SessionErrorAssistantMessageComposer,
)
from ailit.tui_session_types import TuiSessionState

DiagSink = Callable[[dict[str, Any]], None]


class TuiProviderAssembler:
    """Сборка провайдера и эффективного имени модели."""

    def build(
        self,
        *,
        provider: str,
        model: str,
        project_root: Path,
    ) -> tuple[object, str]:
        """Вернуть (provider, model_id для запроса)."""
        root = project_root.resolve()
        if provider == "mock":
            os.environ.setdefault("AILIT_WORK_ROOT", str(root))
            return MockProvider(), "mock"
        cfg = AgentRunProviderConfigBuilder().build(
            root,
            use_dev_repo_yaml=True,
        )
        key = deepseek_api_key_from_env_or_config(cfg)
        if not key:
            msg = (
                "Нет ключа DeepSeek: DEEPSEEK_API_KEY или ключ в merge "
                "(см. `ailit config show`)."
            )
            raise RuntimeError(msg)
        ds = cfg.get("deepseek")
        api_root = "https://api.deepseek.com/v1"
        m = model or "deepseek-chat"
        if isinstance(ds, dict):
            api_root = str(ds.get("base_url") or api_root).rstrip("/")
            m = str(ds.get("model") or m)
        return DeepSeekAdapter(key, api_root=api_root), m


class TuiChatController:
    """История сообщений и вызов ``SessionRunner``."""

    def __init__(
        self,
        *,
        seed_messages: list[ChatMessage] | None = None,
    ) -> None:
        """Начать с системного сообщения или с восстановленного снимка."""
        if seed_messages:
            self._messages = list(seed_messages)
        else:
            self._messages = [
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content="You are a helpful concise assistant.",
                ),
            ]

    def snapshot_messages(self) -> list[ChatMessage]:
        """Копия истории для сериализации."""
        return list(self._messages)

    def replace_messages(self, messages: list[ChatMessage]) -> None:
        """Восстановить историю (после загрузки с диска)."""
        self._messages = list(messages)

    def run_user_turn(
        self,
        text: str,
        *,
        state: TuiSessionState,
        diag_sink: DiagSink,
        log_path: str,
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Прогон цикла: текст, статус, usage последнего ответа (или None)."""
        self._messages.append(ChatMessage(role=MessageRole.USER, content=text))
        provider_obj, model_eff = TuiProviderAssembler().build(
            provider=state.provider,
            model=state.model,
            project_root=state.project_root,
        )
        root = state.project_root.resolve()
        os.environ["AILIT_WORK_ROOT"] = str(root)
        reg = default_builtin_registry()
        perm = PermissionEngine(write_default=PermissionDecision.ALLOW)
        runner = SessionRunner(provider_obj, reg, permission_engine=perm)
        settings = SessionSettings(
            model=model_eff,
            max_turns=state.max_turns,
            temperature=0.3,
        )
        out = runner.run(
            list(self._messages),
            ApprovalSession(),
            settings,
            diag_sink=diag_sink,
        )
        self._messages = list(out.messages)
        status = _last_diag_status_line(out)
        usage_payload = _last_usage_payload(out)
        if out.state is SessionState.FINISHED:
            last = self._messages[-1]
            if last.role is MessageRole.ASSISTANT:
                return (last.content or "(пусто)", status, usage_payload)
            return ("(нет ответа ассистента)", status, usage_payload)
        if out.state is SessionState.ERROR:
            comp = SessionErrorAssistantMessageComposer()
            detail = comp.compose(
                reason=out.reason,
                log_path=log_path,
                effective_max_turns=state.max_turns,
            )
            if out.reason == MAX_TURNS_EXCEEDED_REASON:
                return (detail, status, usage_payload)
            return (detail, status, usage_payload)
        msg = f"Состояние: {out.state.value} ({out.reason!r})"
        return (msg, status, usage_payload)


def _last_diag_status_line(out: SessionOutcome) -> str:
    """Короткая строка из последнего model.response."""
    for row in reversed(out.events):
        if row.get("event_type") != "model.response":
            continue
        totals = row.get("usage_session_totals")
        if isinstance(totals, dict):
            i = totals.get("input_tokens")
            o = totals.get("output_tokens")
            cr = totals.get("cache_read_tokens")
            cw = totals.get("cache_write_tokens")
            return f"ctx | usage Σ in={i} out={o} cache_r={cr} cache_w={cw}"
    return ""


def _last_usage_payload(out: SessionOutcome) -> dict[str, Any] | None:
    """Блок ``usage`` последнего ``model.response``."""
    for row in reversed(out.events):
        if row.get("event_type") != "model.response":
            continue
        u = row.get("usage")
        if isinstance(u, dict):
            return dict(u)
    return None
