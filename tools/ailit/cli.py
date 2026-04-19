"""Точка входа CLI: `ailit chat` и `ailit agent run`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ailit.agent_provider_config import AgentRunProviderConfigBuilder
from ailit.config_cli import register_config_parser


def _repo_root() -> Path:
    """Корень репозитория (…/ailit-agent)."""
    return Path(__file__).resolve().parents[2]


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
        provider = ProviderFactory.create(
            ProviderKind.DEEPSEEK,
            config=cfg,
        )
    else:
        sys.stderr.write(f"Неизвестный провайдер: {args.provider}\n")
        return 2
    reg = default_builtin_registry()
    eng = WorkflowEngine(wf, provider, reg)  # type: ignore[arg-type]
    run_cfg = WorkflowRunConfig(
        model=args.model,
        dry_run=args.dry_run,
        max_turns=args.max_turns,
        extra_system_messages=aug_extra,
        shortlist_keywords=aug_keys,
        temperature=aug_temp,
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


def main(argv: list[str] | None = None) -> int:
    """Точка входа `ailit`."""
    parser = argparse.ArgumentParser(
        prog="ailit",
        description="ailit-agent CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    register_config_parser(sub)

    p_chat = sub.add_parser(
        "chat",
        help="Интерактивный чат в браузере (Streamlit)",
    )
    p_chat.set_defaults(func=_cmd_chat)

    p_agent = sub.add_parser("agent", help="Запуск workflow")
    agent_sub = p_agent.add_subparsers(dest="agent_cmd", required=True)
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
        choices=("deepseek", "mock"),
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
    p_run.set_defaults(func=_cmd_agent_run)

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

    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
