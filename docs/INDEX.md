# Документация `ailit-agent`

## Назначение

Этот каталог фиксирует, как развивать `ailit-agent` как новый runtime core для `ai-multi-agents`, не ломая текущую рабочую систему на базе Cursor runtime.

## Главная идея

На текущем этапе:

- `ai-multi-agents` используется как рабочая мультиагентная оболочка;
- `ailit-agent` строится как новый runtime core;
- разработка идет через задачи из `plan/`;
- migration в новый runtime будет постепенной и контролируемой.

## Основные документы

### Практический запуск разработки через `ai-multi-agents`

- [`runtime-development-with-ai-multi-agents.md`](runtime-development-with-ai-multi-agents.md)

Этот документ отвечает на вопросы:

- как использовать `ai-multi-agents` для разработки `ailit-agent`;
- почему это не ломает текущий рабочий путь через Cursor;
- как давать мультиагентной системе задачи из workflow;
- какой формат итераций использовать.

### Главный roadmap

- [`../plan/agent-core-workflow.md`](../plan/agent-core-workflow.md)

Главный документ для пошаговой разработки runtime и платформы:

- этапы;
- задачи этапов;
- критерии приемки;
- проверки для каждой задачи;
- stage gates.

### Целевая архитектура

- [`../plan/agent-core-architecture.md`](../plan/agent-core-architecture.md)

Фиксирует:

- трехслойную модель `core runtime / workflow layer / project layer`;
- судьбу `orchestrator*.md`;
- локальное хранение;
- визуализацию;
- token/cost governance;
- dynamic agents/workflows.

### Canonical context

- [`../context/INDEX.md`](../context/INDEX.md)
- установка через `scripts/install` (режимы, пути, env): [`../context/proto/install.md`](../context/proto/install.md)

### Память и экономия контекста (канон уровней)

- [`memory-canon.md`](memory-canon.md) — три уровня (сессия `run` / локальный ПК / MCP), глоссарий методик, соотнесение с репозиториями-донорами и планами `workflow-token-economy` / `workflow-hybrid-memory-mcp` / `workflow-memory-3`.

### Реализация AI memory в ailit (снимок + доноры)

- [`ailit-ai-memory-implementation.md`](ailit-ai-memory-implementation.md) — **актуальная** реализация (код, CLI, события), **сопоставление с донорами** (сильные/слабые стороны), ссылки на `plan/`. **Workflow M3** по документации **завершён**; детальная стратегия — в `plan/workflow-memory-3.md` и `plan/m3-*.md`.
- **Namespace при репозитории без `git`:** ветка и стабильный `repo_uri` в политике retrieval слабее, чем при `git init` + `origin` — match по path; см. `memory_preview` / сессию в `ailit chat` и канон уровней в [`memory-canon.md`](memory-canon.md).
- **Граф архитектуры проекта (PAG) + веб-GUI `ailit memory`:** [`../plan/7-workflow-project-architecture-graph.md`](../plan/7-workflow-project-architecture-graph.md) (workflow `arch-graph-7`, постановка; анализ доноров внутри документа).

### Provider layer (код, этап 3)

- реализация: каталог [`../tools/agent_core/`](../tools/agent_core/) (pytest: `python3 -m pytest` из корня репозитория).

### Ручная проверка и CLI (этапы 4–6)

- инструкция: [`../user-test.md`](../user-test.md) (`ailit chat`, `ailit agent run`, DeepSeek);
- workflow engine: [`../tools/workflow_engine/`](../tools/workflow_engine/).

Фиксирует канонические артефакты текущего состояния:

- `context/arch/*`
- `context/proto/*`
- трехслойную модель;
- границы state and persistence;
- local-first storage model и event contract для UI/resume;
- сквозной контракт live интеграционных тестов DeepSeek (`DEEPSEEK_API_KEY`, без секретов в git);
- внешний workflow shell;
- roadmap интерфейсов.

### Стратегия провайдеров

- [`../plan/agent-core-provider-strategy.md`](../plan/agent-core-provider-strategy.md)

Фиксирует:

- подключение `Kimi K2`;
- подключение `DeepSeek`;
- provider abstraction;
- shared transport;
- cost-aware routing;
- strict schema и fallback policy.

### Рабочий workflow этого репозитория (Cursor)

- [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc) — порядок работы по плану для агента Cursor, ссылки на референсы, правило «конец workflow → research и постановка».

### Дизайн (Candy) и `ailit desktop`

- [`../design/INDEX.md`](../design/INDEX.md) — брендбук Candy и границы desktop UI (Workflow 9).
- [`g9-9-release-checklist.md`](g9-9-release-checklist.md) — чеклист готовности релиза Workflow 9 (`ailit desktop`).

### Глобальный CLI, Agent Teams, плагины и human-readable chat

- [`../plan/ailit-global-agent-teams-strategy.md`](../plan/ailit-global-agent-teams-strategy.md)

