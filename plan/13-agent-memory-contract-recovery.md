# Workflow 13: AgentMemory contract recovery + semantic PAG deltas

**Идентификатор:** `agent-memory-contract-recovery-13` (файл `plan/13-agent-memory-contract-recovery.md`).

**Статус:** **активен**. Workflow 12 закрыт формально, но аудит текущего runtime показывает, что часть продуктового контракта была реализована не сквозным образом: дельты PAG существуют, но не покрывают все пути записи; LLM/C-node семантика и desktop graph state не закреплены как единый контракт.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Почему нужен Workflow 13

Workflow 12 должен был исправить OOM в `ailit desktop` и перевести Memory Graph на живые PAG-дельты:

- `pag.node.upsert` / `pag.edge.upsert` в trace;
- `rev` / `graph_rev` per namespace;
- полный sync по Refresh и при смене чата/проекта;
- 2D/3D graph state с одинаковыми правилами;
- AgentMemory как live semantic graph builder: query-driven A/B/C/D, LLM segmentation C, pending link claims.

Фактическая реализация после нескольких агентных итераций закрыла часть инфраструктуры, но слабая фиксация в плане 12 привела к потере главных контрактов:

1. **Дельты есть, но не являются обязательным graph-write contract.** В `SqlitePagStore` callback включается только через `graph_trace`, а не через каждый runtime-путь записи.
2. **AgentMemory LLM loop есть как модуль, но не является каноническим путём `memory.query_context`.** Текущий worker сначала делает эвристический `QueryDrivenPagGrowth`, затем берёт `PagRuntimeAgentMemory.build_slice_for_goal`, а не строгий LLM-plan -> read -> extract -> upsert -> slice pipeline.
3. **C-node semantics частично механические.** Есть chunk catalog и remap, но отсутствует сквозной контракт LLM segmentation result: `stable_key`, `semantic_locator`, bounded excerpts, link claims как часть query loop.
4. **Desktop 2D/3D не используют единый graph session store.** 3D применяет `applyPagGraphTraceDelta`, 2D дублирует merge/rev вручную и работает только с `ns0`.
5. **Тесты проверяют отдельные детали, но не продуктовый сценарий:** "LLM создаёт новые C-ноды, runtime эмитит дельты, Desktop применяет их без полного `pag-slice`".

Workflow 13 — восстановительный план. Он должен превратить существующие фрагменты G12 в проверяемый контракт.

---

## Положение в графе планов

- **Workflow 7:** PAG A/B/C, SQLite store, `ailit memory index` — [`plan/7-workflow-project-architecture-graph.md`](7-workflow-project-architecture-graph.md).
- **Workflow 8:** broker/supervisor/trace substrate — [`plan/8-agents-runtime.md`](8-agents-runtime.md).
- **Workflow 9:** desktop runtime bridge / PAG graph — [`plan/9-ailit-ui.md`](9-ailit-ui.md).
- **Workflow 10:** Context Ledger + highlights — [`plan/10-context-ledger-memory-highlights.md`](10-context-ledger-memory-highlights.md).
- **Workflow 11:** AgentMemory LLM + journal — [`plan/11-agent-memory-llm-journal.md`](11-agent-memory-llm-journal.md).
- **Workflow 12:** PAG trace deltas + OOM fix — [`plan/12-pag-trace-delta-desktop-sync.md`](12-pag-trace-delta-desktop-sync.md). Считается исходным материалом, но не достаточным каноном для AgentMemory semantics.

---

## Ключевые решения из обсуждения (зафиксировать как контракт)

### Ошибка OOM и hot path

Обсуждение началось с ошибки:

```text
OOM error in V8: CALL_AND_RETRY_LAST Allocation failed - JavaScript heap out of memory
```

Вывод:

- причина не в самом PAG как БД, а в связке `react-force-graph-3d` + частые крупные аллокации;
- главный hot path: при каждом изменении `rawTraceRows` нельзя делать полный `pag-slice`;
- дельты должны дополнять graph state, а полный sync должен быть редким.

### Debounce не выбран как основной sync

Обсуждение debounce:

- `debounce` = "выполнить после тишины";
- для PAG sync решили не делать фоновый full sync по debounce;
- выбран контракт: **глобальный sync только Refresh**, плюс полная загрузка при смене чата/проекта.

