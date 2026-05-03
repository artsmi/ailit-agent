<!-- Canonical AgentMemory target algorithm — published after user approval 2026-05-03 -->
**Источник:** черновик `context/artifacts/target_doc/target_algorithm_draft.md` (Produced by: 21_target_doc_author), верификация `context/artifacts/target_doc/verification.md`.

# AgentMemory — целевой алгоритм (канон)

## Документы раздела

| Файл | Содержание |
|------|------------|
| [runtime-flow.md](runtime-flow.md) | Текущая реальность, целевое поведение, target flow, state lifecycle |
| [memory-graph-links.md](memory-graph-links.md) | Типы рёбер, `agent_memory_link_candidate.v1` |
| [llm-commands.md](llm-commands.md) | Протокол runtime↔LLM, команды, repair |
| [prompts.md](prompts.md) | Роли промптов и ограничения |
| [external-protocol.md](external-protocol.md) | События, слои compact/journal/stdout |
| [failure-retry-observability.md](failure-retry-observability.md) | Failure/retry, observability, donor notes |

---

## Статус и происхождение

- **Статус канона:** `approved` (явное OK пользователя в чате, 2026-05-03).
- **Верификация:** findings MAJOR-1 … MAJOR-3, MINOR-1 … MINOR-2 закрыты в `context/artifacts/target_doc/verification.md`.
- **Карта разделов:** см. таблицу «Документы раздела» выше; детальные контракты — в соседних `.md` файлах этого каталога.

---
## Source User Goal

Пользователь хочет **нормализованный целевой алгоритм** модуля AgentMemory: закрытый LLM command protocol, типизированные graph links A/B/C/D с runtime-валидацией, multi-language/docs, внешний протокол событий, строгие исходы `complete` / `partial` / `blocked`, примеры и acceptance criteria — с опорой на **фактическое** состояние репозитория и protos/tests, а не только на `plan/14-agent-memory-runtime.md`.

Исходная постановка: [`context/artifacts/target_doc/original_user_request.md`](../../artifacts/target_doc/original_user_request.md).

## Why This Exists

AgentMemory — отдельный модуль памяти графа проекта (PAG и смежные артефакты), к которому подключаются **AgentWork**, **CLI** и **другие broker-клиенты**. Он не решает пользовательскую задачу целиком: он возвращает **memory result** для конкретного memory subgoal (subgoal / goal), чтобы вызывающая сторона могла продолжить рассуждение или индексацию с проверяемым контрактом.

## Scope

### In Scope

- Внешние инициаторы и transport matrix (broker, subprocess, in-process CLI).
- Целевая state machine и caps; явное разделение **нормативного целевого поведения** и **текущего снимка реализации** (см. synthesis P1–P7, D3).
- LLM command protocol: владение runtime vs LLM; реестр команд; repair bounded.
- Типы связей графа из user request; кандидаты ссылок; runtime validation.
- Multi-language / documentation handling (`file_kind`, `language`, `semantic_chunk_kind`, fallbacks).
- Роли промптов и запреты на вывод/логи.
- Внешний протокол событий: compact / journal / stdout; liveness без фиктивного heartbeat (D1).
- CLI `ailit memory init`: default goal, прогресс, завершения, proof commands.
- Envelope `agent_memory_result.v1` и известные gaps относительно кода.
- Failure/retry матрица и observability security levels.

### Out Of Scope

- Изменение product code в этом workflow.
- Публикация канона без явного user approval и без прохождения `22` (для этого workflow уже выполнено).
- Обязательная реализация donor API (opencode/claude-code) — только **design notes**, не норма продукта.
## Examples

### Example 1: Happy Path — AgentWork и сервер

