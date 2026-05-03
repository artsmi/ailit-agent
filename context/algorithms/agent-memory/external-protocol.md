# AgentMemory: внешний протокол (инициаторы, события, CLI)

## Current reality

- **AgentWork → broker → memory subprocess:** JSON-lines RPC; payload `memory.query_context` с `schema_version: agent_work_memory_query.v1` и полями v1; дополнительно `query_kind`, `level` из сырого dict (`agent_work_memory_integration.md` F1–F2).
- **Ответ:** `memory_slice`, `agent_memory_result`, `grants`, дубликаты `decision_summary`/`recommended_next_step` на верхнем уровне и внутри `agent_memory_result`; SoT для continuation — `agent_memory_result` (`agent_work_memory_integration.md` F4, F6).
- **Grants:** в payload есть, но AgentWork в показанном пути **не** подключает `grants` к enforcement (`agent_work_memory_integration.md` F5) — **`implementation_backlog`**.
- **CLI init:** default goal `MEMORY_INIT_CANONICAL_GOAL`; summary `emit_memory_init_user_summary` с `exit_kind` ∈ {`complete`,`partial`,`aborted`}; строка **`blocked` как exit_kind не используется** (`agent_memory_entrypoints_cli.md` F9).
- **Корреляция:** `MemoryJournalRow.request_id` — broker id; `query_id` внутри payload событий W14 (`memory_journal_trace_observability.md` F8).
- **Stdout trace:** JSONL `pag.node.upsert`, `memory.w14.graph_highlight`; compact.log нормализует имена (`memory_journal_trace_observability.md` F9, F12).

## Target behavior

### Инициаторы

| Initiator | Transport | Обязательные корреляторы |
|-----------|-----------|-------------------------|
| AgentWork | broker stdin/stdout | `user_turn_id`, `query_id`, `namespace`, `project_root` |
| CLI `ailit memory init` | in-process worker | synthetic `query_id` per orchestrator round, `namespace` from repo detect, `project_root` normalized |
| Другой broker client | как AgentWork | должен повторять v1 контракт |

### Schema-like: `agent_work_memory_query.v1` (subset)

```json
{
  "service": "memory.query_context",
  "schema_version": "agent_work_memory_query.v1",
  "subgoal": "string, required, natural language memory-only goal",
  "user_turn_id": "string, required",
  "query_id": "string, required, unique per sub-goal round",
  "project_root": "string, required, absolute normalized",
  "namespace": "string, required",
  "expected_result_kind": "string, required, whitelist per parser",
  "known_paths": "array[string], required, may be empty",
  "known_node_ids": "array[string], required, may be empty",
  "stop_condition": { "max_rounds": "int", "allow_partial": "bool" },
  "query_kind": "string|omit — advisory from initiator, not validated by v1 parser",
  "level": "string|omit — advisory"
}
```

**Forbidden:** смешивать пользовательскую «полную задачу» без декомпозиции: AgentMemory **не** решает end-to-end задачу, только memory subgoal (`original_user_request.md`).

### Много запросов на один user turn

- Initiator **may** отправить серию `memory.query_context` с разными `query_id` при continuation; cap `memory.runtime.max_memory_queries_per_user_turn` (default 6, clamp 1..1000) (`agent_work_memory_integration.md` F7).

### Поле приоритета дубликатов

**Норматив для потребителей:** при конфликте верхнего уровня и `agent_memory_result` для continuation/decisions — **SoT = `agent_memory_result`**; top-level поля — UX/legacy mirror (**default** mirror must match; если не совпадают — `implementation_bug`).

### Внешние события (OR-010) — каталог (discriminant)

Каждое событие: `schema_version: agent_memory.external_event.v1`, поля:

```json
{
  "schema_version": "agent_memory.external_event.v1",
  "event_type": "heartbeat|progress|highlighted_nodes|link_candidates|links_updated|nodes_updated|partial_result|complete_result|blocked_result",
  "query_id": "string, required",
  "timestamp": "string, required, RFC3339",
  "payload": "object, required",
  "truncated": "bool, default false",
  "units": "utf8_chars|node_count|edge_count, required for size-related fields"
}
```

**Durable vs ephemeral (идея donor opencode):** `heartbeat`, fine-grained `progress` — ephemeral; `complete_result`/`blocked_result`/`partial_result` финальные — durable в journal/agent result path.

#### Обязательные поля payload по типу (кратко)

- **`heartbeat`:** `session_alive=true`.
- **`progress`:** `runtime_state` (строка из целевой state machine), `message` compact.
- **`highlighted_nodes`:** `node_ids: string[]` (bounded count), `reason` short.
- **`link_candidates`:** массив `agent_memory_link_candidate.v1` **до** validation (optional для CLI, required для Desktop при включённой feature).
- **`links_updated`:** `{ "applied": [...], "rejected": [{ "link_id", "reason"}] }`.
- **`nodes_updated`:** `{ "upserted_node_ids": [], "kind": "B|C|D" }` bounded.
- **`partial_result` / `complete_result` / `blocked_result`:** ссылка на финальный `agent_memory_result.v1` или его подмножество + hash; **forbidden** включать raw prompts.

### CLI `ailit memory init` (OR-011) — target vs current

**Target UX:**

- Default NL goal — константа уровня продукта (аналог `MEMORY_INIT_CANONICAL_GOAL`), пользователь **may** расширить в будущем; сейчас только константа (`agent_memory_entrypoints_cli.md` F6).
- Progress: stderr compact sink + orchestrator phases + worker journal shadow.
- Nodes/links: логировать через `nodes_updated` / `links_updated` / stdout trace согласно политике caps.
- Итоги: **`complete` | `partial` | `blocked`** как **видимые** статусы + exit codes с таблицей соответствия.

**Current reality mismatch (D1):** CLI summary использует `aborted` вместо отдельного UX `blocked` — пометить **`implementation_backlog`** до выравнивания.

### Команды проверки (manual / CI)

- Ручной smoke (после реализации): `ailit memory init <repo>` — ожидать финальный маркер `memory.result.returned` в shadow journal и compact log без raw prompts (`memory_journal_trace_observability.md` tests refs).
- CI: список pytest в `failure-retry-observability.md` (фактические имена).

## Traceability

| Report | Topics |
|---------|--------|
| `agent_memory_entrypoints_cli.md` | CLI, transports |
| `agent_work_memory_integration.md` | AgentWork payload, grants gap |
| `memory_journal_trace_observability.md` | channels, D-OBS |
| `donor/opencode_typed_events_for_memory_protocol.md` | discriminant, durable/ephemeral |