### Выбранный MVP для дельт

Решение:

- дельты идут как структурированные строки trace;
- без отдельного файла/IPC в MVP;
- два вида событий:
  - `pag.node.upsert`;
  - `pag.edge.upsert`;
- `rev` монотонный по `namespace`;
- `pag-slice` возвращает `graph_rev`;
- при рассинхроне — предупреждение/Refresh.

### Чат/проект/вкладки

Решение:

- при смене чата/проекта граф загружается полностью;
- старый graph state удаляется, если чат закрыт;
- переключение вкладок и сворачивание Memory panel **не** считается закрытием, graph state должен сохраняться на уровне desktop/session store.

### Что было плохо зафиксировано в Workflow 12

Недостаточно было зафиксировано:

1. где именно находится authoritative graph state в desktop;
2. что `memory.query_context` обязан использовать LLM semantic graph builder, а не только эвристический path shortlist;
3. что каждый runtime writer PAG обязан либо эмитить дельту, либо явно помечаться как offline writer с требованием Refresh;
4. schema для C-node, link claim, D-node и journal событий;
5. тестовый сценарий "LLM -> C nodes -> edges -> trace deltas -> Desktop".

---

## Аудит текущего runtime (подтверждение проблемы)

### 1. `rev` и trace delta частично есть

В `SqlitePagStore` есть `graph_trace`, `get_graph_rev`, `_bump_graph_rev`; `upsert_node` и `upsert_edge` возвращают `rev` и вызывают callback, если он установлен:

- `tools/agent_core/memory/sqlite_pag.py:230-269` — `graph_trace`, `get_graph_rev`, `_bump_graph_rev`;
- `tools/agent_core/memory/sqlite_pag.py:309-382` — `upsert_node` + optional callback;
- `tools/agent_core/memory/sqlite_pag.py:384-447` — `upsert_edge` + optional callback.

Проблема: callback **optional**, значит "после записи ноды/ребра всегда эмитить trace" не является системным инвариантом.

### 2. Эмит покрывает только AgentMemory subprocess paths

`AgentMemoryWorker._graph_trace_hook` формирует `pag.node.upsert` / `pag.edge.upsert`:

- `tools/agent_core/runtime/subprocess_agents/memory_agent.py:94-129`.

`memory.query_context` передаёт этот hook в `QueryDrivenPagGrowth.grow`:

- `tools/agent_core/runtime/subprocess_agents/memory_agent.py:158-176`;
- `tools/agent_core/runtime/memory_growth.py:156-175`.

`memory.file_changed` передаёт hook в C remap:

- `tools/agent_core/runtime/subprocess_agents/memory_agent.py:283-333`;
- `tools/agent_core/runtime/memory_c_remap.py:285-305`.

Проблема: другие writers PAG не покрыты:

- `tools/agent_core/memory/pag_indexer.py` вызывает `upsert_node` / `upsert_edge` напрямую;
- `tools/agent_core/memory/pag_runtime.py` синхронизирует PAG после write_file через indexer facade;
- `tools/agent_core/session/d_level_compact.py:115-138` пишет D-ноду и edges без graph_trace.

### 3. LLM loop не является обязательным query pipeline

Есть `AgentMemoryLLMLoop`:

- `tools/agent_core/runtime/memory_llm.py:26-37` — prompt result-only JSON;
- `tools/agent_core/runtime/memory_llm.py:123-260` — A/B/C loop.

Но текущий `AgentMemoryWorker.handle` на `memory.query_context`:

- сначала вызывает `_grow_pag_for_query` (`tools/agent_core/runtime/subprocess_agents/memory_agent.py:454-460`);
- затем строит slice через `PagRuntimeAgentMemory.build_slice_for_goal` (`tools/agent_core/runtime/subprocess_agents/memory_agent.py:461-467`);
- fallback строит synthetic A/B/C ids (`tools/agent_core/runtime/subprocess_agents/memory_agent.py:359-391`).

Проблема: нет обязательного контракта:

```text
LLM plan -> bounded reads -> semantic C extraction -> upsert C/D/edges -> emit deltas -> return compact slice
```

### 4. C-node segmentation есть механически, но не как LLM contract

Есть механический каталог:

- `tools/agent_core/runtime/memory_c_segmentation.py:143-271`.

