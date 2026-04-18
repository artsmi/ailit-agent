# External Workflow And CLI

## Назначение

Зафиксировать текущую внешнюю схему, в которой `ai-multi-agents` используется как workflow shell, а `ailit-agent` развивается как новый runtime core.

## Текущее состояние

Сейчас рабочая схема выглядит так:

1. `ai-multi-agents` продолжает работать через `Cursor` runtime.
2. Он используется как orchestration shell для разработки `ailit-agent`.
3. Задачи берутся из `plan/agent-core-workflow.md`.
4. Каждая задача выполняется как отдельная feature-итерация.

## Целевой переход

Переход должен быть постепенным:

1. Сначала развивается `ailit-agent` как отдельный runtime substrate.
2. Затем появляется compatibility adapter.
3. Потом включается hybrid mode.
4. И только после этого возможен controlled rollout нового runtime в `ai-multi-agents`.

## Важное ограничение

На текущем этапе нельзя ухудшать рабочий путь `ai-multi-agents` через `Cursor`.

## Что должно стать протоколом взаимодействия позже

Будущий compatibility layer должен формализовать:

- вход workflow task;
- role and stage metadata;
- artifacts in and artifacts out;
- lifecycle events;
- blocked and resume semantics;
- usage and cost telemetry.
