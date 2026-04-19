"""M.1: установка плагина и snippets в tuning."""

from __future__ import annotations

from pathlib import Path

import yaml

from ailit.plugin_install import PluginInstaller
from project_layer.bootstrap import compute_chat_tuning
from project_layer.loader import load_project


def test_plugin_install_local_copy(tmp_path: Path) -> None:
    """Копирование каталога с манифестом в ``.ailit/plugins``."""
    src = tmp_path / "srcplug"
    src.mkdir()
    (src / "ailit-plugin.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "demo_plug",
                "version": "0.0.1",
                "skills_paths": ["skills/hi.md"],
            },
        ),
        encoding="utf-8",
    )
    sk = src / "skills"
    sk.mkdir()
    (sk / "hi.md").write_text("# Hi skill\nbody", encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "project.yaml").write_text(
        yaml.safe_dump({"project_id": "p1", "runtime": "ailit"}),
        encoding="utf-8",
    )
    res = PluginInstaller.install(str(src), project_root=proj)
    assert res.manifest_name == "demo_plug"
    assert (res.dest_dir / "ailit-plugin.yaml").is_file()
    loaded = load_project(proj / "project.yaml")
    tuning = compute_chat_tuning(loaded, "default", snapshot=None)
    joined = "\n".join(tuning.extra_system_messages)
    assert "Hi skill" in joined or "hi.md" in joined