Есть source boundary / full-B policy:

- `tools/agent_core/runtime/memory_c_segmentation.py:90-122`.

Проблема: нет обязательного structured output schema для LLM C extraction, который создаёт C-ноды с:

- `stable_key`;
- `semantic_locator`;
- `line_hint`;
- `content_fingerprint`;
- `summary_fingerprint`;
- `confidence`;
- `source_boundary_decision`;
- `link_claims`.

### 5. Desktop graph state не общий для 2D/3D

3D:

- `desktop/src/renderer/views/MemoryGraph3DPage.tsx:114-145` — full load через `loadPagGraphMerged`;
- `desktop/src/renderer/views/MemoryGraph3DPage.tsx:180-219` — trace deltas через `applyPagGraphTraceDelta`.

2D:

- `desktop/src/renderer/views/MemoryGraphPage.tsx:68-81` — local refs для trace index/rev;
- `desktop/src/renderer/views/MemoryGraphPage.tsx:90-158` — ручной merge дельт;
- `desktop/src/renderer/views/MemoryGraphPage.tsx:160-201` — отдельный `pagGraphSlice`.

Проблемы:

- state не в `DesktopSessionContext` или отдельном `PagGraphSessionContext`;
- 2D обрабатывает только `ns0`, 3D — все namespaces;
- 2D не использует `applyPagGraphTraceDelta`;
- смена `activeSessionId` с тем же namespace рискует не перезагрузить полный срез.

---

## Целевой контракт Workflow 13

### Runtime write contract

Все записи PAG должны идти через один слой:

```text
PagGraphWriteService
  -> SqlitePagStore.upsert_node/upsert_edge
  -> bump graph_rev
  -> emit trace delta if a runtime trace context exists
  -> append compact memory journal row when relevant
```

Если writer offline (`ailit memory index`, CLI maintenance) и trace context отсутствует:

- запись допускается;
- `graph_rev` бампится;
- desktop узнаёт об изменении только через full Refresh / смену чата/проекта;
- этот путь должен быть явно помечен в тестах как `offline_writer_no_trace`.

### AgentMemory query contract

`memory.query_context` должен быть каноническим pipeline:

```text
AgentWork
  -> memory.query_context(goal, workspace_projects, budget)
    -> AgentMemory
       1. Build GraphPassport (A + selected B/C/D summaries)
       2. Memory LLM planner returns result-only JSON
       3. AgentMemory performs bounded local reads
       4. Memory LLM extractor returns semantic C nodes + link claims
       5. Runtime writes C/D/edges through PagGraphWriteService
       6. Trace emits pag.node.upsert / pag.edge.upsert
       7. AgentMemory returns compact memory_slice + project_refs
```

### AgentWork post-change feedback contract

`AgentWork` обязан возвращать `AgentMemory` сведения о **успешных изменениях**, чтобы память росла не только по запросу `memory.query_context`, но и после фактических edits/tools. Это отдельный feedback-loop:

```text
AgentWork
  -> tool/edit/write succeeds
  -> memory.change_feedback(change_set, intent, touched paths/symbol hints)
    -> AgentMemory
       1. Validate changed files against source boundary
       2. Compare B fingerprints / existing C semantic locators
       3. Decide update mode:
          a. mechanical_remap (без LLM)
          b. llm_remap (нужен semantic extraction)
          c. skip_artifact / no_source_change
       4. Upsert B/C/D + resolve link claims through PagGraphWriteService
       5. Emit pag.node.upsert / pag.edge.upsert
       6. Append compact journal rows
```

Минимальный payload `memory.change_feedback`:

- `chat_id`, `request_id`, `turn_id`, `namespace`, `project_root`;
- `goal` / `user_intent_summary` — короткое описание зачем выполнялись изменения;
- `changed_files[]`:
  - `path`;
  - `operation`: `create | modify | delete | rename`;
  - `old_path` для rename;
  - `tool_call_id` / `message_id`;
  - `content_before_fingerprint` (если известен);
  - `content_after_fingerprint`;
  - `line_ranges_touched[]` (если tool/runtime знает);
  - `symbol_hints[]` (если AgentWork/tool знает: function/class/config key/heading);
  - `change_summary` — результат-only summary без chain-of-thought;
  - `requires_llm_review`: optional hint, не окончательное решение.
