# Workflow 11: AgentMemory LLM-guided exploration + journal + chat split memory

**Идентификатор:** `agent-memory-llm-journal-11` (файл `plan/11-agent-memory-llm-journal.md`).

**Статус:** закрыт в G11.9. Дальше не расширять без новой постановки/research.

Документ задаёт следующую итерацию после `Workflow 10`: превратить `AgentMemory` из минимального slice/grant worker в **global runtime service** с собственным LLM-контекстом, query-driven exploration по уровням **A -> B -> C**, отдельным structured journal и split-view UI в `ailit desktop`, где пользователь видит либо 3D Memory, либо журнал работы памяти для активного чата.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Положение в графе планов

- **Workflow 7 закрыт:** PAG A/B/C является каноном структуры памяти проекта: A = project/repository, B = files/folders, C = file internals/ranges/symbols. См. `plan/7-workflow-project-architecture-graph.md:34-75`.
- **Workflow 8 закрыт:** `AilitRuntimeSupervisor`, `AgentBroker`, subprocess agents и durable trace store считаются substrate для multi-agent runtime. См. `plan/8-agents-runtime.md:22-35`.
- **Workflow 9 закрыт:** `ailit desktop` является продуктовой UI-поверхностью для чата, agents dialogue, Memory graph и runtime bridge. См. `plan/9-ailit-ui.md:82-118`.
- **Workflow 10 закрыт:** Context Ledger, `memory_slice`, D-level compact/restore, Context Fill и Memory 3D highlights по реально попавшим в prompt нодам реализованы. См. `plan/10-context-ledger-memory-highlights.md:77-110`, `tools/agent_core/session/context_ledger.py`, `tools/agent_core/session/d_level_compact.py`, `desktop/src/renderer/views/MemoryGraph3DPage.tsx`.
- **Workflow 11 не заменяет G10:** он расширяет `AgentMemory` как сервис принятия memory-решений и делает его работу наблюдаемой через journal, не расширяя scope до shared/MCP memory.

---

## Зафиксированные решения пользователя

1. `AgentMemory` имеет **отдельный LLM-контекст** и сам делает guided exploration по A -> B -> C.
2. `AgentMemory` использует тот же provider/model, что `AgentWork`, но с отдельными memory-настройками: меньше токенов, короткие structured decisions, минимум reasoning.
3. `max_memory_turns` — глобальная настройка.
4. `AgentMemory` является **global runtime service** и обслуживает много чатов / много `AgentWork`.
5. `AgentMemory` не индексирует весь репозиторий. Индексация и exploration должны быть **query-driven**: только то, что нужно под текущий запрос.
6. Если в чате несколько проектов, поиск идёт только исходя из запроса, а не по всем проектам целиком.
7. Журнал `AgentMemory` общий на диске: `~/.ailit/runtime/memory-journal.jsonl`.
8. UI показывает journal по активному `chat_id`; в аналитике и journal обязательно присутствует `chat_id`.
9. Raw chain-of-thought не логируется. Логируются structured summaries/actions/results: куда идём дальше, что смотрим, какие ноды выбраны, что обновлено.
10. В правой split-области Desktop: верхняя кнопка `Memory` открывает/закрывает right split; внутри tabs `3D` / `Журнал`.
11. `Analytics` и `Memory` взаимоисключающие.
12. Splitter draggable сразу; split ratio сохраняется глобально.
13. 3D Memory в product mode не показывает mock data. Если real PAG пустой — показывается `empty/indexing/error`, а не демо-граф.

---

## Доноры и best practices без копипаста

