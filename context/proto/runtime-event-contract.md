# Runtime Event Contract

## Назначение

Зафиксировать единый контракт событий для:

- core runtime;
- workflow layer;
- project layer;
- transport/providers;
- tool runtime.

События — главный мост между исполнением, UI и отладкой.

## Главный принцип

1. События **нормализованы** и не завязаны на конкретного vendor.
2. Любая UI проекция строится из событий + явных snapshot проекций.
3. События **не** являются заменой `context/*`.

## Envelope (обязательные поля)

Каждое событие — JSON object со следующими полями:

- `schema_version` (string): версия контракта событий;
- `event_id` (string): ULID/UUIDv7 — глобально уникален в пределах `run_id`;
- `occurred_at` (string): RFC3339 UTC timestamp;
- `run_id` (string);
- `layer` (string enum): `core` | `workflow` | `project` | `transport` | `tool` | `ui`;
- `producer` (string): стабильное имя компонента (`session_loop`, `workflow_engine`, ...);
- `severity` (string enum): `debug` | `info` | `warn` | `error`;
- `event_type` (string): стабильный тип из реестра ниже;
- `correlation` (object):
  - `trace_id` (string, optional but recommended);
  - `parent_event_id` (string, optional);
  - `session_id` (string, optional);
  - `workflow_id` (string, optional);
  - `workflow_revision` (string, optional);
  - `stage_id` (string, optional);
  - `task_id` (string, optional);
  - `agent_id` (string, optional);

Рекомендуемые дополнительные поля envelope:

- `dedupe_key` (string, optional): для идемпотентных повторов transport;
- `redaction` (object, optional): что вырезано из payload по policy.

## Payload правила

- Payload — JSON object.
- Любые большие тексты должны быть либо:
  - ссылкой на artifact hash,
  - либо укорочены с явным `truncated=true`.
- Никаких секретов: ключи, токены, заголовки авторизации запрещены в payload.

## Реестр обязательных типов событий

Ниже — минимальный набор, который должен позволить **восстановить исполнение** и **нарисовать operator UI**.

### Run lifecycle

- `run.started`
- `run.finished`
- `run.failed`

Payload минимум:

- `reason` (structured, optional on success paths);
- `exit_code` (string enum) для машинной классификации.

### Workflow layer

- `workflow.loaded`
- `workflow.validation_failed`
- `stage.entered`
- `stage.exited`
- `task.started`
- `task.finished`
- `task.failed`
- `workflow.blocked`
- `workflow.unblocked`
- `human.gate.requested`
- `human.gate.resolved`

Инвариант: любая смена `stage_id` сопровождается парой/цепочкой событий, достаточной для UI graph highlight.

### Session / model interaction (provider-agnostic)

- `session.created`
- `session.turn.started`
- `session.turn.finished`
- `model.requested`
- `model.response.received`
- `model.stream.delta` (optional, может быть высокочастотным)
- `model.usage.recorded`

Нормализация:

- `provider_id` (string): например `deepseek`, `kimi`;
- `model_id` (string): конкретная модель;
- `capabilities` (object, optional): флаги capability, не сырой vendor config.

### Tool runtime

- `tool.call.requested`
- `tool.call.approved`
- `tool.call.denied`
- `tool.call.started`
- `tool.call.finished`
- `tool.call.failed`

Payload минимум:

- `tool_name` (string);
- `tool_call_id` (string);
- `side_effect_class` (string enum): `none` | `read` | `write` | `network` | `destructive`.

### Permissions / safety

- `permission.evaluated`
- `approval.required`
- `approval.granted`
- `approval.rejected`

### Persistence / observability

- `state.snapshot.created`
- `artifact.materialized`
- `telemetry.usage.updated`

### Project layer (policy-facing, но машинно)

- `project.config.resolved`
- `project.rules.loaded` (metadata only: версии, пути, hash; без копирования больших текстов)

### Transport

- `transport.request.started`
- `transport.request.finished`
- `transport.retry.scheduled`

Payload минимум:

- `attempt` (integer);
- `error_class` (string enum): `timeout` | `rate_limit` | `http_error` | `malformed` | `unknown`.

## Частота, батчинг и UI friendliness

Правила:

- высокочастотные `model.stream.delta` могут агрегироваться в reducer, но **в лог** пишется либо:
  - агрегированная версия,
  - либо delta с лимитом частоты + ссылками на snapshot.

UI должен уметь работать даже если deltas отключены (только агрегаты).

## Восстановление состояния

Минимальный recovery алгоритм:

1. прочитать `manifest.json`;
2. replay `events.jsonl` в порядке записи;
3. применить reducer проекций → получить `state.json`;
4. сверить `state.json` с последним snapshot (если есть) и выбрать консистентный вариант.

## Snapshot vs events

Snapshot события (`state.snapshot.created`) обязаны содержать:

- `snapshot_id`;
- `based_on_event_id`;
- ссылку на файл snapshot.