Пользователь в Desktop спрашивает: «какие файлы нужны, чтобы поменять поведение сервера». AgentWork создаёт `user_turn_id`, первый `query_id`, шлёт broker RPC `memory.query_context` с `subgoal` = текст пользователя, `expected_result_kind: "mixed"`, `namespace` и `project_root` workspace. AgentMemory читает PAG, выполняет W14 plan round, при необходимости материализует B/C, возвращает `agent_memory_result` со `status=complete` и списком `results` (в т.ч. `b_path` / `read_lines` / `c_summary`), плюс `memory_slice` с `injected_text` для последующего inject. В журнале появляется компактное `memory.result.returned` с агрегированными счётчиками, без сырого текста C-summary в payload journal.

### Example 2: Init Path — `ailit memory init`

Пользователь в корне репозитория запускает:

```bash
ailit memory init ./
```

Оркестратор создаёт CLI session dir, shadow journal, destructive clear PAG+KB для `namespace_for_repo`, затем в цикле (до лимита раундов) вызывает **in-process** `AgentMemoryWorker.handle` с `memory_init: true` и `goal = MEMORY_INIT_CANONICAL_GOAL` (константа в коде — единственный default NL). Прогресс виден как поток **compact** строк на stderr и фазы `orch_memory_init_*`. Успех **commit** и exit `0` требуют journal marker `memory.result.returned` со `status=complete` для `chat_id`, а не «успешного вида» stderr при внутреннем `blocked` в AMR.

### Example 3: Cross-Language — Go / C++ / TypeScript

Репозиторий содержит сервис на Go и обвязку на TypeScript. AgentMemory обязан **не** предполагать Python AST для всех файлов: для каждого B путь определяется `file_kind` и `language`; C-ноды создаются как `semantic_chunk_kind` вроде `function`, `struct`, `interface`, либо `text_window` при unknown language. LLM возвращает кандидатов с evidence (lines / symbol / heading). Runtime отбрасывает кандидатов без evidence для жёстких типов связей (`calls`).

### Example 4: Documentation — Markdown → code `references`

В `docs/architecture.md` секция «Deployment» ссылается на `k8s/service.yaml` и на handler в `src/server.ts`. После обхода AgentMemory предлагает link candidates типа `references` от `heading_section` C-ноды к C/B нодам с `evidence.kind = heading_text` / `line_range`. Runtime валидирует, что пути относительны, узлы существуют, и только затем фиксирует рёбра; low-confidence кандидаты остаются advisory или отбрасываются политикой.

### Example 5: Failure / Recovery — invalid JSON и недоступный файл

**5a.** LLM возвращает JSON с хвостом текста вне envelope → парсер даёт `W14CommandParseError`; если `_should_repair_w14_error` разрешает — один repair round; иначе bounded `partial` с причиной контрактного отказа, без молчаливого success.

**5b.** Один из файлов удалён между индексацией и чтением → `partial` с reason вида missing file (не crash), журнал фиксирует compact error path.

**5c.** LLM API недоступен после bounded retries на уровне provider policy → `blocked` (единственный класс ошибок, который может маппиться на недоступность провайдера), с человекочитаемым `recommended_next_step` для оператора.

## Inputs

### Initiator matrix

| Инициатор | Transport | Кто формирует NL | `query_id` / `user_turn_id` |
|-----------|-----------|----------------|------------------------------|
| AgentWork | Broker Unix socket RPC | Первый раз: user text; continuation: `recommended_next_step` если не пусто | `user_turn_id = ut-{uuid4 hex[:20]}`; `query_id = mq-{user_turn_id}-{idx}` |
| `ailit memory init` | In-process `AgentMemoryWorker` | Константа `MEMORY_INIT_CANONICAL_GOAL` | Генерация в оркестраторе (см. код) |
| Другой broker client | Как AgentWork или subprocess JSONL | Поле `goal` / `subgoal` в payload | Должен поставлять корреляцию; иначе non-normative |

### Envelope: `agent_work_memory_query.v1` (AgentWork / совместимые клиенты)

**Required:**

