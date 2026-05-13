"""Пути runtime (XDG_RUNTIME_DIR / AILIT_RUNTIME_DIR)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Набор путей для supervisor/broker runtime."""

    runtime_dir: Path

    @property
    def supervisor_socket(self) -> Path:
        """Unix socket path supervisor."""
        return self.runtime_dir / "supervisor.sock"

    @property
    def brokers_dir(self) -> Path:
        """Каталог сокетов broker-ов."""
        return self.runtime_dir / "brokers"

    def broker_socket(self, *, chat_id: str) -> Path:
        """Unix socket path для broker данного chat."""
        safe = "".join(c for c in chat_id if c.isalnum() or c in ("-", "_"))
        return self.brokers_dir / f"broker-{safe}.sock"


def default_runtime_dir() -> Path:
    """Определить runtime dir для сокетов и state."""
    explicit = os.environ.get("AILIT_RUNTIME_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    xdg = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if xdg:
        return (Path(xdg) / "ailit").expanduser().resolve()
    return (Path.home() / ".ailit" / "runtime").resolve()
