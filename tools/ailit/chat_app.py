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
from ailit.chat_presenters import (
    format_assistant_chat_block_markdown,
    format_tool_message_content_markdown,
    summarize_workflow_jsonl_for_user,
    tool_message_should_offer_raw_json,
)
from ailit.chat_session_turn_progress import ChatSessionTurnProgress
from ailit.session_outcome_user_copy import (
    OutcomeReasonHumanizer,
    SessionErrorAssistantMessageComposer,
)
from ailit.teams_panel_presenter import TeamMailboxPanelPresenter
from ailit.teams_tools import teammate_tool_registry
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


def _registry_for_chat(
    *,
    file_tools: bool,
    work_root: Path | None,
    teammate_tools: bool,
) -> ToolRegistry:
    """Собрать реестр: file tools + опционально ``send_teammate_message``."""
    reg: ToolRegistry
    if file_tools:
        root = (work_root or _REPO).resolve()
        os.environ["AILIT_WORK_ROOT"] = str(root)
        reg = default_builtin_registry()
    else:
        reg = empty_tool_registry()
    if teammate_tools and work_root is not None:
        pr = work_root.resolve()
        os.environ["AILIT_TEAM_PROJECT_ROOT"] = str(pr)
        os.environ.setdefault("AILIT_WORK_ROOT", str(pr))
        reg = reg.merge(teammate_tool_registry())
    return reg


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