- `schema_version`: строка, **ровно** `"agent_work_memory_query.v1"`.
- `subgoal`: non-empty string (NL или machine-readable subgoal id — но строка не пустая).
- `user_turn_id`: non-empty string.
- `query_id`: non-empty string.
- `project_root`: non-empty string (абсолютный путь на стороне клиента).
- `namespace`: string; **если** после strip пусто — трактуется как `"default"` при формировании в Work (см. handoff F6).
- `expected_result_kind`: whitelist: `c_summary` | `read_lines` | `b_path` | `mixed`.
- `stop_condition`: object с полями:
  - `max_runtime_steps`: int (required в DTO),
  - `max_llm_commands`: int (required),
  - `must_finish_explicitly`: bool (required).

**Default / empty list:**

- `known_paths`: если отсутствует → **empty list** (не `null`).
- `known_node_ids`: если отсутствует → **empty list**.

**Nullable / forbidden:**

- `null` для `schema_version`, `subgoal`, `query_id`, `user_turn_id`, `project_root`, `namespace` (после нормализации), `expected_result_kind`, `stop_condition` — **forbidden** (отсутствие ключа трактуется как ошибка парсинга v1).
- Сырой chain-of-thought в любом поле — **forbidden** контрактом промптов, не только схемой.

**Multi-query per turn:** каждый успешный RPC с валидным `agent_memory_result` увеличивает счётчик; при превышении `max_memory_queries_per_user_turn` (config default 6, clamp 1..1000) — событие `memory.query.budget_exceeded`, **RPC не выполняется**, ответного envelope от AgentMemory **нет** (synthesis P4).

### Init payload (`memory_init`)

См. канон: `context/proto/memory-query-context-init.md`.

**Required:**

- `memory_init`: bool, **строго** `true` для режима init.
- `goal`: non-empty string (в CLI — константа).
- `project_root`, `namespace` — как в обычном query.

**Forbidden при init:**

- Непустые `path` / `hint_path` → `ok: false`, код `memory_init_path_forbidden`.

---

## Outputs

### Primary: `agent_memory_result.v1`

Сборка через `build_agent_memory_result_v1` (`tools/agent_core/runtime/agent_memory_result_v1.py`).

**Required (верхний уровень объекта):**

- `schema_version`: `"agent_memory_result.v1"`.
- `status`: `complete` | `partial` | `blocked`.
- `query_id`: non-empty string.
- `results`: list (может быть empty только если политика partial/block это объясняет — не использовать как silent success).

**Default / optional (нормативно уточнять в реализации, не как «молча опционально»):**

- `recommended_next_step`: string; для terminal partial может указывать `fix_memory_llm_json` и др.; при `complete` — обычно пустая строка или стабильное `none` — **источник истины:** текущая сборка в коде; target-doc требует **явной** строки в ответе, never omitted if partial.

**Forbidden в public projection:**

- raw prompts, CoT, полные файлы без выбора как result evidence.

### Secondary: `memory_slice` (projection)

- `kind`: `"memory_slice"`, `schema`: `"memory.slice.v1"` на типичном W14 пути.
- `injected_text` используется AgentWork для system message; SoT для continuation — **не** slice.

### Grants

- Список dict грантов на `read_lines` диапазоны строится AgentMemory.
- **Нормативно:** клиент, выполняющий чтение файлов по результату памяти, обязан уважать гранты; **текущий снимок:** `work_agent.py` гранты не применяет (synthesis D2).

---

## State Lifecycle

| Сущность | Ключ | Операции |
|----------|------|----------|
| PAG SQLite | `(namespace, node_id)` | upsert nodes/edges; namespace partition |
| KB SQLite | `namespace` | init: `delete_all_for_namespace`; query path: **no write today** |
| Journal JSONL | `chat_id`, события | durable audit; redact on append |
| CLI session | `cli_session_dir` | `compact.log`, `legacy.log` (verbose), shadow journal |
| Broker stdout | topic publish | rich graph trace без journal redaction |

