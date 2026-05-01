# Feature: Agent Memory CLI `memory init`

## Что изменилось

- Подкоманда `ailit memory init`, оркестратор и транзакция PAG/KB, shadow journal с merge в канонический journal.
- Режимы лога сессии: каталог `ailit-cli-*` с `legacy.log` и `compact.log` (`CompactObservabilitySink`).

## Верификация

- Финальный gate **11** v2: [`../artifacts/reports/test_runner_final_11.md`](../artifacts/reports/test_runner_final_11.md).

## Пробелы

- Ручной smoke UC-05 (Desktop ↔ тот же корень/namespace) в прогоне **11** не выполнялся (`human_operator`).

**Оглавление канона:** [`../INDEX.md`](../INDEX.md).