def _render_header_and_menu(
    *,
    project_root: Path,
    loaded: LoadedProject | None,
    load_error: str | None,
) -> tuple[str, int, bool, str, bool, bool]:
    """Верхняя строка: настройки чата + заметная кнопка «Меню» (popover с вкладками)."""
    col_left, col_mid, col_menu = st.columns([5, 3, 3])
    with col_left:
        choice = st.selectbox("Провайдер", ("deepseek", "mock"), index=0, label_visibility="collapsed")
        _mt_help = (
            "Сколько раз агент может повторить цикл "
            "«модель → инструменты → снова модель». "
            "Это не лимит длины ответа API (max_tokens у провайдера — "
            "отдельно в конфиге)."
        )
        max_turns = st.slider(
            "Лимит итераций сессии (max_turns)",
            1,
            32,
            8,
            help=_mt_help,
        )
        file_tools = st.checkbox("Файловые tools", value=True)
    with col_mid:
        use_project = st.toggle("Проект", value=True)
        agent_id = st.text_input("agent_id", value="default", label_visibility="visible")
        teammate_tools = st.checkbox(
            "Инструмент команды (mailbox)",
            value=loaded is not None,
            disabled=loaded is None,
            help="send_teammate_message: запись в .ailit/teams/<team_id>/inboxes/",
        )
    with col_menu:
        st.caption("Дополнительно")
        with st.popover(
            "Меню",
            help="Проект, контекст, workflow, adapter, debug, команды CLI",
            use_container_width=True,
        ):
            tab_p, tab_team, tab_c, tab_w, tab_a, tab_d, tab_cmd = st.tabs(
                ["Проект", "Команда", "Контекст", "Workflow", "Adapter", "Debug", "CLI"],
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
            with tab_team:
                st.caption("Файловый mailbox: `.ailit/teams/<team_id>/inboxes/<agent>.json`")
                root = Path(st.session_state.get("ailit_project_root", project_root))
                st.text_input("team_id", key="ailit_team_panel_id", value="default")
                st.text_input("Фильтр: только inbox получателя (пусто = все)", key="ailit_team_filter_to")
                if st.button("Обновить панель команды", key="ailit_team_refresh"):
                    st.session_state["ailit_team_digest_tick"] = (
                        int(st.session_state.get("ailit_team_digest_tick", 0)) + 1
                    )
                tid = str(st.session_state.get("ailit_team_panel_id", "default")).strip() or "default"
                flt_raw = str(st.session_state.get("ailit_team_filter_to", "")).strip()
                flt = flt_raw or None
                if loaded is not None:
                    pres = TeamMailboxPanelPresenter(project_root=root, team_id=tid)
                    st.markdown(pres.markdown_digest(filter_to=flt))
                    inbox_dir = root / ".ailit" / "teams" / tid / "inboxes"
                    with st.expander("Сырой JSON (пути inbox)", expanded=False):
                        if inbox_dir.is_dir():
                            st.json(
                                {
                                    "inbox_dir": str(inbox_dir),
                                    "files": sorted(str(p.name) for p in inbox_dir.glob("*.json")),
                                },
                            )
                        else:
                            st.json({"inbox_dir": str(inbox_dir), "files": []})
                else:
                    st.info("Нужен загруженный project.yaml и корень проекта.")
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
                prog_raw = st.session_state.get("ailit_last_turn_progress")
                if isinstance(prog_raw, ChatSessionTurnProgress):
                    st.caption(prog_raw.markdown_caption())
                    log_p = ensure_process_log("chat").path
                    with st.expander(
                        "Диагностика шагов последнего прогона чата",
                        expanded=False,
                    ):
                        st.markdown(
                            f"{prog_raw.markdown_caption()}\n\n"
                            f"Полный след: `{log_p}` (события `session.turn`, …)."
                        )
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
    return choice, max_turns, file_tools, agent_id, use_project, teammate_tools


def _render_dialogue_messages(messages: list[ChatMessage]) -> None:
    """Отрисовать user/assistant/tool (без system)."""
    for m in messages:
        if m.role is MessageRole.SYSTEM:
            continue
        with st.chat_message(m.role.value):
            if m.role is MessageRole.TOOL:
                st.markdown(format_tool_message_content_markdown(m.content))
                if tool_message_should_offer_raw_json(m.content):
                    with st.expander("Сырой JSON (инструмент)", expanded=False):
                        st.code(m.content, language="json")
            elif m.role is MessageRole.ASSISTANT:
                st.markdown(
                    format_assistant_chat_block_markdown(
                        content=m.content,
                        tool_calls=m.tool_calls,
                    ),
                )
            else:
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
    teammate_tools = bool(snap.get("teammate_tools", False))
    agent_id = str(snap["agent_id"])
    project_root = Path(str(snap["project_root"]))
    os.environ["AILIT_CHAT_AGENT_ID"] = agent_id.strip() or "default"

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
    work_for_tools = project_root if use_project else _REPO
    perm = (
        PermissionEngine(write_default=PermissionDecision.ALLOW)
        if file_tools or teammate_tools
        else None
    )
    runner = SessionRunner(
        provider,
        _registry_for_chat(
            file_tools=file_tools,
            work_root=work_for_tools,
            teammate_tools=teammate_tools,
        ),
        permission_engine=perm,
    )
    out = runner.run(
        runner_msgs,
        ApprovalSession(),
        settings,
        diag_sink=ensure_process_log("chat").sink,
    )

    log_handle = ensure_process_log("chat")
    log_path = str(log_handle.path)
    composer = SessionErrorAssistantMessageComposer()
    if out.state is SessionState.ERROR:
        runner_msgs.append(
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=composer.compose(
                    reason=out.reason,
                    log_path=log_path,
                    effective_max_turns=settings.max_turns,
                ),
            ),
        )

    if use_project and loaded_local is not None and tuning is not None:
        st.session_state[_ChatPageState.MESSAGES] = store_after_run(base_system, prefix_len, runner_msgs)
    else:
        st.session_state[_ChatPageState.MESSAGES] = runner_msgs

    progress = ChatSessionTurnProgress.from_outcome_events(
        out.events,
        limit=settings.max_turns,
    )
    st.session_state["ailit_last_turn_progress"] = progress

    hz = OutcomeReasonHumanizer()
    hint = hz.humanize(out.reason)
    cap_parts: list[str] = [f"state={out.state.value}"]
    cap_parts.append(f"сессия: {progress.short_label_ru()}")
    if hint:
        cap_parts.append(hint)
    elif out.reason:
        cap_parts.append(f"reason={out.reason!r}")
    cap_parts.append(f"log=`{log_path}`")
    st.caption(" | ".join(cap_parts))


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

    st.session_state.setdefault("ailit_wf_ref", "minimal")
    st.session_state.setdefault("ailit_wf_model", "deepseek-chat")
    st.session_state.setdefault("ailit_wf_max_turns", 8)
    st.session_state.setdefault("ailit_wf_dry_run", True)

    fac = ProjectSessionFactory(project_root)
    plr = fac.load()
    loaded = plr.loaded
    load_error = plr.error

    choice, max_turns, file_tools, agent_id, use_project, teammate_tools = _render_header_and_menu(
        project_root=project_root,
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
        "teammate_tools": teammate_tools,
        "agent_id": agent_id,
        "project_root": str(project_root),
    }
    st.session_state[_ChatPageState.PENDING_LLM] = True
    st.rerun()


if __name__ == "__main__":
    main()
