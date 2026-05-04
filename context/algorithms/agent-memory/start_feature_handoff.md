# start-feature handoff: agent-memory

## Recommended First Slices

| ID | Slice | Why First | Target Doc Sections | Must Not Include |
|----|-------|-----------|---------------------|------------------|
| S1 | LLM command envelope + repair semantics + `AgentMemoryCommandName` vs planner actions; границы payload для `plan_traversal` / `finish_decision` / целевой `propose_links` | Снижает drift с контрактом pipeline и W14 | `llm-commands.md`; фрагменты `runtime-flow.md`, `failure-retry-observability.md` | Полный graph engine и все prompt-тела |
| S2 | Каталог внешних событий: discriminant `event_type`, compact vs verbose, durable vs ephemeral; маппинг stdout / journal / compact.log | Развязывает CLI/Desktop от внутренних шагов | `external-protocol.md`, `failure-retry-observability.md` | Полные per-event JSON-schema в одном PR без утверждённого порядка |
| S3 | Typed link validation + `agent_memory_link_candidate.v1` vs текущие `pag_edges` / pending | Фиксирует data model до масштабного prompt work | `memory-graph-links.md` | Все варианты текстов промптов |
| S4 | `ailit memory init`: целевой контракт exit/summary vs текущий `aborted` | Узкий пользовательский путь | `external-protocol.md` §CLI; `failure-retry-observability.md` при необходимости | Полный broker API |
| S5 | Failure/retry, caps→partial, правила статуса `agent_memory_result.v1` | Закрывает OR-012/OR-013 до расширения LLM | `failure-retry-observability.md` | Новые LLM провайдеры |

## Forbidden Broad Scope

- Одна задача «реализовать весь AgentMemory» или «выровнять весь граф + все события + CLI + grants» без нарезки S1–S5.
- Подмена канона `plan/14-agent-memory-runtime.md` вместо пакета `context/algorithms/agent-memory/` как SoT для целевого поведения.
- Добавление raw prompts / CoT в broker-facing compact channel (нарушает `prompts.md` и draft anti-patterns).

## Required Inputs For start-feature

- target docs: `context/algorithms/agent-memory/INDEX.md` и связанные файлы;


## Required Final Evidence

- Pytest: имена из `failure-retry-observability.md` §Acceptance (venv проекта).
- Journal/compact: отсутствие raw prompts в compact channel там, где канон требует compact (см. `memory_journal_trace_observability` в current_state).
- Ручной smoke (после реализации целевого UX): `ailit memory init ./` — ожидаемые `complete`/`partial`/целевой `blocked` и маркер `memory.result.returned` по тексту канона.

## Known Gaps To Consider

| ID | Gap | Type | Severity | Can Approve Without Fix? | Waiver Needed | Follow-up |
|----|-----|------|----------|--------------------------|---------------|-----------|
| G-IMPL-1 | CLI UX: целевой видимый `blocked` vs текущий `aborted` / exit mapping | implementation_backlog | major | да (target ≠ current явно) | нет | Slice S4 + код (`agent_memory_entrypoints_cli.md` F-CLI-3) |
| G-IMPL-2 | `grants` в ответе не подключены к read enforcement в AgentWork | implementation_backlog | major | да | нет | Slice S2/S5 + `agent_work_memory_integration.md` F-AW-4 |
| G-IMPL-3 | Два шаблона A `node_id` (indexer vs W14) | implementation_backlog | major | да | нет | Отдельная миграция / канон A-id |
| G-IMPL-4 | Целевой envelope `propose_links` + строгая валидация vs текущий реестр | implementation_backlog | major | да | нет | Slice S1/S3 |
| G-IMPL-5 | D-OBS-1 vs полный internal journal catalog | implementation_backlog | minor | да | нет | Slice S2 |
| G-DOC-1 | Нет полноформатных отдельных JSON примеров на каждую LLM envelope-команду (`finish_decision`, `propose_links`) | doc_incomplete | minor | да | нет | Slice S1 или post-approval добивка `21` |
| G-DOC-2 | Нет отдельного полного schema-like блока payload на каждый `event_type` | doc_incomplete | minor | да | нет | Slice S2 |
| G-NAMING-1 | Текст OR упоминает `user_request` как source; `created_by` в candidate — три enum значения; противоречие не разведено | naming_tbd | minor | да | нет | Уточнить enum при первом link UX slice |
| G-VERIFY-1 | Ручной smoke `ailit memory init` доказывает end-to-end только после реализации target UX | verification_gap | info | да | нет | `11_test_runner` + human smoke |
