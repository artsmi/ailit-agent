"""Эвристика корня пользовательского проекта относительно каталога запуска."""

from __future__ import annotations

from pathlib import Path


class ProjectRootDetector:
    """Ищет корень проекта вверх по родителям ``start``."""

    def find(self, start: Path | None = None) -> Path | None:
        """Вернуть каталог, где найден ``project.yaml`` или ``.ailit/config.yaml``."""
        cur = Path(start or Path.cwd()).resolve()
        for parent in [cur, *cur.parents]:
            if (parent / "project.yaml").is_file():
                return parent
            proj_cfg = parent / ".ailit" / "config.yaml"
            if proj_cfg.is_file():
                return parent
        return None
