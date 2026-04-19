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

from agent_core.config_loader import deepseek_api_key_from_env_or_config
from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.deepseek import DeepSeekAdapter
from agent_core.providers.mock_provider import MockProvider
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.state import SessionState
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.permission import PermissionDecision, PermissionEngine
from agent_core.tool_runtime.registry import ToolRegistry, default_builtin_registry, empty_tool_registry
from ailit.agent_provider_config import AgentRunProviderConfigBuilder
from ailit.chat_handlers import (
    ProjectSessionFactory,
    attach_runner_suffix,
    store_after_run,
    strip_system_messages,
)
from ailit.chat_presenters import summarize_workflow_jsonl_for_user
from ailit.chat_workflow_runner import run_workflow_capture_jsonl
from ailit.process_log import ensure_process_log
from ailit.compat_adapter import read_status, run_compat_workflow
from ailit.debug_bundle import build_debug_bundle, default_rollout_phase
from project_layer.bootstrap import format_agent_run_command
from project_layer.loader import LoadedProject


def _load_merged_chat_cfg(project_root: Path) -> dict:
    """Тот же merge, что и в ``ailit agent run`` (включая dev ``test.local.yaml``)."""
    return AgentRunProviderConfigBuilder().build(
        project_root.resolve(),
        use_dev_repo_yaml=True,
    )


def _make_provider(choice: str, cfg: dict) -> tuple[object, str]:
    """Собрать провайдер и имя модели для запросов."""
    if choice == "mock":
        return MockProvider(), "mock"
    if choice == "deepseek":
        key = deepseek_api_key_from_env_or_config(cfg)
        if not key:
            st.error(
                "Нет ключа: задайте DEEPSEEK_API_KEY или `deepseek.api_key` "
                "в глобальном/проектном merge (см. `ailit config show`).",
            )
            st.stop()
        ds = cfg.get("deepseek")
        root = "https://api.deepseek.com/v1"
        model = "deepseek-chat"
        if isinstance(ds, dict):
            root = str(ds.get("base_url") or root).rstrip("/")
            model = str(ds.get("model") or model)
        return DeepSeekAdapter(key, api_root=root), model
    raise ValueError(choice)


def _registry_for_chat(file_tools: bool, work_root: Path | None = None) -> ToolRegistry:
    """File tools: песочница = корень проекта (или репозиторий по умолчанию)."""
    if not file_tools:
        return empty_tool_registry()
    root = (work_root or _REPO).resolve()
    os.environ["AILIT_WORK_ROOT"] = str(root)
    return default_builtin_registry()