| Донор | Локальная ссылка | Что взять |
|-------|------------------|-----------|
| **Claude Code `/context` и compaction** | `/home/artem/reps/claude-code/utils/analyzeContext.ts`, `/home/artem/reps/claude-code/services/compact/compact.ts` | Context Ledger уже перенял lifecycle; для G11 взять discipline: compact/retrieval events должны быть объяснимы и cache-aware, но не раскрывать chain-of-thought. |
| **Claude Code subagents / tool isolation** | `/home/artem/reps/claude-code/tools/AgentTool/runAgent.ts:292-359`, `/home/artem/reps/claude-code/coordinator/coordinatorMode.ts:116-145` | Отдельный agent context, capability isolation, собственный tool pool для памяти. |
| **OpenCode session/compaction model** | `/home/artem/reps/opencode/packages/opencode/src/session/message-v2.ts:925-937`, `/home/artem/reps/opencode/packages/opencode/src/session/compaction.ts` | Сохранять полную историю/артефакты, но в модель отправлять compact/context view; journal как persistent event log. |
| **OpenCode session events / UI projection** | `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:6-74`, `/home/artem/reps/opencode/packages/app/src/components/session/session-context-tab.tsx` | Typed event stream -> UI projection; G11 journal должен быть projection-friendly, а не raw logs. |
| **Graphiti temporal graph** | `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:12-80` | Queue/group-id pattern: serialized updates per namespace/project, useful for global `AgentMemory` multi-chat service. |
| **obsidian-memory-mcp graph contract** | `/home/artem/reps/obsidian-memory-mcp/types.ts:1-16` | Простая graph semantics: nodes/relations/observations; journal rows должны ссылаться на graph nodes/edges. |
| **Ailit runtime substrate** | `tools/agent_core/runtime/broker.py:242-384`, `tools/agent_core/runtime/subprocess_agents/memory_agent.py`, `tools/agent_core/runtime/trace_store.py` | Уже есть broker routing and trace; G11 переводит `AgentMemory` в global service semantics и добавляет memory journal. |
| **Ailit PAG store/indexer** | `tools/agent_core/memory/sqlite_pag.py:215-330`, `tools/agent_core/memory/pag_indexer.py:137-178` | Использовать existing `upsert_node`, `upsert_edge`, incremental sync; не делать full-repo indexing per request. |
| **Ailit Desktop 3D / Context UI** | `desktop/src/renderer/views/MemoryGraph3DPage.tsx`, `desktop/src/renderer/runtime/pagHighlightFromTrace.ts`, `desktop/src/renderer/views/ChatPage.tsx` | Реальный 3D graph, Context Ledger highlights, chat split target for `Memory` panel. |

---

## Целевая модель

### AgentMemory as global service

`AgentMemory` — долгоживущий runtime service, а не worker на один чат:

```text
AilitRuntimeSupervisor
  -> AgentMemoryService (global)
  -> AgentBroker(chat A)
       -> AgentWork:A
  -> AgentBroker(chat B)
       -> AgentWork:B
```

Минимальная изоляция в каждом request/event/journal row:

- `chat_id`
- `agent_work_id`
- `request_id`
- `namespace`
- `project_id`
- `project_root`
- `trace_id`
- `turn_id`

### AgentMemory LLM-guided exploration

`AgentMemory` отвечает на `memory.query_context` через отдельный memory loop:

```text
AgentWork
  -> memory.query_context(goal, workspace_projects, budget)
    -> AgentMemory LLM context
       1. A pass: выбрать релевантные проекты / A-ноды
       2. B pass: выбрать релевантные файлы/папки, при необходимости query-driven index
       3. C pass: выбрать ranges/symbols/sections, при необходимости query-driven C-index
       4. return memory_slice + project_refs[] + short decision_summary
```

Правила:

1. Не индексировать весь репозиторий по запросу.
2. Если PAG пустой, `AgentMemory` сначала делает cheap A/B discovery под запрос: filenames, known entrypoints, manifests, already indexed nodes.
3. Если запрос общий, `AgentMemory` выбирает минимальный seed, но всё равно не весь repo.
4. Для каждого pass LLM возвращает structured JSON, не свободный reasoning.
5. `max_memory_turns` ограничивает число A/B/C passes.
6. Если лимита не хватило: `partial=true`, `recommended_next_step` и короткий journal row.

### Memory LLM prompt policy

System prompt `AgentMemory` должен требовать:

- отвечать только structured JSON;
- не раскрывать chain-of-thought;
- давать `decision_summary`, `candidate_nodes`, `selected_nodes`, `next_action`;
- быть экономным по токенам;
- не вызывать write/edit tools;
- не делать full repo scan;
- возвращать только context slice, достаточный для `AgentWork`.

### Journal

Файл:

```text
~/.ailit/runtime/memory-journal.jsonl
```

Journal общий для global `AgentMemory`, но UI по умолчанию фильтрует по активному `chat_id`.

Минимальные события:

- `memory.request.received`
- `memory.llm.turn.started`
- `memory.explore.A.started`
- `memory.explore.A.finished`
- `memory.explore.B.started`
- `memory.explore.B.finished`
- `memory.explore.C.started`
- `memory.explore.C.finished`
- `memory.index.node_updated`
- `memory.index.edge_updated`
- `memory.slice.returned`
- `memory.partial`
- `memory.error`

Запрещено:

- raw chain-of-thought;
- полный raw prompt;
- секреты/env;
- большие tool outputs.

### Namespace-aware context events

`context.memory_injected.v1` должен перейти от плоских `node_ids` к `project_refs[]`, сохранив совместимость на время миграции:

