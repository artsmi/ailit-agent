# System Overview

## Назначение

`ailit-agent` развивается как локальная AI-agent platform, которая встраивается под `ai-multi-agents`, не ломая его текущий рабочий путь через `Cursor`.

На текущем этапе система должна пониматься не как "еще один chat runtime", а как платформа из трех слоев:

1. `core runtime`
2. `workflow layer`
3. `project layer`

## Три слоя

### `core runtime`

Нижний исполняющий слой отвечает за:

- provider abstraction;
- session loop;
- tool runtime;
- streaming;
- permissions;
- retries;
- token and cost accounting;
- hooks в local state и events.

### `workflow layer`

Средний слой отвечает за:

- workflow graph;
- stage transitions;
- blocked and resume semantics;
- machine-readable orchestration;
- artifact lifecycle;
- compatibility bridge к `ai-multi-agents`.

### `project layer`

Верхний слой отвечает за:

- `rules/*` как policy layer;
- `context/*` как canonical knowledge;
- project-specific agents;
- project-specific workflows;
- project configuration.

## Роль `ai-multi-agents`

`ai-multi-agents` на текущем этапе остается:

- workflow shell;
- policy shell;
- development shell для сборки нового runtime;
- текущим рабочим контуром через `Cursor`.

## Главный принцип

`machine logic` должна постепенно переезжать в `core runtime` и `workflow layer`, а `policy logic` должна оставаться в `rules/*`.
