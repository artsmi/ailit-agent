"""Детерминированное демо-мини-приложение под .ailit/ (для ревью и e2e)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from ailit.paths import repo_root


def default_demo_app_path() -> Path:
    """Каталог демо по умолчанию: <repo>/.ailit/demo-mini-app."""
    return repo_root().resolve() / ".ailit" / "demo-mini-app"


def _readme_text(workflow_ref_key: str) -> str:
    """README внутри сгенерированного приложения."""
    return (
        "# Демо-мини-проект ailit-agent\n\n"
        "Этот каталог сгенерирован инструментом материализации (не в git).\n\n"
        "## Запуск workflow\n\n"
        "```bash\n"
        f"ailit agent run {workflow_ref_key} "
        "--project-root . --provider mock\n"
        "```\n\n"
        "С `--dry-run` модель не вызывается.\n"
    )


@dataclass(frozen=True, slots=True)
class DemoAppBlueprint:
    """Описание дерева демо-приложения."""

    project_id: str = "demo_mini_app"
    workflow_id: str = "demo_smoke"
    workflow_ref_key: str = "smoke"
    info_line: str = "ailit demo mini application"

    def project_mapping(self) -> dict[str, object]:
        """Содержимое project.yaml."""
        return {
            "project_id": self.project_id,
            "runtime": "ailit",
            "workflows": {
                self.workflow_ref_key: {
                    "path": "workflows/smoke.yaml",
                },
            },
            "context": {
                "knowledge_refresh": {"mode": "stub"},
            },
        }

    def workflow_mapping(self) -> dict[str, object]:
        """Содержимое workflows/smoke.yaml."""
        return {
            "workflow_id": self.workflow_id,
            "hybrid": False,
            "stages": [
                {
                    "id": "main",
                    "tasks": [
                        {
                            "id": "greet",
                            "system_prompt": (
                                "You are a terse assistant. "
                                "Answer in one short sentence."
                            ),
                            "user_text": "Say hello in English.",
                        },
                    ],
                },
            ],
        }

    def extra_text_files(self) -> Mapping[str, str]:
        """Относительные пути → содержимое."""
        inner_test = '''"""Проверка, что дерево мини-приложения на месте."""

from __future__ import annotations

from pathlib import Path


def test_info_file_exists() -> None:
    """Корень приложения содержит маркерный файл."""
    app_root = Path(__file__).resolve().parents[1]
    info = app_root / "INFO.txt"
    assert info.is_file()
    text = info.read_text(encoding="utf-8").strip()
    assert len(text) > 0
'''
        ctx_readme = (
            "Контекст проекта для project layer. "
            "В демо используется knowledge_refresh.mode=stub.\n"
        )
        return {
            "README.md": _readme_text(self.workflow_ref_key),
            "INFO.txt": self.info_line,
            "context/README.md": ctx_readme,
            "tests/test_bootstrap.py": inner_test,
        }


@dataclass(frozen=True, slots=True)
class DemoAppMaterializer:
    """Запись blueprint на диск."""

    blueprint: DemoAppBlueprint = field(default_factory=DemoAppBlueprint)

    def write(self, app_root: Path) -> None:
        """Создать каталоги и файлы под app_root."""
        root = app_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        wf_dir = root / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        tests_dir = root / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        ctx_dir = root / "context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        proj_yaml = yaml.safe_dump(
            self.blueprint.project_mapping(),
            allow_unicode=True,
            sort_keys=False,
        )
        (root / "project.yaml").write_text(proj_yaml, encoding="utf-8")
        wf_yaml = yaml.safe_dump(
            self.blueprint.workflow_mapping(),
            allow_unicode=True,
            sort_keys=False,
        )
        (wf_dir / "smoke.yaml").write_text(wf_yaml, encoding="utf-8")
        for rel, body in self.blueprint.extra_text_files().items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")


def materialize_demo_app(
    dest: Path | None = None,
    *,
    overwrite: bool = False,
    blueprint: DemoAppBlueprint | None = None,
) -> Path:
    """Создать демо-приложение. При dest=None — default_demo_app_path()."""
    target = (dest or default_demo_app_path()).resolve()
    if target.exists():
        if not overwrite:
            msg = (
                f"каталог уже существует: {target} "
                "(передайте overwrite=True для перезаписи)"
            )
            raise FileExistsError(msg)
        shutil.rmtree(target)
    DemoAppMaterializer(blueprint=blueprint or DemoAppBlueprint()).write(
        target,
    )
    return target