## PAG graph: `graph_rev` и дельты в trace (Workflow 12, контракт восстановлен в Workflow 13)

- Монотонный счётчик **`graph_rev` per `namespace`** хранится в SQLite PAG; полный срез `ailit memory pag-slice` возвращает `graph_rev` (текущее значение) для стыковки с дельтами.
- Ответ `pag-slice` включает **`has_more.{nodes,edges}`**: признак, что в БД ещё есть страница после `offset+len` (в т.ч. «лишняя» выборка `limit+1` в CLI при `node_limit<10_000` / `edge_limit<20_000`; на верхних капах — сравнение с `COUNT`).
- Графовые дельты (MVP) — **`topic.publish`** в durable trace, `event_name` **`pag.node.upsert`** / **`pag.edge.upsert`**, compact payload (внутренняя строка: `kind` совпадает с `event_name`, поля `namespace`, **`rev`**, `node` или `edges[]`). Без копии больших BLOB/исходников. Нормализованные поля и сценарии: **[`plan/12-pag-trace-delta-desktop-sync.md`](../../plan/12-pag-trace-delta-desktop-sync.md)**.
- **Desktop** применяет дельты к удерживаемой модели графа, полный re-sync из БД — только **Refresh** или смена сессии/проекта (см. план 12).

## G13.1 / G13.8 — Runtime PAG write contract и финальные payload-схемы (канон D13.1, D13.8)

- **Единая точка записи в runtime:** все вызовы `upsert_node` / `upsert_edge` / `upsert_edges_batch` в `tools/agent_core` идут через `PagGraphWriteService` (делегат к `SqlitePagStore`); низкоуровневые DML вне сервиса — только в `sqlite_pag.py` и теле `PagGraphWriteService`.
- **`graph_rev`:** монотонно растёт per `namespace` при любом успешном upsert ноды/ребра (см. `SqlitePagStore._bump_graph_rev`).
- **`rev` в trace payload:** равен текущему `graph_rev` namespace **после** данной операции (один upsert — один bump — одно значение `rev` в delta).
- **G13.8:** ниже — нормативные JSON-формы для trace (`topic.publish` inner payload) и IPC `memory.change_feedback`; их отражают тесты `tests/test_g13_*.py` и интеграция [`plan/13-agent-memory-contract-recovery.md`](../../plan/13-agent-memory-contract-recovery.md).

### `pag.node.upsert` (durable trace / `topic.publish` inner payload)

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

Тело compact: без сырого исходника файла; `summary`/`attrs`/`staleness_state` — как в реализации `PagGraphWriteService` / store.

### `pag.edge.upsert`

Одно ребро или пачка (batch — одна строка trace, `edges` — массив).

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

### `memory.change_feedback` (AgentWork → AgentMemory)

Сервисное сообщение после успешных изменений кода/инструментов (см. G13.3, D13.3):

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

### `SemanticCNodeCandidate` (LLM / идентичность C, D13.6)

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

### `SemanticLinkClaim` (pending / resolved, D13.7)

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

### Режимы

| Режим | Trace delta | `graph_rev` | Когда |
|--------|-------------|-------------|--------|
| `runtime_traced` | Да, compact | Да | Есть `RuntimeRequestEnvelope` + hook в `SqlitePagStore.graph_trace` |
| `offline_writer` | Нет | Да | `ailit memory index`, `PagIndexer`, инкрементальный index без trace; Desktop — только **Refresh** / смена чата |
| `runtime_untraced` | Нет | Да (или N/A) | Только явный allowlist (см. `RUNTIME_UNTRACED_WRITE_ALLOWLIST` / тесты); иначе запрещён |

## W14R / G14R.10 — AgentMemory journal (compact, desktop-safe)

События пишутся в AgentMemory JSONL journal (`MemoryJournalRow`, `event_name`) и, при `memory.debug.verbose=1`, зеркалятся в `chat_logs` только для `memory.chat_debug.command` (см. C14R.11). Запрещено дублировать сырой prompt, CoT, полные тексты файлов и длинные summary из `agent_memory_result` в journal.

| `event_name` (journal) | Когда | Обязательные поля `payload` (компакт) |
|------------------------|-------|----------------------------------------|
| `memory.runtime.step` | Переход W14 внутри `AgentMemoryQueryPipeline` (planner / parse / finish) | `step_id`, `state`, `next_state`, `action_kind`, `query_id`, `counters` |
| `memory.result.returned` | Перед отдачей `payload.agent_memory_result` в `memory.query_context` | `query_id`, `status`, `result_kind_counts`, `results_total` |

`memory.result.returned` **не** содержит `results[]`, `decision_summary`, `read_lines` — только агрегаты по `kind` и число записей. Полный ответ остаётся в IPC payload, не в журнале.

## Связанные документы

- [`../arch/runtime-local-storage-model.md`](../arch/runtime-local-storage-model.md)
- [`../arch/visual-monitoring-ui-map.md`](../arch/visual-monitoring-ui-map.md)
- [`../INDEX.md`](../INDEX.md)