class _ChatPageState:
    """Ключи session_state."""

    MESSAGES = "messages"
    SNAPSHOT_CACHE = "context_snapshot_cache"
    PENDING_LLM = "ailit_pending_llm"
    LLM_WIDGET_SNAPSHOT = "ailit_llm_widget_snapshot"


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
        file_tools = st.checkbox("Файловые tools", value=True)
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
    """Правое бургер-меню: проект, контекст, workflow, Adapter, Debug, команда."""
    _, col_burger = st.columns([6, 1])
    with col_burger:
        with st.popover("☰", use_container_width=True):
            tab_p, tab_c, tab_w, tab_a, tab_d, tab_cmd = st.tabs(
                ["Проект", "Контекст", "Workflow", "Adapter", "Debug", "Команда"],
            )
            with tab_p:
                st.text_input("Корень проекта", key="ailit_project_root")
                if load_error:
                    st.error(load_error)
                elif loaded is not None:
                    st.success(f"project_id={loaded.config.project_id}")
                    wf_keys = ", ".join(sorted(loaded.config.workflows.keys())) or "—"
                    ag_keys = ", ".join(sorted(loaded.config.agents.keys())) or "—"
                    st.markdown(
                        f"- **runtime:** `{loaded.config.runtime.value}`\n"
                        f"- **workflows:** {wf_keys}\n"
                        f"- **agents:** {ag_keys}\n"
                        f"- **rollout.phase:** `{loaded.config.rollout.phase}`",
                    )
                    with st.expander("Сырой JSON (диагностика)", expanded=False):
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
            with tab_w:
                st.caption("Запуск workflow YAML (как `ailit agent run`)")
                root = Path(st.session_state.get("ailit_project_root", project_root))
                st.text_input(
                    "workflow_ref",
                    key="ailit_wf_ref",
                    help="Id из project.yaml или путь *.yaml относительно корня проекта",
                )
                st.text_input("model", key="ailit_wf_model")
                st.number_input("max_turns (workflow)", min_value=1, max_value=64, key="ailit_wf_max_turns")
                st.checkbox("dry_run", key="ailit_wf_dry_run")
                if st.button("Запустить workflow", key="ailit_wf_run"):
                    try:
                        ref = str(st.session_state.get("ailit_wf_ref", "minimal")).strip()
                        wf_model = str(st.session_state.get("ailit_wf_model", "deepseek-chat")).strip()
                        wf_mt = int(st.session_state.get("ailit_wf_max_turns", 8))
                        wf_dry = bool(st.session_state.get("ailit_wf_dry_run", True))
                        prov = "mock" if choice == "mock" else "deepseek"
                        if prov == "deepseek" and wf_dry is False:
                            st.warning(
                                "Live DeepSeek: нужен DEEPSEEK_API_KEY или ключ в merge "
                                "(см. `ailit config show`).",
                            )
                        text = run_workflow_capture_jsonl(
                            repo_root=_REPO,
                            project_root=root,
                            workflow_ref=ref,
                            provider=prov,
                            model=wf_model if prov == "deepseek" else "mock",
                            max_turns=wf_mt,
                            dry_run=wf_dry,
                            diag_sink=ensure_process_log("chat").sink,
                        )
                        st.session_state["ailit_wf_last_jsonl"] = text
                    except (OSError, ValueError, TypeError, KeyError, FileNotFoundError) as exc:
                        st.session_state["ailit_wf_last_jsonl"] = f"# error\n{type(exc).__name__}: {exc}\n"
                wfj = st.session_state.get("ailit_wf_last_jsonl")
                if wfj:
                    st.markdown(summarize_workflow_jsonl_for_user(str(wfj)))
                    with st.expander("Сырой JSONL (диагностика)", expanded=False):
                        st.code(str(wfj)[:50000], language="json")
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
                            diag_sink=ensure_process_log("chat").sink,
                        )
                        st.session_state["compat_last_jsonl"] = buf.getvalue()
                    lj = st.session_state.get("compat_last_jsonl")
                    if lj:
                        st.markdown(summarize_workflow_jsonl_for_user(str(lj)))
                        with st.expander("Сырой JSONL compat (диагностика)", expanded=False):
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


def _render_dialogue_messages(messages: list[ChatMessage]) -> None:
    """Отрисовать user/assistant/tool (без system)."""
    for m in messages:
        if m.role is MessageRole.SYSTEM:
            continue
        with st.chat_message(m.role.value):
            st.markdown(m.content if m.content else " ")


_FILE_TOOLS_SYSTEM_HINT = (
    "Когда пользователь просит создать или записать файл, обязательно вызови инструмент "
    "write_file с относительным путём внутри рабочего корня и содержимым файла. "
    "Не утверждай, что файл создан, если инструмент не был вызван."
)

_FS_TOOLS_SYSTEM_HINT = (
    "Обзор дерева: list_dir (один уровень) или glob_file (шаблон имён). "
    "read_file — только один текстовый файл, не каталог и не '.'. "
    "Поиск по содержимому: grep (нужен `rg` в PATH); не выдумывай вывод grep."
)


def _inject_file_tools_system_hint(runner_msgs: list[ChatMessage], file_tools: bool) -> None:
    """Подсказки модели: write_file и обзор/поиск по Claude-style."""
    if not file_tools:
        return
    for i, m in enumerate(runner_msgs):
        if m.role is MessageRole.USER:
            runner_msgs.insert(
                i,
                ChatMessage(role=MessageRole.SYSTEM, content=_FS_TOOLS_SYSTEM_HINT),
            )
            runner_msgs.insert(
                i + 1,
                ChatMessage(role=MessageRole.SYSTEM, content=_FILE_TOOLS_SYSTEM_HINT),
            )
            return


