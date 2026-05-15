# Workflow 13: AgentMemory contract recovery + semantic PAG deltas

**Идентификатор:** `agent-memory-contract-recovery-13` (файл `plan/13-agent-memory-contract-recovery.md`).

**Статус:** **закрыт** (G13.0–G13.8, 2026-04). Историческая мотивация: Workflow 12 был закрыт формально, но аудит показал разрыв сквозного контракта; recovery реализован в G13.1–G13.7 и задокументирован в G13.8 (`context/proto/runtime-event-contract.md`, `context/arch/visual-monitoring-ui-map.md`, корневой `README.md`).

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
  - `content_before_fingerprint` — строка или `null`, если runtime не знает прежний fingerprint;
  - `content_after_fingerprint`;
  - `line_ranges_touched[]` — массив, пустой если tool/runtime не знает ranges;
  - `symbol_hints[]` — массив, пустой если AgentWork/tool не знает function/class/config key/heading;
  - `change_summary` — результат-only summary без chain-of-thought;
  - `requires_llm_review`: advisory boolean, не окончательное решение; отсутствующее значение трактуется как `false`.
- `created_artifacts[]` — массив, пустой если build/cache/generated outputs не были обнаружены; по умолчанию AgentMemory не анализирует content artifacts, только metadata.

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

### Обязательная трассировка описаний в этапы

Все выводы аудита и все целевые описания ниже являются **нормативными требованиями**, а не справочным текстом. Исполнитель этапа обязан открыть этот подраздел перед кодом и выполнить все ID, перечисленные в строке своего этапа.

Запрещённая трактовка: "можно реализовать частично", "оставить на потом", "сделать похожий helper", "добавить fallback без теста", "обойти контракт ради скорости". Если в этапе указан ID, этап считается незавершённым, пока требования этого ID не реализованы и не покрыты критериями/тестами этапа.

#### ID выводов аудита

| ID | Вывод аудита | Где описан | Обязательный этап |
|----|--------------|------------|-------------------|
| `A13.1` | PAG `rev`/delta есть, но callback optional и не является инвариантом | `Аудит текущего runtime / 1` | `G13.1`, `G13.7` |
| `A13.2` | Эмит покрывает только часть writers PAG | `Аудит текущего runtime / 2` | `G13.1`, `G13.7` |
| `A13.3` | LLM loop не является обязательным `memory.query_context` pipeline | `Аудит текущего runtime / 3` | `G13.2`, `G13.7` |
| `A13.4` | C-node segmentation есть механически, но нет строгого LLM/identity/remap contract | `Аудит текущего runtime / 4` | `G13.3`, `G13.4`, `G13.7` |
| `A13.5` | Desktop graph state не общий для 2D/3D | `Аудит текущего runtime / 5` | `G13.6`, `G13.7` |

#### ID целевых описаний и контрактов

| ID | Описание / контракт | Что обязано быть реализовано | Обязательный этап |
|----|---------------------|------------------------------|-------------------|
| `D13.1` | Runtime write contract | `PagGraphWriteService` как единственный traced runtime write layer; whitelist offline writers; no direct runtime `SqlitePagStore.upsert_*` | `G13.1`, `G13.7` |
| `D13.2` | AgentMemory query contract | `memory.query_context` -> GraphPassport -> optimized LLM planner/extractor/remap -> `PagGraphWriteService` -> compact slice | `G13.2`, `G13.7` |
| `D13.3` | AgentWork post-change feedback contract | `memory.change_feedback` после successful write/edit/tool; no direct PAG writes by AgentWork; mechanical/LLM decision matrix | `G13.3`, `G13.7` |
| `D13.4` | Desktop graph contract | Единый session-level graph store для 2D/3D, lifecycle по session record, Refresh/full-load rules | `G13.6`, `G13.7` |
| `D13.5` | Memory LLM optimization policy | no-LLM first, caps, JSON-only, thinking/reasoning off by default, bounded excerpts, provider flag tests | `G13.2`, `G13.3`, `G13.4`, `G13.7` |
| `D13.6` | Canonical C-node identity/search contract | `stable_key`, `semantic_locator`, line hints only as hints, `±100/±200/±500`, thresholds/caps | `G13.4`, `G13.7` |
| `D13.7` | Link claims / resolved edge contract | pending claims separate from graph edges, enum `relation_type`, resolved edge deltas only | `G13.5`, `G13.7` |
| `D13.8` | Regression/documentation closure | Сквозные tests + `context/*`/README alignment, no closure without contract proof | `G13.7`, `G13.8` |

#### Этапы и обязательные ID

| Этап | Обязательные ID | Запрет на завершение этапа |
|------|-----------------|----------------------------|
| `G13.0` | `A13.1`–`A13.5`, `D13.1`–`D13.8` | Нельзя закрыть плановый этап без этой трассировки. |
| `G13.1` | `A13.1`, `A13.2`, `D13.1` | Нельзя оставить runtime writer вне write service без whitelist/test. |
| `G13.2` | `A13.3`, `D13.2`, `D13.5` | Нельзя добавить LLM pipeline без `MemoryLlmOptimizationPolicy`. |
| `G13.3` | `A13.4`, `D13.3`, `D13.5`, `D13.6` | Нельзя считать feedback готовым, если AgentWork не отправляет `memory.change_feedback` после successful changes. |
| `G13.4` | `A13.4`, `D13.5`, `D13.6` | Нельзя создавать C-ноды по line offsets; identity только через `stable_key`/`semantic_locator`. |
| `G13.5` | `D13.1`, `D13.7` | Нельзя писать pending claim как real `pag_edge`. |
| `G13.6` | `A13.5`, `D13.4` | Нельзя держать 2D/3D graph state внутри отдельных components. |
| `G13.7` | `A13.1`–`A13.5`, `D13.1`–`D13.8` | Нельзя подменить сквозные tests чистыми mocks без SQLite/trace/parser path. |
| `G13.8` | `D13.8` | Нельзя закрыть Workflow 13, пока README/context не отражают фактический контракт. |