- `created_artifacts[]` — если были build/cache/generated outputs; по умолчанию AgentMemory не анализирует content artifacts, только metadata.

Правила:

1. `AgentWork` не пишет PAG напрямую. Он отправляет feedback; `AgentMemory` решает, что делать.
2. Если файл text-like source и существующие C-ноды можно перенести по `semantic_locator` / line remap — используется **mechanical_remap без LLM**.
3. Если файл новый, C-нода потеряла locator, изменился смысловой блок, появились новые symbols/sections или `needs_llm_remap` — используется **LLM extraction/remap**.
4. Если путь запрещён source boundary (`node_modules`, `.venv`, `dist`, cache, binary, build output) — AgentMemory пишет journal `memory.change.skipped` и не создаёт C.
5. Если изменённый файл связан с pending link claims, resolver запускается после C update.
6. Feedback должен быть идемпотентным: повтор одного `tool_call_id` / `change_id` не создаёт дубликаты C/D/edges.

### Desktop contract

2D и 3D используют один graph store:

```text
DesktopSessionContext
  -> PagGraphSessionStore
     key: activeSessionId + namespace
     state: graph, graphRevByNamespace, warnings, loading state
     methods: loadFull(), applyTraceRows(), refresh()
  -> MemoryGraphPage (2D projection)
  -> MemoryGraph3DPage (3D projection)
```

---

## Доноры и best practices (без копипаста)

| Донор | Локальная ссылка | Что взять |
|-------|------------------|-----------|
| OpenCode typed session events | `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:6-74` | Строгие типы событий и projection-friendly поток. |
| OpenCode session context | `/home/artem/reps/opencode/packages/app/src/components/session/session-context-tab.tsx` | Отделить state/projection от visual components. |
| Claude Code compaction discipline | `/home/artem/reps/claude-code/services/compact/compact.ts` | Не писать raw CoT, хранить compact result. |
| Graphiti queue | `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:12-80` | Сериализация graph updates per namespace. |
| Obsidian memory graph DTO | `/home/artem/reps/obsidian-memory-mcp/types.ts:1-16` | Минимальные node/relation DTO. |
| Текущий PAG store | `tools/agent_core/memory/sqlite_pag.py:230-447` | База для `graph_rev` и write service. |
| Текущий desktop deltas | `desktop/src/renderer/runtime/pagGraphTraceDeltas.ts` | Парсер/merge как общий модуль для 2D+3D. |

---

## Порядок реализации

Каждый этап должен завершаться отдельным коммитом с префиксом `g13/G13.n`. До коммита выполнять проверки из этапа. После успешного коммита — уведомление по `.cursor/rules/project-workflow.mdc`.

---

## G13.0 — План recovery и статус README

**Цель:** зафиксировать этот recovery workflow как активный, потому что Workflow 12 закрыт формально, но не закрепил сквозной runtime/LLM/Desktop contract.

Задачи:

1. Добавить `plan/13-agent-memory-contract-recovery.md`.
2. Обновить `README.md`: Workflow 13 активен; Workflow 12 — закрыт, но требует recovery/audit.
3. Обновить `context/INDEX.md`: указать, что текущий канон восстановления AgentMemory/PAG contract — Workflow 13; детальный proto обновляется в G13.1.
4. В плане сохранить доказательный аудит текущего runtime с ссылками на реальные файлы.

Критерии приёмки:

- План содержит G13.0–G13.8.
- README указывает Workflow 13 как актуальный план.
- В плане есть раздел "Аудит текущего runtime".
- Код не меняется.

Проверки:

- Markdown review.

Коммит:

- `g13/G13.0 plan: AgentMemory contract recovery`

---

## G13.1 — Runtime/PAG write contract и proto

**Цель:** сделать graph writes явным runtime contract, а не optional callback.

Задачи:

1. Спроектировать `PagGraphWriteService` или эквивалентный wrapper над `SqlitePagStore`.
2. Зафиксировать write modes:
   - `runtime_traced` — есть `RuntimeRequestEnvelope`, эмитим trace delta;
   - `runtime_untraced` — runtime write без request запрещён или требует явного reason;
   - `offline_writer` — CLI/indexer, без trace, только `graph_rev`.
