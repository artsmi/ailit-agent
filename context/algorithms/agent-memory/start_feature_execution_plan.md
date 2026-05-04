# План выполнения start-feature / start-fix: AgentMemory

Produced by: 24_start_feature_execution_planner

Этот файл — **долгоживущий** артефакт в `context/algorithms/agent-memory/`. Каталог
`context/artifacts/target_doc/` может быть удалён; ниже в приложениях перенесены **полные копии**
ключевых документов gate и исполненных research waves (JSON), чтобы не потерять контекст.

## Назначение

- Дать `01_orchestrator` / человеку **порядок работ** после утверждения канона.
- Зафиксировать **риски** неверной реализации и типичные отклонения от контракта.
- Согласовать с pipeline: читать вместе с `INDEX.md`, `runtime-flow.md`, …; slices S1–S5 не смешивать.

## Входы после удаления `context/artifacts/target_doc`

Использовать:

1. Пакет `context/algorithms/agent-memory/*.md` (канон поведения).
2. **Этот файл** — план, риски и замороженные копии gate/research/draft.

## Порядок выполнения для start-feature / start-fix

| Шаг | Кто | Действие | Зависит от |
|-----|-----|----------|------------|
| 1 | Человек / `01` | Прочитать `INDEX.md`, этот план, приложения A–H. | — |
| 2 | `02_analyst` | ТЗ и контракт задачи только в терминах канона и OR-id из приложения G. | шаг 1 |
| 3 | `06_planner` | Разбить на задачи по **S1→S5** (приложение B); одна задача не покрывает весь граф + CLI + grants. | шаг 2 |
| 4 | `08_developer` | Реализация slice; не подменять `plan/14` каноном поведения (см. приложение B Forbidden). | шаг 3 |
| 5 | `11_test_runner` | Pytest имена из `failure-retry-observability.md` §Acceptance; venv проекта. | шаг 4 |
| 6 | `09_code_reviewer` | Проверка границ payload LLM, grants, journal compact. | шаг 4–5 |
| 7 | `13_tech_writer` | Обновление канона только при **намеренном** сдвиге целевого поведения после OK. | по необходимости |

Рекомендуемый **технический** порядок slices (см. приложение B): **S1 → S3 → S2 → S5 → S4**
(сначала контракт команд и ссылок, затем события, затем статусы результата, затем CLI UX),
если `06` не видит блокирующих зависимостей между S2 и S3.

## Риски и некорректная реализация

| ID | Риск | Некорректное проявление | Проверка / смягчение |
|----|------|-------------------------|---------------------|
| R1 | Широкий PR | Один PR «весь AgentMemory» | План `06` режет по S1–S5; ревью отклоняет scope |
| R2 | LLM пишет граф напрямую | Рёбра без runtime validation | Код должен отклонять; тесты на reject path |
| R3 | CoT / raw prompts в compact | Утечка в journal/stdout | Grep/markers; `prompts.md` anti-patterns |
| R4 | Игнор `agent_memory_result` | Continuation по top-level mirror | Интеграционные тесты AgentWork (см. приложение G) |
| R5 | Grants не enforced | Чтение файлов вне slice | Slice S2/S5 + тесты на read path |
| R6 | A-id дрейф | Два шаблона A node_id | Явная миграция/один канон перед массовой индексацией |
| R7 | Неверные pytest имена | Ссылки на несуществующие `*_prompt_contains_*` | Список из `failure-retry-observability.md` |
| R8 | CLI `blocked` смешан с `aborted` | Неверный UX при LLM fail | Slice S4; сравнение с приложением A backlog |
| R9 | События без `event_type` / schema | Ломается Desktop | Slice S2; discriminant обязателен |
| R10 | Repair loop >1 | Нарушение bounded repair | Юнит-тесты pipeline |

## Соответствие target-doc pipeline

- `20` → research waves (приложение H) → `19`/`14` → `20` → `21` → `22` → `23` → **`24`** (этот документ) → user approval (`18`).
- `24` не запускает других агентов; результат — только этот файл в `context/algorithms/`.

---

## Приложение A — полная копия `human_review_packet.md`

````markdown
# Human Review Packet: AgentMemory target algorithm

Produced by: 23_target_doc_reader_reviewer

## What You Are Approving

- Целевое поведение AgentMemory как **memory-only** модуля: инициаторы AgentWork, `ailit memory init`, другие broker-клиенты; NL subgoal не заменяет полную пользовательскую задачу.
- Нормативная **state machine** (intake → … → result_emit), статусы `complete` / `partial` / `blocked`, где `blocked` допустим только при провале LLM-транспорта или невалидируемом ответе после bounded repair для обязательной LLM-фазы (`context/algorithms/agent-memory/runtime-flow.md`, `failure-retry-observability.md`).
- Закрытый **LLM command protocol**: envelope vs planner actions, фаза `planner_repair` без публичного имени `repair_invalid_response`, целевая команда `propose_links` (`context/algorithms/agent-memory/llm-commands.md`).
- **Typed graph links** с кандидатами от LLM и валидацией runtime; набор `link_type` и схема `agent_memory_link_candidate.v1` (`context/algorithms/agent-memory/memory-graph-links.md`).
- **Внешний протокол** wire-событий `agent_memory.external_event.v1`, envelope `agent_work_memory_query.v1`, результат `agent_memory_result.v1` (`context/algorithms/agent-memory/external-protocol.md`, сводка в `context/artifacts/target_doc/target_algorithm_draft.md`).
- **Контракт промптов по ролям** (не дословные тексты в репо), multi-language / `file_kind`, запреты CoT и raw dumps в machine channel (`context/algorithms/agent-memory/prompts.md`).
- Матрица failure/retry, observability-слои, acceptance по **фактическим** именам pytest из `context/artifacts/target_doc/current_state/tests_plan14_alignment.md` (`failure-retry-observability.md`).
- Пять пользовательских сценариев OR-014 плюс сценарий cap в `target_algorithm_draft.md` §Examples; трассировка OR-001…OR-015 в draft §Traceability и в `context/algorithms/agent-memory/INDEX.md`.

