"""Knowledge refresh и canonical context."""

from __future__ import annotations

from pathlib import Path

import yaml

from project_layer.knowledge import FilesystemKnowledgeRefresh, StubKnowledgeRefresh
from project_layer.loader import LoadedProject, load_project
from project_layer.models import project_config_from_mapping


def test_stub_refresh() -> None:
    """Stub даёт предупреждение и keywords из hints."""
    cfg = project_config_from_mapping(
        {
            "project_id": "p",
            "context": {
                "knowledge_refresh": {"mode": "stub"},
            },
            "memory_hints": ["important_keyword_alpha"],
        },
    )
    loaded = LoadedProject(root=Path("/tmp"), config_path=Path("project.yaml"), config=cfg)
    snap = StubKnowledgeRefresh().refresh(loaded)
    assert "important_keyword_alpha" in snap.shortlist_keywords
    assert snap.warnings


def test_filesystem_refresh_keywords(tmp_path: Path) -> None:
    """Filesystem извлекает keywords из markdown."""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "note.md").write_text(
        "# HeadingLongToken\nbody with superlongwordtoken here\n",
        encoding="utf-8",
    )
    proj = tmp_path / "project.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "project_id": "p",
                "context": {
                    "canonical_globs": ["context/**/*.md"],
                    "knowledge_refresh": {
                        "mode": "filesystem",
                        "max_files": 5,
                        "max_chars_per_file": 500,
                        "max_keywords": 10,
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    loaded = load_project(proj)
    snap = FilesystemKnowledgeRefresh().refresh(loaded)
    assert "superlongwordtoken" in snap.shortlist_keywords
    assert snap.canonical_rel_paths