#### Dependencies между этапами

Этапы не являются независимыми. Исполнитель обязан соблюдать порядок:

1. `G13.1` перед `G13.2`/`G13.3`/`G13.5`: без `PagGraphWriteService` нельзя подключать новые writers.
2. `G13.2` перед любыми новыми LLM-вызовами в `G13.3`/`G13.4`: без `MemoryLlmOptimizationPolicy` нельзя писать extractor/remap calls.
3. `G13.3` перед полноценным post-edit memory growth: без `memory.change_feedback` AgentWork не считается связанным с памятью после изменений.
4. `G13.4` перед `G13.5`: link claims должны ссылаться на canonical C identity (`stable_key`/`semantic_locator`), а не на line ranges.
5. `G13.6` перед UI-facing проверками `G13.7`: regression tests desktop должны проверять общий store, а не старые component-local states.
6. `G13.8` только после зелёных проверок `G13.7`.

#### Implementation anchors

Эти anchors не являются исчерпывающим списком файлов, но являются обязательными стартовыми точками. Создание новых параллельных модулей без интеграции в эти anchors не закрывает этап.

| Этап | Обязательные anchors |
|------|----------------------|
| `G13.1` | `tools/agent_core/memory/sqlite_pag.py::SqlitePagStore`, `tools/agent_core/runtime/pag_graph_trace.py`, `tools/agent_core/runtime/subprocess_agents/memory_agent.py::AgentMemoryWorker._graph_trace_hook`, `tools/agent_core/memory/pag_indexer.py`, `tools/agent_core/memory/pag_runtime.py`, `tools/agent_core/session/d_level_compact.py` |
| `G13.2` | `tools/agent_core/runtime/subprocess_agents/memory_agent.py::AgentMemoryWorker.handle`, `tools/agent_core/runtime/memory_llm.py::AgentMemoryLLMLoop`, `tools/agent_core/runtime/agent_memory_config.py`, `tools/agent_core/runtime/memory_growth.py` |
| `G13.3` | `tools/agent_core/session/loop.py`, `tools/agent_core/runtime/subprocess_agents/work_agent.py`, `tools/agent_core/runtime/subprocess_agents/memory_agent.py`, `tools/agent_core/runtime/memory_c_remap.py`, `tools/agent_core/runtime/memory_c_segmentation.py` |
| `G13.4` | `tools/agent_core/runtime/memory_c_segmentation.py`, `tools/agent_core/runtime/memory_c_remap.py`, `tools/agent_core/memory/sqlite_pag.py::PagNode`, `tools/agent_core/runtime/agent_memory_config.py` |
| `G13.5` | `tools/agent_core/runtime/link_claim_resolver.py`, `tools/agent_core/runtime/memory_c_remap.py`, `tools/agent_core/memory/sqlite_pag.py::upsert_edge`, `tools/agent_core/runtime/pag_graph_trace.py` |
| `G13.6` | `desktop/src/renderer/runtime/DesktopSessionContext.tsx`, `desktop/src/renderer/runtime/pagGraphTraceDeltas.ts`, `desktop/src/renderer/runtime/loadPagGraphMerged.ts`, `desktop/src/renderer/views/MemoryGraphPage.tsx`, `desktop/src/renderer/views/MemoryGraph3DPage.tsx`, `desktop/src/shared/ipc.ts` |
| `G13.7` | all anchors from `G13.1`–`G13.6`, plus корневой `conftest.py`, `desktop/src/renderer/runtime/*.test.ts`, `ailit/agent_memory/tests/test_memory_pag_slice.py` |

#### Anti-patterns: Do not implement this as

Эти реализации считаются ошибочными, даже если локальный тест проходит:

1. Новый helper для PAG writes, но старые `SqlitePagStore.upsert_node/upsert_edge` в runtime продолжают вызываться напрямую.
2. Trace delta emit только внутри `AgentMemoryWorker`, без покрытия D compact, file-change, link resolver и других runtime writers.
3. `memory.query_context` сначала делает эвристический `QueryDrivenPagGrowth.grow`, а LLM pipeline влияет только на journal.
4. Fallback создаёт C-ноды, помеченные как semantic/validated.
5. `AgentWork` пишет PAG напрямую или вызывает indexer вместо `memory.change_feedback`.
6. C identity строится из строк (`start_line:end_line`) или byte offsets.
7. LLM получает full file выше caps "для простоты".
8. Thinking/reasoning включается по умолчанию для AgentMemory.
9. Pending link claim пишется как real `pag_edge` до resolution.
10. 2D и 3D хранят отдельные graph states и rev refs.
11. Regression suite состоит только из pure mocks и не проходит через SQLite + trace + desktop parser.

#### Exact schema snippets

Минимальные JSON schemas ниже должны быть перенесены в `context/proto/runtime-event-contract.md` на `G13.1/G13.8` и использоваться в tests.

