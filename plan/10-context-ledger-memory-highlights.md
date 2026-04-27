# Workflow 10: Context Ledger + AgentMemory actor + Memory 3D highlights

**Идентификатор:** `context-ledger-memory-highlights-10` (файл `plan/10-context-ledger-memory-highlights.md`).

**Статус:** закрыт в G10.8. Дальше не расширять без новой постановки/research.

Документ задаёт следующую итерацию после `Workflow 9`: сделать контекст LLM наблюдаемым и управляемым, вернуть полноценный **Memory 3D graph** в `ailit desktop`, подключить `AgentMemory` как обязательного runtime actor для Desktop-чата и связать подсветку нод памяти с тем, что **реально попало в prompt**.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Положение в графе планов

- **Workflow 7 закрыт:** PAG A/B/C считается базовым графом проекта: A = проект/репозиторий, B = файлы/папки/вложенность, C = строки/ranges/структура файла. См. `plan/7-workflow-project-architecture-graph.md:34-75`.
- **Workflow 8 закрыт:** supervisor/broker/subprocess agents и durable trace store считаются готовым substrate. См. `plan/8-agents-runtime.md:22-35`, `tools/agent_core/runtime/broker.py:242-282`.
- **Workflow 9 закрыт:** `ailit desktop` существует как продуктовая поверхность, но 3D-граф памяти и runtime-путь `AgentWork -> AgentMemory` требуют возвращения/усиления.
- **Workflow 10 не переопределяет A/B/C:** он добавляет `D` как уровень compact/session artifacts и вводит `Context Ledger` как журнал фактического использования памяти в LLM-контексте.

---

## Зафиксированные решения пользователя

1. `AgentMemory` должен быть **обязательным actor** для Desktop-чата.
2. Memory 3D highlights показывают только то, что **реально попало в prompt**, а не кандидатов retrieval.
3. Compact/session summary становится уровнем **D** в памяти; связи D с A/B/C обязательны.
4. Управление подсветкой автоматическое; ручные фильтры не входят в MVP.
5. Учёт токенов как у доноров: `estimated` перед ответом, `confirmed` после provider usage.
6. Восстановление контекста при открытии чата автоматическое.
7. В плане обязательно отразить возвращение **Memory 3D graph** в Desktop.

---

## Доноры и best practices без копипаста

| Донор | Локальная ссылка | Что взять |
|-------|------------------|-----------|
| **Claude Code token accounting** | `/home/artem/reps/claude-code/utils/tokens.ts:201-261` | Канон для thresholds: последнее provider usage + rough estimate новых сообщений после него; cache tokens входят в размер окна. |
| **Claude Code effective window** | `/home/artem/reps/claude-code/services/compact/autoCompact.ts:32-49` | Effective context window = model context window минус reserve под summary/output. |
| **Claude Code compact boundary** | `/home/artem/reps/claude-code/services/compact/compact.ts:325-337`, `/home/artem/reps/claude-code/utils/messages.ts` | `/compact` создаёт boundary, summary messages, tail и post-compact attachments; это источник идеи для D-узлов. |
| **Claude Code context visualization** | `/home/artem/reps/claude-code/utils/analyzeContext.ts`, `/home/artem/reps/claude-code/commands/context/context.tsx` | Breakdown по категориям `system/tools/MCP/agents/memory/skills/messages/free space`. |
| **OpenCode overflow** | `/home/artem/reps/opencode/packages/opencode/src/session/overflow.ts:8-22` | Простая политика overflow по provider usage и reserved tokens. |
| **OpenCode compacted history** | `/home/artem/reps/opencode/packages/opencode/src/session/message-v2.ts:925-937` | Полная история остаётся в store, а в модель идёт хвост после последней успешной compaction. |
| **OpenCode compaction storage** | `/home/artem/reps/opencode/packages/opencode/src/session/compaction.ts` | Compaction как normal session artifact, а не скрытая мутация истории. |
| **Ailit current PAG injection** | `tools/agent_core/session/loop.py:474-570`, `tools/agent_core/session/loop.py:2769-2787` | Сейчас `SessionRunner` вызывает `PagRuntimeAgentMemory` напрямую; Workflow 10 переводит это в обязательный actor-path через `AgentMemory`. |
| **Ailit current AgentMemory worker** | `tools/agent_core/runtime/subprocess_agents/memory_agent.py:34-96` | Минимальный worker `memory.query_context -> MemoryGrant`; его нужно заменить/расширить до владельца memory slice. |
| **Ailit Desktop graph bridge** | `desktop/src/main/pagGraphBridge.ts:34-86`, `desktop/src/renderer/views/MemoryPage.tsx:9-66` | Есть bridge `ailit memory pag-slice` и страница памяти; Workflow 10 возвращает 3D как live-context visualization. |

