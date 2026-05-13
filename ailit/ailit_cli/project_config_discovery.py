"""Поиск проектного ``.ailit/config.yaml`` вверх по каталогам (этап G.3)."""

from __future__ import annotations

from pathlib import Path


class ProjectAilitConfigDiscovery:
    """Собирает пути к ``config.yaml`` от ``start`` к корню ФС."""

    _RELATIVE = Path(".ailit") / "config.yaml"

    @classmethod
    def collect_deepest_first(cls, start: Path) -> tuple[Path, ...]:
        """Файлы от ``start`` к корню: сначала ближайший каталог, потом предки.

        Merge идёт в ``reversed(...)``, чтобы потомок перекрывал родителя.
        """
        cur = start.resolve()
        acc: list[Path] = []
        while True:
            candidate = cur / cls._RELATIVE
            if candidate.is_file():
                acc.append(candidate.resolve())
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
        return tuple(acc)
