"""Минимальный placeholder-broker для тестов supervisor (до G8.3).

Это не продуктовый broker: он просто держит Unix socket и отвечает "ok".
"""

from __future__ import annotations

import json
import socket
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BrokerPlaceholderConfig:
    """Конфиг placeholder broker."""

    socket_path: Path


class BrokerPlaceholderServer:
    """Простейший Unix socket server: ping/pong для healthcheck."""

    def __init__(self, cfg: BrokerPlaceholderConfig) -> None:
        self._cfg = cfg

    def serve_forever(self) -> None:
        """Блокирующий запуск."""
        path = self._cfg.socket_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.bind(str(path))
            s.listen(5)
            while True:
                conn, _ = s.accept()
                with conn:
                    data = conn.recv(4096)
                    msg = data.decode("utf-8", errors="replace").strip()
                    if msg == "ping":
                        conn.sendall(b"pong\n")
                        continue
                    try:
                        _ = json.loads(msg) if msg else {}
                    except Exception:
                        conn.sendall(b"{\"ok\":false}\n")
                        continue
                    conn.sendall(b"{\"ok\":true}\n")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for placeholder broker (internal)."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if len(args) != 1:
        sys.stderr.write("usage: broker_placeholder <socket_path>\n")
        return 2
    cfg = BrokerPlaceholderConfig(
        socket_path=Path(args[0]).expanduser().resolve()
    )
    BrokerPlaceholderServer(cfg).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
