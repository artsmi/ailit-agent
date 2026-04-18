# Context Index

## Назначение

`context/*` хранит каноническое знание о текущей платформенной стратегии `ailit-agent`.

На `Этапе 1` здесь зафиксированы:

- трехслойная архитектура;
- layout репозитория;
- границы state and persistence;
- внешний workflow shell;
- roadmap интерфейсов целевой платформы.

На `Этапе 2` добавлены канонические контракты local-first runtime:

- модель локального хранения;
- единый event contract;
- operator-first UI map;
- сквозной контракт live интеграционных тестов DeepSeek (без хранения секретов в git).

На `Этапе 3` в репозитории появилась реализация provider layer:

- Python-пакет `tools/agent_core` (см. `context/arch/repository-layout.md`).

На `Этапе 4` добавлен слой **tool runtime** (`tools/agent_core/tool_runtime/`): контракт инструмента, permissions, approvals, исполнитель.

На `Этапе 5` добавлен **session loop** (`tools/agent_core/session/`): `SessionRunner`, бюджет, compaction, keyword shortlist, `StreamReducer`.

На `Этапе 6` добавлены **workflow_engine**, CLI **`ailit`**, пример [`examples/workflows/minimal.yaml`](../examples/workflows/minimal.yaml) и руководство [`user-test.md`](../user-test.md).

## Разделы

### `arch/`

- `system-overview.md`
- `repository-layout.md`
- `state-and-persistence.md`
- `runtime-local-storage-model.md`
- `visual-monitoring-ui-map.md`

### `proto/`

- `external-workflow-and-cli.md`
- `target-platform-interfaces-roadmap.md`
- `runtime-event-contract.md`
- `deepseek-integration-test-contract.md`

## Главный принцип

`context/*` остается canonical source of truth о проекте.  
Runtime state и events не подменяют эти документы.