## What You Are Not Approving

- Изменения product code, новые LLM-провайдеры, реализацию slices — это последующие `start-feature` / `start-fix`.
- Дословные тексты промптов в репозитории: канон фиксирует **роли и требования**; тексты остаются в коде до отдельной задачи.
- Совпадение текущего CLI UX (`aborted` vs целевой `blocked`), enforcement `grants` в AgentWork, унификацию A `node_id`, полные per-event JSON-schema файлы в wire-доке — помечено как `implementation_backlog` или follow-up slice (см. `open_gaps_and_waivers.md`).

## Key Decisions

| Decision | Meaning For Product | Risk |
|----------|---------------------|------|
| D3 (state machine vs journal-only) | Продуктовая истина — именованные состояния; `memory.runtime.step` обязан нести `state`/`next_state` или явный legacy window | Реализация должна сменить текущий journal-free-text путь; иначе drift |
| D1 CLI `blocked` | Целевой UX отделяет `blocked` от `aborted`; код пока на `aborted` | Пользователь может ожидать другое поведение CLI до выравнивания |
| D2 `grants` | Целевое подключение read enforcement в AgentWork | До кода гранты в payload не ограничивают чтение |
| D4 единицы лимитов | UTF-8 символы для строк; counts для graph; не смешивать с tokenizer | Неверная имплементация даст silent crop |
| SoT `agent_memory_result` | Continuation только из вложенного объекта, не top-level mirror | Legacy-потребители могут читать не то поле |

## Weak / Thin Sections

| Section | Why Thin | Required Action |
|---------|----------|-----------------|
| `llm-commands.md` per-command JSON | Happy/invalid примеры агрегированы; нет полноформатного вход/выход на каждую envelope-команду (`22` MINOR-1) | Первый slice S1 уточняет границы payload при кодинге; опционально добить док после approval |
| `external-protocol.md` per-event payload | Bullet-правила по `event_type`, нет отдельного полного schema-блока на каждый тип (`22` MINOR-2) | Slice S2; или явный waiver «schema-by-type позже» |
| `user_request` в provenance links | Текст OR допускает `user_request`; `created_by` в candidate — три значения (`22` MINOR-3) | Зафиксировать enum в slice или user decision |

## Open Gaps And TBD

| Gap | Can Approve? | Needs Waiver? |
|-----|--------------|---------------|
| Per-command deep JSON examples | да, канон достаточен для направления | нет |
| Per-event-type full wire schemas | да | нет, если принять поэтапное ужесточение |
| `user_request` в `created_by` | да | только если позже запретить/разрешить явно |

## How Future start-feature Must Use This

- Читать пакет `context/algorithms/agent-memory/` (от `INDEX.md`) и сводку `context/artifacts/target_doc/target_algorithm_draft.md` до постановки задач.
- Резать работу по таблице slices в `start_feature_handoff.md` (S1–S5), не смешивать «весь AgentMemory» в одном PR.
- Проверять pytest-имена только из `failure-retry-observability.md` / `tests_plan14_alignment.md`, не из устаревших имён plan §C14R.4.
- Любое изменение целевого поведения после вашего OK — через обновление канона (`13_tech_writer` / осознанное изменение алгоритма).

## Questions For Human

- Нужны ли вам до первого slice **полные** JSON-schema на каждый `event_type` и на каждую LLM-команду в самом target doc? Если да — это rework документации (`21`), не блокер для утверждения целевого поведения при текущем пакете.

## Approval Text

Если вы согласны с целевым каноном AgentMemory (поведение, контракты, backlog отдельно от кода), ответьте в чат явной формой OK, например: «утверждаю target doc agent-memory» или `утверждаю` / `ок` / `approved` по правилам проекта.

````

## Приложение B — полная копия `start_feature_handoff.md`

````markdown
# start-feature handoff: agent-memory

Produced by: 23_target_doc_reader_reviewer

## Recommended First Slices

| ID | Slice | Why First | Target Doc Sections | Must Not Include |
|----|-------|-----------|---------------------|------------------|
| S1 | LLM command envelope + repair semantics + `AgentMemoryCommandName` vs planner actions; границы payload для `plan_traversal` / `finish_decision` / целевой `propose_links` | Снижает drift с контрактом pipeline и W14 | `llm-commands.md`; фрагменты `runtime-flow.md`, `failure-retry-observability.md` | Полный graph engine и все prompt-тела |
| S2 | Каталог внешних событий: discriminant `event_type`, compact vs verbose, durable vs ephemeral; маппинг stdout / journal / compact.log | Развязывает CLI/Desktop от внутренних шагов | `external-protocol.md`, `failure-retry-observability.md` | Полные per-event JSON-schema в одном PR без утверждённого порядка |
| S3 | Typed link validation + `agent_memory_link_candidate.v1` vs текущие `pag_edges` / pending | Фиксирует data model до масштабного prompt work | `memory-graph-links.md` | Все варианты текстов промптов |
| S4 | `ailit memory init`: целевой контракт exit/summary vs текущий `aborted` | Узкий пользовательский путь | `external-protocol.md` §CLI; `failure-retry-observability.md` при необходимости | Полный broker API |
| S5 | Failure/retry, caps→partial, правила статуса `agent_memory_result.v1` | Закрывает OR-012/OR-013 до расширения LLM | `failure-retry-observability.md` | Новые LLM провайдеры |

