# flake8: noqa
"""Streamlit: минималистичный чат + правое бургер-меню (project layer)."""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
import uuid
import time
import socket
import json
from typing import Any, Callable

import streamlit as st
import streamlit.components.v1 as components

from agent_core.models import ChatMessage, MessageRole
from agent_core.providers.factory import ProviderFactory, ProviderKind
from agent_core.providers.mock_provider import MockProvider
from agent_core.memory.kb_tools import kb_tools_config_from_env
from agent_core.memory.sqlite_kb import SqliteKb
from agent_core.session.loop import SessionRunner, SessionSettings
from agent_core.session.repo_context import detect_repo_context
from agent_core.system_style_defaults import merge_with_base_system
from agent_core.session.state import SessionState
from agent_core.tool_runtime.approval import ApprovalSession
from agent_core.tool_runtime.permission import PermissionDecision, PermissionEngine
from agent_core.shell_output_preview import LineTailSelector
from agent_core.tool_runtime.bash_tools import bash_tool_registry
from agent_core.tool_runtime.registry import (
    ToolRegistry,
    default_builtin_registry,
)
from ailit.bash_chat_store import (
    append_execution,
    append_output_delta,
    chat_tail_lines,
    mark_finished,
    runs_list,
    set_chat_tail_lines,
    set_view_tail_lines,
    upsert_running_call,
    view_tail_lines,
)
from ailit.bash_project_env import BashProjectEnvSync, BashSessionProjectEnvSync
from ailit.chat_stop_worker import ChatStopWorker
from ailit.agent_provider_config import AgentRunProviderConfigBuilder
from ailit.chat_handlers import (
    ProjectSessionFactory,
    attach_runner_suffix,
    store_after_run,
    strip_system_messages,
)
from ailit.chat_presenters import summarize_workflow_jsonl_for_user
from ailit.chat_transcript_view import (
    ChatTranscriptProjector,
    format_assistant_body_for_ui,
)
from ailit.chat_session_turn_progress import ChatSessionTurnProgress
from ailit.session_outcome_user_copy import (
    MAX_TURNS_EXCEEDED_REASON,
    OutcomeReasonHumanizer,
    SessionErrorAssistantMessageComposer,
)
from ailit.teams_panel_presenter import TeamMailboxPanelPresenter
from ailit.teams_tools import teammate_tool_registry
from ailit.chat_workflow_runner import run_workflow_capture_jsonl
from ailit.perm_mode_chat import (
    ChatPermModeCoordinator,
    build_mode_kb_namespace,
    memory_namespace_from_cfg,
    perm_mode_enabled_from_env,
)
from ailit.process_log import ensure_process_log
from ailit.compat_adapter import read_status, run_compat_workflow
from ailit.debug_bundle import build_debug_bundle, default_rollout_phase
from ailit.defaults_resolver import DefaultProviderModelResolver
from ailit.tool_system_hints import (
    inject_tool_hints_before_first_user,
    memory_kb_first_enabled,
)
from ailit.token_economy_aggregates import (
    analyze_log_rows,
    build_memory_efficiency_score,
    build_memory_diagnosis,
    build_memory_stats,
    build_session_summary,
    compute_resume_signals,
    empty_cumulative,
    format_cumulative_caption,
    merge_cumulative_for_display,
    merge_events_into_cumulative,
    read_jsonl_session_log,
)
from ailit.usage_display import (
    SessionEventsUsageExtractor,
    UsageSummaryMarkdownFormatter,
)
from project_layer.bootstrap import format_agent_run_command
from project_layer.loader import LoadedProject

from agent_core.runtime.models import RuntimeRequestEnvelope
from agent_core.runtime.paths import RuntimePaths, default_runtime_dir
from agent_core.runtime.supervisor import supervisor_request

_REPO = Path(__file__).resolve().parents[2]


def _ensure_runtime_chat_id() -> str:
    chat_id = str(st.session_state.get("ailit_runtime_chat_id", "") or "").strip()
    if chat_id:
        return chat_id
    chat_id = str(uuid.uuid4())
    st.session_state["ailit_runtime_chat_id"] = chat_id
    return chat_id


