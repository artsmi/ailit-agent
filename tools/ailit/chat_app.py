"""Streamlit: минималистичный чат + правое бургер-меню (project layer)."""

from __future__ import annotations

import os
import sys
from io import StringIO
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
from ailit.chat_handlers import (
    ProjectSessionFactory,
    attach_runner_suffix,
    store_after_run,
    strip_system_messages,
)
from ailit.compat_adapter import read_status, run_compat_workflow
from ailit.debug_bundle import build_debug_bundle, default_rollout_phase
from project_layer.bootstrap import format_agent_run_command
from project_layer.loader import LoadedProject


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
    """По умолчанию без file tools."""
    if not file_tools:
        return empty_tool_registry()
    os.environ.setdefault("AILIT_WORK_ROOT", str(_REPO))
    return default_builtin_registry()


class _ChatPageState:
    """Ключи session_state."""

    MESSAGES = "messages"
    SNAPSHOT_CACHE = "context_snapshot_cache"


def _init_messages() -> None:
    if _ChatPageState.MESSAGES not in st.session_state:
        st.session_state[_ChatPageState.MESSAGES] = [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content="You are a helpful concise assistant.",
            ),
        ]


def _render_header_bar() -> tuple[str, int, bool, str, bool]:
    """Верхняя строка: провайдер, лимиты, project toggle. Возвращает выбранные значения."""
    c_left, c_right = st.columns([5, 1])
    with c_left:
        choice = st.selectbox("Провайдер", ("deepseek", "mock"), index=0, label_visibility="collapsed")
        max_turns = st.slider("max_turns", 1, 32, 8)
        file_tools = st.checkbox("Файловые tools", value=False)
    with c_right:
        use_project = st.toggle("Проект", value=True)
        agent_id = st.text_input("agent_id", value="default", label_visibility="visible")
    return choice, max_turns, file_tools, agent_id, use_project


def _render_burger_menu(
    *,
    project_root: Path,
    choice: str,
    max_turns: int,
    loaded: LoadedProject | None,
    load_error: str | None,
) -> None:
    """Правое бургер-меню: проект, контекст, Adapter, Debug, команда."""
    _, col_burger = st.columns([6, 1])
    with col_burger:
        with st.popover("☰", use_container_width=True):
            tab_p, tab_c, tab_a, tab_d, tab_cmd = st.tabs(
                ["Проект", "Контекст", "Adapter", "Debug", "Команда"],
            )
            with tab_p:
                st.text_input("Корень проекта", key="ailit_project_root")
                if load_error:
                    st.error(load_error)
                elif loaded is not None:
                    st.success(f"project_id={loaded.config.project_id}")
                    st.json(
                        {
                            "runtime": loaded.config.runtime.value,
                            "workflows": list(loaded.config.workflows.keys()),
                            "agents": list(loaded.config.agents.keys()),
                            "rollout.phase": loaded.config.rollout.phase,
                        },
                    )
                else:
                    st.info("Нет загруженного project.yaml")
            with tab_c:
                if loaded is None:
                    st.caption("Сначала укажите корректный корень и project.yaml")
                else:
                    if st.button("Обновить shortlist / context"):
                        fac = ProjectSessionFactory(Path(st.session_state.get("ailit_project_root", project_root)))
                        lr = fac.load()
                        if lr.loaded:
                            snap = fac.refresh_snapshot(lr.loaded)
                            st.session_state[_ChatPageState.SNAPSHOT_CACHE] = snap
                    snap = st.session_state.get(_ChatPageState.SNAPSHOT_CACHE)
                    if snap is not None:
                        st.caption("canonical paths")
                        st.code("\n".join(snap.canonical_rel_paths) or "(пусто)", language="text")
                        st.caption("keywords (фрагмент)")
                        keys = sorted(snap.shortlist_keywords)
                        st.code(", ".join(keys[:40]), language="text")
                        if snap.warnings:
                            st.warning("\n".join(snap.warnings))
                        st.text_area("preview", snap.preview_text[:12000], height=220)
            with tab_a:
                st.caption("Compat adapter (этап 8)")
                root = Path(st.session_state.get("ailit_project_root", project_root))
                if loaded is None:
                    st.info("Нужен project.yaml")
                else:
                    st.text(f"runtime={loaded.config.runtime.value}")
                    if st.button("Смок compat (mock, dry-run)", key="ailit_compat_smoke"):
                        buf = StringIO()
                        run_compat_workflow(
                            project_root=root,
                            workflow_ref="minimal",
                            provider="mock",
                            model="deepseek-chat",
                            max_turns=6,
                            dry_run=True,
                            sink=buf,
                            repo_root=_REPO,
                        )
                        st.session_state["compat_last_jsonl"] = buf.getvalue()
                    lj = st.session_state.get("compat_last_jsonl")
                    if lj:
                        st.code(str(lj)[:20000], language="json")
                    st.markdown("**status.md**")
                    st.code(read_status(root) or "(нет)", language="markdown")
            with tab_d:
                st.caption("Debug bundle / rollout (этап 9)")
                root = Path(st.session_state.get("ailit_project_root", project_root))
                st.text(f"rollout.phase={default_rollout_phase(root)}")
                if st.button("Собрать debug bundle", key="ailit_debug_bundle"):
                    out_zip = root / ".ailit" / "debug-bundle.zip"
                    res = build_debug_bundle(project_root=root, dest_zip=out_zip)
                    st.session_state["debug_bundle_path"] = str(res.zip_path)
                bp = st.session_state.get("debug_bundle_path")
                if bp and Path(bp).is_file():
                    st.download_button(
                        "Скачать bundle",
                        data=Path(bp).read_bytes(),
                        file_name="debug-bundle.zip",
                        key="ailit_dl_bundle",
                    )
            with tab_cmd:
                root = Path(st.session_state.get("ailit_project_root", project_root))
                cmd = format_agent_run_command(
                    project_root=root,
                    workflow_ref="minimal",
                    provider="mock" if choice == "mock" else "deepseek",
                    model="deepseek-chat",
                    max_turns=max_turns,
                    dry_run=True,
                )
                st.code(cmd, language="bash")
                st.caption("Скопируйте для проверки CLI")
                st.download_button("Скачать .sh", data=cmd + "\n", file_name="ailit-run.sh", key="ailit_dl_sh")
                st.caption("Compat CLI")
                st.code(
                    f"ailit compat run minimal --project-root {root} "
                    f"--provider mock --dry-run --max-turns {max_turns}",
                    language="bash",
                )
                st.caption("Debug bundle CLI")
                st.code(
                    f"ailit debug bundle --project-root {root} --out {root / '.ailit' / 'debug-bundle.zip'}",
                    language="bash",
                )