`pag.node.upsert` (trace `topic.publish.payload.payload`):

```json
{
  "kind": "pag.node.upsert",
  "namespace": "string",
  "rev": 1,
  "node": {
    "node_id": "string",
    "level": "A|B|C|D",
    "kind": "string",
    "path": "string",
    "title": "string",
    "summary": "string",
    "attrs": {},
    "staleness_state": "fresh|stale|needs_llm_remap"
  }
}
```

`pag.edge.upsert`:

```json
{
  "kind": "pag.edge.upsert",
  "namespace": "string",
  "rev": 2,
  "edges": [
    {
      "edge_id": "string",
      "edge_class": "containment|semantic|provenance",
      "edge_type": "calls|imports|implements|configures|reads|writes|tests|documents|depends_on|summarizes|related_to",
      "from_node_id": "string",
      "to_node_id": "string"
    }
  ]
}
```

`memory.change_feedback`:

```json
{
  "service": "memory.change_feedback",
  "chat_id": "string",
  "request_id": "string",
  "turn_id": "string",
  "namespace": "string",
  "project_root": "string",
  "source": "AgentWork",
  "change_batch_id": "string",
  "user_intent_summary": "string",
  "changed_files": [
    {
      "path": "string",
      "operation": "create|modify|delete|rename",
      "old_path": null,
      "tool_call_id": "string",
      "message_id": "string",
      "content_before_fingerprint": null,
      "content_after_fingerprint": "sha256:string",
      "line_ranges_touched": [{"start": 1, "end": 10}],
      "symbol_hints": ["string"],
      "change_summary": "string",
      "requires_llm_review": false
    }
  ],
  "created_artifacts": []
}
```

`SemanticCNodeCandidate`:

```json
{
  "stable_key": "string",
  "semantic_locator": {
    "kind": "function|class|method|heading|config_key|xml_block|notebook_cell|text_chunk",
    "name": "string",
    "signature": "string",
    "parent": "string|null",
    "module_path": "string"
  },
  "line_hint": {"start": 1, "end": 20},
  "content_fingerprint": "sha256:string",
  "summary_fingerprint": "sha256:string",
  "confidence": 0.95,
  "source_boundary_decision": "source|excluded_artifact",
  "b_node_id": "B:path",
  "b_fingerprint": "string",
  "aliases": [],
  "extraction_contract_version": "g13.semantic_c.v1"
}
```

`SemanticLinkClaim`:

```json
{
  "from_stable_key": "string",
  "from_node_id": "string|null",
  "to_stable_key": "string",
  "to_node_id": "string|null",
  "relation_type": "calls|imports|implements|configures|reads|writes|tests|documents|depends_on|summarizes|related_to",
  "confidence": 0.9,
  "evidence_summary": "string",
  "source_request_id": "string"
}
```

#### Exact test names and static checks

Имена можно дополнять, но нельзя заменить одним общим тестом без этих сценариев.

| Этап | Tests / checks |
|------|----------------|
| `G13.1` | `tests/test_g13_pag_graph_write_service.py::test_runtime_write_emits_trace_delta`; `tests/test_g13_pag_graph_write_service.py::test_offline_writer_bumps_rev_without_trace`; `tests/test_g13_pag_graph_write_service.py::test_runtime_direct_upsert_is_guarded` |
| `G13.2` | `ailit/agent_memory/tests/test_g13_agent_memory_llm_pipeline.py::test_query_context_creates_c_node_via_structured_llm`; `ailit/agent_memory/tests/test_g13_agent_memory_llm_pipeline.py::test_llm_requests_use_optimization_policy`; `ailit/agent_memory/tests/test_g13_agent_memory_llm_pipeline.py::test_disabled_llm_fallback_does_not_create_validated_c` |
| `G13.3` | `tests/test_g13_agentwork_change_feedback.py::test_successful_write_sends_change_feedback`; `tests/test_g13_agentwork_change_feedback.py::test_failed_or_rejected_tool_sends_no_feedback`; `tests/test_g13_agentwork_change_feedback.py::test_mechanical_remap_does_not_call_provider` |
| `G13.4` | `tests/test_g13_semantic_c_identity.py::test_line_hint_is_not_identity`; `tests/test_g13_semantic_c_identity.py::test_lookup_expands_100_200_500_then_llm`; `tests/test_g13_semantic_c_identity.py::test_full_b_above_cap_is_not_sent_to_llm` |
| `G13.5` | `tests/test_g13_link_claims.py::test_pending_claim_not_graph_edge`; `tests/test_g13_link_claims.py::test_resolved_claim_emits_edge_delta`; `tests/test_g13_link_claims.py::test_relation_type_enum_enforced` |
| `G13.6` | `desktop/src/renderer/runtime/pagGraphSessionStore.test.ts::keepsStateAcrossUnmount`; `desktop/src/renderer/runtime/pagGraphSessionStore.test.ts::appliesDeltaTo2dAnd3d`; `desktop/src/renderer/runtime/pagGraphSessionStore.test.ts::activeSessionChangeLoadsFullGraph` |
| `G13.7` | `tests/test_g13_agent_memory_contract_integration.py::test_llm_to_c_edge_trace_desktop_parser_path`; plus all tests above |

Static check for `G13.1` (document expected whitelist in the test):

```bash
rg "upsert_node\\(|upsert_edge\\(" tools/agent_core
```

Static check for `G13.6`:

