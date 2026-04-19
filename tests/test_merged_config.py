"""Тесты merge пользовательской конфигурации ``ailit``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ailit.merged_config import (
    AilitConfigMerger,
    GLOBAL_USER_CONFIG_FILENAME,
    load_merged_ailit_config,
)
from ailit.user_paths import GlobalDirResolver


def test_project_overrides_global_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Один и тот же вложенный ключ: проект перекрывает глобальный файл."""
    home = tmp_path / "h"
    gdir = home / "gcfg"
    gdir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(gdir))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)

    global_yaml = gdir / "ailit" / GLOBAL_USER_CONFIG_FILENAME
    global_yaml.parent.mkdir(parents=True)
    global_yaml.write_text(
        yaml.safe_dump({"deepseek": {"model": "from-global", "api_key": ""}}),
        encoding="utf-8",
    )

    proj = tmp_path / "proj"
    proj.mkdir()
    proj_cfg = proj / ".ailit" / "config.yaml"
    proj_cfg.parent.mkdir(parents=True)
    proj_cfg.write_text(
        yaml.safe_dump({"deepseek": {"model": "from-project"}}),
        encoding="utf-8",
    )

    r = GlobalDirResolver()
    m = AilitConfigMerger(path_resolver=r)
    out = m.load(proj)
    assert out["deepseek"]["model"] == "from-project"


def test_global_layer_used_when_no_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без project_root глобальный файл всё равно участвует."""
    home = tmp_path / "h"
    gdir = home / "xdg"
    gdir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(gdir))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)

    global_yaml = gdir / "ailit" / GLOBAL_USER_CONFIG_FILENAME
    global_yaml.parent.mkdir(parents=True)
    global_yaml.write_text(
        yaml.safe_dump({"deepseek": {"model": "only-global"}}),
        encoding="utf-8",
    )

    r = GlobalDirResolver()
    out = AilitConfigMerger(path_resolver=r).load(None)
    assert out["deepseek"]["model"] == "only-global"


def test_defaults_when_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пустое дерево: остаются defaults + отсутствие вложенных ключей."""
    home = tmp_path / "h"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    r = GlobalDirResolver()
    out = AilitConfigMerger(path_resolver=r).load(None)
    assert out["live"]["run"] is False
    assert out["deepseek"] == {}


def test_ailit_config_dir_global_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """При ``AILIT_CONFIG_DIR`` читается ``config.yaml`` из этого каталога."""
    cfg_home = tmp_path / "ailit_home"
    cfg_home.mkdir()
    yaml_path = cfg_home / "config.yaml"
    yaml_path.write_text(
        yaml.safe_dump({"kimi": {"api_key": "from-yaml"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_home))
    r = GlobalDirResolver()
    out = AilitConfigMerger(path_resolver=r).load(None)
    assert out["kimi"]["api_key"] == "from-yaml"


def test_deepseek_env_overrides_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEEPSEEK_API_KEY в env перекрывает значение из yaml."""
    cfg_home = tmp_path / "ch"
    cfg_home.mkdir()
    (cfg_home / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"api_key": "from-file", "model": "m"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_home))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env-secret")
    out = load_merged_ailit_config(None)
    assert out["deepseek"]["api_key"] == "from-env-secret"
    assert out["deepseek"]["model"] == "m"
