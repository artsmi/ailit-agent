"""Тесты allowlist и записи глобального ``config.yaml``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ailit.cli import main
from ailit.config_store import (
    ConfigSetKeyAllowlist,
    GlobalUserConfigFileStore,
    NestedMappingWriter,
    apply_config_set,
)


def test_apply_config_set_rejects_unknown_key() -> None:
    """Неразрешённый ключ даёт ValueError с перечислением."""
    with pytest.raises(ValueError, match="allowlist"):
        apply_config_set("not.allowed.key", "x")


def test_apply_config_set_writes_nested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Разрешённый ключ создаёт вложенную структуру."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_dir))
    path = apply_config_set("deepseek.model", "  my-model  ")
    assert path == (cfg_dir / "config.yaml").resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["deepseek"]["model"] == "my-model"


def test_apply_config_set_merges_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Новое поле не стирает существующие."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_dir))
    p = cfg_dir / "config.yaml"
    p.write_text(
        yaml.safe_dump({"deepseek": {"model": "keep"}}),
        encoding="utf-8",
    )
    apply_config_set("deepseek.base_url", "https://example.com")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["deepseek"]["model"] == "keep"
    assert data["deepseek"]["base_url"] == "https://example.com"


def test_live_run_coerced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """live.run приводится к bool."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_dir))
    apply_config_set("live.run", "true")
    data = yaml.safe_load((cfg_dir / "config.yaml").read_text(encoding="utf-8"))
    assert data["live"]["run"] is True


def test_config_set_cli_unknown_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI: неразрешённый ключ — код 2 и подсказка в stderr."""
    rc = main(["config", "set", "forbidden.key", "v"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "allowlist" in err or "Допустимые" in err


def test_config_set_cli_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI: успешная запись."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_dir))
    rc = main(["config", "set", "schema_version", "2"])
    assert rc == 0
    assert "Записано" in capsys.readouterr().out


def test_nested_mapping_writer_single_segment() -> None:
    """Один сегмент — запись в корень."""
    root: dict = {}
    NestedMappingWriter().set_path(root, ("schema_version",), "1")
    assert root == {"schema_version": "1"}


def test_allowlist_sorted_nonempty() -> None:
    """Справочник allowlist не пуст."""
    keys = ConfigSetKeyAllowlist().allowed_keys_sorted()
    assert "deepseek.model" in keys


def test_global_store_roundtrip(tmp_path: Path) -> None:
    """Файловый store читает и пишет."""
    p = tmp_path / "config.yaml"
    st = GlobalUserConfigFileStore(p)
    st.save_mapping({"a": 1})
    assert st.load_mapping() == {"a": 1}
