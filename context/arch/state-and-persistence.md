# State And Persistence

## Назначение

Зафиксировать, какие данные должны жить в local-first runtime слое, а какие должны оставаться в canonical project knowledge.

## Главный принцип

Нельзя смешивать runtime state и `context/*`.

`context/*` остается главным источником правды о проекте.  
Runtime state, event log и snapshots существуют рядом с ним, но не заменяют его.

## Что относится к runtime persistence

В local-first runtime layer должны жить:

- `run_state`;
- event log;
- snapshots;
- usage and cost telemetry;
- episodic summaries;
- workflow execution state;
- approval and blocked state.

## Что относится к canonical knowledge

В canonical knowledge layer должны жить:

- архитектурные документы;
- протокольные документы;
- knowledge about project behavior;
- project conventions;
- зафиксированные проектные решения.

## Memory boundaries

Нужно разделять:

1. `canonical project memory`
2. `retrieval memory`
3. `episodic runtime memory`
4. `working session memory`
5. `procedural memory`

## Практический вывод для `Этапа 1`

На этом этапе важно только зафиксировать границы:

- runtime state не становится новой заменой `context/*`;
- `knowledge_refresh` использует `context/*`, а не runtime snapshots как source of truth;
- будущая визуализация должна питаться из runtime events и snapshots, а не из ad-hoc логов.
