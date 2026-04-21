"""Bootstrap augmentation без session loop."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from project_layer.bootstrap import (
    compute_chat_tuning,
    compute_workflow_augmentation,
)
from project_layer.loader import LoadedProject, load_project
from project_layer.models import BashSectionModel, project_config_from_mapping
from project_layer.registry import ProjectRegistries


def test_workflow_augmentation_includes_rules(tmp_path: Path) -> None:
    """Правила и превью попадают в extra system."""
    rules = tmp_path / "rules.md"
    rules.write_text("# RuleOne\nUse RuleOne always.\n", encoding="utf-8")
    proj = tmp_path / "project.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "project_id": "p",
                "paths": {"rules": "rules.md"},
                "context": {"knowledge_refresh": {"mode": "stub"}},
            },
        ),
        encoding="utf-8",
    )
    loaded = load_project(proj)
    aug = compute_workflow_augmentation(loaded)
    joined = "\n".join(aug.extra_system_messages)
    assert "RuleOne" in joined


def test_chat_tuning_merges_agent_shortlist(tmp_path: Path) -> None:
    """shortlist_extra агента объединяется со snapshot."""
    proj = tmp_path / "project.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "project_id": "p",
                "agents": {
                    "default": {"shortlist_extra_keywords": ["customtoken"]},
                },
                "context": {"knowledge_refresh": {"mode": "stub"}},
                "memory_hints": ["hinttoken"],
            },
        ),
        encoding="utf-8",
    )
    loaded = load_project(proj)
    tuning = compute_chat_tuning(loaded, "default")
    assert tuning.shortlist_keywords is not None
    assert "customtoken" in tuning.shortlist_keywords
    assert "hinttoken" in tuning.shortlist_keywords


def test_registry_agent_fallback() -> None:
    """Неизвестный агент → default."""
    cfg = project_config_from_mapping({"project_id": "p"})
    loaded = LoadedProject(
        root=Path.cwd(),
        config_path=Path("project.yaml"),
        config=cfg,
    )
    reg = ProjectRegistries(loaded)
    a = reg.agent("nope")
    assert a.agent_id == "default"


def test_project_yaml_parses_bash_section() -> None:
    """Секция bash: в project.yaml → BashSectionModel."""
    cfg = project_config_from_mapping(
        {
            "project_id": "p",
            "bash": {
                "default_timeout_ms": 30_000,
                "max_output_mb": 1.0,
                "allow_patterns": ["echo *", "git status"],
            },
        },
    )
    assert cfg.bash is not None
    assert cfg.bash.default_timeout_ms == 30_000
    assert cfg.bash.max_output_mb == 1.0
    assert cfg.bash.allow_patterns == ("echo *", "git status")
    assert isinstance(cfg.bash, BashSectionModel)


def test_project_yaml_bash_null_is_none() -> None:
    """bash: null не оставляет секцию."""
    cfg = project_config_from_mapping({"project_id": "p", "bash": None})
    assert cfg.bash is None


def test_project_yaml_bash_must_be_mapping() -> None:
    """bash: не dict → TypeError."""
    with pytest.raises(TypeError, match="bash"):
        project_config_from_mapping({"project_id": "p", "bash": "bad"})


def test_project_yaml_bash_rejects_nonpositive_max_output_mb() -> None:
    """bash.max_output_mb <= 0 запрещён."""
    with pytest.raises(ValueError, match="max_output_mb"):
        project_config_from_mapping(
            {"project_id": "p", "bash": {"max_output_mb": 0.0}},
        )