Фиксирует:

- отвязку `ailit` от клона репозитория (глобальный конфиг, XDG, merge слоёв);
- режимы `ailit chat` / `ailit agent` и требования к UX;
- e2e на материализованных проектах и произвольный ввод задачи;
- этапы G–M с промптами, тестами и критериями приёмки;
- точные ссылки на строки в `claude-code`, `opencode`, `ailit-agent` и образец в `reps-research`.

**Статус:** этапы **G–Q** закрыты; дальнейшая продуктовая ветка вынесена в [`../plan/deploy-project-strategy.md`](../plan/deploy-project-strategy.md).

### Деплой, проекты на диске, TUI как основной агент (актуально)

- [`../plan/deploy-project-strategy.md`](../plan/deploy-project-strategy.md)
- [`../plan/ailit-bash-strategy.md`](../plan/ailit-bash-strategy.md) — bash/shell tools, превью вывода, UX Chat и TUI, этап **H** (сессионный shell)

Фиксирует:

- production-установку и сохранение глобальных настроек при обновлении;
- работу из любого каталога и смену репозитория;
- перенос интерактива в `ailit agent` (TUI по умолчанию), сохранение `ailit agent run`;
- потоковый вывод в chat и TUI;
- карту скрытых промптов и оптимизацию токенов;
- ссылки на `claude-code`, `opencode`, `context-mode` (без опоры на `ai-multi-agents` как референс этой ветки).

### Стратегия верхнего project orchestrator-а

- [`../plan/project-orchestrator-strategy.md`](../plan/project-orchestrator-strategy.md)

Этот документ фиксирует отдельную стратегическую ветку:

- верхний orchestrator проектов;
- intake пользовательской цели;
- milestones и batches;
- human approval gates;
- делегирование в `ai-multi-agents`;
- local-first project state.

## Как этим пользоваться

Правильный порядок чтения и использования:

1. Сначала прочитать [`runtime-development-with-ai-multi-agents.md`](runtime-development-with-ai-multi-agents.md)
2. Затем использовать [`../plan/agent-core-workflow.md`](../plan/agent-core-workflow.md) как основной список задач
3. При необходимости уточнять детали через:
   - [`memory-canon.md`](memory-canon.md) — модель памяти и токен-экономии по уровням
   - [`../plan/agent-core-architecture.md`](../plan/agent-core-architecture.md)
   - [`../plan/agent-core-provider-strategy.md`](../plan/agent-core-provider-strategy.md)
   - [`../plan/deploy-project-strategy.md`](../plan/deploy-project-strategy.md) для текущей ветки деплоя, TUI и промптов
   - [`../plan/ailit-global-agent-teams-strategy.md`](../plan/ailit-global-agent-teams-strategy.md) для закрытой ветки G–Q (глобальный CLI, teams, UX chat)
   - [`../plan/project-orchestrator-strategy.md`](../plan/project-orchestrator-strategy.md) для верхнеуровневой стратегической ветки

## Какой workflow сейчас считается правильным

На текущем этапе рабочий режим такой:

1. `ai-multi-agents` продолжает работать через Cursor runtime.
2. Вы выбираете одну задачу из `plan/agent-core-workflow.md`.
3. Даете ее мультиагентной системе как отдельную feature-итерацию.
4. Реализация идет в `ailit-agent`.
5. После выполнения проходятся критерии приемки и проверки из workflow.
6. Только потом берется следующая задача.

## Локальные репозитории-референсы

Мы берем архитектурные идеи, best practices и отдельные runtime-паттерны из следующих локальных репозиториев:

### `claude-code`

Путь на диске:

- `/home/artem/reps/claude-code`

Оттуда берем:

- явный agent loop;
- tool runtime;
- permission/safety patterns;
- streaming reducer;
- compaction and recovery patterns.

### `opencode`

Путь на диске:

- `/home/artem/reps/opencode`

Оттуда берем:

- provider abstraction;
- session/runtime model;
- typed event/state patterns;
- extensibility boundaries;
- UI-friendly execution patterns.

### Образец плагинов (исследование)

Путь на диске:

- каталог `claude-code-plugins-sample` в локальном клоне `reps-research` (shallow clone коллекции плагинов; структура каталогов для MVP совместимости)

## Текущая стратегическая формула

На текущем этапе:

- `ai-multi-agents` = workflow shell
- `ailit-agent` = runtime core

Это основной режим работы, который и должен использоваться для разработки нового runtime.

## Что считается результатом готовности документации

Документация считается приведенной в рабочее состояние, если:

1. можно открыть `INDEX.md` и понять, в каком порядке читать документы;
2. можно взять задачу из `plan/agent-core-workflow.md`;
3. можно передать ее в `ai-multi-agents`;
4. можно развивать `ailit-agent`, не ломая текущий Cursor-based путь;
5. можно опираться на локальные референсы `claude-code` и `opencode` без повторного исследования с нуля.