def _execute_llm_turn(
    *,
    cfg: dict,
    snap: dict[str, object],
) -> None:
    """Второй проход: SessionRunner (настройки из снимка отправки)."""
    choice = str(snap["choice"])
    max_turns = int(snap["max_turns"])
    file_tools = bool(snap["file_tools"])
    use_project = bool(snap["use_project"])
    agent_id = str(snap["agent_id"])
    project_root = Path(str(snap["project_root"]))

    fac_local = ProjectSessionFactory(project_root)
    plr = fac_local.load()
    loaded_local = plr.loaded
    base_system = "You are a helpful concise assistant."
    msgs_src = st.session_state[_ChatPageState.MESSAGES]
    tuning = None
    prefix_len = 0
    if use_project and loaded_local is not None:
        ctx_snap = st.session_state.get(_ChatPageState.SNAPSHOT_CACHE)
        tuning = fac_local.tuning_for_chat(loaded_local, agent_id.strip() or "default", ctx_snap)
        suffix = strip_system_messages(list(msgs_src))
        runner_msgs = attach_runner_suffix(base_system, tuning, suffix)
        prefix_len = len(runner_msgs) - len(suffix)
    else:
        runner_msgs = list(msgs_src)

    _inject_file_tools_system_hint(runner_msgs, file_tools)

    provider, model = _make_provider(choice, cfg)
    settings = SessionSettings(
        model=model,
        max_turns=tuning.max_turns if tuning and tuning.max_turns is not None else max_turns,
        temperature=tuning.temperature if tuning and tuning.temperature is not None else 0.3,
        shortlist_keywords=tuning.shortlist_keywords if tuning else None,
    )
    perm = (
        PermissionEngine(write_default=PermissionDecision.ALLOW)
        if file_tools
        else None
    )
    runner = SessionRunner(
        provider,
        _registry_for_chat(file_tools, project_root),
        permission_engine=perm,
    )
    out = runner.run(
        runner_msgs,
        ApprovalSession(),
        settings,
        diag_sink=ensure_process_log("chat").sink,
    )

    if out.state is SessionState.ERROR:
        detail = out.reason or "unknown_error"
        runner_msgs.append(
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=(
                    "Не удалось получить ответ модели. "
                    f"Подробности: {detail}. См. JSONL-лог процесса."
                ),
            ),
        )

    if use_project and loaded_local is not None and tuning is not None:
        st.session_state[_ChatPageState.MESSAGES] = store_after_run(base_system, prefix_len, runner_msgs)
    else:
        st.session_state[_ChatPageState.MESSAGES] = runner_msgs

    st.caption(
        f"state={out.state.value} reason={out.reason!r} | "
        f"log={ensure_process_log('chat').path}",
    )


def main() -> None:
    """Точка входа Streamlit."""
    ensure_process_log("chat")
    st.set_page_config(page_title="ailit chat", layout="wide", initial_sidebar_state="collapsed")
    _init_messages()
    st.markdown("### ailit chat")
    root_default = _REPO
    if "ailit_project_root" not in st.session_state:
        st.session_state["ailit_project_root"] = str(root_default)
    project_root = Path(str(st.session_state.get("ailit_project_root", root_default)))
    cfg = _load_merged_chat_cfg(project_root)

    choice, max_turns, file_tools, agent_id, use_project = _render_header_bar()

    st.session_state.setdefault("ailit_wf_ref", "minimal")
    st.session_state.setdefault("ailit_wf_model", "deepseek-chat")
    st.session_state.setdefault("ailit_wf_max_turns", 8)
    st.session_state.setdefault("ailit_wf_dry_run", True)

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

    msgs = st.session_state[_ChatPageState.MESSAGES]
    pending = bool(st.session_state.get(_ChatPageState.PENDING_LLM, False))

    if pending:
        snap_raw = st.session_state.get(_ChatPageState.LLM_WIDGET_SNAPSHOT)
        if not isinstance(snap_raw, dict):
            st.session_state[_ChatPageState.PENDING_LLM] = False
            st.rerun()
            return
        _render_dialogue_messages(msgs)
        with st.chat_message("assistant"):
            wait_ph = st.empty()
            wait_ph.markdown("_Ожидание ответа…_")
            with st.spinner("Запрос к модели…"):
                _execute_llm_turn(cfg=cfg, snap=snap_raw)
            wait_ph.empty()
        st.session_state[_ChatPageState.PENDING_LLM] = False
        st.session_state.pop(_ChatPageState.LLM_WIDGET_SNAPSHOT, None)
        st.rerun()
        return

    _render_dialogue_messages(msgs)

    prompt = st.chat_input("Сообщение…")
    if not prompt:
        return

    st.session_state[_ChatPageState.MESSAGES].append(
        ChatMessage(role=MessageRole.USER, content=prompt),
    )
    st.session_state[_ChatPageState.LLM_WIDGET_SNAPSHOT] = {
        "choice": choice,
        "max_turns": max_turns,
        "file_tools": file_tools,
        "use_project": use_project,
        "agent_id": agent_id,
        "project_root": str(project_root),
    }
    st.session_state[_ChatPageState.PENDING_LLM] = True
    st.rerun()


if __name__ == "__main__":
    main()