Источник таблицы: `context/artifacts/target_doc/synthesis.md` §Small-Scope Recommendations.

## Forbidden Broad Scope

- Одна задача «реализовать весь AgentMemory» или «выровнять весь граф + все события + CLI + grants» без нарезки S1–S5.
- Подмена канона `plan/14-agent-memory-runtime.md` вместо пакета `context/algorithms/agent-memory/` как SoT для целевого поведения.
- Добавление raw prompts / CoT в broker-facing compact channel (нарушает `prompts.md` и draft anti-patterns).

## Required Inputs For start-feature

- target docs: `context/algorithms/agent-memory/INDEX.md` и связанные файлы; `context/artifacts/target_doc/target_algorithm_draft.md`
- source coverage: `context/artifacts/target_doc/source_request_coverage.md`
- quality matrix: `context/artifacts/target_doc/target_doc_quality_matrix.md`
- gaps/waivers: `context/artifacts/target_doc/open_gaps_and_waivers.md`

## Required Final Evidence

- Pytest: имена из `failure-retry-observability.md` §Acceptance (venv проекта).
- Journal/compact: отсутствие raw prompts в compact channel там, где канон требует compact (см. `memory_journal_trace_observability` в current_state).
- Ручной smoke (после реализации целевого UX): `ailit memory init ./` — ожидаемые `complete`/`partial`/целевой `blocked` и маркер `memory.result.returned` по тексту канона.

## Known Gaps To Consider

- См. `context/artifacts/target_doc/open_gaps_and_waivers.md`: G-IMPL-1…5, G-DOC-1–2, G-NAMING-1, G-VERIFY-1.

````

## Приложение C — полная копия `reader_review.md`

````markdown
# Reader Review

Produced by: 23_target_doc_reader_reviewer

## Decision

approved_for_user_review

## Human Summary

`22_target_doc_verifier` вернул `approved` без BLOCKING/MAJOR. Пакет `context/algorithms/agent-memory/` (все файлы из `INDEX.md` существуют) плюс `context/artifacts/target_doc/target_algorithm_draft.md` дают проверяемое целевое поведение, отделение target/current, шесть сценариев OR-014, acceptance с фактическими pytest. Оставшиеся пробелы — задокументированный `implementation_backlog` (CLI, grants, A-id, propose_links) и MINOR doc depth (per-command/per-event JSON), не скрытые как `pass`. `18_target_doc_orchestrator` может запросить user approval на **human review packet + пакет + draft**, с приложением coverage/matrix/gaps/handoff.

## Findings

### RR1: Per-command JSON examples depth (OR-006)

Severity: MINOR  
Section: `context/algorithms/agent-memory/llm-commands.md`  
Problem: Агрегированные happy/invalid сценарии; не для каждой envelope-команды отдельный полный вход/выход JSON.  
Why A Human Will Struggle: При первом slice кодирования границы payload для `finish_decision` / `propose_links` могут потребовать уточнения у автора или тестов.  
Required Fix: Не блокирует approval; закрыть в slice S1 или post-approval добивкой документации по желанию человека.  
Requires New Research: false

### RR2: Per-event payload schemas (OR-010)

Severity: MINOR  
Section: `context/algorithms/agent-memory/external-protocol.md`  
Problem: Bullet-описание обязательных полей по `event_type` без отдельного полного schema-like JSON на каждый тип.  
Why A Human Will Struggle: Строгий парсер Desktop по каждому типу события напишет позже.  
Required Fix: Slice S2; опционально расширить канон после OK.  
Requires New Research: false

### RR3: `user_request` vs `created_by` enum (OR graph narrative)

Severity: MINOR  
Section: `context/algorithms/agent-memory/memory-graph-links.md`, `22` MINOR-3  
Problem: В постановке фигурирует `user_request`; в schema-like candidate перечислены три значения `created_by`.  
Why A Human Will Struggle: Edge case user-driven provenance не назван однозначно.  
Required Fix: Явно запретить или добавить значение при первом изменении link-модели; не блокирует понимание целевого графа.  
Requires New Research: false

## File And Link Existence (spot-check)

- `context/algorithms/agent-memory/INDEX.md` и sibling: `runtime-flow.md`, `memory-graph-links.md`, `llm-commands.md`, `prompts.md`, `external-protocol.md`, `failure-retry-observability.md` — присутствуют.
- `context/algorithms/INDEX.md` ссылается на `agent-memory/INDEX.md`.
- `context/artifacts/target_doc/current_state/*.md` (6 файлов), `donor/*.md` (3 файла) — использованы в тексте пакета/draft.
- `target_algorithm_draft.md` содержит `Produced by: 21_target_doc_author`.

````

## Приложение D — полная копия `open_gaps_and_waivers.md`

````markdown
# Open Gaps And Waivers

Produced by: 23_target_doc_reader_reviewer

## Gaps

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

## Proposed Waivers

| Waiver | Human Meaning | Risk | Expiration / Follow-up |
|--------|---------------|------|------------------------|
| — | Нет обязательных waiver для approval пакета в текущем виде | — | — |

Waiver **не** предлагается для отсутствующих goal/flow/examples/acceptance: эти элементы присутствуют в draft и пакете.

````

## Приложение E — полная копия `source_request_coverage.md`

````markdown
# Source Request Coverage

Produced by: 23_target_doc_reader_reviewer