```bash
rg "graphRevByNsRef|setGraph\\(|setNodes\\(|setEdges\\(" desktop/src/renderer/views
```

After `G13.6`, component-local graph source of truth in `MemoryGraphPage` / `MemoryGraph3DPage` is not allowed.

#### Config source of truth

Primary config for AgentMemory LLM policy:

```text
~/.ailit/agent-memory/config.yaml
```

Tests must isolate this via existing test isolation rules (`HOME`, `AILIT_CONFIG_DIR`, `AILIT_PAG_DB_PATH`, `AILIT_MEMORY_JOURNAL_PATH`). Environment overrides are allowed only for documented keys in `agent_memory_config.py`; undocumented env keys do not count as config implementation.

#### Observability contract

Every runtime path must leave compact evidence:

| Path | Required journal events | Required trace deltas |
|------|-------------------------|-----------------------|
| `memory.query_context` creates C | `memory.request.received`, `memory.explore.*`, `memory.slice.returned` | `pag.node.upsert` for B/C/D, `pag.edge.upsert` for resolved edges |
| `memory.change_feedback` mechanical remap | `memory.change.received`, `memory.change.file_decided`, `memory.change.mechanical_remap.finished` | `pag.node.upsert` for changed B/C |
| `memory.change_feedback` LLM remap | `memory.change.received`, `memory.change.llm_remap.started`, `memory.change.llm_remap.finished` | `pag.node.upsert`, optional resolved `pag.edge.upsert` |
| artifact skip | `memory.change.skipped` | none |
| pending link unresolved | link-claim journal row with reason | none |
| pending link resolved | resolver finished journal row | `pag.edge.upsert` |

Payloads must be compact: node/edge ids, summaries, reasons, revs. Raw prompts, CoT, full source bodies and secrets are forbidden.

#### Manual smoke per major stage

Manual smoke does not replace tests, but must be reported in the final answer for the relevant stage when feasible:

- `G13.1`: perform one runtime node write in a temp namespace; observe `graph_rev` increment and one compact trace delta.
- `G13.2`: run mock memory query; observe C node creation and provider request with caps/thinking-off.
- `G13.3`: perform a successful write/edit; observe `memory.change_feedback`, mechanical or LLM decision, and no feedback for failed tool.
- `G13.4`: move a known function down by more than old range but within `±100`; observe C found by signature and `line_hint` updated.
- `G13.5`: create unresolved link claim, then create target C; observe pending -> resolved edge delta.
- `G13.6`: open Memory 3D, switch to journal/2D and back; graph state remains; delete session clears it.
- `G13.7`: run integration path from fake provider to DB, trace, desktop parser.

---

## G13.0 — План recovery и статус README

**Цель:** зафиксировать этот recovery workflow как активный, потому что Workflow 12 закрыт формально, но не закрепил сквозной runtime/LLM/Desktop contract.

**Обязательные описания/выводы:** `A13.1`–`A13.5`, `D13.1`–`D13.8`.

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

**Обязательные описания/выводы:** `A13.1`, `A13.2`, `D13.1`.

Задачи:

1. Спроектировать **единственный** runtime write layer `PagGraphWriteService` над `SqlitePagStore`. Формулировка "эквивалентный wrapper" не допускается для реализации: в runtime-коде все записи PAG (`upsert_node`, `upsert_edge`, batch edge writes, D-node writes) обязаны проходить через этот сервис.
2. Зафиксировать write modes:
   - `runtime_traced` — есть `RuntimeRequestEnvelope`, эмитим trace delta;
   - `runtime_untraced` — **запрещён по умолчанию**; разрешён только для явно перечисленных internal maintenance paths в whitelist с тестом, что Desktop узнаёт изменения только через Refresh;
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
   - static/grep-style test или unit guard: в runtime paths нет прямого `SqlitePagStore.upsert_node/upsert_edge` вне `PagGraphWriteService`; whitelist offline-путей перечислен явно.

Критерии приёмки:

- В runtime-коде нет прямых writes PAG вне `PagGraphWriteService`; исключения возможны только в whitelist `offline_writer`.
- `runtime_untraced` не появляется как "временный" shortcut; если он нужен, путь добавлен в whitelist и покрыт тестом Refresh-only semantics.
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

**Обязательные описания/выводы:** `A13.3`, `D13.2`, `D13.5`.

Задачи:

0. Перед кодом открыть и применить подраздел **`Memory LLM optimization policy`** ниже. Любая реализация G13.2, которая добавляет LLM-вызов без этой policy (caps, no-LLM first, thinking off, JSON-only), считается неготовой.
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
   - fallback **не имеет права** создавать semantic C-ноды как LLM-validated; он может создавать только A/B, weak candidates, journal diagnostics и partial slice.
4. Убрать ситуацию, где `memory.query_context` всегда сначала делает `QueryDrivenPagGrowth.grow`, а LLM loop не влияет на созданные ноды.
5. Ввести `MemoryLlmOptimizationPolicy` (config + enforcement), чтобы все запросы AgentMemory к LLM были дешёвыми и bounded by design.
6. Применить `MemoryLlmOptimizationPolicy` в каждой точке вызова provider:
   - planner;
   - extractor;
   - remap;
   - synth/summary, если такой вызов появится.
