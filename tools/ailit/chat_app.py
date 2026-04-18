"""Streamlit: интерактивный чат с провайдером (DeepSeek / mock)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "tools") not in sys.path:
    sys.path.insert(0, str(_REPO / "tools"))

from agent_core.config_loader import deepseek_api_key_from_env_or_config, load_test_local_yaml
from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.deepseek import DeepSeekAdapter
from agent_core.providers.mock_provider import MockProvider
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.registry import ToolRegistry, default_builtin_registry, empty_tool_registry


def _load_cfg() -> dict:
    p = _REPO / "config" / "test.local.yaml"
    return dict(load_test_local_yaml(p)) if p.is_file() else {}


def _make_provider(choice: str, cfg: dict) -> tuple[object, str]:
    """Собрать провайдер и имя модели для запросов."""
    if choice == "mock":
        return MockProvider(), "mock"
    if choice == "deepseek":
        key = deepseek_api_key_from_env_or_config(cfg)
        if not key:
            st.error("Нет ключа: DEEPSEEK_API_KEY или `deepseek.api_key` в config/test.local.yaml")
            st.stop()
        ds = cfg.get("deepseek")
        root = "https://api.deepseek.com/v1"
        model = "deepseek-chat"
        if isinstance(ds, dict):
            root = str(ds.get("base_url") or root).rstrip("/")
            model = str(ds.get("model") or model)
        return DeepSeekAdapter(key, api_root=root), model
    raise ValueError(choice)


def _registry_for_chat(file_tools: bool) -> ToolRegistry:
    """По умолчанию без file tools — иначе модель зовёт read_file и ловит песочницу/ошибки путей."""
    if not file_tools:
        return empty_tool_registry()
    os.environ.setdefault("AILIT_WORK_ROOT", str(_REPO))
    return default_builtin_registry()


def main() -> None:
    """Точка входа Streamlit."""
    st.set_page_config(page_title="ailit chat", layout="wide")
    st.title("ailit chat")
    cfg = _load_cfg()
    choice = st.sidebar.selectbox("Провайдер", ("deepseek", "mock"), index=0)
    max_turns = st.sidebar.slider("max_turns", 1, 32, 8)
    file_tools = st.sidebar.checkbox(
        "Файловые инструменты (read_file / write_file)",
        value=False,
        help="Выкл.: обычный диалог без tool calling. Вкл.: песочница = корень репозитория (AILIT_WORK_ROOT).",
    )

    if "messages" not in st.session_state:
        st.session_state.messages = [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content="You are a helpful concise assistant.",
            ),
        ]

    for m in st.session_state.messages:
        if m.role is MessageRole.SYSTEM:
            continue
        with st.chat_message(m.role.value):
            st.markdown(m.content if m.content else " ")

    prompt = st.chat_input("Сообщение…")
    if prompt:
        st.session_state.messages.append(ChatMessage(role=MessageRole.USER, content=prompt))
        provider, model = _make_provider(choice, cfg)
        msgs = list(st.session_state.messages)
        runner = SessionRunner(provider, _registry_for_chat(file_tools))
        out = runner.run(
            msgs,
            ApprovalSession(),
            SessionSettings(model=model, max_turns=max_turns, temperature=0.3),
        )
        st.session_state.messages = msgs
        st.caption(f"state={out.state.value} reason={out.reason!r}")
        st.rerun()


if __name__ == "__main__":
    main()