| Original Request Block | Covered In | Depth | Missing | Needs User Decision |
|------------------------|------------|-------|---------|---------------------|
| OR-001 Канон `context/algorithms/agent-memory/`, `INDEX.md`, discoverability из `context/algorithms/INDEX.md` | `context/algorithms/agent-memory/INDEX.md`; `context/algorithms/INDEX.md` (строка AgentMemory); `target_algorithm_draft.md` §Canonical Package / Traceability | full | — | нет |
| OR-002 NL через broker; `complete`/`partial`; `blocked` только LLM API / bounded retry | `runtime-flow.md` §Статусы; `failure-retry-observability.md` матрица; `target_algorithm_draft.md` §Target Behavior | full | — | нет |
| OR-003 Обход дерева + graph A/B/C/D; typed links; runtime валидирует | `memory-graph-links.md`; `runtime-flow.md` §w14_action_materialize, link_apply | full | — | нет |
| OR-004 Контракт инициаторов; schema-like JSON | `external-protocol.md`; `target_algorithm_draft.md` §Inputs/Outputs (envelope) | full | — | нет |
| OR-005 State machine intake → finish | `runtime-flow.md` целевые состояния; `target_algorithm_draft.md` §Target Flow | full | — | нет |
| OR-006 LLM command protocol; команды; repair | `llm-commands.md`; `target_algorithm_draft.md` §Traceability OR-006 | partial | Нет отдельного полного JSON-примера на каждую команду (см. `22` MINOR-1) | нет, если устраивает slice S1 |
| OR-007 Типы связей B/C/D; confidence/source | `memory-graph-links.md` таблица + candidate schema | full | — | нет |
| OR-008 Multi-language; file_kind; запреты | `prompts.md` §Multi-language; draft §Example 3–4 | full | — | нет |
| OR-009 Каталог prompts по состояниям | `prompts.md` таблица ролей | partial | Нет дословных system/developer/user текстов в каноне (намеренно out of scope workflow) | нет, если утверждаете контракт ролей |
| OR-010 Внешние события; schema; log rules | `external-protocol.md`; `failure-retry-observability.md` observability | partial | Нет полного schema-like блока на каждый `event_type` payload (`22` MINOR-2) | нет, если устраивает поэтапное ужесточение |
| OR-011 CLI `ailit memory init` | `external-protocol.md` §CLI; draft Example 2; current vs target | full | — | нет |
| OR-012 Result `agent_memory_result.v1` | `failure-retry-observability.md`; `target_algorithm_draft.md` §Outputs | full | — | нет |
| OR-013 Failure/retry матрица | `failure-retry-observability.md` | full | — | нет |
| OR-014 ≥4 человекочитаемых сценария (в запросе 5 путей) | `target_algorithm_draft.md` §Examples (6 сценариев); `INDEX.md` §Индекс примеров | full | — | нет |
| OR-015 Acceptance criteria | `failure-retry-observability.md` §Acceptance; `target_algorithm_draft.md` §Acceptance Criteria | full | — | нет |

**Критические OR:** по таблице нет `missing` и нет критического `thin` без явного waiver: OR-006/OR-010 помечены `partial` из-за глубины примеров/schema-per-type; это не ломает понимание целевого поведения при наличии slices S1/S2.

````

## Приложение F — полная копия `target_doc_quality_matrix.md`

````markdown
# Target Doc Quality Matrix

Produced by: 23_target_doc_reader_reviewer

Оценка покрывает сводный draft и пакет `context/algorithms/agent-memory/*` как единый target doc для human approval.

| Section | Human Clarity | Technical Completeness | Examples | Commands / Proof | Gaps | Verdict |
|---------|---------------|------------------------|----------|------------------|------|---------|
| Source User Goal (`target_algorithm_draft.md`) | high | high | n/a | n/a | — | pass |
| Scope In/Out (`target_algorithm_draft.md`) | high | high | n/a | n/a | Out of scope явный | pass |
| Current Reality Summary (draft таблица + блоки в пакете) | high | high | n/a | Ссылки на `current_state/*.md` | Donor как идеи, не код | pass |
| Target Behavior (`target_algorithm_draft.md`, `runtime-flow.md`) | high | high | Ссылки в Examples | — | — | pass |
| Target Flow (draft numbered list, `runtime-flow.md`) | high | high | Примеры 1–6 в draft | — | — | pass |
| Examples OR-014 (draft §Examples + `INDEX.md` индекс) | high | high | high (6 сценариев) | Cap-сценарий вне ядра OR-014 — допустимое расширение | — | pass |
| Inputs/Outputs (draft schema-like, `external-protocol.md`) | high | high | Фрагменты JSON в draft/pакете | — | — | pass |
| State Lifecycle (draft, `runtime-flow.md`, PAG refs) | high | high | Примеры init/failure | — | A-id backlog описан | pass |
| Commands / manual smoke (`target_algorithm_draft.md`, пакет) | high | medium | CLI smoke описан qualitatively | pytest список в `failure-retry-observability.md` | Полный smoke после реализации кода | pass |
| Observability (`failure-retry-observability.md`, `external-protocol.md`) | high | high | Таблица stdout→compact | Journal rules | D-OBS vs internal — задокументировано | pass |
| Failure/Retry (`failure-retry-observability.md`) | high | high | Пример repair/missing file в draft | Матрица + pytest | — | pass |
| Acceptance Criteria (draft, `failure-retry-observability.md`) | high | high | n/a | Имена тестов явные | — | pass |
| Do Not Implement (`target_algorithm_draft.md`) | high | high | n/a | n/a | — | pass |
| How start-feature/start-fix (`target_algorithm_draft.md`) | high | high | n/a | Роли 02/06/08/11/13 | — | pass |
| `memory-graph-links.md` | high | high | draft Ex. 3–4 | Validation matrix | MINOR-3 `user_request` vs `created_by` | pass |
| `llm-commands.md` | high | medium | Агрегированный happy/invalid | Ссылка на failure matrix | `22` MINOR-1 deep per-command JSON | pass |
| `prompts.md` | high | medium | JSON fragment OR-008 | Запреты явные | Нет полных prompt тел (намеренно) | pass |
| `external-protocol.md` | high | medium | Wire каркас события | CLI + pytest refs | `22` MINOR-2 per-event full schema | pass |