def _runtime_dir_from_ui() -> Path:
    raw = str(st.session_state.get("ailit_runtime_dir", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return default_runtime_dir()


def _supervisor_sock(runtime_dir: Path) -> Path:
    return RuntimePaths(runtime_dir=runtime_dir).supervisor_socket


def _connect_unix(path: Path, *, timeout_s: float) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    s.connect(str(path))
    return s


def _send_work_prompt_to_broker(
    *,
    broker_socket: Path,
    chat_id: str,
    namespace: str,
    prompt: str,
) -> dict[str, object]:
    env = RuntimeRequestEnvelope(
        contract_version="ailit_agent_runtime_v1",
        runtime_id="rt-ui",
        chat_id=chat_id,
        broker_id=f"broker-{chat_id}",
        trace_id=f"trace-{chat_id}",
        message_id=f"ui-{time.time_ns()}",
        parent_message_id=None,
        goal_id=f"goal-{time.time_ns()}",
        namespace=namespace,
        from_agent="client:ailit-chat",
        to_agent=f"AgentWork:{chat_id}",
        created_at="2026-04-25T00:00:00Z",
        type="action.start",
        payload={"action": "work.handle_user_prompt", "prompt": prompt},
    )
    s = _connect_unix(broker_socket, timeout_s=2.0)
    try:
        s.sendall(env.to_json_line().encode("utf-8") + b"\n")
        data = s.recv(1_000_000).decode("utf-8", errors="replace").strip()
    finally:
        try:
            s.close()
        except OSError:
            pass
    obj = json.loads(data) if data else {}
    return obj if isinstance(obj, dict) else {"ok": False, "error": "invalid_response"}


def _load_merged_chat_cfg(project_root: Path) -> dict:
    """Тот же merge, что и в ``ailit agent run`` (включая dev yaml)."""
    return AgentRunProviderConfigBuilder().build(
        project_root.resolve(),
        use_dev_repo_yaml=True,
    )


def _make_provider(choice: str, cfg: dict) -> tuple[object, str]:
    """Собрать провайдер и имя модели для запросов."""
    if choice == "mock":
        return MockProvider(), "mock"
    if choice == "deepseek":
        try:
            prov = ProviderFactory.create(ProviderKind.DEEPSEEK, config=cfg)
        except ValueError:
            st.error(
                "Нет ключа: задайте DEEPSEEK_API_KEY или `deepseek.api_key` "
                "в глобальном/проектном merge (см. `ailit config show`).",
            )
            st.stop()
        ds = cfg.get("deepseek")
        model = "deepseek-chat"
        if isinstance(ds, dict):
            model = str(ds.get("model") or model)
        return prov, model
    if choice == "kimi":
        try:
            prov = ProviderFactory.create(ProviderKind.KIMI, config=cfg)
        except ValueError:
            st.error(
                "Нет ключа: задайте KIMI_API_KEY/MOONSHOT_API_KEY или "
                "`kimi.api_key` в merge (см. `ailit config show`).",
            )
            st.stop()
        km = cfg.get("kimi")
        model = "moonshot-v1-8k"
        if isinstance(km, dict):
            model = str(km.get("model") or model)
        return prov, model
    raise ValueError(choice)


def _registry_for_chat(
    *,
    cfg: dict,
    work_root: Path | None,
    teammate_tools: bool,
) -> ToolRegistry:
    """Собрать реестр: file tools, shell, teammate."""
    root = (work_root or _REPO).resolve()
    os.environ["AILIT_WORK_ROOT"] = str(root)
    reg = default_builtin_registry().merge(bash_tool_registry())
    mem = cfg.get("memory")
    if isinstance(mem, dict) and bool(mem.get("enabled", False)):
        # H4.1: local-first KB scaffold (sqlite tools).
        ns = str(mem.get("namespace") or "default").strip() or "default"
        os.environ["AILIT_KB_NAMESPACE"] = ns
        from agent_core.memory.kb_tools import (
            build_kb_tool_registry,
            kb_tools_config_from_env,
        )

        reg = reg.merge(build_kb_tool_registry(kb_tools_config_from_env()))
    if teammate_tools and work_root is not None:
        pr = work_root.resolve()
        os.environ["AILIT_TEAM_PROJECT_ROOT"] = str(pr)
        os.environ.setdefault("AILIT_WORK_ROOT", str(pr))
        reg = reg.merge(teammate_tool_registry())
    return reg


def _default_tool_exposure(cfg: dict) -> str:
    """Профиль selective tool exposure: config → env → full."""
    ag = cfg.get("agent")
    if isinstance(ag, dict):
        raw = ag.get("tool_exposure")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    env_te = os.environ.get("AILIT_TOOL_EXPOSURE", "").strip().lower()
    if env_te:
        return env_te
    return "full"


class _ChatPageState:
    """Ключи session_state."""

    MESSAGES = "messages"
    SNAPSHOT_CACHE = "context_snapshot_cache"
    PENDING_LLM = "ailit_pending_llm"
    LLM_WIDGET_SNAPSHOT = "ailit_llm_widget_snapshot"
    SHELL_BY_ASSISTANT_SEQ = "ailit_shell_by_assistant_seq"
    SCROLL_BOTTOM = "ailit_scroll_to_bottom"
    SEND_REQUEST = "ailit_chat_send_request"
    CLEAR_INPUT = "ailit_chat_clear_input"
    PERM_MODE_GATE = "ailit_perm_mode_gate"


def _parse_tool_output(text: str) -> tuple[str, str]:
    """Вернуть (stdout, stderr) из формата run_shell."""
    lines = (text or "").splitlines()
    so: list[str] = []
    se: list[str] = []
    mode: str | None = None
    saw_sections = False
    for ln in lines:
        if ln.strip() == "--- stdout ---":
            mode = "stdout"
            saw_sections = True
            continue
        if ln.strip() == "--- stderr ---":
            mode = "stderr"
            saw_sections = True
            continue
        if mode == "stdout":
            if ln.strip() != "(empty)":
                so.append(ln)
            continue
        if mode == "stderr":
            if ln.strip() != "(empty)":
                se.append(ln)
            continue
    if not saw_sections:
        return ((text or "").rstrip(), "")
    return ("\n".join(so).rstrip(), "\n".join(se).rstrip())


def _strip_shell_ui_noise(text: str) -> str:
    """Убрать служебные строки, не несущие пользы в UI."""
    if not text:
        return ""
    out: list[str] = []
    for ln in str(text).splitlines():
        s = ln.strip()
        if s.startswith("Agent pid ") and s[10:].strip().isdigit():
            continue
        out.append(ln)
    return "\n".join(out).rstrip()


def _render_shell_runs_inline(
    runs: list[dict[str, Any]],
    *,
    n_tail: int,
    pending: bool,
    worker: ChatStopWorker | None,
) -> None:
    """Рендерить shell активность прямо в чате (под ответом)."""
    for row in runs:
        cid = str(row.get("call_id", "") or "")
        cmd = str(row.get("command", "") or "")
        stt = str(row.get("status", "") or "")
        out_txt = str(row.get("combined_output", "") or "")
        err = row.get("error")
        stdout_txt, stderr_txt = _parse_tool_output(out_txt)
        stdout_txt = _strip_shell_ui_noise(stdout_txt)
        stderr_txt = _strip_shell_ui_noise(stderr_txt)
        out_lines = stdout_txt.splitlines() if stdout_txt else []
        more_than_tail = len(out_lines) > int(n_tail)

        cols = st.columns([1, 10])
        with cols[0]:
            can_stop = (
                pending
                and worker is not None
                and stt == "running"
                and bool(cid)
            )
            if can_stop and st.button("■", key=f"bash_stop_{cid}"):
                worker.request_cancel()
        with cols[1]:
            if cmd.strip():
                st.code(cmd.strip(), language="bash")
            if stdout_txt.strip():
                st.code(
                    LineTailSelector.last_lines(stdout_txt, int(n_tail)),
                    language="bash",
                )
            if stderr_txt.strip():
                st.code(stderr_txt, language="bash")
            if err:
                st.caption(f"error: `{str(err)[:200]}`")
            if more_than_tail:
                with st.expander("Лог", expanded=False):
                    st.code(stdout_txt, language="bash")
                    if stderr_txt.strip():
                        st.code(stderr_txt, language="bash")


def _render_chat_end_anchor() -> None:
    """Невидимый якорь внизу потока чата (для скролла к актуальным сообщениям)."""
    st.markdown(
        '<div id="ailit-chat-end" style="height:1px"></div>',
        unsafe_allow_html=True,
    )


def _scroll_streamlit_main_to_bottom() -> None:
    """Прокрутить основной скролл приложения к низу (новые сообщения у нижнего края)."""
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const selectors = [
            '[data-testid="stAppViewContainer"] [data-testid="stMain"]',
            '[data-testid="stAppViewContainer"] .main .block-container',
        ];
        for (const sel of selectors) {
            const el = doc.querySelector(sel);
            if (el && el.scrollHeight > el.clientHeight) {
                el.scrollTop = el.scrollHeight;
                break;
            }
        }
        const end = doc.getElementById("ailit-chat-end");
        if (end) {
            end.scrollIntoView({block: "end", inline: "nearest"});
        }
        </script>
        """,
        height=0,
    )


def _pin_chat_composer_to_viewport() -> None:
    """Закрепить строку ввода у нижнего края окна безопасным CSS sticky."""
    st.markdown(
        """
<style>
.st-key-ailit_chat_composer_container {
  position: sticky;
  bottom: 0;
  z-index: 20;
  background: var(--background-color, white);
  border-top: 1px solid rgba(128, 128, 128, 0.25);
  padding-top: 0.35rem;
  padding-bottom: 0.5rem;
}
.st-key-ailit_chat_composer_container > div {
  background: inherit;
}
[data-testid="stMain"] .block-container {
  padding-bottom: 7rem;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _render_chat_composer_row(
    *,
    pending: bool,
    worker: ChatStopWorker | None,
    on_request_send: Callable[[], None] | None,
) -> tuple[str, bool]:
    """Одна строка: поле ввода + кнопка отправки или стоп. Возвращает (prompt, send_clicked)."""
    with st.container(key="ailit_chat_composer_container"):
        if pending and worker is not None:
            cols = st.columns([30, 1])
            with cols[0]:
                st.text_input(
                    "Сообщение…",
                    value="",
                    disabled=True,
                    key="ailit_chat_input_pending_bottom",
                )
            with cols[1]:
                stop = st.button(
                    "■",
                    key="ailit_chat_stop_btn",
                    use_container_width=True,
                )
                if stop:
                    worker.request_cancel()
            if worker.state.stop_requested and not worker.state.finished:
                st.caption("Останавливаю…")
            return ("", False)

        cols = st.columns([30, 1])
        with cols[0]:
            if bool(st.session_state.get(_ChatPageState.CLEAR_INPUT, False)):
                st.session_state["ailit_chat_input"] = ""
                st.session_state[_ChatPageState.CLEAR_INPUT] = False
            if on_request_send is None:
                msg = "on_request_send is required when pending is False"
                raise ValueError(msg)
            prompt = st.text_input(
                "Сообщение…",
                value="",
                key="ailit_chat_input",
                on_change=on_request_send,
            )
        with cols[1]:
            send_btn = st.button(
                "➤",
                key="ailit_chat_send_btn",
                use_container_width=True,
            )
        send_enter = bool(st.session_state.pop(_ChatPageState.SEND_REQUEST, False))
        send = bool(send_btn or send_enter)
        return (str(prompt), send)


def _init_messages() -> None:
    if _ChatPageState.MESSAGES not in st.session_state:
        st.session_state[_ChatPageState.MESSAGES] = [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=merge_with_base_system(
                    "You are a helpful concise assistant.",
                ),
            ),
        ]


def _render_header_and_menu(
    *,
    project_root: Path,
    loaded: LoadedProject | None,
    load_error: str | None,
) -> tuple[str, int, str, bool, str, bool]:
    """Настройки в popover (бургер), без левой панели."""
    col_l, col_mid, col_r = st.columns([1, 6, 1])
    with col_mid:
        st.markdown("### ailit chat")
    with col_r:
        with st.popover("☰", use_container_width=True):
            cfg_for_defaults = _load_merged_chat_cfg(project_root)
            defaults = DefaultProviderModelResolver().from_mapping(cfg_for_defaults)
            providers = ("deepseek", "kimi", "mock")
            idx = (
                providers.index(defaults.provider)
                if defaults.provider in providers
                else 0
            )
            choice = st.selectbox(
                "Провайдер",
                providers,
                index=idx,
                label_visibility="visible",
            )
            _mt_help = (
                "Сколько раз агент может повторить цикл "
                "«модель → инструменты → снова модель». "
                "Это не лимит длины ответа API (max_tokens у провайдера — "
                "отдельно в конфиге). При исчерпании лимита ядро делает "
                "дополнительный text-only вызов модели с кратким резюме. "
                "Переменная **AILIT_AGENT_HARD_CAP** задаёт верхнюю границу "
                "независимо от слайдера."
            )
            max_turns = st.slider(
                "Лимит итераций сессии (max_turns)",
                1,
                20_000,
                10_000,
                help=_mt_help,
            )
            te_order = ("full", "read_only", "filesystem")
            te_labels = {
                "full": "full — все tools",
                "read_only": "read_only — без write/shell",
                "filesystem": "filesystem — только обзор/чтение файлов",
            }
            te_def = _default_tool_exposure(cfg_for_defaults)
            te_idx = te_order.index(te_def) if te_def in te_order else 0
            tool_exposure = st.selectbox(
                "Tool exposure (M3)",
                options=te_order,
                index=te_idx,
                format_func=lambda k: te_labels.get(str(k), str(k)),
                help=(
                    "Снижает размер схемы tool-calling. "
                    "Переменная окружения `AILIT_TOOL_EXPOSURE` задаёт значение "
                    "по умолчанию; здесь можно переопределить для UI-сессии."
                ),
            )
            st.caption("tools включены по умолчанию")
            use_project = st.toggle("Проект", value=True)
            use_runtime = st.toggle(
                "Runtime supervisor (G8)",
                value=True,
                help=(
                    "Если включено, UI не запускает агент loop напрямую: "
                    "prompt уходит в runtime broker через supervisor, "
                    "а наблюдение идёт через Trace."
                ),
            )
            st.text_input(
                "runtime_dir (опционально)",
                key="ailit_runtime_dir",
                value=str(st.session_state.get("ailit_runtime_dir", "") or ""),
                help="По умолчанию: XDG_RUNTIME_DIR/ailit",
            )
            agent_id = st.text_input(
                "agent_id",
                value="default",
                label_visibility="visible",
            )
            teammate_tools = bool(use_project and loaded is not None)
            if loaded is None:
                st.caption("Команда: нужен project.yaml")
            tab_p, tab_team, tab_shell, tab_trace, tab_c, tab_w, tab_a, tab_d, tab_cmd = st.tabs(
                [
                    "Проект",
                    "Команда",
                    "Shell",
                    "Trace",
                    "Контекст",
                    "Workflow",
                    "Adapter",
                    "Debug",
                    "CLI",
                ],
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
            with tab_shell:
                st.caption("История `run_shell` (последние N строк вывода)")
                runs = runs_list(st.session_state)
                if not runs:
                    st.caption("Пока нет завершённых shell-вызовов в этой сессии.")
                else:
                    n_tail = st.number_input(
                        "N строк в превью",
                        min_value=1,
                        max_value=5000,
                        value=view_tail_lines(st.session_state),
                        key="ailit_bash_tail_n",
                    )
                    set_view_tail_lines(st.session_state, int(n_tail))
                    rev = list(reversed(runs))
                    labels = [
                        f"{str(r.get('call_id', ''))[:10]}… "
                        f"{str(r.get('command', ''))[:36]}"
                        for r in rev
                    ]
                    pick = st.selectbox(
                        "Вызов",
                        options=list(range(len(rev))),
                        format_func=lambda i: labels[i],
                        key="ailit_bash_pick_idx",
                    )
                    row = rev[int(pick)]
                    out_txt = str(row.get("combined_output", ""))
                    out_txt = _strip_shell_ui_noise(out_txt)
                    st.code(
                        LineTailSelector.last_lines(out_txt, int(n_tail)),
                        language="bash",
                    )
                    if row.get("detached_recommended"):
                        st.caption(
                            "Помечен как длинный вывод (эвристика detached view).",
                        )
                st.divider()
                st.caption("Превью в чате")
                n_chat = st.number_input(
                    "N строк в превью (по умолчанию 5)",
                    min_value=1,
                    max_value=200,
                    value=chat_tail_lines(st.session_state),
                    key="ailit_bash_chat_tail_n",
                )
                set_chat_tail_lines(st.session_state, int(n_chat))
            with tab_trace:
                st.caption("Runtime trace (G8.6): durable JSONL + tail/диагностика.")
                chat_id = _ensure_runtime_chat_id()
                rd = _runtime_dir_from_ui()
                st.code(f"chat_id={chat_id}\nruntime_dir={rd}", language="text")
                sup_sock = _supervisor_sock(rd)
                if not sup_sock.exists():
                    st.error(
                        "Supervisor недоступен (нет supervisor.sock). "
                        "Проверьте: `systemctl --user status ailit.service` "
                        "или запустите `ailit runtime supervisor`."
                    )
                else:
                    st.success("Supervisor socket найден.")
                    if st.button(
                        "Создать/получить broker для этого chat",
                        key="ailit_rt_get_broker",
                    ):
                        ns = "repo"
                        proj = str(
                            Path(
                                st.session_state.get(
                                    "ailit_project_root",
                                    project_root,
                                )
                            )
                            .expanduser()
                            .resolve()
                        )
                        resp = supervisor_request(
                            socket_path=sup_sock,
                            request={
                                "cmd": "create_or_get_broker",
                                "chat_id": chat_id,
                                "namespace": ns,
                                "project_root": proj,
                            },
                        )
                        st.session_state["ailit_rt_last_broker_resp"] = resp
                    last = st.session_state.get("ailit_rt_last_broker_resp")
                    if isinstance(last, dict):
                        st.json(last)

                st.divider()
                st.caption("Trace-файл broker-а (best-effort tail).")
                n_tail = int(
                    st.number_input(
                        "N строк",
                        min_value=10,
                        max_value=5000,
                        value=200,
                        key="ailit_rt_trace_tail_n",
                    )
                )
                safe = "".join(
                    c for c in chat_id if c.isalnum() or c in ("-", "_")
                )
                trace_path = rd / "trace" / f"trace-{safe}.jsonl"
                st.code(str(trace_path), language="text")
                if trace_path.exists():
                    try:
                        lines = trace_path.read_text(
                            encoding="utf-8", errors="replace"
                        ).splitlines()
                    except Exception as e:  # noqa: BLE001
                        st.error(str(e))
                        lines = []
                    tail = lines[-n_tail:] if n_tail > 0 else lines
                    st.text("\n".join(tail))
                else:
                    st.info("Trace файл пока не создан.")
            with tab_team:
                st.caption("Файловый mailbox: `.ailit/teams/<team_id>/inboxes/<agent>.json`")
                root = Path(st.session_state.get("ailit_project_root", project_root))
                if loaded is None:
                    st.info("Нужен загруженный project.yaml и корень проекта.")
                else:
                    st.text_input("team_id", key="ailit_team_panel_id", value="default")
                    st.text_input(
                        "Фильтр: только inbox получателя (пусто = все)",
                        key="ailit_team_filter_to",
                    )
                    if st.button("Обновить панель команды", key="ailit_team_refresh"):
                        st.session_state["ailit_team_digest_tick"] = (
                            int(st.session_state.get("ailit_team_digest_tick", 0)) + 1
                        )
                    tid = (
                        str(st.session_state.get("ailit_team_panel_id", "default")).strip()
                        or "default"
                    )
                    flt_raw = str(st.session_state.get("ailit_team_filter_to", "")).strip()
                    flt = flt_raw or None
                    pres = TeamMailboxPanelPresenter(project_root=root, team_id=tid)
                    st.markdown(pres.markdown_digest(filter_to=flt))
                    inbox_dir = root / ".ailit" / "teams" / tid / "inboxes"
                    with st.expander("Сырой JSON (пути inbox)", expanded=False):
                        if inbox_dir.is_dir():
                            st.json(
                                {
                                    "inbox_dir": str(inbox_dir),
                                    "files": sorted(
                                        str(p.name) for p in inbox_dir.glob("*.json")
                                    ),
                                },
                            )
                        else:
                            st.json({"inbox_dir": str(inbox_dir), "files": []})
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
                st.number_input(
                    "max_turns (workflow)",
                    min_value=1,
                    max_value=50_000,
                    key="ailit_wf_max_turns",
                )
                st.checkbox("dry_run", key="ailit_wf_dry_run")
                if st.button("Запустить workflow", key="ailit_wf_run"):
                    try:
                        ref = str(st.session_state.get("ailit_wf_ref", "minimal")).strip()
                        wf_model = str(st.session_state.get("ailit_wf_model", "deepseek-chat")).strip()
                        wf_mt = int(st.session_state.get("ailit_wf_max_turns", 10_000))
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
    return (
        choice,
        max_turns,
        agent_id,
        use_project,
        str(tool_exposure),
        bool(use_runtime),
    )


def _render_usage_tokens_panel() -> None:
    """Панель токенов после последнего прогона (O.2)."""
    raw = st.session_state.get("ailit_last_usage_pair")
    if not isinstance(raw, tuple) or len(raw) != 2:
        return
    lu_raw, st_raw = raw
    if not isinstance(lu_raw, dict) or not isinstance(st_raw, dict):
        return
    fmt = UsageSummaryMarkdownFormatter()
    st.caption("**Токены** (последний вызов и накопление за сессию)")
    st.caption(fmt.compact_last_call_line(lu_raw))
    st.caption(fmt.compact_session_line(st_raw))
    with st.expander("Токены: подробности (JSON)", expanded=False):
        st.markdown(
            fmt.expander_markdown(last_usage=lu_raw, session_totals=st_raw),
        )


def _render_token_economy_panel() -> None:
    """Накопленные события token-economy (pager / budget / prune) в сессии UI."""
    c = st.session_state.get("ailit_token_econ_cumulative")
    if not isinstance(c, dict):
        return
    cap = format_cumulative_caption(c)
    st.caption("**Экономия** (оценка по `bytes/chars/4` по накопленным событиям)")
    if not cap:
        st.caption(
            "Пока нет событий `context.pager` / `tool.output_budget` / "
            "`tool.output_prune` / `compaction.restore` / `tool.exposure` "
            "(выполните ход с tool-вызовами).",
        )
    else:
        st.caption(cap)
    with st.expander("Экономия: JSON (сессия браузера)", expanded=False):
        st.json(c)
    ph = st.session_state.get("ailit_chat_log_path")
    if isinstance(ph, str) and ph:
        st.caption(f"Process log: `{ph}` — `ailit session usage show` для файла")


def _render_memory_stack_panel() -> None:
    """Память M3/M4: KB, auto-write, perm-5, диагноз при нуле memory.access."""
    c_live_raw = st.session_state.get("ailit_token_econ_cumulative")
    c_live: dict[str, Any] = c_live_raw if isinstance(c_live_raw, dict) else {}
    ph = st.session_state.get("ailit_chat_log_path")
    rows: list[dict[str, Any]] = []
    if isinstance(ph, str) and ph.strip():
        p = Path(ph)
        if p.is_file():
            try:
                rows = read_jsonl_session_log(p)
            except OSError:
                rows = []
    c_file: dict[str, Any] = {}
    if rows:
        ar = analyze_log_rows(rows)
        c_raw = ar.get("cumulative")
        if isinstance(c_raw, dict):
            c_file = c_raw
    c_m = merge_cumulative_for_display(c_live, c_file)
    r = compute_resume_signals(rows)
    stats = build_memory_stats(c_m, r)
    eff = build_memory_efficiency_score(c_m, r)
    mem_pol = None
    mem_fb = None
    mem_match = None
    sm2: dict[str, Any] = {}
    mfr: dict[str, Any] | None = None
    if rows:
        try:
            sm2 = build_session_summary(rows)
        except Exception:  # noqa: BLE001
            sm2 = {}
        mem_pol = sm2.get("memory_policy")
        mem_fb = sm2.get("memory_retrieval_fallback")
        mem_match = sm2.get("memory_retrieval_match")
        mfr_raw = sm2.get("memory_full_report")
        mfr = mfr_raw if isinstance(mfr_raw, dict) else None
    diag = build_memory_diagnosis(
        cumulative=c_m,
        resume=r,
        memory_policy=mem_pol if isinstance(mem_pol, dict) else None,
    )
    sc = int(eff.get("score_0_100", 0) or 0)
    label = str(eff.get("label", "") or "")
    st.caption(
        f"**Память (M3/M4):** оценка **{sc}/100** — {label}",
    )
    st.caption(
        "Оценка **не** про «правильность ответа», а про **дисциплину** сигналов: "
        "доля range-read к `read_file`, обращения к `kb_*`, promotion, "
        "pager / tool.exposure и resume; сравнивайте прогоны по компонентам ниже.",
    )
    comp = eff.get("components")
    if isinstance(comp, dict) and comp:
        with st.expander("Память: из чего сложилось N/100 (компоненты)", expanded=False):
            st.json(comp)
    acc_n = int(c_m.get("memory_access_total", 0) or 0)
    fs_n = int(c_m.get("fs_read_file_calls", 0) or 0)
    p_used = int(c_m.get("pager_page_used", 0) or 0)
    if fs_n or p_used:
        st.caption(
            f"Слой чтения: `read_file`≈{fs_n} · context pager={p_used} — это **не** "
            "вызовы KB; события KB только у инструментов `kb_*`.",
        )
    if isinstance(sm2, dict):
        sub = sm2.get("subsystems")
        if isinstance(sub, dict):
            pmx = sub.get("perm_mode")
            if isinstance(pmx, dict):
                ltm = str(pmx.get("last_tool_mode") or "").strip()
                if ltm or int(pmx.get("enforced_n", 0) or 0) > 0:
                    st.caption(
                        "Режим инструментов (perm-5): "
                        f"last_mode=`{ltm or '—'}` · "
                        f"classified={int(pmx.get('classified_n', 0) or 0)} · "
                        f"user_choice={int(pmx.get('user_choice_n', 0) or 0)}",
                    )
    if isinstance(mfr, dict):
        aw = mfr.get("auto_write")
        if isinstance(aw, dict):
            done_by = aw.get("done_by_kind")
            if isinstance(done_by, dict) and done_by:
                st.caption(
                    "Автозапись в KB (по видам): "
                    + " · ".join(
                        f"{k}={int(v)}" for k, v in done_by.items()
                    ),
                )
        lg = mfr.get("loop_guards")
        if isinstance(lg, dict) and int(lg.get("doom_loop_total", 0) or 0) > 0:
            st.caption(
                f"Loop-guard: doom_loop={int(lg.get('doom_loop_total', 0) or 0)}",
            )
    kb_info_shown = False
    if acc_n == 0:
        hint_lines: list[str] = []
        dsrc = mfr.get("diagnosis") if isinstance(mfr, dict) else None
        if isinstance(dsrc, dict):
            h = dsrc.get("hints")
            if isinstance(h, list) and h:
                hint_lines = [str(x) for x in h if str(x).strip()]
        if not hint_lines and isinstance(diag, dict):
            h2 = diag.get("hints")
            if isinstance(h2, list) and h2:
                hint_lines = [str(x) for x in h2 if str(x).strip()]
        if hint_lines:
            st.info(
                "Нет событий **memory.access** (обращения к `kb_*`). "
                + " ".join(hint_lines),
            )
            kb_info_shown = True
    if isinstance(mem_pol, dict):
        repo = mem_pol.get("repo")
        if isinstance(repo, dict):
            br = repo.get("branch")
            dbr = repo.get("default_branch")
            src = repo.get("default_branch_source")
            st.caption(
                f"Repo context: branch=`{br}` · default=`{dbr}` ({src})",
            )
    fb_total = int(c_m.get("memory_retrieval_fallback_total", 0) or 0)
    if fb_total > 0 and isinstance(mem_fb, dict):
        st.caption(
            f"Fallback на default branch: {fb_total} (последний: "
            f"`{mem_fb.get('from_namespace')}` → `{mem_fb.get('to_namespace')}`)",
        )
    if isinstance(mem_match, dict):
        st.caption(
            f"Match: `{mem_match.get('level')}` · id=`{mem_match.get('id')}`",
        )
    aw_ok = int(c_m.get("memory_auto_write_done_total", 0) or 0)
    aw_sk = int(c_m.get("memory_auto_write_skipped", 0) or 0)
    if aw_ok or aw_sk:
        st.caption(
            f"Auto-write: ok={aw_ok} · skipped={aw_sk}",
        )
    rl = int(c_m.get("memory_auto_kb_rate_limited_total", 0) or 0)
    if rl:
        st.caption(f"Rate-limited: {rl} (auto‑KB)")
    by = stats.get("access_by_tool")
    if isinstance(by, dict) and by:
        line = " · ".join(
            f"`{k}`: {v}" for k, v in by.items()
        )
        st.caption(f"KB по инструментам: {line}")
    elif acc_n == 0 and not kb_info_shown:
        st.caption(
            "Пока нет событий `memory.access` (инструменты KB не вызывались).",
        )
    with st.expander("Память: детали (эвристика + merge)", expanded=False):
        st.json(
            {
                "tooling": stats,
                "efficiency": eff,
                "diagnosis": diag,
                "memory_full_report": mfr,
                "policy": mem_pol,
                "retrieval_fallback": mem_fb,
                "retrieval_match": mem_match,
                "cumulative_merged": c_m,
            },
        )
        st.caption(
            "Слитые счётчики: live (браузер) и JSONL-лог; по числу — max, "
            "по `tool` в KB — max по каждому ключу.",
        )


def _render_unified_session_summary_panel() -> None:
    """E2E-M3-02: тот же отчёт, что `ailit session usage summary` (one source)."""
    ph = st.session_state.get("ailit_chat_log_path")
    if not isinstance(ph, str) or not ph.strip():
        return
    p = Path(ph)
    if not p.is_file():
        return
    try:
        rows = read_jsonl_session_log(p)
        sm = build_session_summary(rows)
    except OSError:
        return
    res = sm.get("resume") or {}
    rr = bool(res.get("resume_ready"))
    notes = res.get("notes")
    if isinstance(notes, list) and notes:
        note_s = "; ".join(str(x) for x in notes)
    else:
        note_s = "—"
    st.caption(
        f"**Сводка лога (unified):** contract={sm.get('contract', '')!s} · "
        f"resume_ready={rr} · {note_s}",
    )
    with st.expander("Сводка сессии: JSON (как `session usage summary --json`)", expanded=False):
        st.json(sm)
        st.code(
            f"ailit session usage summary {p}",
            language="bash",
        )


def _render_dialogue_messages(
    messages: list[ChatMessage],
    *,
    shell_by_assistant_seq: dict[int, list[dict[str, Any]]],
    n_tail: int,
) -> None:
    """Отрисовать диалог + shell активность под ответами."""
    projector = ChatTranscriptProjector()
    aseq = -1
    for line in projector.project(messages):
        with st.chat_message(line.role.value):
            st.markdown(line.markdown)
            if line.role is MessageRole.ASSISTANT:
                aseq += 1
                runs = shell_by_assistant_seq.get(aseq) or []
                if runs:
                    _render_shell_runs_inline(
                        runs,
                        n_tail=n_tail,
                        pending=False,
                        worker=None,
                    )


def _execute_llm_turn(
    *,
    cfg: dict,
    snap: dict[str, object],
) -> None:
    """Второй проход: SessionRunner (настройки из снимка отправки)."""
    choice = str(snap["choice"])
    max_turns = int(snap["max_turns"])
    use_project = bool(snap["use_project"])
    teammate_tools = bool(snap.get("teammate_tools", False))
    tool_exposure = str(snap.get("tool_exposure") or "full").strip().lower()
    agent_id = str(snap["agent_id"])
    project_root = Path(str(snap["project_root"]))
    os.environ["AILIT_CHAT_AGENT_ID"] = agent_id.strip() or "default"

    fac_local = ProjectSessionFactory(project_root)
    plr = fac_local.load()
    loaded_local = plr.loaded
    if use_project and loaded_local is not None:
        BashProjectEnvSync.apply(loaded_local.config.bash)
        BashSessionProjectEnvSync.apply(loaded_local.config.bash_session)
    else:
        BashProjectEnvSync.clear()
        BashSessionProjectEnvSync.clear()
    base_system = merge_with_base_system("You are a helpful concise assistant.")
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

    inject_tool_hints_before_first_user(
        runner_msgs,
        include_kb_first=memory_kb_first_enabled(cfg),
    )

    provider, model = _make_provider(choice, cfg)
    pm_en = perm_mode_enabled_from_env()
    perm_mode_str = str(snap.get("perm_tool_mode") or "explore").strip().lower()
    perm_bypass = bool(snap.get("perm_classifier_bypass", False))
    status_ph = st.session_state.get("ailit_stream_status_ph")
    delta_ph = st.session_state.get("ailit_stream_delta_ph")
    live_text: list[str] = []
    file_change_log: list[str] = []

    def on_event(ev: object) -> None:
        try:
            et = getattr(ev, "type", "")
            payload = getattr(ev, "payload", {})
        except Exception:
            return
        if not isinstance(et, str):
            return
        if et == "model.request":
            if status_ph is not None:
                status_ph.markdown("_Запрос к модели…_")
            return
        if et == "assistant.delta":
            if not isinstance(payload, dict):
                return
            d = payload.get("text")
            if not isinstance(d, str) or not d:
                return
            live_text.append(d)
            if delta_ph is not None:
                joined = "".join(live_text)
                shown = format_assistant_body_for_ui(
                    joined,
                    aggressive_tail=True,
                )
                delta_ph.markdown(shown)
            return
        if et == "tool.call_started":
            if isinstance(payload, dict):
                t = payload.get("tool")
                cid = payload.get("call_id")
                args_json = payload.get("arguments_json")
                if status_ph is not None and isinstance(t, str):
                    status_ph.markdown(f"_Шаг:_ **{t}** …")
                if (
                    isinstance(t, str)
                    and t in ("run_shell", "run_shell_session", "shell_reset")
                    and isinstance(cid, str)
                    and isinstance(args_json, str)
                ):
                    cmd = ""
                    try:
                        import json as _json

                        raw = _json.loads(args_json)
                        if isinstance(raw, dict):
                            cmd = str(raw.get("command", "") or "").strip()
                    except Exception:
                        cmd = ""
                    upsert_running_call(
                        st.session_state,
                        call_id=cid,
                        command=cmd,
                        tool_name=t,
                    )
            return
        if et == "tool.call_finished":
            if isinstance(payload, dict):
                t = payload.get("tool")
                ok = payload.get("ok")
                cid = payload.get("call_id")
                if status_ph is not None and isinstance(t, str):
                    mark = "✓" if ok is True else "✗"
                    extra = ""
                    rp = payload.get("relative_path")
                    fk = payload.get("file_change_kind")
                    if (
                        ok is True
                        and t in ("write_file", "apply_patch")
                        and isinstance(rp, str)
                        and fk in ("created", "updated")
                    ):
                        sym = "+" if fk == "created" else "~"
                        extra = f" `{sym} {rp}`"
                    status_ph.markdown(f"_Шаг:_ **{t}** — {mark}{extra}")
                if (
                    isinstance(t, str)
                    and t in ("run_shell", "run_shell_session", "shell_reset")
                    and isinstance(cid, str)
                ):
                    mark_finished(
                        st.session_state,
                        call_id=cid,
                        ok=bool(ok is True),
                        error=str(payload.get("error")) if payload.get("error") else None,
                    )
                if (
                    isinstance(t, str)
                    and t in ("write_file", "apply_patch")
                    and ok is True
                    and isinstance(payload.get("relative_path"), str)
                    and payload.get("file_change_kind") in ("created", "updated")
                ):
                    rp2 = str(payload.get("relative_path"))
                    fk2 = str(payload.get("file_change_kind"))
                    sym2 = "+" if fk2 == "created" else "~"
                    file_change_log.append(f"{sym2} `{rp2}` ({fk2})")
            return
        if et == "bash.execution":
            if isinstance(payload, dict):
                append_execution(st.session_state, payload)
            return
        if et == "bash.output_delta":
            if isinstance(payload, dict):
                cid = payload.get("call_id")
                ch = payload.get("chunk")
                if isinstance(cid, str) and isinstance(ch, str):
                    append_output_delta(
                        st.session_state,
                        call_id=cid,
                        chunk=ch,
                    )
            return
        if et == "bash.finished":
            if isinstance(payload, dict):
                cid = payload.get("call_id")
                ok = payload.get("ok")
                err = payload.get("error")
                if isinstance(cid, str):
                    mark_finished(
                        st.session_state,
                        call_id=cid,
                        ok=bool(ok is True),
                        error=str(err) if err else None,
                    )
            return

    settings = SessionSettings(
        model=model,
        max_turns=tuning.max_turns if tuning and tuning.max_turns is not None else max_turns,
        temperature=tuning.temperature if tuning and tuning.temperature is not None else 0.3,
        shortlist_keywords=tuning.shortlist_keywords if tuning else None,
        tool_exposure=tool_exposure,
        use_stream=True,
        perm_mode_enabled=pm_en,
        perm_tool_mode=perm_mode_str,
        perm_classifier_bypass=perm_bypass,
        perm_history_max=8,
    )
    work_for_tools = project_root if use_project else _REPO
    perm = PermissionEngine(
        write_default=PermissionDecision.ALLOW,
        shell_default=PermissionDecision.ALLOW,
    )
    runner = SessionRunner(
        provider,
        _registry_for_chat(
            cfg=cfg,
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
        event_sink=on_event,
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
        if out.reason == MAX_TURNS_EXCEEDED_REASON:
            st.session_state["ailit_limit_turns_banner"] = (
                "Сессия завершилась с устаревшим кодом ошибки по лимиту шагов. "
                "В актуальном ядре ожидается text-only резюме; проверьте "
                "версию `agent_core` и JSONL-лог."
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

    pair = SessionEventsUsageExtractor.last_pair(out.events)
    if pair is not None:
        st.session_state["ailit_last_usage_pair"] = pair
    else:
        st.session_state.pop("ailit_last_usage_pair", None)
    _acc0 = st.session_state.get("ailit_token_econ_cumulative")
    if not isinstance(_acc0, dict):
        _acc0 = empty_cumulative()
    st.session_state["ailit_token_econ_cumulative"] = merge_events_into_cumulative(
        _acc0,
        out.events,
    )
    st.session_state["ailit_chat_log_path"] = log_path

    hz = OutcomeReasonHumanizer()
    hint = hz.humanize(out.reason)
    cap_parts: list[str] = [f"state={out.state.value}"]
    cap_parts.append(f"сессия: {progress.short_label_ru()}")
    if hint:
        cap_parts.append(hint)
    elif out.reason:
        cap_parts.append(f"reason={out.reason!r}")
    cap_parts.append(f"log=`{log_path}`")
    if file_change_log:
        cap_parts.append("файлы: " + " · ".join(file_change_log))
    st.caption(" | ".join(cap_parts))
    if file_change_log:
        with st.expander("Изменения файлов (ход)", expanded=False):
            st.markdown("\n".join(f"- {row}" for row in file_change_log))


def _build_chat_turn_worker(
    *,
    cfg: dict,
    snap: dict[str, object],
) -> tuple[ChatStopWorker, str, int, bool, object | None, object | None]:
    """Подготовить worker для фонового прогона (нужно для кнопки Stop)."""
    choice = str(snap["choice"])
    max_turns = int(snap["max_turns"])
    use_project = bool(snap["use_project"])
    teammate_tools = bool(snap.get("teammate_tools", False))
    tool_exposure = str(snap.get("tool_exposure") or "full").strip().lower()
    agent_id = str(snap["agent_id"])
    project_root = Path(str(snap["project_root"]))
    os.environ["AILIT_CHAT_AGENT_ID"] = agent_id.strip() or "default"

    fac_local = ProjectSessionFactory(project_root)
    plr = fac_local.load()
    loaded_local = plr.loaded
    if use_project and loaded_local is not None:
        BashProjectEnvSync.apply(loaded_local.config.bash)
    else:
        BashProjectEnvSync.clear()

    base_system = merge_with_base_system("You are a helpful concise assistant.")
    msgs_src = st.session_state[_ChatPageState.MESSAGES]
    tuning = None
    prefix_len = 0
    if use_project and loaded_local is not None:
        ctx_snap = st.session_state.get(_ChatPageState.SNAPSHOT_CACHE)
        tuning = fac_local.tuning_for_chat(
            loaded_local,
            agent_id.strip() or "default",
            ctx_snap,
        )
        suffix = strip_system_messages(list(msgs_src))
        runner_msgs = attach_runner_suffix(base_system, tuning, suffix)
        prefix_len = len(runner_msgs) - len(suffix)
    else:
        runner_msgs = list(msgs_src)

    inject_tool_hints_before_first_user(
        runner_msgs,
        include_kb_first=memory_kb_first_enabled(cfg),
    )
    provider, model = _make_provider(choice, cfg)

    pm_en = perm_mode_enabled_from_env()
    perm_mode_str = str(snap.get("perm_tool_mode") or "explore").strip().lower()
    perm_bypass = bool(snap.get("perm_classifier_bypass", False))
    settings = SessionSettings(
        model=model,
        max_turns=tuning.max_turns if tuning and tuning.max_turns is not None else max_turns,
        temperature=tuning.temperature if tuning and tuning.temperature is not None else 0.3,
        shortlist_keywords=tuning.shortlist_keywords if tuning else None,
        tool_exposure=tool_exposure,
        use_stream=True,
        perm_mode_enabled=pm_en,
        perm_tool_mode=perm_mode_str,
        perm_classifier_bypass=perm_bypass,
        perm_history_max=8,
    )
    work_for_tools = project_root if use_project else _REPO
    perm = PermissionEngine(
        write_default=PermissionDecision.ALLOW,
        shell_default=PermissionDecision.ALLOW,
    )
    runner = SessionRunner(
        provider,
        _registry_for_chat(
            cfg=cfg,
            work_root=work_for_tools,
            teammate_tools=teammate_tools,
        ),
        permission_engine=perm,
    )
    log_handle = ensure_process_log("chat")
    worker = ChatStopWorker(
        runner=runner,
        runner_messages=runner_msgs,
        settings=settings,
        diag_sink=log_handle.sink,
    )
    return worker, base_system, prefix_len, use_project, loaded_local, tuning


def main() -> None:
    """Точка входа Streamlit."""
    _chat_log_handle = ensure_process_log("chat")
    # Путь к JSONL существует с первой загрузки страницы; раньше key ставился
    # только после завершения хода — из-за этого «вторая сессия» в новой вкладке
    # не показывала ссылку на process log, хотя process.start уже записан.
    st.session_state.setdefault(
        "ailit_chat_log_path",
        str(_chat_log_handle.path),
    )
    st.set_page_config(page_title="ailit chat", layout="wide", initial_sidebar_state="collapsed")
    _init_messages()
    _banner = st.session_state.pop("ailit_limit_turns_banner", None)
    if isinstance(_banner, str) and _banner.strip():
        st.warning(_banner)
    st.session_state.setdefault(_ChatPageState.SHELL_BY_ASSISTANT_SEQ, {})
    st.session_state.setdefault(_ChatPageState.SCROLL_BOTTOM, False)
    st.session_state.setdefault(_ChatPageState.SEND_REQUEST, False)
    st.session_state.setdefault(_ChatPageState.CLEAR_INPUT, False)
    st.markdown("### ailit chat")
    st.session_state.setdefault("ailit_shell_session_key", uuid.uuid4().hex)
    root_default = Path.cwd().resolve()
    if "ailit_project_root" not in st.session_state:
        st.session_state["ailit_project_root"] = str(root_default)
    project_root = Path(str(st.session_state.get("ailit_project_root", root_default)))
    cfg = _load_merged_chat_cfg(project_root)
    os.environ["AILIT_SHELL_SESSION_KEY"] = str(
        st.session_state.get("ailit_shell_session_key", "default"),
    )

    st.session_state.setdefault("ailit_wf_ref", "minimal")
    st.session_state.setdefault("ailit_wf_model", "deepseek-chat")
    st.session_state.setdefault("ailit_wf_max_turns", 10_000)
    st.session_state.setdefault("ailit_wf_dry_run", True)
    st.session_state.setdefault("ailit_token_econ_cumulative", empty_cumulative())

    fac = ProjectSessionFactory(project_root)
    plr = fac.load()
    loaded = plr.loaded
    load_error = plr.error

    (
        choice,
        max_turns,
        agent_id,
        use_project,
        tool_exposure,
        use_runtime,
    ) = _render_header_and_menu(
        project_root=project_root,
        loaded=loaded,
        load_error=load_error,
    )
    teammate_tools = bool(use_project and loaded is not None)

    msgs = st.session_state[_ChatPageState.MESSAGES]
    pending = bool(st.session_state.get(_ChatPageState.PENDING_LLM, False))
    n_tail = chat_tail_lines(st.session_state)
    shell_map_raw = st.session_state.get(_ChatPageState.SHELL_BY_ASSISTANT_SEQ, {})
    shell_map: dict[int, list[dict[str, Any]]] = (
        dict(shell_map_raw) if isinstance(shell_map_raw, dict) else {}
    )

    col_l, col_mid, col_r = st.columns([1, 2, 1])
    with col_mid:
        gate_raw = st.session_state.get(_ChatPageState.PERM_MODE_GATE)
        if (
            perm_mode_enabled_from_env()
            and isinstance(gate_raw, dict)
            and isinstance(gate_raw.get("snap"), dict)
        ):
            snap0 = dict(gate_raw["snap"])
            prompt0 = str(gate_raw.get("prompt") or "")
            _render_dialogue_messages(
                msgs,
                shell_by_assistant_seq=shell_map,
                n_tail=n_tail,
            )
            st.warning(
                "Режим инструментов не определён автоматически. "
                "Выберите режим — ответ модели начнётся после выбора.",
            )
            opts = ("read", "read_plan", "explore", "edit")
            mode_pick = st.radio(
                "Режим",
                opts,
                index=2,
                horizontal=True,
                key="ailit_perm_gate_radio",
            )
            remember = st.checkbox(
                "Запомнить для проекта",
                key="ailit_perm_gate_remember",
            )
            if st.button("Продолжить", key="ailit_perm_gate_go"):
                mem_ns = memory_namespace_from_cfg(cfg)
                root_gate = Path(str(snap0.get("project_root") or project_root))
                mode_ns = build_mode_kb_namespace(
                    memory_namespace=mem_ns,
                    project_root=root_gate,
                )
                rc_gate = detect_repo_context(root_gate)
                coord = ChatPermModeCoordinator(
                    kb_namespace=mode_ns,
                    history_max=8,
                    repo_payload=rc_gate.to_event_payload(),
                )
                log = ensure_process_log("chat")
                coord.record_user_choice(
                    user_intent=prompt0,
                    mode=str(mode_pick),
                    remember_project=bool(remember),
                    diag_sink=log.sink,
                )
                snap0["perm_tool_mode"] = str(mode_pick)
                snap0["perm_classifier_bypass"] = False
                st.session_state.pop(_ChatPageState.PERM_MODE_GATE, None)
                st.session_state[_ChatPageState.LLM_WIDGET_SNAPSHOT] = snap0
                st.session_state[_ChatPageState.PENDING_LLM] = True
                st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
                st.rerun()
            return

        if pending:
            snap_raw = st.session_state.get(_ChatPageState.LLM_WIDGET_SNAPSHOT)
            if not isinstance(snap_raw, dict):
                st.session_state[_ChatPageState.PENDING_LLM] = False
                st.rerun()
                return

            _render_dialogue_messages(
                msgs,
                shell_by_assistant_seq=shell_map,
                n_tail=n_tail,
            )
            with st.chat_message("assistant"):
                worker_raw = st.session_state.get("ailit_chat_turn_worker")
                if not isinstance(worker_raw, ChatStopWorker):
                    worker_new, base_system, prefix_len, up, loaded_local, tuning = (
                        _build_chat_turn_worker(
                            cfg=cfg,
                            snap=snap_raw,
                        )
                    )
                    st.session_state["ailit_chat_turn_worker"] = worker_new
                    st.session_state["ailit_chat_turn_worker_meta"] = {
                        "base_system": base_system,
                        "prefix_len": int(prefix_len),
                        "use_project": bool(up),
                        "has_loaded": loaded_local is not None,
                        "has_tuning": tuning is not None,
                    }
                    worker_new.start()
                    worker_raw = worker_new

                worker = worker_raw

                error = worker.state.error
                bash_execs = list(worker.state.bash_executions)

                # Таймлайн: мысль → bash → мысль → ...
                tl = list(worker.state.timeline)
                for item in tl:
                    kind = str(item.get("kind") or "")
                    if kind == "thought":
                        txt = str(item.get("text") or "")
                        if txt.strip():
                            st.markdown(
                                format_assistant_body_for_ui(
                                    txt,
                                    aggressive_tail=True,
                                ),
                            )
                        continue
                    if kind == "shell":
                        row = dict(item)
                        _render_shell_runs_inline(
                            [row],
                            n_tail=n_tail,
                            pending=True,
                            worker=worker,
                        )
                        continue

                if error:
                    st.error(error)

            if not worker.state.finished:
                _render_chat_end_anchor()
                _render_chat_composer_row(
                    pending=True,
                    worker=worker,
                    on_request_send=None,
                )
                _pin_chat_composer_to_viewport()
                _scroll_streamlit_main_to_bottom()
                time.sleep(0.2)
                st.rerun()
                return

            meta = st.session_state.get("ailit_chat_turn_worker_meta", {})
            base_system = str(meta.get("base_system") or "")
            prefix_len = int(meta.get("prefix_len") or 0)
            use_project_meta = bool(meta.get("use_project") or False)
            has_loaded = bool(meta.get("has_loaded") or False)
            has_tuning = bool(meta.get("has_tuning") or False)

            outcome2 = worker.state.outcome
            if outcome2 is not None:
                runner_msgs = list(outcome2.messages)
                if worker.state.cancelled:
                    runner_msgs.append(
                        ChatMessage(
                            role=MessageRole.ASSISTANT,
                            content="Остановлено пользователем. Контекст сохранён.",
                        ),
                    )
                if use_project_meta and has_loaded and has_tuning:
                    st.session_state[_ChatPageState.MESSAGES] = store_after_run(
                        base_system,
                        prefix_len,
                        runner_msgs,
                    )
                else:
                    st.session_state[_ChatPageState.MESSAGES] = runner_msgs

                for row in bash_execs:
                    append_execution(st.session_state, row)

                a_count = sum(1 for m in runner_msgs if m.role is MessageRole.ASSISTANT)
                aseq = max(0, a_count - 1)
                live_final = list(reversed(runs_list(worker.state.shell_store)))
                if live_final:
                    shell_map2 = dict(shell_map)
                    shell_map2[int(aseq)] = list(reversed(live_final))
                    st.session_state[_ChatPageState.SHELL_BY_ASSISTANT_SEQ] = shell_map2

                progress = ChatSessionTurnProgress.from_outcome_events(
                    outcome2.events,
                    limit=int(snap_raw.get("max_turns", 10_000)),
                )
                st.session_state["ailit_last_turn_progress"] = progress

                pair = SessionEventsUsageExtractor.last_pair(outcome2.events)
                if pair is not None:
                    st.session_state["ailit_last_usage_pair"] = pair
                else:
                    st.session_state.pop("ailit_last_usage_pair", None)
                _acc1 = st.session_state.get("ailit_token_econ_cumulative")
                if not isinstance(_acc1, dict):
                    _acc1 = empty_cumulative()
                st.session_state["ailit_token_econ_cumulative"] = (
                    merge_events_into_cumulative(
                        _acc1,
                        outcome2.events,
                    )
                )
                _lh = ensure_process_log("chat")
                st.session_state["ailit_chat_log_path"] = str(_lh.path)

            st.session_state.pop("ailit_chat_turn_worker", None)
            st.session_state.pop("ailit_chat_turn_worker_meta", None)
            st.session_state[_ChatPageState.PENDING_LLM] = False
            st.session_state.pop(_ChatPageState.LLM_WIDGET_SNAPSHOT, None)
            st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
            st.rerun()
            return

        _render_dialogue_messages(
            msgs,
            shell_by_assistant_seq=shell_map,
            n_tail=n_tail,
        )
        _render_usage_tokens_panel()
        _render_token_economy_panel()
        _render_memory_stack_panel()
        _render_unified_session_summary_panel()

        def _request_send() -> None:
            st.session_state[_ChatPageState.SEND_REQUEST] = True

        _render_chat_end_anchor()
        prompt, send = _render_chat_composer_row(
            pending=False,
            worker=None,
            on_request_send=_request_send,
        )
        _pin_chat_composer_to_viewport()
        if bool(st.session_state.get(_ChatPageState.SCROLL_BOTTOM, False)):
            _scroll_streamlit_main_to_bottom()
            st.session_state[_ChatPageState.SCROLL_BOTTOM] = False

        if not send or not prompt.strip():
            return
        prompt = prompt.strip()

        st.session_state[_ChatPageState.MESSAGES].append(
            ChatMessage(role=MessageRole.USER, content=prompt),
        )
        st.session_state[_ChatPageState.CLEAR_INPUT] = True

        if use_runtime:
            chat_id = _ensure_runtime_chat_id()
            rd = _runtime_dir_from_ui()
            sup_sock = _supervisor_sock(rd)
            if not sup_sock.exists():
                st.session_state[_ChatPageState.MESSAGES].append(
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=(
                            "Runtime supervisor недоступен (нет supervisor.sock). "
                            "Проверьте `systemctl --user status ailit.service` "
                            "или запустите `ailit runtime supervisor`."
                        ),
                    )
                )
                st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
                st.rerun()
                return
            ns = "repo"
            sup = supervisor_request(
                socket_path=sup_sock,
                request={
                    "cmd": "create_or_get_broker",
                    "chat_id": chat_id,
                    "namespace": ns,
                    "project_root": str(project_root.resolve()),
                },
            )
            if not isinstance(sup, dict) or sup.get("ok") is not True:
                st.session_state[_ChatPageState.MESSAGES].append(
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=f"Supervisor error: {sup!r}",
                    )
                )
                st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
                st.rerun()
                return
            res = sup.get("result") if isinstance(sup.get("result"), dict) else {}
            endpoint = str(res.get("endpoint", "") or "")
            if not endpoint.startswith("unix://"):
                st.session_state[_ChatPageState.MESSAGES].append(
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=f"Bad broker endpoint: {endpoint!r}",
                    )
                )
                st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
                st.rerun()
                return
            broker_sock = (
                Path(endpoint[len("unix://") :]).expanduser().resolve()
            )
            if not broker_sock.exists():
                st.session_state[_ChatPageState.MESSAGES].append(
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=(
                            "Broker socket ещё не готов. "
                            "Откройте вкладку Trace и повторите отправку через секунду."
                        ),
                    )
                )
                st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
                st.rerun()
                return
            out = _send_work_prompt_to_broker(
                broker_socket=broker_sock,
                chat_id=chat_id,
                namespace=ns,
                prompt=prompt,
            )
            st.session_state["ailit_rt_last_action_resp"] = out
            st.session_state[_ChatPageState.MESSAGES].append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=(
                        "Prompt отправлен в runtime (action.start). "
                        "Следите за событиями во вкладке Trace.\n\n"
                        f"Ответ: `{out}`"
                    ),
                )
            )
            st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
            st.rerun()
            return

        base_snap: dict[str, object] = {
            "choice": choice,
            "max_turns": max_turns,
            "use_project": use_project,
            "teammate_tools": teammate_tools,
            "tool_exposure": str(tool_exposure),
            "agent_id": agent_id,
            "project_root": str(project_root),
            "turn_id": uuid.uuid4().hex,
        }
        bypass = os.environ.get("AILIT_MULTI_AGENT", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        forced = os.environ.get("AILIT_PERM_TOOL_MODE", "").strip() or None
        base_snap["perm_classifier_bypass"] = bypass

        perm_tool_mode = "explore"
        if perm_mode_enabled_from_env():
            mem_ns = memory_namespace_from_cfg(cfg)
            mode_ns = build_mode_kb_namespace(
                memory_namespace=mem_ns,
                project_root=project_root,
            )
            rc0 = detect_repo_context(project_root)
            coord = ChatPermModeCoordinator(
                kb_namespace=mode_ns,
                history_max=8,
                repo_payload=rc0.to_event_payload(),
            )
            prov, model_eff = _make_provider(choice, cfg)
            res = coord.resolve_turn(
                provider=prov,
                model=model_eff,
                temperature=0.3,
                user_intent=prompt,
                classifier_bypass=bypass,
                forced_mode=forced,
                diag_sink=ensure_process_log("chat").sink,
            )
            if not bypass and res.not_sure:
                st.session_state[_ChatPageState.PERM_MODE_GATE] = {
                    "snap": base_snap,
                    "prompt": prompt,
                }
                st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
                st.rerun()
                return
            perm_tool_mode = res.final_mode

        snap = dict(base_snap)
        snap["perm_tool_mode"] = perm_tool_mode
        st.session_state[_ChatPageState.LLM_WIDGET_SNAPSHOT] = snap
        st.session_state[_ChatPageState.PENDING_LLM] = True
        st.session_state[_ChatPageState.SCROLL_BOTTOM] = True
        st.rerun()


if __name__ == "__main__":
    main()
