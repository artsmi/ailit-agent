"""Debug bundle zip."""

from __future__ import annotations

from pathlib import Path

import yaml

from ailit_cli.debug_bundle import build_debug_bundle, default_rollout_phase


def test_build_debug_bundle_contains_project(tmp_path: Path) -> None:
    """Zip содержит manifest и project.yaml."""
    (tmp_path / "project.yaml").write_text(yaml.safe_dump({"project_id": "x"}), encoding="utf-8")
    dest = tmp_path / "out.zip"
    res = build_debug_bundle(project_root=tmp_path, dest_zip=dest)
    assert res.zip_path.is_file()
    assert "manifest.json" in res.members


def test_default_rollout_phase(tmp_path: Path) -> None:
    """Чтение rollout.phase из project.yaml."""
    (tmp_path / "project.yaml").write_text(
        yaml.safe_dump({"project_id": "x", "rollout": {"phase": "beta_hybrid"}}),
        encoding="utf-8",
    )
    assert default_rollout_phase(tmp_path) == "beta_hybrid"