```json
{
  "schema": "context.memory_injected.v2",
  "chat_id": "chat-id",
  "turn_id": "turn-id",
  "source_agent": "AgentMemory:global",
  "usage_state": "estimated",
  "project_refs": [
    {
      "project_id": "proj-id",
      "namespace": "namespace",
      "node_ids": ["A:...", "B:...", "C:..."],
      "edge_ids": []
    }
  ],
  "estimated_tokens": 1200,
  "prompt_section": "memory",
  "decision_summary": "short, no CoT",
  "recommended_next_step": "read C range X"
}
```

### Desktop split Memory panel

Chat top buttons:

- `Analytics`
- `Memory`

Rules:

1. `Analytics` и `Memory` взаимоисключающие.
2. `Memory` открывает right split в центральной области чата.
3. Splitter draggable, ratio persisted globally.
4. Right panel tabs: `3D` / `Журнал`.
5. При переключении chat tab показывается память активного `chat_id`.
6. 3D canvas один; для нескольких проектов показываются несколько A-ноды.
7. Цвета уровней единые: A/B/C/D, проекты различать layout/group/label, не ломая цвета уровней.
8. Product mode не показывает mock data.

---

## Порядок реализации стратегии

Эта стратегия исполняется строго по этапам. После логического завершения каждого этапа выполняются проверки из этапа и создаётся отдельный коммит с префиксом `agent-memory-11/G11.n`. После каждого успешного коммита отправляется:

```bash
curl -d "<commit subject>" ntfy.sh/ai
```

Если этап завершает текущую работу агента, также отправляется:

```bash
curl -d "Мне нужна работа! Я выполнил последнюю задачу <commit subject>" ntfy.sh/ai
```

---

## G11.0 — Design contracts and workflow status

**Цель:** зафиксировать Workflow 11, README status и границы с закрытым Workflow 10.

Задачи:

1. Добавить `plan/11-agent-memory-llm-journal.md`.
2. Обновить `README.md`: Workflow 11 активен, Workflow 10 закрыт.
3. Зафиксировать terminology: global `AgentMemoryService`, memory LLM, journal, query-driven A/B/C exploration, split Memory panel.
4. Зафиксировать non-goals.

Критерии приёмки:

- План содержит G11.0-G11.8.
- В README есть ссылка на Workflow 11.
- В плане есть donor references с локальными путями.
- В плане явно запрещены raw chain-of-thought и full repo indexing per request.

Проверки:

- Документальная проверка ссылок/терминов.
- Автотесты не требуются: код не меняется.

Коммит:

- `agent-memory-11/G11.0 add AgentMemory LLM journal workflow`

---

## G11.1 — Memory journal store and event contract

**Цель:** добавить persistent journal `~/.ailit/runtime/memory-journal.jsonl` и typed event contract.

Задачи:

1. Добавить `MemoryJournalStore` с append/read/filter API.
2. Путь по умолчанию: `~/.ailit/runtime/memory-journal.jsonl`.
3. Схема row: `schema`, `created_at`, `chat_id`, `request_id`, `namespace`, `project_id`, `event_name`, `summary`, `node_ids`, `edge_ids`, `payload`.
4. Redaction: не писать raw prompt, secrets, chain-of-thought.
5. Добавить CLI/debug helper или internal API для чтения по `chat_id`.

Критерии приёмки:

- Journal append атомарен для JSONL row.
- Можно прочитать journal по `chat_id`.
- Rows валидируются и не содержат raw CoT fields.

Проверки:

- Unit-тесты store append/read/filter.
- Unit-тест redaction.
- `pytest` и `flake8` по затронутым Python-файлам.

Коммит:

- `agent-memory-11/G11.1 add memory journal store`

---

## G11.2 — Global AgentMemory service contract

**Цель:** отделить global `AgentMemory` service от per-chat `AgentWork`, сохранив broker compatibility.

Задачи:

1. Расширить runtime/broker routing: `memory.query_context` идёт в global `AgentMemoryService`.
2. Сохранить совместимость с существующим `AgentMemory:chat-id` на переходный период или явно мигрировать routing.
3. `memory.query_context` payload принимает `workspace_projects[]`, `chat_id`, `goal`, `budget_tokens`, `max_memory_turns`.
4. Response возвращает `memory_slice`, `project_refs[]`, `partial`, `recommended_next_step`, `decision_summary`.
5. Все request/response rows пишутся в runtime trace и memory journal.

Критерии приёмки:

- Два разных чата могут обращаться к одному `AgentMemoryService`.
- Journal rows содержат разные `chat_id`.
- Response не зависит от in-process per-chat state.

