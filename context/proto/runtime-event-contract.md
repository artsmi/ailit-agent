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

## Связанные документы

- [`../arch/runtime-local-storage-model.md`](../arch/runtime-local-storage-model.md)
- [`../arch/visual-monitoring-ui-map.md`](../arch/visual-monitoring-ui-map.md)
- [`../INDEX.md`](../INDEX.md)
