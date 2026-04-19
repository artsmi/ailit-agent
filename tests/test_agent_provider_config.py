"""Тесты сборки провайдерского конфига для agent/chat."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ailit.agent_provider_config import (
    AgentRunProviderConfigBuilder,
    DevRepoTestLocalSource,
)


def test_dev_layer_under_global_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``test.local.yaml`` слабее глобального ``config.yaml``."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "config").mkdir(parents=True)
    dev_yaml = fake_repo / "config" / "test.local.yaml"
    dev_yaml.write_text(
        yaml.safe_dump({"deepseek": {"model": "from-dev"}}),
        encoding="utf-8",
    )

    gdir = tmp_path / "xdg"
    (gdir / "ailit").mkdir(parents=True)
    global_yaml = gdir / "ailit" / "config.yaml"
    global_yaml.write_text(
        yaml.safe_dump({"deepseek": {"model": "from-global"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(gdir))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)

    dev_src = DevRepoTestLocalSource(repo_root_override=fake_repo)
    cfg = AgentRunProviderConfigBuilder(dev_source=dev_src).build(
        None,
        use_dev_repo_yaml=True,
    )
    assert cfg["deepseek"]["model"] == "from-global"


def test_no_dev_skips_repo_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без dev-слоя только merge (глобальный перекрывает default)."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "config").mkdir(parents=True)
    (fake_repo / "config" / "test.local.yaml").write_text(
        yaml.safe_dump({"deepseek": {"model": "only-dev"}}),
        encoding="utf-8",
    )

    gdir = tmp_path / "xdg"
    (gdir / "ailit").mkdir(parents=True)
    (gdir / "ailit" / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"model": "from-global"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(gdir))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)

    dev_src = DevRepoTestLocalSource(repo_root_override=fake_repo)
    cfg = AgentRunProviderConfigBuilder(dev_source=dev_src).build(
        None,
        use_dev_repo_yaml=False,
    )
    assert cfg["deepseek"]["model"] == "from-global"


def test_project_layer_over_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Проектный ``.ailit/config.yaml`` перекрывает глобальный."""
    gdir = tmp_path / "xdg"
    (gdir / "ailit").mkdir(parents=True)
    (gdir / "ailit" / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"model": "global-m"}}),
        encoding="utf-8",
    )
    proj = tmp_path / "proj"
    (proj / ".ailit").mkdir(parents=True)
    (proj / ".ailit" / "config.yaml").write_text(
        yaml.safe_dump({"deepseek": {"model": "proj-m"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(gdir))
    monkeypatch.delenv("AILIT_CONFIG_DIR", raising=False)

    cfg = AgentRunProviderConfigBuilder().build(proj, use_dev_repo_yaml=False)
    assert cfg["deepseek"]["model"] == "proj-m"