7. Tests:
   - mock provider выбирает B -> pipeline читает файл -> создаёт C -> slice содержит C;
   - invalid JSON -> partial fallback без raw CoT;
   - LLM disabled -> old heuristic fallback, но с journal reason.
   - LLM disabled fallback не создаёт validated C-ноды и возвращает `partial=true` / `memory.fallback`.
   - planner/extractor/remap получают capped request и provider flags `thinking/reasoning=off|none|low`;
   - mechanical/cache-hit path не вызывает provider.

### Memory LLM optimization policy

Все LLM-вызовы AgentMemory (`planner`, `extractor`, `remap`, `synth`) обязаны быть оптимизированы по токенам и latency. Дефолтная политика — **не вызывать LLM**, если безопасно сработала механика, и **не включать reasoning/thinking**, если он не нужен для качества результата.

Обязательные требования:

1. **No-LLM first:** сначала mechanical remap, fingerprint/locator match, cached B/C/D summaries; LLM вызывается только при ambiguity/new C/low confidence.
2. **Thinking/reasoning off by default:** если provider/SDK поддерживает `thinking`, `reasoning`, `reasoning_effort` или аналог, для memory planner/extractor по умолчанию выставлять `off`, `none` или `low`. Включение допускается только отдельным config flag и только для ambiguous remap.
3. **Result-only structured JSON:** все memory LLM calls используют JSON-only contract (`response_format=json_schema`, strict parser или эквивалент); запрещены markdown/prose/raw CoT.
4. **Token caps per phase:**
   - `planner.max_input_chars`;
   - `planner.max_output_tokens`;
   - `extractor.max_excerpt_chars`;
   - `extractor.max_output_tokens`;
   - `remap.max_candidates`;
   - `max_memory_turns`;
   - `max_reads_per_turn`.
5. **Candidate pruning:** LLM получает не весь PAG/репозиторий, а compact `GraphPassport`: A + top relevant B/C/D summaries + bounded candidate list.
6. **Bounded excerpts:** вместо full file передавать excerpt вокруг `semantic_locator` / окна `±100`, `±200`, `±500`; full B допускается только если файл text-like, source-owned и меньше configured cap.
7. **Summary reuse:** если `content_fingerprint` не изменился, переиспользовать существующие B/C/D summaries; не пересуммаризировать неизменившиеся C.
8. **Batching with caps:** группировать related C candidates в один extractor/remap call только до лимитов `max_candidates` / `max_excerpt_chars`, иначе дробить.
9. **Low-cost deterministic settings:** отдельные memory-настройки модели: `temperature=0`, низкий `max_tokens`, опционально более дешёвая model tier, если качество extraction не падает.
10. **Stop conditions:** при достижении `max_memory_turns`, token budget, read budget или низкой уверенности возвращать `partial=true` + `recommended_next_step`, а не продолжать расширять prompt.
11. **Prompt compression:** system prompt короткий и стабильный; per-call payload compact JSON без повторения длинных инструкций, если они уже заданы в system prompt/config.
12. **Decision/result cache:** idempotency по `request_id`, `change_batch_id`, `content_fingerprint`, `semantic_locator`; повторный запрос не вызывает LLM, если входные fingerprints не изменились.
13. **Provider feature flags:** policy должна уметь прокинуть provider-specific параметры (`thinking.enabled=false`, `reasoning_effort=none|low`, `response_format=json_schema`) без привязки бизнес-логики к конкретному SDK.
14. **Default confidence thresholds:** AgentMemory не должен сам придумывать пороги:
   - `confidence >= 0.85` — mechanical match accepted;
   - `0.50 <= confidence < 0.85` — ambiguous, LLM remap;
   - `confidence < 0.50` — stale / `needs_llm_remap`;
   - пороги можно вынести в config, но эти defaults обязательны.

Минимальный config:

```yaml
memory:
  llm:
    enabled: true
    model: ""
    temperature: 0.0
    max_memory_turns: 4
    thinking:
      enabled: false
      allow_for_remap: false
      effort: none
    planner:
      max_input_chars: 12000
      max_output_tokens: 512
      max_candidates: 24
    extractor:
      max_excerpt_chars: 24000
      max_output_tokens: 1200
      max_candidates: 12
    remap:
      max_excerpt_chars: 32000
      max_output_tokens: 1200
      max_candidates: 8
    thresholds:
      mechanical_accept: 0.85
      ambiguous_min: 0.50
    cache:
      enabled: true
      key_fields:
        - request_id
        - change_batch_id
        - content_fingerprint
        - semantic_locator
```

Критерий для реализации: tests/config должны доказывать, что AgentMemory LLM calls идут с capped tokens, result-only JSON, provider feature flags для отключения thinking/reasoning выставляются по умолчанию, а mechanical path не вызывает provider вообще.

Инструкция для исполнителя этапа: **сначала** реализуется config/enforcement `MemoryLlmOptimizationPolicy`, **затем** подключаются planner/extractor/remap. Нельзя сначала добавить "рабочий" LLM pipeline и отложить token/thinking оптимизации на потом.

Критерии приёмки:

- При включённом memory LLM хотя бы один тест доказывает создание C-ноды по structured LLM result.
- `memory_slice` не содержит raw repo dump.
- Journal содержит compact actions/results.
- `MemoryLlmOptimizationPolicy` применяется ко всем planner/extractor/remap calls.
- Thinking/reasoning mode выключен по умолчанию для AgentMemory LLM calls, если provider это поддерживает.
- Mechanical remap и cache-hit paths не вызывают LLM provider.
- Все LLM inputs имеют явные caps по chars/tokens/candidates.

