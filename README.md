# ailit-agent

Репозиторий CLI и runtime-ядра **`ailit`**: глобальный конфиг, `ailit chat`, `ailit agent`, TUI (`ailit tui`), workflow engine и `agent_core`.

## Статус разработки (2026-04)

| Область | Состояние |
|---------|-----------|
| Актуальная стратегия продукта | [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md) — этапы **DP-1–DP-5** (деплой, глобальный runtime, TUI как основной `ailit agent`, потоковый вывод, карта промптов, установка одной командой). Таблица статуса — §8 плана. |
| [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md) | Этапы **G–Q** закрыты; документ архивен как ориентир закрытой ветки. |

## Как работать по проекту

1. **Workflow:** обязательный порядок задач и правило «конец workflow → research и постановка» — в [`.cursor/rules/project-workflow.mdc`](.cursor/rules/project-workflow.mdc).
2. **Стратегия и критерии этапов:** [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md) (актуально); закрытая ветка — [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md).
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