---

## Целевая модель

### PAG levels

Workflow 10 использует существующую смысловую модель:

- **A** — project/repository/namespace.
- **B** — folders, files, workspace nesting.
- **C** — file internals: line ranges, symbols, sections, imports, functions/classes.
- **D** — compact/session context artifacts:
  - compact summary;
  - restored context recipe;
  - pinned decisions;
  - unresolved questions;
  - changed-files summary;
  - session memory digest.

`D` не является дочерним слоем файла. Это слой **семантических артефактов сессии**, который обязан иметь provenance-связи на A/B/C.

Минимальные связи:

- `D summarizes A|B|C`;
- `D derived_from_trace trace_id/message_id`;
- `D restored_into_context chat_id/turn_id`;
- `D supersedes D`;
- `D references B|C`;
- `D decision_about B|C`.

### Context Ledger

`Context Ledger` не владеет PAG. Он фиксирует, что из памяти и истории реально участвовало в LLM-контексте:

- `context.snapshot` — оценка окна перед model request;
- `context.memory_injected` — A/B/C/D ноды, реально вставленные в prompt;
- `context.compacted` — compact boundary, token savings, D-узел;
- `context.restored` — автоматический recipe при открытии чата;
- `context.provider_usage_confirmed` — подтверждённый usage после ответа.

### Actor path

Целевой runtime-путь:

```text
Desktop Chat
  -> AgentBroker
    -> AgentWork
      -> service.request memory.query_context
        -> AgentMemory
          -> PAG/KB/D artifacts
        <- memory slice + node ids + estimated tokens
      -> Context Builder
      -> Context Ledger event
      -> LLM provider
```

Запрещённый целевой путь:

```text
SessionRunner -> PagRuntimeAgentMemory напрямую как основной Desktop-path
```

Прямой in-process fallback допустим только для CLI/debug/degradation и должен быть явно помечен событием `memory.actor_fallback_used`.

---

## Event contracts

### `context.snapshot.v1`

```json
{
  "event_name": "context.snapshot",
  "schema": "context.snapshot.v1",
  "chat_id": "chat-id",
  "turn_id": "turn-id",
  "model": "provider/model",
  "model_context_limit": 200000,
  "effective_context_limit": 180000,
  "reserved_output_tokens": 20000,
  "estimated_context_tokens": 54321,
  "usage_state": "estimated",
  "breakdown": {
    "system": 1000,
    "tools": 8000,
    "messages": 22000,
    "memory_abc": 2400,
    "memory_d": 1600,
    "tool_results": 18000,
    "free": 126000
  }
}
```

### `context.memory_injected.v1`

```json
{
  "event_name": "context.memory_injected",
  "schema": "context.memory_injected.v1",
  "chat_id": "chat-id",
  "turn_id": "turn-id",
  "source_agent": "AgentMemory:chat-id",
  "usage_state": "estimated",
  "node_ids": [
    "A:repo",
    "B:tools/agent_core/session/loop.py",
    "C:tools/agent_core/session/loop.py:2769-2787",
    "D:compact-summary:uuid"
  ],
  "edge_ids": [],
  "estimated_tokens": 1200,
  "prompt_section": "memory",
  "reason": "matched current user goal"
}
```