**Core sections:** ни одна не имеет `Human Clarity=low` или `Technical Completeness=low`. Примеры для workflow присутствуют. Commands/proof: pytest-имена заданы в `failure-retry-observability.md`.

````

## Приложение G — полная копия `target_algorithm_draft.md`

````markdown
Produced by: 21_target_doc_author
Source synthesis: context/artifacts/target_doc/synthesis.md

# Target Algorithm: AgentMemory (broker, CLI, W14, memory graph)

## Status

`approved` — пользователь явно подтвердил в чате Cursor (2026-05-03); канонический пакет: `context/algorithms/agent-memory/`.

## Source User Goal

Пользователь запросил усиленный **целевой алгоритм** AgentMemory как самостоятельного модуля с NL-subgoals через broker, с типизированным графом памяти, закрытым LLM JSON-протоколом, внешними событиями для Desktop/CLI и контрактом результата `agent_memory_result.v1`. Источник постановки: `context/artifacts/target_doc/original_user_request.md`. Исторический документ `plan/14-agent-memory-runtime.md` — evidence, **не** финальный канон (см. synthesis).

## Why This Exists

Человек, управляющий агентской системой, должен иметь **проверяемый** эталон: что делает AgentMemory, когда возвращает `partial`, когда допустим `blocked`, какие события видит оператор, и какие инварианты нельзя ломать в следующих `start-feature` / `start-fix`. Разработчики должны иметь один пакет в `context/algorithms/agent-memory/` без необходимости читать весь plan/14.

## Scope

### In Scope

- Внешние инициаторы: AgentWork, `ailit memory init`, другие broker-клиенты.
- Runtime flow, state machine (норматив), journal mapping.
- LLM command protocol: envelope vs planner actions, internal summarize phases, repair phase semantics, целевой `propose_links`.
- Typed graph links с runtime validation и LLM candidates.
- Multi-language / non-code `file_kind` policy в промптах.
- External event protocol + CLI семантика (target vs current gap).
- `agent_memory_result.v1`, failure/retry matrix, observability слои, acceptance по **фактическим** pytest именам.

### Out Of Scope

- Изменение product code в этом workflow.
- Полные тексты промптов из репозитория (здесь — роли и требования; тексты остаются в коде).
- Новые LLM провайдеры.

## Current Reality Summary

Факты только из отчётов `19` и synthesis (см. также файлы пакета `context/algorithms/agent-memory/*.md`):

| Область | Краткий факт | Отчёт |
|---------|--------------|--------|
| Транспорт | Broker subprocess vs CLI in-process | `agent_memory_entrypoints_cli.md` |
| AgentWork payload | v1 + `query_kind`/`level` advisory; SoT `agent_memory_result`; grants не consumed | `agent_work_memory_integration.md` |
| Pipeline | 4 envelope имени; repair 1×; RUNTIME_STATES не assert в pipeline; growth путь разделён | `agent_memory_query_pipeline.md` |
| PAG/KB | KB не в worker query; A-id шаблоны могут расходиться | `pag_kb_memory_state_models.md` |
| Observability | journal `event_name` шире D-OBS; stdout vs compact имена | `memory_journal_trace_observability.md` |
| Тесты | Имена `*_prompt_contains_*` из plan нет; использовать G14R фактические имена | `tests_plan14_alignment.md` |

## Target Behavior

AgentMemory принимает **memory-only** subgoal от инициатора, читает/пишет PAG под политикой namespace/`project_root`, опрашивает LLM только через закрытые JSON-схемы, валидирует все graph mutations, эмитит **typed external events** с caps и флагом `truncated`, и завершает с `complete` или `partial` при любых обычных сбоях данных/капах; `blocked` — только при провале LLM транспорта/валидации ответа после bounded repair для обязательной LLM фазы.

## Target Flow

1. **Intake** — валидация envelope, нормализация путей, извлечение caps (`external-protocol.md`).
2. **DB preflight** — открыть PAG; journal `memory.request.received`.
3. **Cache/mechanical slice** — если попали в короткий путь, собрать slice без LLM (иначе пропуск).
4. **Planner round** — LLM `plan_traversal` (или целевой `propose_links`) строго JSON (`llm-commands.md`).
5. **Repair (optional, bounded)** — фаза `planner_repair`, максимум один LLM repair при разрешённом классе ошибки.
6. **Materialize/index** — A/B/C, `contains`, индексация text-like (`memory-graph-links.md`).
7. **Summarize phase** — internal `summarize_c` / `summarize_b` вызовы.
8. **Link apply** — принять только validated candidates; отклонения в событиях `links_updated`.
9. **Finish assembly** — `finish_decision`, сборка `agent_memory_result.v1`, grants object (**target:** enforcement в AgentWork, см. backlog).
10. **Result emit** — `memory.result.returned`, stdout highlights, broker response.

## Examples

### Example 1: Happy Path — AgentWork и сервер

