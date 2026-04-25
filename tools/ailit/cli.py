"""Точка входа CLI: `ailit chat` и `ailit agent run`."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path


def _repo_root() -> Path:
    """Корень репозитория (…/ailit-agent)."""
    return Path(__file__).resolve().parents[2]


def _venv_python(repo_root: Path) -> Path:
    """Путь до python внутри .venv."""
    return (repo_root / ".venv" / "bin" / "python3").resolve()


def _is_running_in_repo_venv(repo_root: Path) -> bool:
    """True, если текущий интерпретатор — python из repo/.venv."""
    try:
        return Path(sys.executable).resolve() == _venv_python(repo_root)
    except OSError:
        return False


def _bootstrap_repo_venv_if_needed(argv: list[str]) -> None:
    """Поднять repo/.venv и re-exec, если нет runtime deps (например httpx)."""
    repo = _repo_root()
    if os.environ.get("AILIT_REPO_BOOTSTRAP_DISABLED", "").strip():
        return
    if _is_running_in_repo_venv(repo):
        return
    if os.environ.get("AILIT_REPO_BOOTSTRAPPED", "").strip():
        return

    missing_runtime = False
    try:
        import httpx  # noqa: F401, PLC0415
    except Exception:
        missing_runtime = True

    missing_pytest = False
    if argv[:1] == ["agent"] and "run" in argv:
        try:
            import pytest  # noqa: F401, PLC0415
        except Exception:
            missing_pytest = True

    if not (missing_runtime or missing_pytest):
        return

    venv_dir = (repo / ".venv").resolve()
    py = _venv_python(repo)
    if not py.exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(str(venv_dir))
    cmd_prefix = [str(py), "-m", "pip"]
    subprocess.check_call(
        cmd_prefix + ["install", "-U", "pip"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(
        cmd_prefix + ["install", "-e", ".[dev]"],
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    env = os.environ.copy()
    env["AILIT_REPO_BOOTSTRAPPED"] = "1"
    if (
        env.get("AILIT_BOOTSTRAP_SILENT", "").strip()
        not in ("1", "true", "yes")
    ):
        sys.stderr.write(
            f"[ailit] bootstrapped repo venv: {venv_dir}\n"
        )
    os.execve(str(py), [str(py), "-m", "ailit.cli", *argv], env)


def _cmd_tui(args: argparse.Namespace) -> int:
    """Терминальный чат (Textual)."""
    sys.stderr.write(
        "Предупреждение: `ailit tui` устаревает; используйте `ailit agent`.\n"
    )
    try:
        import textual  # noqa: F401, PLC0415
    except ImportError:
        sys.stderr.write("Установите TUI: pip install -e '.[tui]'\n")
        return 1
    from ailit.tui_app import run_ailit_tui

    from ailit.defaults_resolver import DefaultProviderModelResolver

    pr = getattr(args, "project_root", None)
    root = Path(str(pr)).resolve() if pr else Path.cwd().resolve()
    dflt = DefaultProviderModelResolver().resolve(project_root=root)
    if getattr(args, "provider", None) is None:
        args.provider = dflt.provider
    if getattr(args, "model", None) is None:
        args.model = dflt.model
    run_ailit_tui(args, repo_root=_repo_root())
    return 0


def _cmd_agent_tui(args: argparse.Namespace) -> int:
    """Интерактивный агент в терминале (Textual)."""
    try:
        import textual  # noqa: F401, PLC0415
    except ImportError:
        sys.stderr.write("Установите TUI: pip install -e '.[tui]'\n")
        return 1
    from ailit.tui_app import run_ailit_tui

    from ailit.defaults_resolver import DefaultProviderModelResolver

    pr = getattr(args, "project_root", None)
    root = Path(str(pr)).resolve() if pr else Path.cwd().resolve()
    dflt = DefaultProviderModelResolver().resolve(project_root=root)
    if getattr(args, "provider", None) is None:
        args.provider = dflt.provider
    if getattr(args, "model", None) is None:
        args.model = dflt.model
    run_ailit_tui(args, repo_root=_repo_root())
    return 0


def _cmd_chat(_args: argparse.Namespace) -> int:
    """Запустить Streamlit UI (браузер)."""
    try:
        import streamlit  # noqa: F401, PLC0415
    except ImportError:
        msg = "Установите UI-зависимости: pip install -e '.[chat]'\n"
        sys.stderr.write(msg)
        return 1
    app = Path(__file__).resolve().parent / "chat_app.py"
    # Без watcher inotify: иначе EMFILE «inotify instance limit reached».
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.headless",
        "false",
        "--server.fileWatcherType",
        "none",
    ]
    return subprocess.call(cmd)


def _cmd_agent_usage_last(args: argparse.Namespace) -> int:
    """Печать последней сводки usage из лога agent."""
    from pathlib import Path

    from ailit.agent_usage_cli import print_last_usage_from_log

    raw = getattr(args, "usage_log_file", None)
    explicit = Path(str(raw)).resolve() if raw else None
    return print_last_usage_from_log(explicit)


def _cmd_agent_token_econ_report(args: argparse.Namespace) -> int:
    """Сводка pager / budget / prune по JSONL."""
    from pathlib import Path

    from ailit.agent_token_econ_cli import (
        run_token_econ_from_explicit_or_latest,
    )

    raw = getattr(args, "token_econ_log_file", None)
    explicit = Path(str(raw)).resolve() if raw else None
    return run_token_econ_from_explicit_or_latest(explicit)


def _cmd_session_usage_list(_args: argparse.Namespace) -> int:
    """Список ailit-*.log с временем process.start."""
    from ailit.session_usage_cli import print_session_list

    return print_session_list()


def _cmd_session_usage_show(args: argparse.Namespace) -> int:
    """Сводка usage + token-economy по одному .log."""
    from pathlib import Path

    from ailit.session_usage_cli import print_session_show

    p = Path(str(getattr(args, "log_file", ""))).resolve()
    return print_session_show(p)


def _cmd_session_usage_summary(args: argparse.Namespace) -> int:
    """Единый summary: usage + подсистемы + resume_ready."""
    from pathlib import Path

    from ailit.session_usage_cli import print_session_summary

    p = Path(str(getattr(args, "log_file", ""))).resolve()
    return print_session_summary(p, as_json=bool(getattr(args, "json", False)))


def _make_cmd_session_usage_subsystem(subsystem: str):
    """Фабрика: отдельный отчёт по подсистеме (M3: разные команды)."""

    def _cmd(args: argparse.Namespace) -> int:
        from pathlib import Path

        from ailit.session_usage_cli import print_session_subsystem

        p = Path(str(getattr(args, "log_file", ""))).resolve()
        return print_session_subsystem(p, subsystem)

    return _cmd


def _cmd_agent_run(args: argparse.Namespace) -> int:
    """Исполнить workflow YAML, печать JSONL в stdout."""
    from ailit.agent_provider_config import AgentRunProviderConfigBuilder
    from ailit.task_spec import RunTaskArtifactWriter, TaskSpecResolver
    from ailit.process_log import ensure_process_log
    from agent_core.providers.factory import ProviderFactory, ProviderKind
    from agent_core.providers.mock_provider import MockProvider
    from agent_core.tool_runtime.registry import default_builtin_registry
    from project_layer.bootstrap import compute_workflow_augmentation
    from project_layer.loader import default_project_yaml_path, load_project
    from project_layer.registry import ProjectRegistries
    from workflow_engine.engine import WorkflowEngine, WorkflowRunConfig
    from workflow_engine.loader import load_workflow_from_path

    wf_ref = str(args.workflow_ref)
    aug_extra: tuple[str, ...] = ()
    aug_keys: frozenset[str] | None = None
    aug_temp = 0.0
    if args.project_root:
        root = Path(args.project_root).resolve()
        if args.project_file:
            cfg_path = Path(args.project_file).resolve()
        else:
            cfg_path = default_project_yaml_path(root)
        loaded = load_project(cfg_path)
        reg = ProjectRegistries(loaded)
        wf_path = reg.workflow_path(wf_ref)
        aug = compute_workflow_augmentation(loaded)
        aug_extra = aug.extra_system_messages
        aug_keys = aug.shortlist_keywords
        aug_temp = aug.temperature
    else:
        wf_path = Path(wf_ref).resolve()
        if not wf_path.is_file():
            msg = (
                "Файл workflow не найден. Укажите путь к .yaml или задайте "
                "--project-root и id workflow из project.yaml.\n"
            )
            sys.stderr.write(msg)
            return 2
    wf = load_workflow_from_path(wf_path)
    proj_for_cfg: Path | None = None
    if args.project_root:
        proj_for_cfg = Path(args.project_root).resolve()
    cfg = AgentRunProviderConfigBuilder().build(
        proj_for_cfg,
        use_dev_repo_yaml=not bool(args.no_dev_repo_config),
    )
    from ailit.defaults_resolver import DefaultProviderModelResolver

    defaults = DefaultProviderModelResolver().resolve(
        project_root=proj_for_cfg,
    )
    if getattr(args, "provider", None) is None:
        args.provider = defaults.provider
    if getattr(args, "model", None) is None:
        args.model = defaults.model
    if args.provider == "mock":
        provider: object = MockProvider()
    elif args.provider == "deepseek":
        provider = ProviderFactory.create(ProviderKind.DEEPSEEK, config=cfg)
    elif args.provider == "kimi":
        provider = ProviderFactory.create(ProviderKind.KIMI, config=cfg)
    else:
        sys.stderr.write(f"Неизвестный провайдер: {args.provider}\n")
        return 2
    reg = default_builtin_registry()
    eng = WorkflowEngine(wf, provider, reg)  # type: ignore[arg-type]
    try:
        task_spec = TaskSpecResolver.resolve(args)
    except (OSError, ValueError, UnicodeError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    artifact_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else Path.cwd().resolve()
    )
    run_id: str | None = None
    task_artifact_rel: str | None = None
    cli_task_body: str | None = None
    if task_spec is not None:
        run_id = RunTaskArtifactWriter.allocate_run_id()
        paths = RunTaskArtifactWriter.write(
            project_root=artifact_root,
            run_id=run_id,
            spec=task_spec,
        )
        task_artifact_rel = paths.task_rel_posix
        cli_task_body = task_spec.body
    run_cfg = WorkflowRunConfig(
        model=args.model,
        dry_run=args.dry_run,
        max_turns=args.max_turns,
        extra_system_messages=aug_extra,
        shortlist_keywords=aug_keys,
        temperature=aug_temp,
        run_id=run_id,
        cli_task_body=cli_task_body,
        task_artifact_rel=task_artifact_rel,
        perm_tool_mode=str(getattr(args, "perm_tool_mode", "edit") or "edit")
        .strip()
        .lower(),
        perm_classifier_bypass=True,
    )
    diag_sink = ensure_process_log("agent").sink
    list(eng.iter_run_events(run_cfg, diag_sink=diag_sink))
    return 0


def _cmd_compat_run(args: argparse.Namespace) -> int:
    """Compat: JSONL в stdout + status.md в .ailit/."""
    from ailit.compat_adapter import run_compat_workflow
    from ailit.process_log import ensure_process_log

    root = Path(args.project_root).resolve()
    diag_sink = ensure_process_log("agent").sink
    run_compat_workflow(
        project_root=root,
        workflow_ref=str(args.workflow_ref),
        provider=str(args.provider),
        model=str(args.model),
        max_turns=int(args.max_turns),
        dry_run=bool(args.dry_run),
        sink=sys.stdout,
        repo_root=_repo_root(),
        diag_sink=diag_sink,
    )
    return 0


def _cmd_debug_bundle(args: argparse.Namespace) -> int:
    """Упаковать debug bundle в zip."""
    from ailit.debug_bundle import build_debug_bundle

    root = Path(args.project_root).resolve()
    out = Path(args.out).resolve()
    build_debug_bundle(project_root=root, dest_zip=out)
    sys.stdout.write(f"Wrote {out}\n")
    return 0


def _cmd_plugin_install(args: argparse.Namespace) -> int:
    """Скопировать или git clone плагин в ``.ailit/plugins``."""
    from ailit.plugin_install import PluginInstaller
    root = Path(args.project_root).resolve()
    try:
        res = PluginInstaller.install(str(args.source), project_root=root)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        sys.stderr.write(f"git clone failed: {err}\n")
        return 2
    except (OSError, ValueError, TypeError) as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 2
    msg = f"Installed plugin `{res.manifest_name}` → {res.dest_dir}\n"
    sys.stdout.write(msg)
    return 0


def _cmd_doctor_paths(_args: argparse.Namespace) -> int:
    """Печать диагностики путей."""
    from ailit.doctor_cli import cmd_doctor_paths

    return cmd_doctor_paths()


def _cmd_doctor_data_policy(_args: argparse.Namespace) -> int:
    """Печать политики данных пользователя."""
    from ailit.doctor_cli import cmd_doctor_data_policy

    return cmd_doctor_data_policy()


def main(argv: list[str] | None = None) -> int:
    """Точка входа `ailit`."""
    args_in = list(argv) if argv is not None else sys.argv[1:]
    _bootstrap_repo_venv_if_needed(args_in)

    from ailit.config_cli import register_config_parser
    from ailit.kb_cli import (
        cmd_kb_dump_audit,
        cmd_kb_rebuild_index,
        cmd_kb_ttl_apply,
    )
    from ailit.memory_cli import cmd_memory_index
    from ailit.models_cli import register_models_parser
    from ailit.setup_cli import register_setup_parser

    parser = argparse.ArgumentParser(
        prog="ailit",
        description="ailit-agent CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    register_config_parser(sub)
    register_setup_parser(sub)
    register_models_parser(sub)

    p_doctor = sub.add_parser(
        "doctor",
        help="Диагностика установки и путей",
    )
    doc_sub = p_doctor.add_subparsers(dest="doctor_cmd", required=True)
    p_doc_paths = doc_sub.add_parser(
        "paths",
        help="Показать глобальные пути и исполняемые файлы",
    )
    p_doc_paths.set_defaults(func=_cmd_doctor_paths)
    p_doc_pol = doc_sub.add_parser(
        "data-policy",
        help="Показать, какие каталоги сохраняются/удаляются",
    )
    p_doc_pol.set_defaults(func=_cmd_doctor_data_policy)

    p_session = sub.add_parser(
        "session",
        help="Сессии: usage и token-economy по JSONL-логам",
    )
    sess_sub = p_session.add_subparsers(
        dest="session_cmd",
        required=True,
    )
    p_sess_use = sess_sub.add_parser(
        "usage",
        help="Сводка usage + механизмы экономии по лог-файлу",
    )
    sess_use_sub = p_sess_use.add_subparsers(
        dest="session_usage_cmd",
        required=True,
    )
    p_sess_list = sess_use_sub.add_parser(
        "list",
        help="Список ailit-*.log (роль, время start, путь)",
    )
    p_sess_list.set_defaults(func=_cmd_session_usage_list)
    p_sess_show = sess_use_sub.add_parser(
        "show",
        help="Агрегаты usage + синтетика по одному .log",
    )
    p_sess_show.add_argument(
        "log_file",
        type=str,
        help="Путь к JSONL (ailit-chat-*.log / ailit-agent-*.log)",
    )
    p_sess_show.set_defaults(func=_cmd_session_usage_show)
    p_sum = sess_use_sub.add_parser(
        "summary",
        help="Единый отчёт: usage, подсистемы, resume_ready (эвристика)",
    )
    p_sum.add_argument("log_file", type=str, help="Путь к JSONL")
    p_sum.add_argument(
        "--json",
        action="store_true",
        help="Вывести JSON (один объект)",
    )
    p_sum.set_defaults(func=_cmd_session_usage_summary)
    p_usg = sess_use_sub.add_parser(
        "tokens",
        help="Только сводка usage/tokens (по model.response)",
    )
    p_usg.add_argument("log_file", type=str, help="Путь к JSONL")
    p_usg.set_defaults(func=_make_cmd_session_usage_subsystem("usage"))
    p_pg = sess_use_sub.add_parser(
        "pager",
        help="Только context.pager (счётчики в логе)",
    )
    p_pg.add_argument("log_file", type=str, help="Путь к JSONL")
    p_pg.set_defaults(func=_make_cmd_session_usage_subsystem("pager"))
    p_bd = sess_use_sub.add_parser(
        "budget",
        help="Только tool output budget",
    )
    p_bd.add_argument("log_file", type=str, help="Путь к JSONL")
    p_bd.set_defaults(func=_make_cmd_session_usage_subsystem("budget"))
    p_pr = sess_use_sub.add_parser(
        "prune",
        help="Только tool output prune",
    )
    p_pr.add_argument("log_file", type=str, help="Путь к JSONL")
    p_pr.set_defaults(func=_make_cmd_session_usage_subsystem("prune"))
    p_co = sess_use_sub.add_parser(
        "compaction",
        help="Только post-compaction restore файлов",
    )
    p_co.add_argument("log_file", type=str, help="Путь к JSONL")
    p_co.set_defaults(func=_make_cmd_session_usage_subsystem("compaction"))
    p_mem = sess_use_sub.add_parser(
        "memory",
        help="Memory: access + promotion (срез unified summary)",
    )
    p_mem.add_argument("log_file", type=str, help="Путь к JSONL")
    p_mem.set_defaults(func=_make_cmd_session_usage_subsystem("memory"))
    p_exp = sess_use_sub.add_parser(
        "exposure",
        help="Только tool.exposure (schema + savings vs full)",
    )
    p_exp.add_argument("log_file", type=str, help="Путь к JSONL")
    p_exp.set_defaults(func=_make_cmd_session_usage_subsystem("exposure"))
    p_fs = sess_use_sub.add_parser(
        "fs",
        help="Только fs.read_file.completed (range-read метрики)",
    )
    p_fs.add_argument("log_file", type=str, help="Путь к JSONL")
    p_fs.set_defaults(func=_make_cmd_session_usage_subsystem("fs"))

    p_chat = sub.add_parser(
        "chat",
        help="Интерактивный чат в браузере (Streamlit)",
    )
    p_chat.set_defaults(func=_cmd_chat)

    p_tui = sub.add_parser(
        "tui",
        help="Чат в терминале (Textual); зависимость: pip install -e '.[tui]'",
    )
    p_tui.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Корень проекта (по умолчанию текущий каталог)",
    )
    p_tui.add_argument(
        "--provider",
        choices=("mock", "deepseek", "kimi"),
        default=None,
        help="Провайдер LLM",
    )
    p_tui.add_argument(
        "--model",
        type=str,
        default=None,
        help="Имя модели (по умолчанию: mock / deepseek-chat)",
    )
    p_tui.add_argument(
        "--max-turns",
        type=int,
        default=10_000,
        dest="max_turns",
        help="Лимит итераций session loop (как в ailit chat)",
    )
    p_tui.set_defaults(func=_cmd_tui)

    p_agent = sub.add_parser(
        "agent",
        help="Интерактивный агент (TUI) или запуск workflow",
    )
    p_agent.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Корень проекта (по умолчанию текущий каталог)",
    )
    p_agent.add_argument(
        "--provider",
        choices=("mock", "deepseek", "kimi"),
        default=None,
        help="Провайдер LLM для интерактивного режима",
    )
    p_agent.add_argument(
        "--model",
        type=str,
        default=None,
        help="Имя модели (по умолчанию: mock / deepseek-chat)",
    )
    p_agent.add_argument(
        "--max-turns",
        type=int,
        default=10_000,
        dest="max_turns",
        help="Лимит итераций session loop (как в ailit chat)",
    )
    agent_sub = p_agent.add_subparsers(dest="agent_cmd", required=False)
    p_run = agent_sub.add_parser("run", help="Выполнить YAML workflow")
    p_run.add_argument(
        "workflow_ref",
        type=str,
        help="Путь к workflow YAML или id из project.yaml (с --project-root)",
    )
    p_run.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Корень проекта: загрузка project.yaml и реестр workflows",
    )
    p_run.add_argument(
        "--project-file",
        type=str,
        default=None,
        help="Явный путь к project.yaml (иначе <project-root>/project.yaml)",
    )
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Только события, без вызова модели",
    )
    p_run.add_argument(
        "--model",
        default=None,
        help="Идентификатор модели",
    )
    p_run.add_argument(
        "--max-turns",
        type=int,
        default=10_000,
        dest="max_turns",
    )
    p_run.add_argument(
        "--provider",
        choices=("deepseek", "kimi", "mock"),
        default=None,
        help="Провайдер для задач workflow (mock не требует ключа)",
    )
    p_run.add_argument(
        "--no-dev-repo-config",
        action="store_true",
        help=(
            "Не подмешивать config/test.local.yaml из дерева ailit-agent "
            "(только глобальный и проектный merge)"
        ),
    )
    p_run.add_argument(
        "--perm-tool-mode",
        type=str,
        default="edit",
        help=(
            "perm-5: read|read_plan|explore|edit — режим инструментов worker "
            "(без LLM-классификатора)"
        ),
    )
    task_group = p_run.add_mutually_exclusive_group()
    task_group.add_argument(
        "--task",
        default=None,
        metavar="TEXT",
        help=(
            "Текст задачи для первой исполняемой задачи workflow "
            "(см. --task-file, stdin)"
        ),
    )
    task_group.add_argument(
        "--task-file",
        default=None,
        metavar="PATH",
        dest="task_file",
        help="Путь к файлу с задачей (UTF-8); взаимоисключение с --task",
    )
    p_run.set_defaults(func=_cmd_agent_run)

    p_usage = agent_sub.add_parser(
        "usage",
        help="Сводка токенов из JSONL-лога процесса agent",
    )
    usage_sub = p_usage.add_subparsers(dest="usage_cmd", required=True)
    p_usage_last = usage_sub.add_parser(
        "last",
        help="Печать последней пары usage и session totals (как в chat)",
    )
    p_usage_last.add_argument(
        "--log-file",
        type=str,
        default=None,
        dest="usage_log_file",
        help="Путь к JSONL (иначе последний ailit-agent-*.log в global logs)",
    )
    p_usage_last.set_defaults(func=_cmd_agent_usage_last)

    p_tok = agent_sub.add_parser(
        "token-econ",
        help="Сводка pager / tool budget / prune по JSONL-логу",
    )
    tok_sub = p_tok.add_subparsers(dest="token_econ_cmd", required=True)
    p_tok_rep = tok_sub.add_parser(
        "report",
        help="Счётчики и примеры payload (ailit_session_diag_v1 в логе)",
    )
    p_tok_rep.add_argument(
        "--log-file",
        type=str,
        default=None,
        dest="token_econ_log_file",
        help="JSONL (иначе последний ailit-agent-*.log в global logs)",
    )
    p_tok_rep.set_defaults(func=_cmd_agent_token_econ_report)

    p_agent.set_defaults(func=_cmd_agent_tui)

    p_compat = sub.add_parser(
        "compat",
        help="Adapter: runtime из project.yaml + status.md",
    )
    compat_sub = p_compat.add_subparsers(dest="compat_cmd", required=True)
    p_compat_run = compat_sub.add_parser(
        "run",
        help="Прогон через compat adapter",
    )
    p_compat_run.add_argument(
        "workflow_ref",
        type=str,
        help="Id workflow из project.yaml",
    )
    p_compat_run.add_argument(
        "--project-root",
        type=str,
        required=True,
        help="Корень проекта",
    )
    p_compat_run.add_argument("--dry-run", action="store_true")
    p_compat_run.add_argument("--model", default="deepseek-chat")
    p_compat_run.add_argument(
        "--max-turns",
        type=int,
        default=10_000,
        dest="max_turns",
    )
    p_compat_run.add_argument(
        "--provider",
        choices=("deepseek", "mock"),
        default="mock",
    )
    p_compat_run.set_defaults(func=_cmd_compat_run)

    p_debug = sub.add_parser(
        "debug",
        help="Операторские утилиты",
    )
    dbg_sub = p_debug.add_subparsers(dest="debug_cmd", required=True)
    p_dbg_bundle = dbg_sub.add_parser(
        "bundle",
        help="Собрать zip debug bundle",
    )
    p_dbg_bundle.add_argument(
        "--project-root",
        type=str,
        required=True,
    )
    p_dbg_bundle.add_argument(
        "--out",
        type=str,
        required=True,
        help="Путь к .zip",
    )
    p_dbg_bundle.set_defaults(func=_cmd_debug_bundle)

    p_plugin = sub.add_parser("plugin", help="Плагины проекта (MVP)")
    plugin_sub = p_plugin.add_subparsers(dest="plugin_cmd", required=True)
    p_pin = plugin_sub.add_parser(
        "install",
        help="Установить плагин (каталог или git URL) в .ailit/plugins/",
    )
    p_pin.add_argument(
        "source",
        type=str,
        help="Каталог с ailit-plugin.yaml или URL репозитория (.git)",
    )
    p_pin.add_argument(
        "--project-root",
        type=str,
        required=True,
        help="Корень проекта (создаётся .ailit/plugins)",
    )
    p_pin.set_defaults(func=_cmd_plugin_install)

    p_kb = sub.add_parser(
        "kb",
        help="KB: governance/maintenance utilities (M4-5)",
    )
    kb_sub = p_kb.add_subparsers(dest="kb_cmd", required=True)
    p_ttl = kb_sub.add_parser(
        "ttl-apply",
        help="Применить TTL к deprecated (ставит valid_to, не удаляет)",
    )
    p_ttl.add_argument(
        "--ttl-days",
        type=int,
        default=30,
        help="Через сколько дней считать deprecated истёкшим",
    )
    p_ttl.set_defaults(func=cmd_kb_ttl_apply)

    p_reb = kb_sub.add_parser(
        "rebuild-index",
        help="Пересобрать acceleration index (FTS5/BM25), если поддерживается",
    )
    p_reb.set_defaults(func=cmd_kb_rebuild_index)

    p_aud = kb_sub.add_parser(
        "audit",
        help="Показать audit trail для KB записи",
    )
    p_aud.add_argument("id", type=str, help="KB record id")
    p_aud.set_defaults(func=cmd_kb_dump_audit)

    p_mem = sub.add_parser(
        "memory",
        help="PAG: project architecture graph utilities (arch-graph-7)",
    )
    mem_sub = p_mem.add_subparsers(dest="memory_cmd", required=True)
    p_idx = mem_sub.add_parser(
        "index",
        help="Проиндексировать проект в PAG store (SQLite)",
    )
    p_idx.add_argument(
        "--project-root",
        type=str,
        required=False,
        default=None,
        help="Корень проекта (по умолчанию текущий каталог)",
    )
    p_idx.add_argument(
        "--db-path",
        type=str,
        required=False,
        default=None,
        dest="db_path",
        help="Путь к sqlite (по умолчанию ~/.ailit/pag/store.sqlite3)",
    )
    p_idx.add_argument(
        "--full",
        action="store_true",
        help="Полный re-index (в MVP: без оптимизаций)",
    )
    p_idx.set_defaults(func=cmd_memory_index)

    args = parser.parse_args(args_in)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