3. Обновить `context/proto/runtime-event-contract.md`:
   - exact schema `pag.node.upsert`;
   - exact schema `pag.edge.upsert`;
   - `rev` rules;
   - `graph_rev` rules;
   - offline writer semantics.
4. Добавить API для батчевого edge emit, чтобы resolved link claims не создавали сотни отдельных tiny rows.
5. Добавить tests:
   - traced node upsert -> one trace row;
   - traced edge batch -> one trace row with `edges[]`;
   - offline indexer -> graph_rev bumps, no trace row, requires Refresh.

Критерии приёмки:

- В коде нет новых runtime writes PAG вне write service без явного waiver/comment.
- `rev` монотонен per namespace.
- События дельт содержат только compact payload, без raw source.

Проверки:

- `pytest` по `tests/test_pag_graph_rev.py`, новым runtime tests, затронутым пакетам.
- `flake8` по затронутым Python-файлам.

Коммит:

- `g13/G13.1 runtime: enforce PAG graph write contract`

---

## G13.2 — AgentMemory LLM query pipeline как основной путь

**Цель:** `memory.query_context` должен использовать LLM-guided semantic graph builder, а не только эвристический shortlist + PAG runtime slice.

Задачи:

1. Ввести `AgentMemoryQueryPipeline`:
   - input: `goal`, `workspace_projects`, `budget`, `chat_id`, `request_id`;
   - output: `memory_slice`, `project_refs`, `decision_summary`, `recommended_next_step`, `created_node_ids`, `created_edge_ids`.
2. Подключить существующий `AgentMemoryLLMLoop` как planner, но расширить prompt/schema:
   - `selected_projects`;
   - `selected_b_nodes`;
   - `requested_reads`;
   - `extraction_targets`;
   - `decision_summary`;
   - `partial`;
   - `recommended_next_step`.
3. Сделать fallback controlled:
   - если LLM disabled/unavailable, использовать эвристический path shortlist;
   - fallback должен писать `memory.partial` / `memory.fallback` journal row.
4. Убрать ситуацию, где `memory.query_context` всегда сначала делает `QueryDrivenPagGrowth.grow`, а LLM loop не влияет на созданные ноды.
5. Tests:
   - mock provider выбирает B -> pipeline читает файл -> создаёт C -> slice содержит C;
   - invalid JSON -> partial fallback без raw CoT;
   - LLM disabled -> old heuristic fallback, но с journal reason.

Критерии приёмки:

- При включённом memory LLM хотя бы один тест доказывает создание C-ноды по structured LLM result.
- `memory_slice` не содержит raw repo dump.
- Journal содержит compact actions/results.

Проверки:

- `pytest` по runtime memory tests.
- `flake8`.

Коммит:

- `g13/G13.2 agent-memory: route query_context through LLM pipeline`

---

## G13.3 — AgentWork post-change feedback loop

**Цель:** после успешных изменений файлов `AgentWork` обязан отправлять `AgentMemory` структурированный feedback, на основе которого память обновляется: механически без LLM, либо через LLM extraction/remap, если механики недостаточно.

### Контракт события `memory.change_feedback`

`memory.change_feedback` — runtime service request от `AgentWork` к `AgentMemory`, а не запись в PAG напрямую.

Обязательные поля:

- `chat_id`, `request_id`, `turn_id`, `namespace`, `project_root`;
- `goal` / `user_intent_summary`;
- `changed_files[]`;
- `source`: `AgentWork`;
- `change_batch_id` — idempotency key для всего батча.

`changed_files[]`:

- `path`;
- `operation`: `create | modify | delete | rename`;
- `old_path` для rename;
- `tool_call_id` / `message_id`;
- `content_before_fingerprint` (если известен);
- `content_after_fingerprint`;
- `line_ranges_touched[]`;
- `symbol_hints[]`;
- `change_summary`;
- `requires_llm_review`.

Пример:

```json
{
  "service": "memory.change_feedback",
  "chat_id": "chat-1",
  "request_id": "req-42",
  "turn_id": "turn-7",
  "namespace": "repo-ns",
  "project_root": "/home/artem/reps/ailit-agent",
  "source": "AgentWork",
  "change_batch_id": "tool-write-abc",
  "user_intent_summary": "Исправил обработку PAG delta в desktop",
  "changed_files": [
    {
      "path": "desktop/src/renderer/runtime/pagGraphTraceDeltas.ts",
      "operation": "modify",
      "tool_call_id": "tool-write-abc",
      "content_after_fingerprint": "sha256:...",
      "line_ranges_touched": [{"start": 82, "end": 119}],
      "symbol_hints": ["applyPagGraphTraceDelta"],
      "change_summary": "Обновлён merge PAG delta и warning при rev mismatch",
      "requires_llm_review": false
    }
  ]
}
```