### `context.compacted.v1`

```json
{
  "event_name": "context.compacted",
  "schema": "context.compacted.v1",
  "chat_id": "chat-id",
  "turn_id": "turn-id",
  "trigger": "manual|auto|open_chat_restore",
  "boundary_id": "boundary-uuid",
  "d_node_id": "D:compact-summary:uuid",
  "pre_tokens_estimated": 145000,
  "post_tokens_estimated": 38000,
  "freed_tokens_estimated": 107000,
  "linked_node_ids": ["A:repo", "B:path", "C:path:1-50"]
}
```

### `context.provider_usage_confirmed.v1`

```json
{
  "event_name": "context.provider_usage_confirmed",
  "schema": "context.provider_usage_confirmed.v1",
  "chat_id": "chat-id",
  "turn_id": "turn-id",
  "input_tokens": 55000,
  "output_tokens": 1800,
  "cache_read_tokens": 12000,
  "cache_write_tokens": 0,
  "usage_state": "confirmed"
}
```

---

## Desktop UX

### Возврат Memory 3D graph

`/memory?v=3d` должен стать не декоративным viewer, а live-экраном работы памяти:

- граф берёт A/B/C/D nodes и edges из `AgentMemory`/PAG store;
- подсветка берёт activity из `Context Ledger`;
- подсвечиваются только ноды, реально попавшие в prompt;
- интенсивность зависит от recency и token share;
- hover показывает turn, prompt section, estimated/confirmed tokens, reason и trace refs;
- D-узлы видны как compact/session artifacts и связаны с A/B/C.

MVP не содержит ручных фильтров: режим `current context + automatic decay/highlight` включён по умолчанию.

### Context fill panel

В Desktop-чате рядом с header/status нужна компактная панель:

- процент заполнения effective context;
- `estimated` до ответа и `confirmed` после ответа;
- breakdown по категориям;
- warning перед auto-compact;
- кнопка/команда compact в UI, когда будет реализован этап G10.5.

---

## Порядок реализации стратегии

Эта стратегия исполняется строго по этапам. После логического завершения каждого этапа выполняются проверки из этапа и создаётся отдельный коммит с префиксом `context-ledger-10/G10.n`. После каждого успешного коммита отправляется `curl -d "<commit subject>" ntfy.sh/ai`.

### G10.0 — Design contracts and plan alignment

**Цель:** зафиксировать workflow, границы A/B/C/D, actor-path и event contracts.

Задачи:

1. Добавить этот workflow в `plan/10-context-ledger-memory-highlights.md`.
2. Обновить `README.md` со статусом новой активной ветки.
3. Проверить, что `D` не конфликтует с A/B/C из Workflow 7.
4. Зафиксировать, что `AgentMemory` обязателен для Desktop chat.

Критерии приёмки:

- В плане есть stages G10.0-G10.8.
- В плане есть отдельный раздел про возврат Memory 3D graph.
- В README есть ссылка на workflow 10 как следующую активную ветку.
- Коммит: `context-ledger-10/G10.0 add context ledger workflow`.

Проверки:

- Документальная проверка ссылок и терминов.
- Автотесты не требуются: код не меняется.

### G10.1 — AgentMemory actor contract for Desktop chat

**Цель:** перевести Desktop runtime на обязательный actor-path `AgentWork -> Broker -> AgentMemory`.

Задачи:

1. Расширить `memory.query_context` до ответа `memory_slice`, а не только `MemoryGrant`.
2. Ответ должен содержать `node_ids`, `edge_ids`, `level`, `injected_text`, `estimated_tokens`, `staleness`, `reason`.
3. `AgentWork` должен запрашивать `AgentMemory` перед model request в Desktop path.
4. Direct `PagRuntimeAgentMemory` оставить только как fallback с явным событием.
5. Broker trace должен показывать request/response пары `AgentWork <-> AgentMemory`.

Критерии приёмки:

