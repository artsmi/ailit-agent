# ailit-agent

Репозиторий CLI и runtime-ядра **`ailit`**: глобальный конфиг, `ailit chat`, `ailit agent`, TUI (`ailit tui`), workflow engine и `agent_core`.

## Статус разработки (2026-04)

| Область | Состояние |
|---------|-----------|
| Актуальная стратегия продукта | [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md): этапы **DP-1…DP-5** закрыты; проект перешёл в **этап тестирования** (сбор багов → фиксы). |
| Bash / shell в runtime | [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md): **B–E**, **D.4**, **F.1–F.2** — `run_shell` и file tools включены по умолчанию, `bash:` в `project.yaml`, **H** — сессионный shell позже. |
| [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md) | Этапы **G–Q** закрыты; документ архивен как ориентир закрытой ветки. |
| Токен-экономия и внешняя память (ветка) | **Порядок:** сначала [`plan/workflow-token-economy-recipe.md`](plan/workflow-token-economy-recipe.md) (этапы **TE-0…TE-5**, постановка и история), затем по критерию перехода — [`plan/workflow-hybrid-memory-mcp.md`](plan/workflow-hybrid-memory-mcp.md) (этапы **H0…H4**, интеграция в `ailit`), затем [`plan/workflow-memory-3.md`](plan/workflow-memory-3.md) (этапы **M3-0…M3-5**, сравнительные улучшения и следующий слой memory governance / retrieval). |

## Как работать по проекту

1. **Workflow:** обязательный порядок задач и правило «конец workflow → research и постановка» — в [`.cursor/rules/project-workflow.mdc`](.cursor/rules/project-workflow.mdc).
2. **Стратегия и критерии этапов:** [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md) (актуально); bash/shell — [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md); закрытая ветка — [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md).
3. **Токен-экономия и память (если ведёте эту ветку):** строго **1 → 2 → 3**: [`plan/workflow-token-economy-recipe.md`](plan/workflow-token-economy-recipe.md), затем [`plan/workflow-hybrid-memory-mcp.md`](plan/workflow-hybrid-memory-mcp.md), затем [`plan/workflow-memory-3.md`](plan/workflow-memory-3.md) (см. критерии перехода и предусловия в самих документах).
4. **Оглавление документации:** [`docs/INDEX.md`](docs/INDEX.md).

## Установка и быстрая проверка

Из корня клона:

```bash
./scripts/install          # prod: venv в ~/.local/share/ailit (см. план DP-5)
# или:  ./scripts/install dev    # editable + .venv в клоне
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
