# Файлы и пути — индекс

Устойчивые пути конфигов, примеров и манифестов (не generated). Группы `__pycache__/`, `node_modules/`, `.venv/` и т.п. — в каноне не перечисляются пофайлово.

| Документ / элемент | Содержание |
|--------------------|------------|
| [`../../examples/workflows/minimal.yaml`](../../examples/workflows/minimal.yaml) | Пример workflow YAML для `workflow_engine`. |
| `pyproject.toml` | Имя проекта, зависимости, console script `ailit`, настройки pytest. |
| `~/.ailit/config.yaml` | Глобальный реестр проектов (active); в каталоге клона `.ailit` для registry не создаётся — см. README. |
| `~/.ailit/projects/<project_id>/config.yaml` | Конфигурация на проект (per README). |

**Связанные разделы:** [`../INDEX.md`](../INDEX.md), [`../modules/INDEX.md`](../modules/INDEX.md), [`../install/INDEX.md`](../install/INDEX.md).
