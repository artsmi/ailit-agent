"""CLI: `ailit runtime ...` (workflow 8, G8.2.1)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping

from agent_core.runtime.paths import RuntimePaths, default_runtime_dir
from agent_core.runtime.supervisor import (
    run_supervisor_server,
    supervisor_request,
)


def register_runtime_parser(sub: argparse._SubParsersAction) -> None:
    """Зарегистрировать подкоманды `ailit runtime`."""
    p = sub.add_parser(
        "runtime",
        help="Runtime supervisor/brokers (workflow 8)",
    )
    rt_sub = p.add_subparsers(dest="runtime_cmd", required=True)

    p_sup = rt_sub.add_parser(
        "supervisor",
        help="Запустить runtime supervisor (blocking)",
    )
    p_sup.add_argument(
        "--runtime-dir",
        type=str,
        default="",
        help=(
            "Переопределить runtime dir "
            "(по умолчанию: XDG_RUNTIME_DIR/ailit)"
        ),
    )
    p_sup.set_defaults(func=cmd_runtime_supervisor)

    p_status = rt_sub.add_parser(
        "status",
        help="Показать статус supervisor",
    )
    p_status.add_argument(
        "--runtime-dir",
        type=str,
        default="",
        help="Runtime dir",
    )
    p_status.set_defaults(func=cmd_runtime_status)

    p_brok = rt_sub.add_parser(
        "brokers",
        help="Список broker-ов из supervisor registry",
    )
    p_brok.add_argument(
        "--runtime-dir",
        type=str,
        default="",
        help="Runtime dir",
    )
    p_brok.set_defaults(func=cmd_runtime_brokers)

    p_stop = rt_sub.add_parser(
        "stop-broker",
        help="Остановить broker по chat_id",
    )
    p_stop.add_argument("chat_id", type=str, help="Chat id broker-а")
    p_stop.add_argument(
        "--runtime-dir",
        type=str,
        default="",
        help="Runtime dir",
    )
    p_stop.set_defaults(func=cmd_runtime_stop_broker)


def _runtime_dir_from_args(args: argparse.Namespace) -> Path:
    raw = str(getattr(args, "runtime_dir", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return default_runtime_dir()


def _supervisor_sock(runtime_dir: Path) -> Path:
    return RuntimePaths(runtime_dir=runtime_dir).supervisor_socket


def _print_json(obj: Mapping[str, Any]) -> None:
    sys.stdout.write(f"{obj}\n")


def cmd_runtime_supervisor(args: argparse.Namespace) -> int:
    """`ailit runtime supervisor`."""
    rd = _runtime_dir_from_args(args)
    sys.stderr.write(f"[ailit] runtime supervisor: {rd}\n")
    run_supervisor_server(runtime_dir=rd)
    return 0


def cmd_runtime_status(args: argparse.Namespace) -> int:
    """`ailit runtime status`."""
    rd = _runtime_dir_from_args(args)
    sock = _supervisor_sock(rd)
    if not sock.exists():
        sys.stderr.write(
            (
                "Supervisor socket не найден. Запустите: "
                "`ailit runtime supervisor` или "
                "`systemctl --user status ailit.service`.\n"
            )
        )
        return 2
    resp = supervisor_request(socket_path=sock, request={"cmd": "status"})
    _print_json(resp)
    return 0


def cmd_runtime_brokers(args: argparse.Namespace) -> int:
    """`ailit runtime brokers`."""
    rd = _runtime_dir_from_args(args)
    sock = _supervisor_sock(rd)
    if not sock.exists():
        sys.stderr.write("Supervisor socket не найден.\n")
        return 2
    resp = supervisor_request(socket_path=sock, request={"cmd": "brokers"})
    _print_json(resp)
    return 0


def cmd_runtime_stop_broker(args: argparse.Namespace) -> int:
    """`ailit runtime stop-broker <chat_id>`."""
    rd = _runtime_dir_from_args(args)
    sock = _supervisor_sock(rd)
    if not sock.exists():
        sys.stderr.write("Supervisor socket не найден.\n")
        return 2
    chat_id = str(getattr(args, "chat_id", "") or "")
    resp = supervisor_request(
        socket_path=sock,
        request={"cmd": "stop_broker", "chat_id": chat_id},
    )
    _print_json(resp)
    return 0
