"""Тесты merge пользовательской конфигурации ``ailit``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ailit_cli.merged_config import (
    AilitConfigMerger,
    GLOBAL_USER_CONFIG_FILENAME,
    load_merged_ailit_config,
)
from ailit_cli.project_config_discovery import ProjectAilitConfigDiscovery
from ailit_cli.user_paths import GlobalDirResolver


def test_project_overrides_global_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Один и тот же вложенный ключ: проект перекрывает глобальный файл."""
    home = tmp_path / "h"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(home / ".ailit" / "config"))

    global_yaml = (home / ".ailit" / "config" / GLOBAL_USER_CONFIG_FILENAME)
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
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(home / ".ailit" / "config"))

    global_yaml = (home / ".ailit" / "config" / GLOBAL_USER_CONFIG_FILENAME)
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
    monkeypatch.delenv("AILIT_HOME", raising=False)

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


def test_g3_project_config_in_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G.3: конфиг предка виден из вложенного каталога без своего yaml."""
    home = tmp_path / "h"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(home / ".ailit" / "config"))

    global_yaml = (home / ".ailit" / "config" / GLOBAL_USER_CONFIG_FILENAME)
    global_yaml.parent.mkdir(parents=True)
    global_yaml.write_text(
        yaml.safe_dump({"live": {"run": False}}),
        encoding="utf-8",
    )

    root = tmp_path / "monorepo"
    root.mkdir()
    (root / ".ailit").mkdir()
    (root / ".ailit" / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"model": "from-parent-tree"}}),
        encoding="utf-8",
    )
    nested = root / "packages" / "svc"
    nested.mkdir(parents=True)

    r = GlobalDirResolver()
    out = AilitConfigMerger(path_resolver=r).load(nested)
    assert out["deepseek"]["model"] == "from-parent-tree"


def test_g3_deepest_project_file_wins_over_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G.3: ближайший к ``project_root`` конфиг перекрывает предка."""
    home = tmp_path / "h"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(home / ".ailit" / "config"))

    global_yaml = (home / ".ailit" / "config" / GLOBAL_USER_CONFIG_FILENAME)
    global_yaml.parent.mkdir(parents=True)
    global_yaml.write_text(yaml.safe_dump({}), encoding="utf-8")

    root = tmp_path / "r"
    root.mkdir()
    (root / ".ailit").mkdir()
    (root / ".ailit" / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"model": "ancestor"}}),
        encoding="utf-8",
    )
    sub = root / "sub"
    sub.mkdir()
    (sub / ".ailit").mkdir()
    (sub / ".ailit" / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"model": "leaf"}}),
        encoding="utf-8",
    )
    leaf = sub / "leaf"
    leaf.mkdir()

    r = GlobalDirResolver()
    out = AilitConfigMerger(path_resolver=r).load(leaf)
    assert out["deepseek"]["model"] == "leaf"


def test_project_config_discovery_deepest_first_order(tmp_path: Path) -> None:
    """Discovery отдаёт пути от вложенного ``.ailit`` к корневому."""
    root = tmp_path / "a"
    c = root / "b" / "c"
    c.mkdir(parents=True)
    d = c / "d"
    d.mkdir()
    root_cfg = root / ".ailit" / "config.yaml"
    root_cfg.parent.mkdir(parents=True)
    root_cfg.write_text("x: 1\n", encoding="utf-8")
    mid_cfg = c / ".ailit" / "config.yaml"
    mid_cfg.parent.mkdir(parents=True)
    mid_cfg.write_text("x: 2\n", encoding="utf-8")
    found = ProjectAilitConfigDiscovery.collect_deepest_first(d)
    assert found == (mid_cfg.resolve(), root_cfg.resolve())


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