Проверки:

- `pytest` по runtime memory tests.
- `flake8`.

Коммит:

- `g13/G13.2 agent-memory: route query_context through LLM pipeline`

---

## G13.3 — AgentWork post-change feedback loop

**Цель:** после успешных изменений файлов `AgentWork` обязан отправлять `AgentMemory` структурированный feedback, на основе которого память обновляется: механически без LLM, либо через LLM extraction/remap, если механики недостаточно.

**Обязательные описания/выводы:** `A13.4`, `D13.3`, `D13.5`, `D13.6`.

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

### AgentWork integration anchors

Feedback формируется не "где-нибудь", а в конкретных точках runtime:

1. После successful `write_file` / edit tool result, когда изменения уже применены к рабочему дереву.
2. После accepted tool approval and execution; rejected approval, dry-run, failed tool call и отменённая операция **не** создают feedback.
3. После shell/tool операций, которые создали или изменили tracked source files, если runtime смог определить changed files.
4. Батчить изменения одного turn и отправлять feedback:
   - перед следующим `memory.query_context`;
   - либо перед завершением turn, если memory query больше не будет.
5. Feedback не создаётся на чтение файлов, grep/search, pure diagnostics и команды без file changes.
6. Если tool изменил файл, но не вернул ranges/symbol hints, AgentWork всё равно отправляет path + fingerprints + короткий `change_summary`; AgentMemory сам решает mechanical/LLM path.

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
   - хранить idempotency record: `change_batch_id`, input fingerprints, per-file decisions, created/updated node ids, emitted graph_rev range, trace message ids / journal row ids.
5. Реализовать `MemoryChangeUpdateService`:
   - принимает feedback;
   - применяет source boundary;
   - выбирает decision mode;
   - вызывает mechanical C remap или LLM extraction/remap;
   - пишет PAG через `PagGraphWriteService`;
   - запускает pending link resolver.
   - при `llm_extract_new` / `llm_remap` вызывает provider только через `MemoryLlmOptimizationPolicy` из G13.2.
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
- Любой LLM fallback/remap в этом этапе использует caps/JSON-only/thinking-off из `Memory LLM optimization policy`.
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

**Обязательные описания/выводы:** `A13.4`, `D13.5`, `D13.6`.

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
   - `aliases[]` для старых stable keys при rename/remap.
2. Зафиксировать `semantic_locator` как первичный способ поиска C-ноды внутри B. Для разных типов B он должен быть структурным, а не строковым offset:
   - code: `kind`, `name`, `signature`, `parent`, `module_path`;
   - markdown: `heading_path`, `heading_level`, normalized title;
   - json/yaml/toml: `pointer` / key path;
   - xml/launch/urdf: `element_path`, `tag`, key attributes;
   - notebook: `cell_id` / `cell_index`, cell kind, heading/context fingerprint;
   - fallback text chunk: `chunk_kind`, normalized anchor text, `chunk_fingerprint`.
3. Запретить использовать `line_hint`, `start_line`, `end_line`, byte offsets как identity. Они являются только cache/hint для ускорения поиска.
4. Зафиксировать генерацию `stable_key`:
   - LLM предлагает `stable_key`;
   - runtime валидирует, нормализует и делает dedupe;
   - `stable_key` стабилен для semantic entity внутри B;
   - при rename B сохранять связь через `aliases[]` / provenance, если `semantic_locator` совпал;
   - при конфликте добавлять короткий suffix/hash, но старый key сохранять в aliases.
5. Зафиксировать нормализацию `semantic_locator`:
   - signature normalizer удаляет незначимые whitespace/comments;
   - TypeScript/Python type annotations приводятся к canonical form, где это возможно;
   - methods обязаны иметь parent chain;
   - overloaded functions включают arity/types;
   - anonymous/lambda blocks получают nearest named parent + anchor text/fingerprint.
6. Зафиксировать hard caps для C lookup/remap:
   - `full_b_max_chars = 32768`;
   - `excerpt_max_chars = 24000`;
   - `remap_max_excerpt_chars = 32000`;
   - full B выше cap запрещён; только excerpts/candidate windows.
7. Добавить extractor prompt:
   - result-only JSON;
   - no chain-of-thought;
   - no markdown;
   - bounded excerpts only;
   - `excluded_nodes[]` для artifact/cache paths.
8. `MechanicalChunkCatalogBuilder` оставить как candidate catalog, но не как semantic authority.
9. Реализовать validation:
   - C node path must be inside selected B;
   - `line_hint` must be within file bounds;
   - summary length caps.
10. Tests:
   - Python file -> class/function C nodes;
   - Markdown heading -> C node;
   - XML/URDF/launch block -> C node;
   - artifact path -> `excluded_nodes[]`, no C node.
   - extractor/remap prompt builder принимает только bounded excerpts и настройки из `MemoryLlmOptimizationPolicy`.

### C-node lookup / remap algorithm

Поиск C-ноды при `memory.query_context`, `memory.change_feedback` и `memory.file_changed` обязан идти от устойчивых структурных ключей к строковым подсказкам, а не наоборот:

1. Найти B-ноду по `b_node_id` / path / namespace и проверить `b_fingerprint`.
2. Внутри B искать C по точному `stable_key`.
3. Если `stable_key` не найден или B был переиндексирован, искать по `semantic_locator`:
   - code: `kind + name + signature + parent`;
   - markdown: `heading_path`;
   - config: `pointer`;
   - xml/urdf/launch: `element_path + tag + key attributes`;
   - notebook: `cell_id` или stable cell fingerprint.