Пользователь в AgentWork спрашивает: «какие файлы нужно менять для поднятия HTTP сервера?». AgentWork вызывает `memory.query_context` с v1 envelope: `subgoal` содержит эту формулировку, `known_paths` пуст, `query_id=mq-…`. AgentMemory проходит planner, материализует B для релевантных путей, создаёт/обновляет C summaries, собирает `finish_decision`, возвращает `agent_memory_result.v1` со `status=complete`, `results` содержат `c_summary` и/или `read_lines` с грантами, `runtime_trace.final_step=finish`. В журнале `memory.result.returned` compact: `status`, `result_kind_counts`, без raw summaries.

### Example 2: CLI Init

Пользователь запускает `ailit memory init /abs/repo`. Оркестратор создаёт in-process worker, передаёт `memory_init=true`, goal=`MEMORY_INIT_CANONICAL_GOAL`, `namespace` из `detect_repo_context`. На stderr идут compact строки прогресса; stdout содержит graph upsert/highlight JSONL для подписчиков. Финал: **target** — `status=complete` и UX `blocked` отдельно от `aborted` при LLM hard fail; **current** — см. `implementation_backlog` (CLI `aborted` vs `blocked`, `agent_memory_entrypoints_cli.md` F9).

### Example 3: Cross-Language

Репозиторий содержит Go сервис и CMake. Планер выбирает пути `.go` и `CMakeLists.txt`. Summarize промпт требует `file_kind=source_code|build_file`, `language=go|unknown`, chunk kinds `function` vs `build_target`. Runtime не предполагает Python AST; для `unknown` создаётся `text_window` chunk с маркером heuristic. Links: `imports` для Go import evidence; **нет** `calls` без symbol evidence.

### Example 4: Documentation References

Есть `docs/architecture.md` с секцией `# Server` и ссылкой на `src/server.py`. После индексации C для heading и функции, LLM предлагает `link_candidate` `references` от `C:docs/...#server` к `C:src/server.py:Handler` с evidence `heading_text`. Runtime проверяет существование обоих node id и границы строк — при успеху ребро попадает в PAG или pending; Desktop получает `links_updated` и `highlighted_nodes`.

### Example 5: Failure / Recovery — Invalid JSON и missing file

Планер возвращает почти валидный JSON с лишней запятой → `W14CommandParseError`, `_should_repair_w14_error` true → один repair call → парс успешен → продолжение. Если repair запрещён/провален → `partial` с `reason=w14_parse_failed`, без silent success.

Параллельно один из explicit paths отсутствует на диске → candidate path отвергнут runtime до LLM; `partial` с `file_missing` в trace; остальные файлы обработаны.

### Example 6: Caps — AgentWork continuation budget

За один `user_turn_id` AgentWork делает серию continuation запросов; на 7-м запросе при cap=6 broker не вызывается, публикуется `memory.query.budget_exceeded` (см. отчёт AgentWork). AgentMemory не обязан стартовать; это **внешний** partial сценарий инициатора.

## Inputs

### Envelope инициатора (AgentWork / broker client) — `memory.query_context`

```json
{
  "service": "memory.query_context",
  "schema_version": "agent_work_memory_query.v1",
  "subgoal": "string, required",
  "user_turn_id": "string, required",
  "query_id": "string, required, unique per memory sub-goal round",
  "project_root": "string, required, absolute normalized path",
  "namespace": "string, required",
  "expected_result_kind": "string, required, whitelist validated by runtime parser",
  "known_paths": "array[string], required, default empty array",
  "known_node_ids": "array[string], required, default empty array",
  "stop_condition": {
    "max_rounds": "int, required, >=1",
    "allow_partial": "bool, required"
  },
  "query_kind": "string | omitted — not validated by v1 parser; initiator advisory",
  "level": "string | omitted — not validated by v1 parser; initiator advisory",
  "memory_init": "bool | omitted — required true only for CLI init path with forbidden extra paths per worker contract"
}
```

**Forbidden:** передавать произвольные абсолютные пути вне `project_root` scope policy; подменять namespace из free-form NL без `detect_repo_context` эквивалента на CLI.

### CLI `ailit memory init`

- **Input positional:** `project_root` path (required).
- **Env:** `AILIT_PAG_DB_PATH`, `AILIT_KB_DB_PATH`, `AILIT_MEMORY_JOURNAL_PATH`, … как в autouse тестов (`tests_plan14_alignment.md` F5–F6).

## Outputs

### Broker / worker payload (успешный путь)

```json
{
  "memory_slice": "object, required for injectable path; bounded fields",
  "agent_memory_result": {
    "schema_version": "agent_memory_result.v1",
    "query_id": "string, required",
    "status": "complete|partial|blocked",
    "decision_summary": "string, required, utf8-bounded",
    "recommended_next_step": "string, default empty string",
    "results": "array, default [] of result items with kind/path/summary/read_lines/c_node_id per assembly rules",
    "runtime_trace": "object, required, compact; forbidden: raw prompts, secrets, full file contents",
    "memory_continuation_required": "bool | omitted — if unknown, omit key (not null)"
  },
  "grants": "array, default [] of read grants derived from selected read_lines",
  "partial": "bool, required — pipeline-level partial flag",
  "decision_summary": "string, duplicate mirror of agent_memory_result.decision_summary for legacy consumers",
  "recommended_next_step": "string, duplicate mirror; may be empty"
}
```

**SoT rule:** continuation decisions **must** читать `agent_memory_result`, не top-level mirror (`agent_work_memory_integration.md` F4).

### Внешнее событие (wire)

