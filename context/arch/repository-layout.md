# Repository Layout

## Назначение

Этот документ фиксирует целевое размещение основных подсистем `ailit-agent` после нормализации `Этапа 1`.

## Целевое размещение

```text
docs/
plan/
context/
  arch/
  proto/
tools/
  agent_core/
  workflow_engine/
  runtime/
  knowledge_refresh/
```

## Обязанности каталогов

### `docs/`

Документы о стратегии, способе запуска разработки через `ai-multi-agents` и общем порядке чтения документации.

### `plan/`

Roadmap и стратегические документы:

- основной workflow развития платформы;
- архитектура;
- стратегия провайдеров;
- стратегия верхнего project orchestrator.

### `context/arch/`

Каноническая архитектурная фиксация:

- трехслойная модель;
- layout;
- state and persistence boundaries.

### `context/proto/`

Протокольные и интерфейсные фиксации:

- как внешний workflow shell взаимодействует с runtime;
- roadmap интерфейсов целевой платформы.

### `tools/agent_core/`

Нижний runtime слой (после `Этапа 3` — провайдеры и транспорт):

- `providers`, `transport`, нормализация OpenAI-совместимых ответов;
- session, tools, permissions, telemetry — следующие этапы roadmap.

### `tools/workflow_engine/`

Будущий средний слой:

- graph;
- executor;
- compatibility;
- artifact lifecycle.

### `tools/runtime/`

Local state, events, snapshots, status projection и operator-facing runtime helpers.

### `tools/knowledge_refresh/`

Shortlist и canonical-aware retrieval слой для `context/*`.

## Что остается вне немедленной реализации

На `Этапе 1` не требуется реализовывать весь `tools/*`; достаточно зафиксировать placement и boundaries без двусмысленностей.
