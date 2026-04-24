# ailit-agent

Репозиторий CLI и runtime-ядра **`ailit`**: глобальный конфиг, `ailit chat`, `ailit agent`, TUI (`ailit tui`), workflow engine и `agent_core`.

## Статус разработки (2026-04)

| Область | Состояние |
|---------|-----------|
| Актуальная стратегия продукта | [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md): этапы **DP-1…DP-5** закрыты; проект перешёл в **этап тестирования** (сбор багов → фиксы). |
| Bash / shell в runtime | [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md): **B–E**, **D.4**, **F.1–F.2** — `run_shell` и file tools включены по умолчанию, `bash:` в `project.yaml`, **H** — сессионный shell позже. |
| [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md) | Этапы **G–Q** закрыты; документ архивен как ориентир закрытой ветки. |
| Токен-экономия и внешняя память (ветка) | **Порядок:** [`plan/workflow-token-economy-recipe.md`](plan/workflow-token-economy-recipe.md) (TE) → [`plan/workflow-hybrid-memory-mcp.md`](plan/workflow-hybrid-memory-mcp.md) (H0–H4) → [`plan/workflow-memory-3.md`](plan/workflow-memory-3.md) (M3, закрыто) → [**`plan/workflow-memory-4.md`**](plan/workflow-memory-4.md) (**M4:** runtime‑память + loop‑guards; M4‑1.2 / M4‑3.2 закрыты). |
| Режимы/permissions (как у доноров) | [**`plan/5-workflow-perm.md`**](plan/5-workflow-perm.md) — **perm‑5** реализован (классификатор, enforcement, UI not_sure, `ailit agent run --perm-tool-mode`, срез `subsystems.perm_mode`). |
| **Чтение + память (read‑6)** | [**`plan/6-read-improve-strategy.md`**](plan/6-read-improve-strategy.md) — **read‑6 закрыт:** протокол grep→range-read, `read_symbol` (.py), метрика duplicate read, KB-first hints при `memory.enabled`, прозрачность N/100 в чате, R4.4 design note. Далее — research/постановка следующей ветки по [workflow](.cursor/rules/project-workflow.mdc). |

## Как работать по проекту

1. **Workflow:** обязательный порядок задач и правило «конец workflow → research и постановка» — в [`.cursor/rules/project-workflow.mdc`](.cursor/rules/project-workflow.mdc).
2. **Стратегия и критерии этапов:** [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md) (актуально); bash/shell — [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md); закрытая ветка — [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md).
3. **Токен-экономия и память:** ветка M3 закрыта; runtime M4 — [`plan/workflow-memory-4.md`](plan/workflow-memory-4.md). **Текущая доработка read/KB** — [`plan/6-read-improve-strategy.md`](plan/6-read-improve-strategy.md). Сводка M3: [`docs/ailit-ai-memory-implementation.md`](docs/ailit-ai-memory-implementation.md).
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
