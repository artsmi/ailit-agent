# ailit-agent

Репозиторий CLI и runtime-ядра **`ailit`**: глобальный конфиг, `ailit chat`, `ailit agent`, TUI (`ailit tui`), workflow engine и `agent_core`.

## Статус разработки (2026-04)

| Область | Состояние |
|---------|-----------|
| Глобальный CLI, merge конфигов, chat / agent | см. `plan/ailit-global-agent-teams-strategy.md` (этапы G–P закрыты в тексте плана по мере реализации) |
| **Этап Q** — мульти-контекст TUI, usage по контексту, снимок сессии | **Готово:** Q.1 (менеджер контекстов, `/ctx`, горячие клавиши), Q.2 (подзаголовок last/Σ, `/ctx stats` markdown), Q.3 (`~/.ailit/tui-sessions/state.json`, автосохранение при выходе, `/ctx save`) |
| Дальнейшие этапы | по документу стратегии в `plan/` |

## Как работать по проекту

1. **Workflow:** обязательный порядок задач и правило «конец workflow → research и постановка» — в [`docs/project-workflow.md`](docs/project-workflow.md).
2. **Стратегия и критерии этапов:** [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md).
3. **Оглавление документации:** [`docs/INDEX.md`](docs/INDEX.md).

## Установка и быстрая проверка

Из корня клона:

```bash
./scripts/install
# при необходимости: export PATH="${HOME}/.local/bin:${PATH}"
ailit --help
```

TUI (нужен extra `[tui]`):

```bash
pip install -e '.[tui]'
ailit tui --provider mock
```

Тесты (без e2e, если в окружении нет зависимостей вроде `httpx` для полного прогона):

```bash
PYTHONPATH=tools python3 -m pytest -q --ignore=tests/e2e/
```