### Decision matrix AgentMemory

AgentMemory решает mode для каждого файла:

| Mode | Когда | Что делает |
|------|-------|------------|
| `mechanical_remap` | Существующие C-ноды имеют валидный `semantic_locator`, changed ranges не меняют смысловую границу, файл text-like source | Пересчитать B fingerprint, обновить line hints / content fingerprints, `staleness_state=fresh`, без LLM |
| `llm_extract_new` | Файл создан, C-ноды отсутствуют, появились новые symbols/sections | Bounded read + LLM extractor -> новые C + link claims |
| `llm_remap` | `semantic_locator` не найден, C marked `needs_llm_remap`, changed range пересекает несколько C, confidence низкий | Bounded read + LLM remap -> обновить/заменить C |
| `delete_or_stale` | Файл удалён или rename без target | Mark B/C stale или перенести ids по rename policy |
| `skip_artifact` | Path forbidden by source boundary | Journal `memory.change.skipped`, без C |

### Задачи

1. Добавить DTO:
   - `AgentWorkChangeFeedback`;
   - `ChangedFileFeedback`;
   - `TouchedRange`;
   - `SymbolHint`;
   - `MemoryChangeDecision`.
2. Добавить handler `memory.change_feedback` в `AgentMemoryWorker` рядом с существующим `memory.file_changed`, но не смешивать контракты:
   - `memory.file_changed` остаётся низкоуровневым runtime event;
   - `memory.change_feedback` несёт намерение, tool ids, summaries и hints от `AgentWork`.
3. В `AgentWork` / session loop после успешных write/edit/tool операций сформировать feedback:
   - только после успешного commit изменения tool'ом;
   - не отправлять при failed/rejected tool call;
   - батчить несколько изменений одного turn.
4. Реализовать idempotency:
   - `change_batch_id` + `tool_call_id` не создают повторные journal rows / C nodes / edges;
   - повтор feedback возвращает previous decision summary.
5. Реализовать `MemoryChangeUpdateService`:
   - принимает feedback;
   - применяет source boundary;
   - выбирает decision mode;
   - вызывает mechanical C remap или LLM extraction/remap;
   - пишет PAG через `PagGraphWriteService`;
   - запускает pending link resolver.
6. Journal events:
   - `memory.change.received`;
   - `memory.change.file_decided`;
   - `memory.change.mechanical_remap.finished`;
   - `memory.change.llm_remap.started`;
   - `memory.change.llm_remap.finished`;
   - `memory.change.skipped`;
   - `memory.change.error`.
7. Trace deltas:
   - B/C/D node changes -> `pag.node.upsert`;
   - resolved edges -> `pag.edge.upsert`;
   - artifact skips do not emit graph deltas.
8. Tests:
   - modify existing function with valid locator -> mechanical remap, no LLM provider call;
   - create new source file -> LLM extraction creates B/C and emits deltas;
   - modify ambiguous C span -> `llm_remap`;
   - artifact path -> skipped, no C node;
   - duplicate `change_batch_id` -> idempotent;
   - failed tool call -> no feedback sent.

### Критерии приёмки

- После write/edit `AgentWork` отправляет `memory.change_feedback` с достаточными данными для обновления памяти.
- `AgentWork` не пишет PAG напрямую.
- AgentMemory может обновить C **без LLM**, если mechanical remap безопасен.
- AgentMemory использует LLM, если появились новые semantic blocks или старые C нельзя безопасно перенести.
- Все successful graph updates проходят через `PagGraphWriteService` и видны Desktop через trace deltas.
- Tests доказывают оба пути: `mechanical_remap` и `llm_remap`.

### Проверки

- `pytest` по новым tests для `AgentWork` feedback и `AgentMemory` change update.
- `flake8` по затронутым Python-файлам.

### Коммит

- `g13/G13.3 memory: add AgentWork change feedback contract`

---

## G13.4 — Canonical C-node extraction schema

