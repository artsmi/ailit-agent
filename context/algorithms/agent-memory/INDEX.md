# AgentMemory — целевой алгоритм (пакет)

**Статус:** `approved` — явное подтверждение пользователя в чате Cursor (2026-05-03): «подтверждаю, продолжай работу». Product code в этом workflow не менялся.

**Источник постановки:** `context/artifacts/target_doc/original_user_request.md`, синтез `context/artifacts/target_doc/synthesis.md`, current-state отчёты `context/artifacts/target_doc/current_state/*.md`.

**Черновик для gate `22`:** `context/artifacts/target_doc/target_algorithm_draft.md` (обязательный provenance marker `Produced by: 21_target_doc_author`).

## Назначение

Зафиксировать **канон целевого поведения** модуля AgentMemory: кто инициирует запрос, как runtime владеет БД/обходом/валидацией, как LLM работает только в закрытом JSON-протоколе, какие типы рёбер графа памяти допустимы, какие события видят CLI/Desktop/broker, и когда допустимы `complete` / `partial` / `blocked`.

## Части пакета

| Файл | Содержание |
|------|------------|
| [`runtime-flow.md`](runtime-flow.md) | Целевая state machine, intake → DB → LLM → slice → обход → nodes/links → summarization → finish → bounded partial; **нормативный** выбор: явные состояния + маппинг journal. |
| [`memory-graph-links.md`](memory-graph-links.md) | Типы связей (`contains`, `imports`, …), evidence/confidence, runtime validation vs LLM candidates, baseline `derived_from`. |
| [`llm-commands.md`](llm-commands.md) | Команды runtime→LLM: envelope vs `plan_traversal.actions`, repair как фаза, целевая `propose_links`. |
| [`prompts.md`](prompts.md) | Промпты по состояниям/фазам, multi-language/`file_kind`, запреты CoT/raw dumps. |
| [`external-protocol.md`](external-protocol.md) | Инициаторы (AgentWork, CLI, broker client), envelope запроса, события wire, CLI `ailit memory init`. |
| [`failure-retry-observability.md`](failure-retry-observability.md) | Матрица failure/retry, caps→partial, журнал/trace/compact, acceptance tests (фактические имена pytest). |

## Трассировка OR-001…OR-015

| ID | Где закрыто |
|----|-------------|
| OR-001 | Этот `INDEX.md` + корневой [`../INDEX.md`](../INDEX.md) |
| OR-002 | `runtime-flow.md`, `failure-retry-observability.md` |
| OR-003 | `memory-graph-links.md`, `runtime-flow.md` |
| OR-004 | `external-protocol.md`, `runtime-flow.md` |
| OR-005 | `runtime-flow.md` |
| OR-006 | `llm-commands.md` |
| OR-007 | `memory-graph-links.md` |
| OR-008 | `prompts.md`, `llm-commands.md` |
| OR-009 | `prompts.md` |
| OR-010 | `external-protocol.md`, `failure-retry-observability.md` |
| OR-011 | `external-protocol.md`, `failure-retry-observability.md` |
| OR-012 | `runtime-flow.md`, `external-protocol.md` |
| OR-013 | `failure-retry-observability.md` |
| OR-014 | Примеры в draft + краткие ссылки здесь в разделе Examples index ниже |
| OR-015 | `failure-retry-observability.md` (acceptance), этот индекс |

## Индекс примеров (OR-014)

Полные сценарии в `target_algorithm_draft.md` §Examples; смысловые якоря:

1. Happy AgentWork — подбор файлов для изменения сервера.
2. CLI `ailit memory init` — default goal, progress, итог.
3. Cross-language — Go/C++/TS без Python-only допущений.
4. Documentation — `references` из markdown heading к коду.
5. Failure/recovery — invalid JSON + repair, missing file → partial.

## Current reality vs target

В каждом крупном файле пакета: краткий блок **Current reality** со ссылкой на `context/artifacts/target_doc/current_state/*.md`, затем **Target behavior**. Расхождения, уже описанные в синтезе (CLI `blocked`, grants enforcement, A-id drift, D-OBS vs journal), помечаются как **`implementation_backlog`** до выравнивания кода.