Проверки:

- Runtime unit/integration tests: two chat ids -> one memory service.
- Broker routing tests.
- `pytest` и `flake8`.

Коммит:

- `agent-memory-11/G11.2 add global AgentMemory service`

---

## G11.3 — AgentMemory LLM loop and prompt policy

**Цель:** добавить memory LLM loop с A/B/C guided exploration и строгим structured output.

Задачи:

1. Собрать provider/model так же, как `AgentWork`, но через memory config.
2. Добавить настройки:
   - `memory.llm.enabled`
   - `memory.llm.max_memory_turns`
   - `memory.llm.max_tokens`
   - `memory.llm.temperature`
3. Добавить system prompt для structured short decisions.
4. Pass protocol:
   - A pass: выбрать project candidates.
   - B pass: выбрать file/folder candidates.
   - C pass: выбрать ranges/symbols.
5. JSON schema для LLM output: `selected_nodes`, `next_action`, `decision_summary`, `partial`, `recommended_next_step`.
6. Journal events for every pass.

Критерии приёмки:

- Memory loop делает не больше `max_memory_turns`.
- LLM output парсится строго; invalid JSON -> fallback partial response.
- No raw reasoning in journal or trace.

Проверки:

- Unit-тест prompt/output parser.
- Mock provider test: A -> B -> C passes.
- Failure test: invalid JSON -> partial response.
- `pytest` и `flake8`.

Коммит:

- `agent-memory-11/G11.3 add AgentMemory LLM loop`

---

## G11.4 — Query-driven PAG growth

**Цель:** заменить full-repo behavior на query-driven incremental indexing.

Задачи:

1. Добавить `MemoryExplorationPlanner`: по LLM decision выбирает minimal files/ranges для index.
2. A-level: project selection без full scan.
3. B-level: file/folder discovery по request terms, known manifests, entrypoints и already indexed nodes.
4. C-level: range/symbol extraction только для выбранных B nodes.
5. Эмитить:
   - `memory.index.node_updated`
   - `memory.index.edge_updated`
   - `memory.index.partial`
6. Обновлять 3D graph live через trace/journal events.

Критерии приёмки:

- `memory.query_context` на пустом PAG не индексирует весь repo.
- При запросе про конкретный файл индексируется только релевантный B/C subset.
- PAG растёт постепенно; updates видны в events.

Проверки:

- Unit-тест: query mentions one path -> index only that path/ranges.
- Unit-тест: generic query -> minimal entrypoint seed, not full repo.
- Runtime test: node_updated events emitted.
- `pytest` и `flake8`.

Коммит:

- `agent-memory-11/G11.4 add query-driven PAG growth`

---

## G11.5 — Namespace-aware Context Ledger v2

**Цель:** расширить Context Ledger для multi-project workspace.

Задачи:

1. Добавить `context.memory_injected.v2` с `project_refs[]`.
2. Сохранять backward compatibility с v1 для текущего UI.
3. `context.compacted` и `context.restored` должны включать namespace/project refs.
4. `pagHighlightFromTrace` должен понимать v2 и подсвечивать только ноды активного chat workspace.
5. `ContextFill` breakdown учитывает memory per project.

Критерии приёмки:

- Multi-project chat имеет несколько A-nodes на 3D canvas.
- Highlight не конфликтует между namespaces.
- Old v1 tests проходят.

Проверки:

- TypeScript tests for v1/v2 highlight parsing.
- Python tests for v2 payload builder.
- Desktop `npm test`, `npm run typecheck`.
- `pytest` и `flake8` по backend changes.

Коммит:

- `agent-memory-11/G11.5 add namespace-aware context events`

---

## G11.6 — Desktop Memory split panel and draggable splitter

**Цель:** добавить right split `Memory` panel в Chat page.

Задачи:

1. Добавить top button `Memory` рядом с `Analytics`.
2. `Analytics` и `Memory` взаимоисключающие.
3. Split центральной области: chat слева, memory справа.
4. Draggable splitter.
5. Ratio persisted globally, например `memory3dSplitRatio`.
6. Right panel tabs: `3D` / `Журнал`.
7. При переключении chat tab panel показывает active chat memory/journal.

Критерии приёмки:

- Кнопка `Memory` открывает/закрывает split.
- Drag меняет width и сохраняет ratio после reload.
- Analytics закрывается при открытии Memory и наоборот.
- Tabs `3D` / `Журнал` работают.

Проверки:

- React/TypeScript tests for persisted split ratio and mode switching.
- Desktop `npm test`, `npm run typecheck`.
- Ручной smoke `ailit desktop --dev`.