def main() -> None:
    """Точка входа Streamlit."""
    st.set_page_config(page_title="ailit chat", layout="wide", initial_sidebar_state="collapsed")
    _init_messages()
    cfg = _load_cfg()
    st.markdown("### ailit chat")
    choice, max_turns, file_tools, agent_id, use_project = _render_header_bar()

    root_default = _REPO
    if "ailit_project_root" not in st.session_state:
        st.session_state["ailit_project_root"] = str(root_default)
    project_root = Path(str(st.session_state.get("ailit_project_root", root_default)))

    fac = ProjectSessionFactory(project_root)
    plr = fac.load()
    loaded = plr.loaded
    load_error = plr.error

    _render_burger_menu(
        project_root=project_root,
        choice=choice,
        max_turns=max_turns,
        loaded=loaded,
        load_error=load_error,
    )

    for m in st.session_state[_ChatPageState.MESSAGES]:
        if m.role is MessageRole.SYSTEM:
            continue
        with st.chat_message(m.role.value):
            st.markdown(m.content if m.content else " ")

    prompt = st.chat_input("Сообщение…")
    if not prompt:
        return

    st.session_state[_ChatPageState.MESSAGES].append(
        ChatMessage(role=MessageRole.USER, content=prompt),
    )
    provider, model = _make_provider(choice, cfg)
    base_system = "You are a helpful concise assistant."
    msgs_src = st.session_state[_ChatPageState.MESSAGES]
    if use_project and loaded is not None:
        snap = st.session_state.get(_ChatPageState.SNAPSHOT_CACHE)
        tuning = fac.tuning_for_chat(loaded, agent_id.strip() or "default", snap)
        suffix = strip_system_messages(list(msgs_src))
        runner_msgs = attach_runner_suffix(base_system, tuning, suffix)
        prefix_len = len(runner_msgs) - len(suffix)
    else:
        runner_msgs = list(msgs_src)
        prefix_len = 0
        tuning = None

    settings = SessionSettings(
        model=model,
        max_turns=tuning.max_turns if tuning and tuning.max_turns is not None else max_turns,
        temperature=tuning.temperature if tuning and tuning.temperature is not None else 0.3,
        shortlist_keywords=tuning.shortlist_keywords if tuning else None,
    )
    runner = SessionRunner(provider, _registry_for_chat(file_tools))
    out = runner.run(runner_msgs, ApprovalSession(), settings)

    if use_project and loaded is not None and tuning is not None:
        st.session_state[_ChatPageState.MESSAGES] = store_after_run(base_system, prefix_len, runner_msgs)
    else:
        st.session_state[_ChatPageState.MESSAGES] = runner_msgs

    st.caption(f"state={out.state.value} reason={out.reason!r}")
    st.rerun()


if __name__ == "__main__":
    main()
