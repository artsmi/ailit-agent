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
  ailit/
  runtime/
  knowledge_refresh/
examples/
  workflows/
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

Нижний runtime слой:

- `providers`, `transport`, нормализация;
- `session` — session loop, бюджет, compaction, shortlist;
- `tool_runtime` — инструменты, permissions, approvals;
- telemetry и пр. — следующие этапы roadmap.

### `tools/workflow_engine/`

Средний слой (этап 6): YAML workflow, `WorkflowEngine`, JSONL события `workflow_run_events_v1`.

### `tools/ailit/`

CLI (`ailit chat`, `ailit agent run`) и Streamlit `chat_app.py`.

### `examples/workflows/`

Примеры workflow для ручного и интеграционного запуска.

### `tools/runtime/`

Local state, events, snapshots, status projection и operator-facing runtime helpers.

### `tools/knowledge_refresh/`

Shortlist и canonical-aware retrieval слой для `context/*`.

## Что остается вне немедленной реализации

На `Этапе 1` не требуется реализовывать весь `tools/*`; достаточно зафиксировать placement и boundaries без двусмысленностей.