4. Если структурный locator нашёл candidate, проверить `content_fingerprint` / локальный fingerprint найденного body.
5. Если fingerprint не совпал, использовать `line_hint` только как стартовую область:
   - сначала старый `[start_line, end_line]`;
   - затем окно `±100` строк;
   - затем окно `±200` строк;
   - затем окно `±500` строк;
   - затем весь B только если B меньше `full_b_max_chars = 32768`.
6. В каждом окне искать **структурную сигнатуру**, а не просто старые номера строк:
   - `export function applyPagGraphTraceDelta(`;
   - `class Foo`;
   - `def handle(...):`;
   - markdown heading text;
   - config key path.
7. Если найден один уверенный match (`confidence >= 0.85`) — обновить `line_hint`, fingerprints и `staleness_state=fresh` через `mechanical_remap`.
8. Если matches несколько или `0.50 <= confidence < 0.85` — пометить C `needs_llm_remap` и вызвать LLM remap на bounded excerpt.
9. Если `confidence < 0.50` или match не найден даже после расширения — C становится stale/needs_llm_remap; новая C создаётся только после LLM extractor или явного mechanical evidence.

Связь с G13.2: когда алгоритм переходит в `needs_llm_remap`, executor обязан использовать `MemoryLlmOptimizationPolicy`: bounded excerpt, capped candidates, JSON-only output, thinking/reasoning disabled by default. Нельзя передавать весь B-файл "для удобства", если он превышает `full_b_max_chars`.

### Реальный пример поиска C-ноды

Файл B:

```text
B:desktop/src/renderer/runtime/pagGraphTraceDeltas.ts
```

Исходная C-нода для функции `applyPagGraphTraceDelta`:

```json
{
  "node_id": "C:desktop/src/renderer/runtime/pagGraphTraceDeltas.ts#applyPagGraphTraceDelta",
  "stable_key": "ts:function:applyPagGraphTraceDelta",
  "semantic_locator": {
    "kind": "function",
    "name": "applyPagGraphTraceDelta",
    "signature": "applyPagGraphTraceDelta(current: MemoryGraphData, delta: PagGraphTraceDelta, lastRevs: Readonly<Record<string, number>>, newRevsOut: Record<string, number>)",
    "parent": null,
    "module_path": "desktop/src/renderer/runtime/pagGraphTraceDeltas.ts"
  },
  "line_hint": { "start": 82, "end": 119 },
  "content_fingerprint": "sha256:<old-body>",
  "summary": "Applies PAG trace delta to MemoryGraphData and returns optional rev warning."
}
```

Сейчас функция действительно находится в этом файле как:

```82:87:desktop/src/renderer/runtime/pagGraphTraceDeltas.ts
export function applyPagGraphTraceDelta(
  current: MemoryGraphData,
  delta: PagGraphTraceDelta,
  lastRevs: Readonly<Record<string, number>>,
  newRevsOut: Record<string, number>
): { readonly data: MemoryGraphData; readonly revWarning: string | null } {
```

Если `AgentWork` изменил файл выше этой функции и она сместилась с `82-119` на `130-168`, поиск должен пройти так:

1. B найден по path `desktop/src/renderer/runtime/pagGraphTraceDeltas.ts`.
2. Старый `line_hint=82-119` проверяется первым, но там функции уже нет.
3. AgentMemory расширяет окно до `±100`: `max(1, 82-100)..119+100`, то есть примерно `1..219`.
4. В этом окне ищется не строка `82`, а сигнатура `export function applyPagGraphTraceDelta(` и typed параметры.
5. Если найден ровно один match, C обновляется без LLM:
   - новый `line_hint={start:130,end:168}`;
   - новый `content_fingerprint`;
   - `staleness_state=fresh`;
   - emit `pag.node.upsert`.
6. Если в окне две функции с похожими именами или signature изменилась так, что confidence низкий, C получает `needs_llm_remap`, и LLM extractor получает bounded excerpt around candidates, а не весь файл.

Критерии приёмки:

- Новая C-нода не создаётся без `stable_key` и `semantic_locator`.
- `line_hint` не является identity.
- Поиск существующей C-ноды сначала использует `stable_key` / `semantic_locator`; `line_hint` допускается только как стартовая область поиска.
- Реализованы окна расширения `±100`, `±200`, `±500` строк с переходом в `needs_llm_remap`, если confidence низкий.
- Реализованы default thresholds `0.85/0.50`; агент не выбирает пороги произвольно.
- Full-B чтение запрещено выше `32768` chars; LLM получает только bounded excerpts.
- Переход в LLM remap соблюдает `Memory LLM optimization policy`: bounded excerpt вместо full file, caps, JSON-only, thinking off by default.
- Source boundary применяется до LLM и после LLM.

Проверки:

- `pytest` по C segmentation/extraction tests.
- `flake8`.

Коммит:

- `g13/G13.4 memory: canonical semantic C-node extraction`

---

## G13.5 — Link claims, pending edges и resolved edge deltas

**Цель:** связи между конкретными C-нодами фиксируются явно: pending relation не является graph edge до resolution.

**Обязательные описания/выводы:** `D13.1`, `D13.7`.

Задачи:

1. Зафиксировать schema `SemanticLinkClaim`:
   - `from_stable_key` / `from_node_id`;
   - `to_stable_key` / `to_node_id`;
   - `relation_type`;
   - `confidence`;
   - `evidence_summary`;
   - `source_request_id`.
