"""Тесты канонических глобальных путей ``ailit``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ailit_cli.user_paths import (
    GlobalDirResolver,
    global_config_dir,
    global_logs_dir,
    global_state_dir,
)


def test_global_config_dir_respects_ailit_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``AILIT_CONFIG_DIR`` задаёт каталог глобального конфига."""
    target = tmp_path / "cfg_override"
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(target))
    assert global_config_dir() == target.resolve()


def test_global_state_dir_respects_ailit_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """При ``AILIT_STATE_DIR`` состояние не следует за конфигом."""
    cfg = tmp_path / "cfg"
    st = tmp_path / "state_override"
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("AILIT_STATE_DIR", str(st))
    assert global_config_dir() == cfg.resolve()
    assert global_state_dir() == st.resolve()


def test_global_config_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """XDG не используется: дефолтный дом фиксирован как ~/.ailit."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AILIT_HOME", raising=False)
    r = GlobalDirResolver(os.environ)
    assert r.global_config_dir() == (home / ".ailit" / "config").resolve()


def test_global_config_fallback_dot_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Фолбэк без XDG — всё равно ~/.ailit/config."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AILIT_HOME", raising=False)
    r = GlobalDirResolver(os.environ)
    assert r.global_config_dir() == (home / ".ailit" / "config").resolve()


def test_ailit_home_sets_config_and_state_subdirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``AILIT_HOME`` задаёт ``…/config`` и ``…/state`` без XDG."""
    root = tmp_path / "ah"
    root.mkdir()
    monkeypatch.setenv("AILIT_HOME", str(root))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AILIT_STATE_DIR", raising=False)
    r = GlobalDirResolver(os.environ)
    assert r.global_config_dir() == (root / "config").resolve()
    assert r.global_state_dir() == (root / "state").resolve()
    assert global_logs_dir() == (root / "state" / "logs").resolve()


def test_ailit_config_dir_overrides_ailit_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Явный ``AILIT_CONFIG_DIR`` сильнее ``AILIT_HOME``."""
    ah = tmp_path / "ah"
    cfg = tmp_path / "cfg"
    ah.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("AILIT_HOME", str(ah))
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("AILIT_STATE_DIR", raising=False)
    r = GlobalDirResolver(os.environ)
    assert r.global_config_dir() == cfg.resolve()
    assert r.global_state_dir() == (ah / "state").resolve()


def test_global_state_xdg_state_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """XDG не используется: дефолтный state — ~/.ailit/state."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AILIT_STATE_DIR", raising=False)
    monkeypatch.delenv("AILIT_HOME", raising=False)
    r = GlobalDirResolver(os.environ)
    assert r.global_state_dir() == (home / ".ailit" / "state").resolve()
