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

### Глобальный CLI, Agent Teams, плагины и human-readable chat

- [`../plan/ailit-global-agent-teams-strategy.md`](../plan/ailit-global-agent-teams-strategy.md)

Фиксирует:

- отвязку `ailit` от клона репозитория (глобальный конфиг, XDG, merge слоёв);
- режимы `ailit chat` / `ailit agent` и требования к UX;
- e2e на материализованных проектах и произвольный ввод задачи;
- этапы G–M с промптами, тестами и критериями приёмки;
- точные ссылки на строки в `claude-code`, `opencode`, `ailit-agent` и образец в `reps-research`.

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
   - [`../plan/agent-core-architecture.md`](../plan/agent-core-architecture.md)
   - [`../plan/agent-core-provider-strategy.md`](../plan/agent-core-provider-strategy.md)
   - [`../plan/ailit-global-agent-teams-strategy.md`](../plan/ailit-global-agent-teams-strategy.md) для глобального CLI, команд агентов и UX chat
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
