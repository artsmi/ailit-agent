"""Точка входа CLI: `ailit chat` и `ailit agent run`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Корень репозитория (…/ailit-agent)."""
    return Path(__file__).resolve().parents[2]


def _cmd_chat(_args: argparse.Namespace) -> int:
    """Запустить Streamlit UI (браузер)."""
    try:
        import streamlit  # noqa: F401, PLC0415
    except ImportError:
        sys.stderr.write("Установите UI-зависимости: pip install -e '.[chat]'\n")
        return 1
    app = Path(__file__).resolve().parent / "chat_app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app), "--server.headless", "false"]
    return subprocess.call(cmd)


def _cmd_agent_run(args: argparse.Namespace) -> int:
    """Исполнить workflow YAML, печать JSONL в stdout."""
    from agent_core.config_loader import load_test_local_yaml
    from agent_core.providers.deepseek import DeepSeekAdapter
    from agent_core.providers.factory import ProviderFactory, ProviderKind
    from agent_core.providers.mock_provider import MockProvider
    from agent_core.tool_runtime.registry import default_builtin_registry
    from workflow_engine.engine import WorkflowEngine, WorkflowRunConfig
    from workflow_engine.loader import load_workflow_from_path

    wf_path = Path(args.workflow_yaml).resolve()
    wf = load_workflow_from_path(wf_path)
    cfg = dict(load_test_local_yaml(_repo_root() / "config" / "test.local.yaml"))
    if args.provider == "mock":
        provider: object = MockProvider()
    elif args.provider == "deepseek":
        provider = ProviderFactory.create(ProviderKind.DEEPSEEK, config=cfg)
    else:
        sys.stderr.write(f"Неизвестный провайдер: {args.provider}\n")
        return 2
    eng = WorkflowEngine(wf, provider, default_builtin_registry())  # type: ignore[arg-type]
    list(eng.iter_run_events(WorkflowRunConfig(model=args.model, dry_run=args.dry_run, max_turns=args.max_turns)))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа `ailit`."""
    parser = argparse.ArgumentParser(prog="ailit", description="ailit-agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_chat = sub.add_parser("chat", help="Интерактивный чат в браузере (Streamlit)")
    p_chat.set_defaults(func=_cmd_chat)

    p_agent = sub.add_parser("agent", help="Запуск workflow")
    agent_sub = p_agent.add_subparsers(dest="agent_cmd", required=True)
    p_run = agent_sub.add_parser("run", help="Выполнить YAML workflow")
    p_run.add_argument("workflow_yaml", type=str, help="Путь к workflow YAML")
    p_run.add_argument("--dry-run", action="store_true", help="Только события, без вызова модели")
    p_run.add_argument("--model", default="deepseek-chat", help="Идентификатор модели")
    p_run.add_argument("--max-turns", type=int, default=8, dest="max_turns")
    p_run.add_argument(
        "--provider",
        choices=("deepseek", "mock"),
        default="mock",
        help="Провайдер для задач workflow (mock не требует ключа)",
    )
    p_run.set_defaults(func=_cmd_agent_run)

    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