2. Зафиксировать MVP enum `relation_type`; произвольные строки запрещены:
   - `calls`;
   - `imports`;
   - `implements`;
   - `configures`;
   - `reads`;
   - `writes`;
   - `tests`;
   - `documents`;
   - `depends_on`;
   - `summarizes`;
   - `related_to` — fallback для неизвестного, если claim нельзя reject.
3. Pending claims хранить отдельно от `pag_edges`.
4. Resolver:
   - single match -> real `pag_edges` + `pag.edge.upsert`;
   - ambiguous -> stays pending with reason;
   - missing node -> pending until future C node appears.
5. Batch emit resolved edges.
6. Tests:
   - claim unresolved -> no graph edge;
   - later node appears -> resolver creates edge and trace delta;
   - duplicate claim idempotent.
   - unknown `relation_type` rejected or normalized to `related_to` by explicit rule.

Критерии приёмки:

- Desktop видит только resolved edges.
- Pending edge не попадает в `pag.edge.upsert`.
- `relation_type` всегда из enum; UI/поиск не получают произвольные relation names.

Проверки:

- `pytest` по link claim resolver tests.
- `flake8`.

Коммит:

- `g13/G13.5 memory: resolve semantic link claims into graph edges`

---

## G13.6 — Desktop unified PAG graph session store

**Цель:** убрать расхождение 2D/3D; graph state должен жить на уровне desktop session, а не внутри отдельных страниц.

**Обязательные описания/выводы:** `A13.5`, `D13.4`.

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
   - точное правило: graph state key живёт, пока session record существует в persisted UI/session registry;
   - unmount `MemoryGraphPage`, unmount `MemoryGraph3DPage`, переключение вкладки 2D/3D, сворачивание Memory panel и закрытие/открытие right split **не** очищают state;
   - удаление chat/session tab очищает state этого `activeSessionId`;
   - смена active chat/project делает full load для нового key, но не уничтожает state других ещё существующих sessions.
6. Warning UI:
   - rev mismatch -> явный banner/toast + Refresh;
   - >10k nodes -> warning, no silent truncate.
7. Tests:
   - 2D/3D не вызывают `pagGraphSlice` на каждую trace row;
   - same trace delta updates both projections;
   - activeSessionId change triggers full load even if namespace same.
   - unmount/remount Memory panel keeps graph state;
   - delete session clears graph state.

Критерии приёмки:

- В `MemoryGraphPage` нет собственной ручной rev/merge логики.
- В `MemoryGraph3DPage` нет собственного source of truth для graph rev.
- Один trace delta одинаково виден 2D и 3D.
- Lifecycle state соответствует точному правилу session record / delete session, а не факту mounted/unmounted UI.

Проверки:

- `npm test` в `desktop/`.
- `npm run typecheck` в `desktop/`.

Коммит:

- `g13/G13.6 desktop: unify PAG graph session store`

---

## G13.7 — Сквозной runtime/desktop regression suite

**Цель:** тесты должны ловить именно те потери контракта, которые случились после Workflow 12.

**Обязательные описания/выводы:** `A13.1`–`A13.5`, `D13.1`–`D13.8`.

Задачи:

1. Python integration test:
   - mock `memory.query_context`;
   - mock/provider LLM returns C nodes + link claim;
   - runtime writes nodes/edges through traced write service;
   - durable trace contains `pag.node.upsert` and `pag.edge.upsert`.
   - captured provider requests prove `MemoryLlmOptimizationPolicy` was applied.
   - test must exercise `AgentMemoryWorker.handle(...)` (or service-level equivalent), real tmp `SqlitePagStore`, fake provider, captured trace emitter/durable trace, and assert all together: node exists in DB, `graph_rev` advanced, trace row emitted, `pagGraphTraceDeltas` desktop parser accepts the row.
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
- Есть тест, который бы провалился, если AgentMemory LLM call ушёл без caps/JSON-only/thinking-off policy.
- Есть тест, который бы провалился, если writer пишет PAG без traced service в runtime mode.
- Есть integration test, который не является чистым mock unit: он проходит через worker/service handler + tmp SQLite + fake provider + trace capture + desktop parser compatibility.

Проверки:

- `pytest` по новым/затронутым Python tests.
- `npm test` и `npm run typecheck` в `desktop/`.
- `flake8` по затронутым Python-файлам.

Коммит:

- `g13/G13.7 tests: enforce AgentMemory PAG delta contract`

---

## G13.8 — Context/README closure и ручной сценарий

**Цель:** закрыть Workflow 13 только после подтверждения контракта в документации и ручном desktop scenario.

**Обязательные описания/выводы:** `D13.8`.

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
3. Все AgentMemory LLM calls проходят через `MemoryLlmOptimizationPolicy`: no-LLM first, caps, JSON-only, thinking/reasoning off by default where supported.
4. Все runtime traced writes PAG эмитят `pag.node.upsert` / `pag.edge.upsert`.
5. Offline writers documented and tested as Refresh-only.
6. 2D/3D Desktop используют общий graph state.
7. Full `pag-slice` не вызывается на каждую строку trace.
8. Есть сквозной regression test, который доказывает путь:

```text
LLM decision -> C node -> edge claim -> resolved edge -> trace delta -> desktop graph
```

9. `README.md` и `context/*` отражают фактический контракт.