**Известный gap:** два шаблона A id (`PagIndexer` vs pipeline materialize) — target-doc требует будущего **единого генератора**; до исправления допускается сосуществование записей с разными A keys под одним namespace (риск для containment) — см. `agent_memory_pag_kb_state_models.md` F9.

---

## Commands

### Proof commands (существующие тесты — не имена из §G14R.3 плана)

> **Примечание:** в `plan/14-agent-memory-runtime.md` §G14R.3 перечислены pytest node id, которых **нет** в дереве `tests/` (`agent_memory_tests_and_plan14_contracts.md` F14). Ниже — **фактические** файлы.

```bash
cd /home/artem/reps/ailit-agent
./.venv/bin/python -m pytest tests/test_g14r11_w14_integration.py -q
./.venv/bin/python -m pytest tests/test_g14r2_agent_memory_runtime_contract.py -q
./.venv/bin/python -m pytest tests/test_g14r0_w14_clean_replacement.py -q
./.venv/bin/python -m pytest tests/test_g14r7_agent_memory_result_assembly.py -q
./.venv/bin/python -m pytest tests/test_g14r_agentwork_memory_continuation.py tests/test_g14r1_agent_work_memory_query.py -q
./.venv/bin/python -m pytest tests/runtime/test_broker_work_memory_routing.py -q
./.venv/bin/python -m pytest tests/test_memory_init_cli_layout.py tests/runtime/test_memory_init_fix_uc01_uc02.py -q
```

**Manual smoke (оператор):**

```bash
cd /path/to/repo
ailit memory init ./
```

**Ожидаемо:** stderr показывает фазы и итог `=== memory init summary ===`; exit `0` только при успешном VERIFY journal complete; иначе exit `1` partial / `2` protocol по коду оркестратора.

## Observability, failure и retry

Матрица ошибок, FR1/FR2, уровни security observability и donor notes: **[failure-retry-observability.md](failure-retry-observability.md)**. Схемы событий и слои compact/journal/stdout: **[external-protocol.md](external-protocol.md)**.

---

## Acceptance Criteria

Критерии ниже относятся к **канону после реализации** (`start-feature` / `start-fix`), кроме строк, где явно сказано «уже в тексте draft». Статус — относительно этого документа как спецификации.

