"""Точка входа CLI: `ailit chat` и `ailit agent run`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ailit.agent_provider_config import AgentRunProviderConfigBuilder
from ailit.config_cli import register_config_parser
from ailit.models_cli import register_models_parser
from ailit.plugin_install import PluginInstaller
from ailit.setup_cli import register_setup_parser
from ailit.task_spec import RunTaskArtifactWriter, TaskSpecResolver


def _repo_root() -> Path:
    """Корень репозитория (…/ailit-agent)."""
    return Path(__file__).resolve().parents[2]


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


def _cmd_agent_run(args: argparse.Namespace) -> int:
    """Исполнить workflow YAML, печать JSONL в stdout."""
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


def main(argv: list[str] | None = None) -> int:
    """Точка входа `ailit`."""
    parser = argparse.ArgumentParser(
        prog="ailit",
        description="ailit-agent CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    register_config_parser(sub)
    register_setup_parser(sub)
    register_models_parser(sub)

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
        default="mock",
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
        default=8,
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
        default="mock",
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
        default=8,
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
        default="deepseek-chat",
        help="Идентификатор модели",
    )
    p_run.add_argument("--max-turns", type=int, default=8, dest="max_turns")
    p_run.add_argument(
        "--provider",
        choices=("deepseek", "kimi", "mock"),
        default="mock",
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
        default=8,
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

    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
