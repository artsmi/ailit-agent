# ailit-agent

Репозиторий CLI и runtime-ядра **`ailit`**: глобальный конфиг, продуктовый UI **`ailit desktop`** (Linux), legacy `ailit chat`, `ailit agent`, TUI (`ailit tui`), workflow engine и `agent_core`.

## Статус разработки (2026-04)

| Область | Состояние |
|---------|-----------|
| Актуальная стратегия продукта | [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md): этапы **DP-1…DP-5** закрыты; проект перешёл в **этап тестирования** (сбор багов → фиксы). |
| Bash / shell в runtime | [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md): **B–E**, **D.4**, **F.1–F.2** — `run_shell` и file tools включены по умолчанию, `bash:` в `project.yaml`, **H** — сессионный shell позже. |
| [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md) | Этапы **G–Q** закрыты; документ архивен как ориентир закрытой ветки. |
| Токен-экономия и внешняя память (ветка) | **Порядок:** [`plan/workflow-token-economy-recipe.md`](plan/workflow-token-economy-recipe.md) (TE) → [`plan/workflow-hybrid-memory-mcp.md`](plan/workflow-hybrid-memory-mcp.md) (H0–H4) → [`plan/workflow-memory-3.md`](plan/workflow-memory-3.md) (M3, закрыто) → [**`plan/workflow-memory-4.md`**](plan/workflow-memory-4.md) (**M4:** runtime‑память + loop‑guards; M4‑1.2 / M4‑3.2 закрыты). |
| Режимы/permissions (как у доноров) | [**`plan/5-workflow-perm.md`**](plan/5-workflow-perm.md) — **perm‑5** реализован (классификатор, enforcement, UI not_sure, `ailit agent run --perm-tool-mode`, срез `subsystems.perm_mode`). |
| **Чтение + память (read‑6)** | **Закрыто:** протокол grep→range-read, `read_symbol` (.py), метрика duplicate read, KB-first hints при `memory.enabled`, прозрачность N/100 в чате, R4.4 digest после `kb_fetch`. |
| **Граф архитектуры проекта + GUI «ailit memory» (workflow 7)** | [**`plan/7-workflow-project-architecture-graph.md`**](plan/7-workflow-project-architecture-graph.md) — **закрыто:** PAG, автоиндексация, `ailit memory`, `AgentMemory` / `AgentWork`, post-edit sync. |
| **Low-level agents runtime + broker supervisor (workflow 8)** | [**`plan/8-agents-runtime.md`**](plan/8-agents-runtime.md) — **закрыто:** реализованы этапы **G8.0–G8.8** (supervisor/broker/subprocess agents, `MemoryGrant` enforcement, `ailit chat` client/viewer + trace tab, `scripts/install` с `systemd --user`, e2e readiness/деградации). |
| **Standalone UI `ailit desktop` (workflow 9)** | [**`plan/9-ailit-ui.md`**](plan/9-ailit-ui.md) — **закрыт (G9.9):** Linux-only Electron, `ailit project add`, runtime bridge, отчёты MD/JSON, PAG graph. Чеклист: [`docs/g9-9-release-checklist.md`](docs/g9-9-release-checklist.md). |
| **Context Ledger + Memory 3D highlights (workflow 10)** | [**`plan/10-context-ledger-memory-highlights.md`**](plan/10-context-ledger-memory-highlights.md) — **закрыто (G10.8):** `AgentMemory` actor, Context Fill, D-level compact/restore и Memory 3D highlights по нодам, реально попавшим в prompt. |
| **AgentMemory LLM + journal (workflow 11)** | [**`plan/11-agent-memory-llm-journal.md`**](plan/11-agent-memory-llm-journal.md) — **активно:** G11.4 добавляет query-driven PAG growth: AgentMemory индексирует только выбранные под запрос файлы/ranges и пишет memory.index.* journal rows. |

## Как работать по проекту

1. **Workflow:** обязательный порядок задач и правило «конец workflow → research и постановка» — в [`.cursor/rules/project-workflow.mdc`](.cursor/rules/project-workflow.mdc).
2. **Стратегия и критерии этапов:** [`plan/deploy-project-strategy.md`](plan/deploy-project-strategy.md) (актуально); bash/shell — [`plan/ailit-bash-strategy.md`](plan/ailit-bash-strategy.md); закрытая ветка — [`plan/ailit-global-agent-teams-strategy.md`](plan/ailit-global-agent-teams-strategy.md).
3. **Workflow 11 (`AgentMemory LLM + journal`)** — активная постановка в [`plan/11-agent-memory-llm-journal.md`](plan/11-agent-memory-llm-journal.md). Workflow 10 закрыт по [`plan/10-context-ledger-memory-highlights.md`](plan/10-context-ledger-memory-highlights.md). Токен-экономия и память: M3 закрыта; runtime M4 — [`plan/workflow-memory-4.md`](plan/workflow-memory-4.md). Сводка M3: [`docs/ailit-ai-memory-implementation.md`](docs/ailit-ai-memory-implementation.md).
4. **Оглавление документации:** [`docs/INDEX.md`](docs/INDEX.md).

## Установка и быстрая проверка

Из корня клона:

```bash
./scripts/install          # prod: venv в ~/.local/share/ailit (см. план DP-5)
# или:  ./scripts/install dev    # editable + .venv в клоне
# при необходимости: export PATH="${HOME}/.local/bin:${PATH}"
ailit --help
```

Начиная с [`workflow 8`](plan/8-agents-runtime.md), `scripts/install` должен также устанавливать и обновлять user-service runtime supervisor:

```bash
systemctl --user status ailit.service
journalctl --user -u ailit.service -f
```

### `ailit desktop` и проекты (workflow 9)

- Реестр проектов **глобальный**: `~/.ailit/config.yaml` (active) и `~/.ailit/projects/<project_id>/config.yaml` на проект. В каталоге репозитория **не** создаётся `.ailit` для registry.
- Регистрация: `ailit project add` (текущий каталог) или `ailit project add /abs/path`.
- Индексация PAG для памяти: `ailit memory index --project-root PATH` (подсказка печатается после `project add`).
- Запуск UI: после `./scripts/install` — `ailit desktop`; без собранного AppImage — `ailit desktop --dev` из клона (нужен Node.js, каталог `desktop/`).
- Runtime: `ailit runtime status` (если сокета нет — в stderr подсказки `systemctl` / `journalctl` для `ailit.service`).

**Диагностика desktop:** нет бинарника в `~/.local/share/ailit/desktop/ailit-desktop.AppImage` — повторить `./scripts/install`, либо `ailit desktop --dev`. Переменная `AILIT_INSTALL_PREFIX` задаёт префикс, как в `scripts/install`.

TUI (нужен extra `[tui]`):

```bash
pip install -e '.[tui]'
ailit tui --provider mock
```

Тесты (без e2e, если в окружении нет зависимостей вроде `httpx` для полного прогона):

```bash
PYTHONPATH=tools python3 -m pytest -q --ignore=tests/e2e/
```