| # | Критерий | Статус | Указатель |
|---|----------|--------|-----------|
| AC1 | Закрытый LLM command protocol, реестр команд, bounded repair | **Специфицировано** (ожидает кода) | [llm-commands.md](llm-commands.md), [failure-retry-observability.md](failure-retry-observability.md) |
| AC2 | Нет crash на типовых FS / partial graph / invalid candidates; `blocked` только LLM infra | **Специфицировано** | [failure-retry-observability.md](failure-retry-observability.md), [Examples](#examples) п.5 |
| AC3 | Внешние события UI — schema-like (тип, поля, default/null) | **Частично текущий код + целевые** | [external-protocol.md](external-protocol.md) |
| AC4 | Промпты: роли и запреты | **Специфицировано** | [prompts.md](prompts.md) |
| AC5 | `agent_memory_result.v1` + gaps | **Специфицировано** | [Outputs](#outputs), [runtime-flow.md](runtime-flow.md#current-reality-summary) |
| AC6 | Graph links typed + evidence + runtime validation | **Специфицировано** | [memory-graph-links.md](memory-graph-links.md) |
| AC7 | Multi-language / docs | **Специфицировано** | [Examples](#examples) п.3–4, [prompts.md](prompts.md) |
| AC8 | Desktop: highlight + node/link потоки | **Специфицировано** (stdout/journal разделены) | [external-protocol.md](external-protocol.md) |
| AC9 | CLI: progress + итог | **Специфицировано** | [Examples](#examples) п.2, [Commands](#commands) |
| AC10 | `context/algorithms/INDEX.md` ведёт на AgentMemory | **Выполнено** (публикация канона) | [How start-feature / start-fix Must Use This](#how-start-feature--start-fix-must-use-this) |
| AC11 | Pytest — только существующие файлы | **Выполнено** | [Commands](#commands) |

---

## Do Not Implement This As

- Отдельный модуль с именем `agent_memory_commands.py` «потому что так в plan/14» — файла **нет**; не описывать как существующий без оговорки.
- Источник caps только из `stop_condition` без упоминания, что в текущем коде caps из `memory.runtime` YAML.
- Один общий `blocked` для budget cap на стороне Work — **не** соответствует коду.
- Silent `complete` при отсутствии usable results.
- Публикация raw prompts в journal по умолчанию.
- Копирование имён типов/API из donor repos как нормативного wire-формата.

---

## How start-feature / start-fix Must Use This

- `02_analyst` обязан прочитать этот документ перед `technical_specification.md`, если задача касается AgentMemory / PAG / W14 / memory init.
- `06_planner` трассирует задачи к шагам **Target Flow** и строкам **Acceptance Criteria**; явно помечает normative vs implementation backlog.
- `11_test_runner` проверяет команды из раздела Commands или помечает `blocked_by_environment` с причиной.
- `13_tech_writer` обновляет утверждённый канон в `context/algorithms/agent-memory/*` только после **явного** user approval и только если реализация намеренно меняет целевое поведение.

---

## Traceability

| ID | Type | Source | Target Doc Section |
|----|------|--------|---------------------|
| F1 | Current fact | `current_state/agent_memory_entrypoints_and_cli_init.md` F1 | Target Flow, Inputs |
| F2 | Current fact | `current_state/agent_memory_agentwork_handoff.md` F2 | Outputs, Inputs |
| F3 | Current fact | `current_state/agent_memory_query_pipeline_runtime.md` F6 | Failure rules, Current Reality |
| F4 | Current fact | `current_state/agent_memory_pag_kb_state_models.md` F9 | State Lifecycle, memory-graph-links |
| F5 | Current fact | `current_state/agent_memory_journal_trace_chat_events.md` F7 | external-protocol |
| F6 | Current fact | `current_state/agent_memory_tests_and_plan14_contracts.md` F14 | Commands, Acceptance |
| D1 | Decision | `synthesis.md` D1 | Observability heartbeat |
| D2 | Decision | `synthesis.md` D2 | Outputs (grants) |
| D3 | Decision | `synthesis.md` D3 | Target Flow normative vs snapshot |
| O1 | Option | `synthesis.md` Options/Decisions | Scope notes |
| P2 | Plan drift | `synthesis.md` P2 | Inputs (`stop_condition`) |
| V1 | Verifier finding | `verification.md` MAJOR-1 | [llm-commands.md](llm-commands.md) |
| V2 | Verifier finding | `verification.md` MAJOR-2 | [memory-graph-links.md](memory-graph-links.md) |
| V3 | Verifier finding | `verification.md` MAJOR-3 | [external-protocol.md](external-protocol.md) |
| V4 | Verifier finding | `verification.md` MINOR-1 | [Acceptance Criteria](#acceptance-criteria) |
| V5 | Verifier finding | `verification.md` MINOR-2 | [external-protocol.md](external-protocol.md) (`memory.runtime.step`) |

---

**Ключевые контракты:** `context/proto/memory-query-context-init.md`, `context/proto/broker-memory-work-inject.md` (частично), код SoT: `memory_agent.py`, `agent_memory_query_pipeline.py`, `agent_memory_runtime_contract.py`, `agent_memory_summary_service.py`, `agent_memory_result_assembly.py`, `agent_memory_result_v1.py`. **Plan/14:** historical evidence; drift — в `context/artifacts/target_doc/synthesis.md` (P1–P7).

Published by: `18_target_doc_orchestrator` (split из утверждённого `target_algorithm_draft.md`).
