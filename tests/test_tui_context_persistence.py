"""Тесты сохранения/загрузки состояния TUI (этап Q.3)."""

from __future__ import annotations

from pathlib import Path

from agent_core.models import ChatMessage, MessageRole

from ailit.tui_app_state import TuiAppState
from ailit.tui_chat_controller import TuiChatController
from ailit.tui_context_manager import (
    TuiContextManager,
    TuiContextProfile,
    TuiContextRuntime,
)
from ailit.tui_context_persistence import load_app_state, save_app_state


def test_save_load_roundtrip(tmp_path: Path) -> None:
    """Снимок контекстов, usage и истории восстанавливается."""
    root = tmp_path / "proj"
    root.mkdir()
    mgr = TuiContextManager(default_root=root, default_name="default")
    mgr.new_context("job", project_root=root)
    assert mgr.switch("job") is None
    mgr.record_turn_usage({"input_tokens": 4, "output_tokens": 2})
    chat = mgr.active_chat()
    hist = chat.snapshot_messages()
    hist.append(ChatMessage(role=MessageRole.USER, content="ping"))
    chat.replace_messages(hist)
    state = TuiAppState(
        provider="mock",
        model="mock",
        max_turns=3,
        contexts=mgr,
    )
    path = tmp_path / "state.json"
    save_app_state(path, state)
    loaded = load_app_state(path, default_root=root)
    assert loaded is not None
    mgr2, prov, model, mt = loaded
    assert prov == "mock"
    assert model == "mock"
    assert mt == 3
    assert mgr2.active_name() == "job"
    assert mgr2.active_runtime().usage.input_tokens == 4
    msgs = mgr2.active_chat().snapshot_messages()
    assert any(
        m.role is MessageRole.USER and m.content == "ping"
        for m in msgs
    )


def test_load_missing_file(tmp_path: Path) -> None:
    """Нет файла — None."""
    missing = tmp_path / "nope.json"
    assert load_app_state(missing, default_root=tmp_path) is None


def test_load_invalid_json(tmp_path: Path) -> None:
    """Битый JSON — None."""
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    assert load_app_state(p, default_root=tmp_path) is None


def test_load_wrong_version(tmp_path: Path) -> None:
    """Неподдерживаемая версия — None."""
    p = tmp_path / "v0.json"
    p.write_text(
        '{"version": 0, "active": "a", "provider": "x", '
        '"model": "y", "max_turns": 1, "contexts": []}',
        encoding="utf-8",
    )
    assert load_app_state(p, default_root=tmp_path) is None


def test_load_empty_contexts(tmp_path: Path) -> None:
    """Пустой список контекстов — None."""
    p = tmp_path / "empty.json"
    p.write_text(
        '{"version": 1, "active": "a", "provider": "x", '
        '"model": "y", "max_turns": 1, "contexts": []}',
        encoding="utf-8",
    )
    assert load_app_state(p, default_root=tmp_path) is None


def test_replace_from_serialized_restores_active(tmp_path: Path) -> None:
    """Явный сценарий ``replace_from_serialized`` как при загрузке."""
    root = tmp_path / "r"
    root.mkdir()
    rt: dict[str, TuiContextRuntime] = {}
    for key in ("c1", "c2"):
        prof = TuiContextProfile(name=key, project_root=root)
        rt[key] = TuiContextRuntime(profile=prof, chat=TuiChatController())
    mgr = TuiContextManager(default_root=root, default_name="c1")
    mgr.replace_from_serialized(active="c2", runtimes=rt)
    assert mgr.active_name() == "c2"