**Цель:** закрепить LLM-создание C-ноды как строгий typed contract.

Задачи:

1. Добавить DTO/schema `SemanticCNodeCandidate`:
   - `stable_key`;
   - `semantic_locator`;
   - `level = C`;
   - `kind`;
   - `title`;
   - `summary`;
   - `line_hint`;
   - `content_fingerprint`;
   - `summary_fingerprint`;
   - `confidence`;
   - `source_boundary_decision`;
   - `b_node_id`;
   - `b_fingerprint`;
   - `extraction_contract_version`.
2. Добавить extractor prompt:
   - result-only JSON;
   - no chain-of-thought;
   - no markdown;
   - bounded excerpts only;
   - `excluded_nodes[]` для artifact/cache paths.
3. `MechanicalChunkCatalogBuilder` оставить как candidate catalog, но не как semantic authority.
4. Реализовать validation:
   - C node path must be inside selected B;
   - `line_hint` must be within file bounds;
   - summary length caps.
5. Tests:
   - Python file -> class/function C nodes;
   - Markdown heading -> C node;
   - XML/URDF/launch block -> C node;
   - artifact path -> `excluded_nodes[]`, no C node.

Критерии приёмки:

- Новая C-нода не создаётся без `stable_key` и `semantic_locator`.
- `line_hint` не является identity.
- Source boundary применяется до LLM и после LLM.

Проверки:

- `pytest` по C segmentation/extraction tests.
- `flake8`.

Коммит:

- `g13/G13.4 memory: canonical semantic C-node extraction`

---

## G13.5 — Link claims, pending edges и resolved edge deltas

**Цель:** связи между конкретными C-нодами фиксируются явно: pending relation не является graph edge до resolution.

Задачи:

1. Зафиксировать schema `SemanticLinkClaim`:
   - `from_stable_key` / `from_node_id`;
   - `to_stable_key` / `to_node_id`;
   - `relation_type`;
   - `confidence`;
   - `evidence_summary`;
   - `source_request_id`.
2. Pending claims хранить отдельно от `pag_edges`.
3. Resolver:
   - single match -> real `pag_edges` + `pag.edge.upsert`;
   - ambiguous -> stays pending with reason;
   - missing node -> pending until future C node appears.
4. Batch emit resolved edges.
5. Tests:
   - claim unresolved -> no graph edge;
   - later node appears -> resolver creates edge and trace delta;
   - duplicate claim idempotent.

Критерии приёмки:

- Desktop видит только resolved edges.
- Pending edge не попадает в `pag.edge.upsert`.

Проверки:

- `pytest` по link claim resolver tests.
- `flake8`.

Коммит:

- `g13/G13.5 memory: resolve semantic link claims into graph edges`

---

## G13.6 — Desktop unified PAG graph session store

**Цель:** убрать расхождение 2D/3D; graph state должен жить на уровне desktop session, а не внутри отдельных страниц.

Задачи:

1. Добавить `PagGraphSessionStore` / hook:
   - `graphByNamespace`;
   - `graphRevByNamespace`;
   - `lastAppliedTraceIndex`;
   - `warnings`;
   - `loadFullForSession()`;
   - `applyTraceRows()`;
   - `refresh()`.
2. Подключить store в `DesktopSessionContext` или рядом с ним.
3. 2D и 3D должны читать один state и использовать один reducer:
   - `parsePagGraphTraceDelta`;
   - `applyPagGraphTraceDelta`;
   - `loadPagGraphMerged`.
4. Multi-project:
   - 2D должен уметь выбранный namespace/all namespaces;
   - 3D сохраняет текущую multi-namespace модель.
5. Lifecycle:
   - full load при смене чата/проекта;
   - state сохраняется при переключении вкладок;
   - закрытие чата очищает state.
6. Warning UI:
   - rev mismatch -> явный banner/toast + Refresh;
   - >10k nodes -> warning, no silent truncate.
7. Tests:
   - 2D/3D не вызывают `pagGraphSlice` на каждую trace row;
   - same trace delta updates both projections;
   - activeSessionId change triggers full load even if namespace same.

Критерии приёмки:

- В `MemoryGraphPage` нет собственной ручной rev/merge логики.
- В `MemoryGraph3DPage` нет собственного source of truth для graph rev.
- Один trace delta одинаково виден 2D и 3D.