- В trace Desktop-чата виден `service.request memory.query_context` к `AgentMemory`.
- `AgentMemory` возвращает node ids A/B/C и текст, пригодный для prompt.
- При недоступной памяти UI получает структурированную деградацию, а не silent direct-read.

Проверки:

- `pytest` по runtime/broker/agent memory тестам.
- `flake8` по затронутым Python-файлам.
- Минимальный ручной сценарий Desktop: отправить prompt и увидеть в trace обращение к `AgentMemory`.

### G10.2 — Context Ledger core events

**Цель:** ввести append-only события контекста перед/после model request.

Задачи:

1. Добавить модель/строитель `ContextSnapshot`.
2. Перед provider request эмитить `context.snapshot`.
3. При вставке memory slice эмитить `context.memory_injected`.
4. После provider response эмитить `context.provider_usage_confirmed`.
5. Развести `estimated` и `confirmed`.

Критерии приёмки:

- В durable trace есть snapshot перед каждым model request.
- `context.memory_injected.node_ids` совпадает с тем, что реально вошло в prompt.
- Provider usage связывается с тем же `turn_id`.

Проверки:

- Unit-тесты estimator/snapshot builder.
- Runtime-тест на trace event order.
- `pytest` и `flake8` по затронутым пакетам.

### G10.3 — Token estimation and effective context thresholds

**Цель:** реализовать донорский подход к токенам: provider usage как truth после ответа, estimate до ответа.

Задачи:

1. Добавить model limits resolver для текущих provider/model.
2. Добавить reserve output tokens и effective context limit.
3. Оценивать новые сообщения и memory slice через `chars/4` или локальный estimator.
4. Сохранять предупреждения `normal|warning|compact_recommended|overflow_risk`.
5. Не выдавать оценку за точный tokenizer: UI должен показывать `estimated`.

Критерии приёмки:

- Context fill panel получает процент заполненности.
- Thresholds не используют накопленный `max_total_tokens` как proxy размера окна.
- После provider response `confirmed` usage обновляет baseline.

Проверки:

- Unit-тесты на effective window, reserve и warning states.
- Regression-тест: большой tool output повышает estimated context tokens.
- `pytest` и `flake8` по затронутым пакетам.

### G10.4 — Desktop Context Fill panel

**Цель:** показать заполненность контекста в Desktop.

Задачи:

1. Расширить trace projector для событий `context.*`.
2. Добавить UI-компонент Context Fill.
3. Показать breakdown: system/tools/messages/memory_abc/memory_d/tool_results/free.
4. Различать `estimated` и `confirmed`.
5. Показать warning state.

Критерии приёмки:

- В Desktop-чате виден процент заполнения окна.
- После ответа модели статус меняется с `estimated` на `confirmed`.
- При memory injection в breakdown растёт `memory_abc` или `memory_d`.

Проверки:

- TypeScript unit-тесты projector/state.
- UI ручной сценарий в `ailit desktop --dev`.
- `npm` checks по desktop-пакету, если они есть в репозитории.

### G10.5 — Compact to D-level memory

**Цель:** сделать compact источником D-узлов памяти.

Задачи:

1. Добавить compact service, который создаёт structured summary artifact.
2. Создавать D-node с `summary`, `decisions`, `changed_files`, `open_questions`, `boundary_id`.
3. Связывать D-node с A/B/C node ids.
4. Эмитить `context.compacted`.
5. Обновлять prompt: старый chat tail заменяется D-summary + короткий recent tail.

Критерии приёмки:

- Compact создаёт D-node в memory store.
- D-node виден в Memory 3D graph.
- После compact estimated context tokens уменьшаются.
- В trace есть token savings и linked A/B/C nodes.

Проверки:

- Unit-тест compact summary schema.
- Runtime-тест: compact event + D-node persistence.
- `pytest` и `flake8` по затронутым пакетам.

### G10.6 — Automatic context restore on chat open

**Цель:** при открытии старого чата автоматически собрать model context recipe.