```json
{
  "schema_version": "agent_memory.external_event.v1",
  "event_type": "heartbeat|progress|highlighted_nodes|link_candidates|links_updated|nodes_updated|partial_result|complete_result|blocked_result",
  "query_id": "string, required",
  "timestamp": "string, required",
  "payload": "object, required",
  "truncated": "bool, default false",
  "units": "utf8_chars|node_count|edge_count"
}
```

### Journal (durable, compact)

- `memory.result.returned` payload: `query_id`, `status`, `result_kind_counts`, `results_total` — **forbidden** включать `results[].summary` / raw read_lines в compact журнал (`memory_journal_trace_observability.md` F5).

### Link candidate (LLM → runtime, до валидации)

```json
{
  "schema_version": "agent_memory_link_candidate.v1",
  "link_id": "string, required",
  "link_type": "contains|imports|defines|calls|references|summarizes|supports_answer|supersedes",
  "source_node_id": "string, required",
  "target_node_id": "string, required",
  "target_external_ref": "null, default null",
  "source_path": "string, required, repo-relative, no ..",
  "target_path": "string|null, default null",
  "evidence": {
    "kind": "line_range|symbol_name|heading_text|import_statement|llm_summary",
    "value": "string, required",
    "start_line": "int|null, default null",
    "end_line": "int|null, default null"
  },
  "confidence": "high|medium|low",
  "created_by": "static_analysis|llm_inferred|runtime_observed",
  "reason": "string, required"
}
```

## State Lifecycle

- PAG sqlite путь из `AILIT_PAG_DB_PATH` / defaults (`pag_kb_memory_state_models.md`).
- Shadow journal для CLI init транзакций (`agent_memory_entrypoints_cli.md`).
- D digest: после finish (`pag_kb_memory_state_models.md` F9).

## Commands

### Manual smoke (после реализации целевого UX)

```bash
cd /path/to/repo
ailit memory init ./
```

**Expected (target):** завершение с понятным `complete|partial|blocked`; compact log содержит `memory.result.returned` compact payload; нет raw prompts в compact channel.

### CI / verification

Запуск pytest из venv проекта; минимальный набор имён — раздел **Acceptance Criteria** ниже.

## Observability

- Три канала: stdout JSONL, journal JSONL, compact.log (`failure-retry-observability.md`).
- D-OBS-1 = broker-facing subset; полный internal catalog — отдельная таблица в пакете (`runtime-flow.md` D3).

## Failure And Retry Rules

См. матрицу в `failure-retry-observability.md` (FR-no-progress, LLM blocked rules).

## Acceptance Criteria

- Любой future `start-feature` для AgentMemory **must** реализовать закрытый LLM command protocol и runtime validation ссылками на `llm-commands.md` + `memory-graph-links.md`.
- AgentMemory **must not** crash на missing file / unknown language; статус → `partial` с reason.
- Все внешние события **must** иметь discriminant `event_type` + schema версии.
- Промпты **must** соответствовать ролям из `prompts.md`.
- `agent_memory_result.v1` **must** соответствовать каркасу schema в `failure-retry-observability.md`, включая optional `memory_continuation_required` omit/null правила (`tests_plan14_alignment.md` F9).
- Desktop **must** иметь возможность подписаться на highlights и link updates через stdout/broker слой.
- CLI **must** получать progress и итог; до выравнивения кода допускается расхождение UX `blocked` (**backlog**).
- `context/algorithms/INDEX.md` **must** ссылаться на пакет `agent-memory/` (OR-001).

## Do Not Implement This As

- «Тихий успех» без `results`/usable slice при непустом запросе.
- Запись рёбер напрямую из LLM без validation/pending policy.
- Бесконечные repair циклы или неограниченный обход при неизменном input.
- Один глобальный «event_type string без schema версии».
- Смешение токенов и символов в одном public поле без `units` discriminator.
- Использование несуществующих pytest имён из plan §C14R.4 как gate без алиасов.

## How start-feature / start-fix Must Use This

- `02_analyst` читает пакет `context/algorithms/agent-memory/` до написания ТЗ, если задача касается AgentMemory.
- `06_planner` трассирует задачи к **Target Flow** шагам и OR-id из таблицы traceability.
- `08_developer` реализует slices из synthesis Small-Scope (S1–S5), не «весь AgentMemory одним PR».
- `11_test_runner` проверяет команды и pytest имена из `failure-retry-observability.md`; если тест требует live LLM — маркирует `blocked_by_environment`.
- `13_tech_writer` обновляет этот канон **только** при намеренном изменении целевого поведения после user approval.

## Traceability

| ID | Type | Source | Target Doc Section |
|----|------|--------|-------------------|
| OR-001 | Requirement | `original_user_request.md` §Canonical Output | Scope, algorithms path |
| OR-002 | Requirement | `original_user_request.md` §Goal L43 | Target Behavior, Failure |
| OR-003 | Requirement | `original_user_request.md` §Goal graph | memory-graph-links |
| OR-004 | Requirement | `original_user_request.md` §1 | external-protocol |
| OR-005 | Requirement | `original_user_request.md` §2 | Target Flow |
| OR-006 | Requirement | `original_user_request.md` §3 | llm-commands |
| OR-007 | Requirement | `original_user_request.md` §4 | memory-graph-links |
| OR-008 | Requirement | `original_user_request.md` §5 | prompts |
| OR-009 | Requirement | `original_user_request.md` §6 | prompts |
| OR-010 | Requirement | `original_user_request.md` §7 | external-protocol |
| OR-011 | Requirement | `original_user_request.md` §8 | Examples, external-protocol |
| OR-012 | Requirement | `original_user_request.md` §9 | Outputs, failure-retry |
| OR-013 | Requirement | `original_user_request.md` §10 | failure-retry |
| OR-014 | Requirement | `original_user_request.md` §11 | Examples |
| OR-015 | Requirement | `original_user_request.md` §12 | Acceptance |
| F-CLI-3 | Current fact | `current_state/agent_memory_entrypoints_cli.md` | Examples (CLI gap) |
| F-AW-4 | Current fact | `current_state/agent_work_memory_integration.md` | Do Not Implement / backlog |
| F-PL-2 | Current fact | `current_state/agent_memory_query_pipeline.md` | llm-commands repair |
| D1 | Decision | `synthesis.md` Options D1 | CLI blocked UX |
| D4 | Decision | `synthesis.md` Options D4 | failure-retry units |
| O1 | Option | `synthesis.md` OR table | package layout |

