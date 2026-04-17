# Разработка `ailit-agent` через `ai-multi-agents`

## Цель документа

Зафиксировать рабочую модель, в которой:

- `ai-multi-agents` продолжает работать через `Cursor` runtime;
- `ailit-agent` разрабатывается как новый runtime core;
- текущая рабочая схема `ai-multi-agents` не ломается;
- development идет через `plan`-документы и последовательные workflow-задачи.

## Короткий ответ: это сработает?

Да, это рабочая стратегия.

И это лучший путь на текущем этапе, потому что он позволяет:

- сохранить рабочий `ai-multi-agents` как есть;
- использовать его как уже готовую мультиагентную оболочку;
- развивать `ailit-agent` отдельно и спокойно;
- подключать новый runtime постепенно, а не через резкую замену.

## Роли двух репозиториев

### `ai-multi-agents`

Роль этого репозитория:

- workflow shell;
- policy layer;
- role pipeline;
- canonical knowledge workflow;
- current orchestration through Cursor runtime;
- начальная визуализация межагентного взаимодействия;
- исполнительный контур для разработки нового runtime.

Путь на диске:

- `/home/artem/reps/ai-multi-agents`

### `ailit-agent`

Роль этого репозитория:

- `core runtime`;
- provider abstraction;
- tool runtime;
- session loop;
- local state/event substrate;
- база для визуализации;
- база для token/cost governance;
- будущий runtime для `ai-multi-agents`.

Путь на диске:

- `/home/artem/reps/ailit-agent`

## Правильная модель взаимодействия

Не нужно пытаться сначала переписать `ai-multi-agents`.

Правильная схема такая:

1. `ai-multi-agents` остается рабочим workflow shell.
2. `ailit-agent` развивается как отдельный runtime core.
3. Для разработки `ailit-agent` используется текущая мультиагентная система `ai-multi-agents`.
4. По мере зрелости `ailit-agent` появляется compatibility adapter.
5. Только потом начинается controlled rollout нового runtime внутрь `ai-multi-agents`.

## Что важно не делать

### Не делать сейчас

- не ломать текущий pipeline `ai-multi-agents`;
- не переносить всю логику `orchestrator*.md` в код одним шагом;
- не пытаться сразу заменить Cursor runtime в рабочем сценарии;
- не переписывать `rules/*` до появления зрелого workflow/runtime substrate.

### Что делать сейчас

- использовать `ai-multi-agents` как development shell;
- использовать `plan/agent-core-workflow.md` как основной roadmap;
- выполнять roadmap маленькими feature-итерациями;
- строить `ailit-agent` как новый нижний слой;
- поддерживать текущую рабочую схему в `ai-multi-agents` без деградации.

## Какой workflow использовать

Главный workflow для разработки runtime:

- `plan/agent-core-workflow.md`

Поддерживающие документы:

- `plan/agent-core-architecture.md`
- `plan/agent-core-provider-strategy.md`

### Как с ним работать practically

Для каждой итерации разработки:

1. Выбирается один task из `plan/agent-core-workflow.md`.
2. Этот task передается в `ai-multi-agents` как отдельная feature-задача.
3. `ai-multi-agents` работает через текущий Cursor runtime.
4. Изменения делаются только в `ailit-agent`.
5. После завершения task проходится проверка из workflow.
6. Только после этого берется следующий task.

## Рекомендуемый режим работы

### Единица работы

Правильная единица работы:

- `одна задача из workflow = одна feature-итерация`

Не надо давать мультиагентной системе сразу целый этап.

### Размер итерации

Итерация должна быть:

- маленькой;
- проверяемой;
- обратимой;
- с понятным acceptance criterion;
- с понятной проверкой после выполнения.

### Роль человека

Человек здесь нужен как:

- stage gate reviewer;
- приоритизатор следующей задачи;
- контролер scope;
- принимающая сторона по каждой маленькой итерации.

## Как формулировать промпты для `ai-multi-agents`

Правильный формат:

1. Указать, что `ai-multi-agents` работает как workflow shell.
2. Указать, что реализация идет в `ailit-agent`.
3. Указать конкретный task из `plan/agent-core-workflow.md`.
4. Указать, что текущий рабочий путь `ai-multi-agents` через Cursor ломать нельзя.
5. Указать, что нужно пройти критерии приемки и проверку из документа.

## Шаблон промпта для очередной итерации

```text
Мы развиваем `/home/artem/reps/ailit-agent` как новый runtime core для системы `/home/artem/reps/ai-multi-agents`.

Текущий `ai-multi-agents` продолжает работать через Cursor runtime и не должен деградировать.

Возьми из `plan/agent-core-workflow.md` следующую задачу:
<вставить точное название задачи>

Контекст:
- `ai-multi-agents` сейчас используется как workflow shell
- `ailit-agent` развивается как runtime core
- нельзя ломать текущий рабочий путь `ai-multi-agents`
- нужно работать только в рамках текущей задачи, без расползания scope

Сделай:
1. Реализацию задачи
2. Проверку по критериям приемки
3. Проверку по разделу "Тесты"
4. Краткий отчет: что сделано, что проверено, что осталось
```

## Какой порядок задач использовать

Строго идти сверху вниз по:

- `plan/agent-core-workflow.md`

То есть:

1. сначала Этап 1;
2. затем Этап 2;
3. затем Этап 3;
4. и так далее.

Нельзя перескакивать к поздним задачам, если не закрыты ранние зависимости.

## Какие документы давать мультиагентной системе

### Всегда давать

- `plan/agent-core-workflow.md`

### Давать по необходимости

- `plan/agent-core-architecture.md`
- `plan/agent-core-provider-strategy.md`
- этот документ

### Не давать без необходимости

- весь набор документов сразу, если задача узкая;
- лишний контекст, не относящийся к текущему task.

## Почему это должно сработать

Потому что у вас уже есть сильная система orchestration и role-based execution в `ai-multi-agents`.

Ее не нужно выбрасывать.

Нужно использовать ее как:

- planning shell;
- execution shell;
- review shell;
- knowledge shell;

для поэтапной сборки собственного runtime.

То есть `ai-multi-agents` сначала помогает вам построить новый runtime для самого себя.

## Что будет считаться успехом

Успех на текущем этапе выглядит так:

1. `ai-multi-agents` продолжает стабильно работать через Cursor runtime.
2. `ailit-agent` постепенно получает:
   - provider layer;
   - tool runtime;
   - session loop;
   - state/events;
   - workflow substrate.
3. Появляется совместимый adapter.
4. Новый runtime можно включать выборочно.
5. Только потом делается controlled migration.

## Итоговая формула

На текущем этапе правильная формула такая:

- `ai-multi-agents` = workflow shell
- `ailit-agent` = runtime core

Именно в таком режиме вы можете уже сейчас запускать мультиагентную систему для разработки собственного runtime без разрушения текущей рабочей схемы.
