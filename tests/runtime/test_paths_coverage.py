"""Unit tests for runtime/paths.py — coverage.

Covers:
- RuntimePaths (the actual class in paths.py)
- default_runtime_dir
"""

from __future__ import annotations

from pathlib import Path

from agent_core.runtime.paths import RuntimePaths, default_runtime_dir


class TestDefaultRuntimeDir:
    def test_default_runtime_dir(self) -> None:
        d = default_runtime_dir()
        assert isinstance(d, Path)
        assert str(d) != ""


class TestRuntimePaths:
    def test_init(self) -> None:
        rp = RuntimePaths(runtime_dir=Path("/tmp/test_runtime"))
        assert rp.runtime_dir == Path("/tmp/test_runtime")

    def test_supervisor_socket(self) -> None:
        rp = RuntimePaths(runtime_dir=Path("/tmp/test_runtime"))
        assert rp.supervisor_socket == Path("/tmp/test_runtime/supervisor.sock")

    def test_brokers_dir(self) -> None:
        rp = RuntimePaths(runtime_dir=Path("/tmp/test_runtime"))
        assert rp.brokers_dir == Path("/tmp/test_runtime/brokers")

    def test_broker_socket(self) -> None:
        rp = RuntimePaths(runtime_dir=Path("/tmp/test_runtime"))
        assert rp.broker_socket(chat_id="chat-123") == Path("/tmp/test_runtime/brokers/broker-chat-123.sock")