## What To Review As A Human

1. Совпадает ли **Source User Goal** с ожидаемым продуктовым поведением AgentMemory.
2. Устраивает ли жёсткое правило: `blocked` только для LLM API/ответа после bounded repair.
3. Понятны ли пять (+1) сценариев и разделение target vs `implementation_backlog` для CLI/Grants/A-id.
4. Нужно ли ужесточать grants enforcement раньше graph-link engine (приоритет slice S4/S5 из synthesis).

## Canonical Package

Детализация по файлам: `context/algorithms/agent-memory/` (этот draft самодостаточен по контрактам OR-001…OR-015; пакет раскладывает текст для сопровождения).

````

## Приложение H — исполненные research waves (`research_waves.json`)

Снимок соответствует `wave_execution_report.md` и не должен затираться пустым массивом после barrier.

```json
{
  "produced_by": "20_target_doc_synthesizer",
  "target_topic": "agent-memory",
  "synthesis_file": "context/artifacts/target_doc/synthesis.md",
  "research_waves": [
    {
      "wave_id": "current_repo_1",
      "parallel": true,
      "depends_on": [],
      "barrier": "all_jobs_completed",
      "jobs": [
        {
          "job_id": "cr_agent_memory_entrypoints_cli",
          "kind": "current_repo",
          "agent": "19_current_repo_researcher",
          "research_question": "Entrypoints AgentMemory, CLI memory init, broker subprocess vs in-process.",
          "output_file": "context/artifacts/target_doc/current_state/agent_memory_entrypoints_cli.md"
        },
        {
          "job_id": "cr_agent_work_memory_payload",
          "kind": "current_repo",
          "agent": "19_current_repo_researcher",
          "research_question": "AgentWork memory.query_context payload, caps, grants, agent_memory_result.",
          "output_file": "context/artifacts/target_doc/current_state/agent_work_memory_integration.md"
        },
        {
          "job_id": "cr_agent_memory_query_pipeline",
          "kind": "current_repo",
          "agent": "19_current_repo_researcher",
          "research_question": "AgentMemoryQueryPipeline: W14 commands, repair, runtime states vs journal.",
          "output_file": "context/artifacts/target_doc/current_state/agent_memory_query_pipeline.md"
        },
        {
          "job_id": "cr_pag_kb_memory_persistence",
          "kind": "current_repo",
          "agent": "19_current_repo_researcher",
          "research_question": "PAG/KB models, sqlite paths, A/B/C/D node ids.",
          "output_file": "context/artifacts/target_doc/current_state/pag_kb_memory_state_models.md"
        },
        {
          "job_id": "cr_memory_journal_trace_chat",
          "kind": "current_repo",
          "agent": "19_current_repo_researcher",
          "research_question": "Journal, trace, compact.log, event_name contract vs D-OBS.",
          "output_file": "context/artifacts/target_doc/current_state/memory_journal_trace_observability.md"
        },
        {
          "job_id": "cr_tests_plan14_runtime_contracts",
          "kind": "current_repo",
          "agent": "19_current_repo_researcher",
          "research_question": "Pytest names and alignment with plan/14 vs repo reality.",
          "output_file": "context/artifacts/target_doc/current_state/tests_plan14_alignment.md"
        }
      ]
    },
    {
      "wave_id": "donors_1",
      "parallel": true,
      "depends_on": [
        "current_repo_1"
      ],
      "barrier": "all_jobs_completed",
      "jobs": [
        {
          "job_id": "donor_opencode_typed_events",
          "kind": "donor_repo",
          "agent": "14_donor_researcher",
          "donor_repo_path": "/home/artem/reps/opencode",
          "research_question": "Как donor регистрирует typed session или bus events и связывает type с payload schema; применимо ли к external-protocol AgentMemory без копирования кода.",
          "output_file": "context/artifacts/target_doc/donor/opencode_typed_events_for_memory_protocol.md"
        },
        {
          "job_id": "donor_claude_code_agent_memory_scopes",
          "kind": "donor_repo",
          "agent": "14_donor_researcher",
          "donor_repo_path": "/home/artem/reps/claude-code",
          "research_question": "Как donor разделяет path ownership и scopes в agent memory tool, что переносимо в контракт AgentWork-owned request vs AgentMemory-owned writes?",
          "output_file": "context/artifacts/target_doc/donor/claude_code_agent_memory_ownership.md"
        },
        {
          "job_id": "donor_letta_memory_compact_limits",
          "kind": "donor_repo",
          "agent": "14_donor_researcher",
          "donor_repo_path": "/home/artem/reps/letta",
          "research_question": "Как donor описывает memory blocks с metadata и лимитами размера, применимо ли к compact agent_memory_result и event payloads?",
          "output_file": "context/artifacts/target_doc/donor/letta_memory_blocks_compact_pattern.md"
        }
      ]
    }
  ]
}
```