Проверки:

- `npm test` в `desktop/`.
- `npm run typecheck` в `desktop/`.

Коммит:

- `g13/G13.6 desktop: unify PAG graph session store`

---

## G13.7 — Сквозной runtime/desktop regression suite

**Цель:** тесты должны ловить именно те потери контракта, которые случились после Workflow 12.

Задачи:

1. Python integration test:
   - mock `memory.query_context`;
   - mock/provider LLM returns C nodes + link claim;
   - runtime writes nodes/edges through traced write service;
   - durable trace contains `pag.node.upsert` and `pag.edge.upsert`.
2. AgentWork feedback integration test:
   - successful write/edit emits `memory.change_feedback`;
   - mechanical remap path updates C without LLM provider call;
   - new source file path triggers LLM extraction/remap;
   - failed/rejected tool call emits no feedback.
3. Desktop vitest:
   - feed trace rows into session store;
   - assert graph grows without `pagGraphSlice`;
   - assert rev mismatch produces warning.
4. CLI test:
   - `ailit memory pag-slice` returns `graph_rev`;
   - offline indexer bumps `graph_rev`;
   - Refresh aligns desktop store to `graph_rev`.
5. Memory safety proxy:
   - N trace rows with deltas do not trigger N full `pagGraphSlice` calls.

Критерии приёмки:

- Есть тест, который бы провалился на текущем расхождении 2D/3D state.
- Есть тест, который бы провалился, если LLM pipeline не создаёт C-ноды.
- Есть тест, который бы провалился, если `AgentWork` не отправляет post-change feedback.
- Есть тест, который бы провалился, если writer пишет PAG без traced service в runtime mode.

Проверки:

- `pytest` по новым/затронутым Python tests.
- `npm test` и `npm run typecheck` в `desktop/`.
- `flake8` по затронутым Python-файлам.

Коммит:

- `g13/G13.7 tests: enforce AgentMemory PAG delta contract`

---

## G13.8 — Context/README closure и ручной сценарий

**Цель:** закрыть Workflow 13 только после подтверждения контракта в документации и ручном desktop scenario.

Задачи:

1. Обновить `context/proto/runtime-event-contract.md` финальной схемой.
2. Обновить `context/arch/visual-monitoring-ui-map.md`:
   - Memory panel graph state;
   - Refresh/lifecycle;
   - warnings.
3. Обновить `README.md`: Workflow 13 закрыт, Workflow 12 архивен как исходная попытка.
4. Ручной сценарий:
   - открыть `ailit desktop`;
   - выбрать проект;
   - выполнить memory query, которая создаёт C;
   - увидеть node/edge deltas в trace;
   - переключить 2D/3D без потери state;
   - Refresh выравнивает `graph_rev`.

Критерии приёмки:

- README и context не расходятся с кодом.
- Workflow 13 можно закрыть без новой скрытой постановки.

Проверки:

- Документальная проверка ссылок.
- Короткий manual smoke log в комментарии коммита/ответе.

Коммит:

- `g13/G13.8 docs: close AgentMemory contract recovery`

---

## Non-goals

- Remote/cloud replication of PAG.
- Отдельный binary/WebSocket graph channel вместо trace (может быть Workflow 14, если trace станет узким местом).
- Поддержка старых SQLite схем без миграции, если пользователь явно согласовал удаление старой базы.
- Раскрытие chain-of-thought memory LLM.

---

## Definition of Done Workflow 13

Workflow 13 считается закрытым только если одновременно выполнено:

1. `memory.query_context` при включённом memory LLM создаёт/обновляет semantic C/D nodes через единый write service.
2. `AgentWork` после successful write/edit/tool изменений отправляет `memory.change_feedback`, а `AgentMemory` обновляет C/D/edges механически или через LLM.
3. Все runtime traced writes PAG эмитят `pag.node.upsert` / `pag.edge.upsert`.
4. Offline writers documented and tested as Refresh-only.
5. 2D/3D Desktop используют общий graph state.
6. Full `pag-slice` не вызывается на каждую строку trace.
7. Есть сквозной regression test, который доказывает путь:

```text
LLM decision -> C node -> edge claim -> resolved edge -> trace delta -> desktop graph
```

8. `README.md` и `context/*` отражают фактический контракт.