Задачи:

1. Найти последний валидный D-summary для `chat_id`/namespace.
2. Подмешать последние сообщения, pinned decisions и релевантные A/B/C nodes.
3. Эмитить `context.restored`.
4. Не загружать всю сырую историю в prompt.
5. UI должен показывать, что контекст восстановлен автоматически.

Критерии приёмки:

- Старый чат продолжает работу через D-summary + recent tail.
- Context Fill показывает вклад `memory_d`.
- Memory 3D подсвечивает D-node и связанные A/B/C, если они вошли в prompt.

Проверки:

- Runtime-тест восстановления после restart/reopen.
- Trace-projection тест на `context.restored`.
- `pytest`, `flake8`, desktop checks по затронутым частям.

### G10.7 — Return Memory 3D graph with Context Ledger highlights

**Цель:** вернуть Memory 3D graph как live-визуализацию фактической работы памяти.

Задачи:

1. Убедиться, что route `/memory?v=3d` использует реальные PAG/D данные, а не mock.
2. Добавить D-node rendering style.
3. Подключить `context.memory_injected` к 3D highlights.
4. Подсвечивать только node ids, реально попавшие в prompt.
5. Добавить hover details: turn id, prompt section, estimated/confirmed tokens, reason, trace ref.
6. Подсветка автоматическая, без ручных фильтров в MVP.

Критерии приёмки:

- Во время Desktop-чата Memory 3D graph подсвечивает A/B/C/D ноды из prompt.
- При compact появляется/подсвечивается D-node.
- При reopen chat подсвечивается восстановленный D-node, если он вошёл в prompt.
- Нет подсветки retrieval-кандидатов, которые не попали в prompt.

Проверки:

- TypeScript tests для highlight projector.
- Ручной Desktop сценарий: prompt -> memory injection -> 3D highlight.
- Ручной Desktop сценарий: compact -> D-node -> 3D highlight.

### G10.8 — End-to-end readiness and docs status

**Цель:** закрыть ветку как пользовательскую фичу.

Задачи:

1. E2E-сценарий Desktop: открыть чат, получить memory injection, увидеть Context Fill и Memory 3D highlights.
2. E2E-сценарий compact: создать D-node, уменьшить context tokens, увидеть D в 3D.
3. E2E-сценарий reopen: автоматическое восстановление контекста.
4. Обновить README статусом закрытия Workflow 10.
5. Зафиксировать ограничения и next workflow, если нужны shared/MCP или ручные фильтры.

Критерии приёмки:

- Пользователь видит реальный рост памяти и её использование в prompt.
- `AgentMemory` в Desktop не является декоративным viewer: он участвует в runtime trace.
- Context Ledger объясняет, почему подсвечена каждая нода.
- Workflow 10 закрыт отдельным коммитом.

Проверки:

- `pytest` по затронутым Python-пакетам.
- `flake8` по затронутым Python-файлам.
- Desktop test/check commands.
- Ручной smoke `ailit desktop --dev`.

---

## MVP vertical slice

Если нужно сузить первый инкремент до минимально демонстрируемой киллер-фичи:

1. `AgentMemory` actor возвращает memory slice с A/B/C node ids.
2. `Context Ledger` пишет `context.memory_injected`.
3. Desktop Memory 3D подсвечивает эти node ids.
4. Context Fill показывает `memory_abc` и общий estimated percent.
5. Compact/D остаётся следующим этапом, но schema уже совместима.

---

## Non-goals Workflow 10

- Не делать shared/MCP memory как отдельный distributed слой.
- Не добавлять ручные фильтры Memory 3D в MVP.
- Не делать provider-specific tokenizer обязательной зависимостью.
- Не переносить всю сырую историю чата в KB/PAG.
- Не ломать существующую A/B/C модель Workflow 7.

---

## Конец workflow

Если G10.0-G10.8 закрыты и нет утверждённой следующей ветки, агент останавливается и запрашивает у пользователя research и постановку следующей цели согласно [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).