Коммит:

- `agent-memory-11/G11.6 add draggable Memory split panel`

---

## G11.7 — Memory journal UI

**Цель:** показать structured journal `AgentMemory` в right split tab.

Задачи:

1. Добавить bridge/API чтения `memory-journal.jsonl` по `chat_id`.
2. Добавить live subscription/refresh из trace или journal tail.
3. UI journal row показывает:
   - event name;
   - short summary;
   - chat_id;
   - namespace/project;
   - selected nodes;
   - next action;
   - errors/partial.
4. Не показывать raw prompt/CoT.
5. Analytics page должна иметь `chat_id` в memory/journal diagnostics.

Критерии приёмки:

- Journal tab показывает ход A -> B -> C exploration текущего chat.
- Journal file общий, UI фильтрует по active `chat_id`.
- Errors/partial видны пользователю.

Проверки:

- Main/preload IPC tests if available.
- TS tests for journal projection/filter.
- `npm test`, `npm run typecheck`.
- Python tests for journal read API.

Коммит:

- `agent-memory-11/G11.7 add AgentMemory journal UI`

---

## G11.8 — Real 3D graph growth and no mock product mode

**Цель:** сделать 3D Memory production-ready: real graph only, live growth, multi-project canvas.

Задачи:

1. Убрать mock fallback из product `MemoryGraph3DPage`.
2. Состояния: `loading`, `indexing`, `empty`, `error`, `real graph`.
3. Один canvas для всех selected projects.
4. Несколько A nodes для нескольких проектов.
5. Цвета уровней A/B/C/D одинаковые.
6. Live updates из:
   - `memory.index.node_updated`
   - `memory.index.edge_updated`
   - `context.memory_injected.v2`
   - `context.compacted`
   - `context.restored`
7. Auto fit/scale так, чтобы вся память была видна после роста.

Критерии приёмки:

- Product 3D не показывает mock data.
- При memory query новые nodes/edges появляются без refresh.
- Highlights только для реально попавших в prompt nodes.
- Multi-project canvas показывает несколько A nodes.

Проверки:

- TS tests for graph state reducer.
- TS tests for no-mock empty state.
- `npm test`, `npm run typecheck`.
- Ручной Desktop сценарий: new chat -> memory query -> graph grows/highlights.

Коммит:

- `agent-memory-11/G11.8 add live multi-project Memory 3D`

---

## G11.9 — End-to-end readiness and docs status

**Цель:** закрыть Workflow 11 как пользовательскую фичу.

Задачи:

1. E2E: Desktop chat -> AgentWork -> global AgentMemory -> A/B/C guided exploration -> memory_slice.
2. E2E: journal file receives rows and UI tab shows active chat rows.
3. E2E: right split Memory 3D grows and highlights nodes.
4. E2E: multi-project chat shows multiple A nodes.
5. README: Workflow 11 closed.
6. Plan status: closed in G11.9.
7. Зафиксировать next workflow needs, если нужны shared/MCP, smarter ranking или long-running indexing queues.

Критерии приёмки:

- Пользователь видит ход `AgentMemory` в journal без CoT.
- Пользователь видит рост памяти в 3D.
- `AgentMemory` обслуживает несколько чатов.
- Query-driven indexing не сканирует весь repo по умолчанию.
- Все target tests проходят.

Проверки:

- `pytest` по затронутым Python пакетам.
- `flake8` по затронутым Python файлам.
- Desktop `npm test`.
- Desktop `npm run typecheck`.
- Ручной smoke `ailit desktop --dev`.

Коммит:

- `agent-memory-11/G11.9 close AgentMemory LLM journal workflow`

---

## MVP vertical slice

Если нужно сузить первую демонстрацию:

1. `AgentMemoryService` global + journal store.
2. Mock-provider memory LLM loop A -> B -> C with structured output.
3. Query-driven index for explicit path/file requests.
4. Journal tab in right split.
5. 3D graph receives `memory.index.node_updated` and `context.memory_injected.v2`.

---

## Non-goals Workflow 11

- Не делать shared/MCP memory.
- Не строить distributed runtime.
- Не делать full-repo indexing по каждому memory query.
- Не логировать raw chain-of-thought.
- Не менять A/B/C/D semantics из Workflow 7/10.
- Не вводить ручные фильтры journal/3D beyond active chat tabs в MVP.
- Не делать provider-specific tokenizer обязательной зависимостью.

---

## Конец workflow

Если G11.0-G11.9 закрыты и нет утверждённой следующей ветки, агент останавливается и запрашивает у пользователя research и постановку следующей цели согласно [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).
