# Broker trace: AgentWork ↔ AgentMemory и `context.memory_injected` (UC 2.4)

## W14: SoT `agent_memory_result`, continuation и таймаут (AgentWork ↔ AgentMemory)

Норматив: `plan/14-agent-memory-runtime.md` (**D14R.3**, **C14R.1**, **C14R.1a**), артефакт `context/artifacts/architecture.md` (итерация по ТЗ AW↔AM).

1. **Source of truth для решений AgentWork** — поле **`payload.agent_memory_result`** (`schema_version: agent_memory_result.v1`). В том же объекте нормативный булев сигнал **`memory_continuation_required`** (если поле отсутствует или `false`, отдельный continuation-запрос в том же turn не оправдан только этим полем — см. `context/artifacts/architecture.md` §2.3). Поле **`memory_slice`** — только compatibility projection для инжекта/UI; не определяет continuation/cap/timeout-политику вместо SoT.
2. **Continuation gate:** политика AW читает **только** SoT: `payload.agent_memory_result.memory_continuation_required` и `status` (в т.ч. терминальные исходы UC-03). При `status=partial` и **`memory_continuation_required: true`** (выставляется AgentMemory из машинного состояния W14, не из эвристики по тексту `memory_slice`) в **том же** `user_turn_id` AW обязан выполнить **следующий** `memory.query_context` с **новым** `query_id`, пока не будет `complete` / `blocked` или cap `memory.runtime.max_memory_queries_per_user_turn`. Запрещено переходить к `glob_file` / `read_file` / `run_shell` как замене незавершённого memory-path.
3. **Таймаут:** SLA ожидания ответа AM должно быть **согласовано** между клиентом AW (`_BrokerServiceClient`), broker (`svc_timeout` для worker AgentMemory) и `memory.runtime.agent_memory_rpc_timeout_s` в merged config; клиент не должен обрывать ожидание существенно раньше broker при целевом SLA W14 pipeline.
4. **Timeout / late response:** ответ `runtime_timeout` или отсутствие валидного `agent_memory_result` **не** трактуется как успешное завершение memory-path. Поздний ответ с устаревшим `query_id` не должен менять состояние текущего turn детерминированно (discard / диагностика).

### AgentMemory: поле `memory_continuation_required` в SoT

Вычисление и встраивание в объект **`agent_memory_result.v1`** — `resolve_memory_continuation_required` и `build_agent_memory_result_v1` в `tools/agent_core/runtime/agent_memory_result_v1.py`; итоговый объект отдаётся в broker-поток из `tools/agent_core/runtime/subprocess_agents/memory_agent.py`. Правила UC-03/UC-04 для поля — в docstring `resolve_memory_continuation_required` (источник правды рядом с кодом).

### Cooperative cancel (UC-05)

Транспорт — тот же broker Unix socket, что и для `work.handle_user_prompt`: логическое имя операции **`runtime.cancel_active_turn`** (константа `RUNTIME_CANCEL_ACTIVE_TURN` в `tools/agent_core/runtime/broker.py` и `tools/agent_core/runtime/subprocess_agents/work_agent.py`). В JSON допускается дублирование имени в `payload.service` и `payload.action`; для корреляции с turn — **`chat_id`**, **`user_turn_id`** (согласовано с Desktop envelope в [`desktop-electron-runtime-bridge.md`](desktop-electron-runtime-bridge.md)). Broker маршрутизирует запрос в AgentWork; терминальные compact-события и порядок относительно memory-path — [`runtime-event-contract.md`](runtime-event-contract.md). **Supervisor** JSON socket (`supervisor.sock`) для UC-05 **не** используется — см. [`supervisor-json-socket.md`](supervisor-json-socket.md).

Компактные события: нормативный whitelist имён и полей — [`runtime-event-contract.md`](runtime-event-contract.md) (**D-OBS-1**), в дословном соответствии с `context/artifacts/architecture.md` §5 и литералами в `work_agent.py`. Кратко: continuation — `memory.query_context.continuation` (`previous_query_id`, `next_query_id`, `user_turn_id`, `reason`); timeout RPC — `memory.query.timeout` (`query_id`, `user_turn_id`, `code`, `timeout_s`); без сырого prompt.

---

## Участники

- **Broker** (P3): Unix socket на `BrokerConfig.socket_path`; процессы `AgentWork:<chat_id>`, `AgentMemory:global`.
- **Trace store:** JSONL (`trace_store_path`), строки = события рантайма.

По умолчанию broker/Python **не** пишут в trace/journal compact-событие **`memory_recall_ui_phase`**; его продюсирует только **renderer** (см. [`desktop-memory-3d-observability.md`](desktop-memory-3d-observability.md)).

## Обязательная тройка для регрессии `test_broker_routes_memory_service_and_work_action`

После `action.start` с `work.handle_user_prompt` и успешного второго запроса памяти в том же чате в trace должны появиться **все** три вида следов:

1. **`service.request`**  
   - `from_agent`: `AgentWork:<chat_id>`  
   - `to_agent`: `AgentMemory:global`  
   - `payload.service`: `memory.query_context`  
   - Payload Work v1: **без** обязательного поля `path` (subgoal, `schema_version`, `query_id`, …).

2. **`service.request`** (ответ memory)  
   - `from_agent`: `AgentMemory:global`  
   - `to_agent`: `AgentWork:<chat_id>`  
   - `ok`: `true`  
   - `payload.memory_slice`: object (dict), пригодный для prompt.

3. **`topic.publish`**  
   - `from_agent`: `AgentWork:<chat_id>`  
   - `payload.event_name`: `context.memory_injected`  
   - Вложенный объект события (как в коде Work): схема **`context.memory_injected.v2`**, поле **`usage_state`** со значением **`estimated`**.

## Условие публикации инжекта (граница Work)

Work публикует `context.memory_injected` **только** если ответ `ok` и в `memory_slice` поле **`injected_text`** после trim **не пустое**; иначе — `memory.actor_slice_skipped`. Следовательно, для UC 2.4 AgentMemory обязан возвращать непустой `injected_text` в успешном pathless сценарии.

Проверка пустоты и ветвление событий: `_WorkChatSession._memory_slice_message`, `_request_memory_slice` — при пустом `injected_text` после успешного ответа памяти публикуется `memory.actor_slice_skipped` с `reason`/`staleness` из слайса; при непустом — `memory.actor_slice_used` и затем `context.memory_injected` с payload из `_memory_injected_payload`.

### W14 planner: каноникализация envelope до repair

Перед repair-LLM `AgentMemoryQueryPipeline` механически нормализует ответ планера к `agent_memory_command_output.v1` (`validate_or_canonicalize_w14_command_envelope_object` в `agent_memory_runtime_contract.py`): канонический `schema_version`, таблица легаси `status` → только `ok` \| `partial` \| `refuse`, восстановление пустого/`null` `command_id` из доверенного runtime id шага планера (trace), если он известен; иначе — явный отказ с `reason` (в т.ч. `w14_command_id_not_recoverable:no_runtime_command_id`), без маскировки под «только schema_version».

Компактные события журнала AgentMemory (см. [`runtime-event-contract.md`](runtime-event-contract.md)): `memory.command.normalized` (в т.ч. `from_schema_version`, `to_schema_version`, `from_status`, `command_id_restored`), при фактическом восстановлении id — `memory.w14.command_id_restored`.

### W14 `propose_links`, PAG write и внешние события

- Команда планера **`propose_links`** обрабатывается в `AgentMemoryQueryPipeline`: wire **`agent_memory_link_candidate.v1`** → **`AgentMemoryLinkCandidateValidator`** (отклонения с компактным `reason`, напр. `invalid_source_path`) → применимые рёбра через **`PagGraphWriteService`** (`pag_graph_write_service.py`). Подробности типов связей и политики — [`../algorithms/agent-memory/memory-graph-links.md`](../algorithms/agent-memory/memory-graph-links.md).
- Каталог внешних событий **`agent_memory.external_event.v1`** (`event_type`: heartbeat, progress, link_candidates, links_updated, nodes_updated, partial_result, complete_result, blocked_result, …), правила durable/ephemeral для конверта и golden map stdout→compact — **SoT в коде** `agent_memory_external_events.py` (обёртки в `agent_memory_w14_observability.py`). В JSONL журнале AgentMemory строка с **`event_name`** = **`memory.external_event`** несёт envelope внешнего протокола; это **не** таблица D-OBS-1 (зона AW↔AM compact), но связано с наблюдаемостью W14 — см. [`runtime-event-contract.md`](runtime-event-contract.md) §Связанные документы.
- **OR-013:** компактные причины частичного исхода и маппинг assembly→наблюдаемость — `agent_memory_terminal_outcomes.py`; нормативная матрица — [`../algorithms/agent-memory/failure-retry-observability.md`](../algorithms/agent-memory/failure-retry-observability.md).

### Журнал: durability строки

`MemoryJournalStore.append` (`memory_journal.py`) пропускает запись JSONL для строк с **`durability: ephemeral`** (классификация internal-событий — `journal_durability_for_internal_event`, напр. `memory.index.partial`); durable шаги (`memory.runtime.step` и др.) остаются в файле журнала. Слияние shadow init → канонический путь — `append_rows_from_jsonl_file` (сценарий init).

## Post-pipeline в AgentMemory (`memory.query_context`)

После `AgentMemoryQueryPipeline.run` в `AgentMemory.handle` применяется цепочка пост-обработки `memory_slice` (источник правды — один блок в `handle`, см. ниже).

### 1. Полный fallback при `memory_slice is None`

Подмена всего dict на `_fallback_slice(...)` (namespace, `want_path`, goal, `query_kind`, `level`).

### 2. Пустой `injected_text`, слайс от pipeline уже есть

Условия (упрощённо):

- `need_fb`: нет непустого `injected_text` и нет «финиша» W14 в смысле поля `am_v1_explicit_results` у результата pipeline (`not w14_finish`).
- Полная замена на `_fallback_slice` выполняется, если `need_fb` и при этом либо нет `w14_contract_failure` в слайсе, либо разрешён **path-fallback**: есть непустой `want_path` и **`reason` слайса не равен** `w14_command_output_invalid`.

Исключение (**G4 / task 2.1**): при `w14_contract_failure` и **`reason == w14_command_output_invalid`** (телеметрия невалидного command output после schema repair в pipeline — см. `agent_memory_query_pipeline.py`, присвоение `reason`) **полная** подмена слайса path-based `_fallback_slice` **не** выполняется, чтобы не затирать метаданные pipeline.

При остальных `w14_contract_failure` с непустым путём path-fallback по-прежнему даёт слайс с `reason: path_hint_fallback` и `node_ids` по пути.

### 3. Дополнительный fallback без W14-контрактного фейла и без пути

Если нет `w14_contract_failure`, нет `want_path`, и `injected_text` всё ещё пуст — снова полный `_fallback_slice`.

### 4. Pathless v1: merge stub-текста без замены dict

**Pathless v1** = envelope `AgentWorkMemoryQueryV1` распознан (`parse_agent_work_memory_query_v1`) и в исходном payload **нет** явного `path` / `hint_path` (`envelope_explicit_path == False`).

Если после шагов 1–3 `injected_text` всё ещё пуст, строится `stub = _fallback_slice(...)` и выполняется **merge** в существующий `memory_slice`: копия полей pipeline сохраняется, в копию записывается `injected_text` (и при необходимости корректируется `estimated_tokens`). Так UC 2.4 получает непустой текст для Work и trace-тройки, не теряя флаги вроде `w14_contract_failure`, `partial`, исходный `reason`.

Реализация: `pathless_v1_memory_query` и блок `merged: dict[str, Any] = dict(memory_slice)` в `memory_agent.py`.

## Связанный код (источник правды)

- `tools/agent_core/runtime/subprocess_agents/work_agent.py` — `_request_memory_slice` (payload pathless v1), `_memory_slice_message`, `_memory_injected_payload` (строки порядка ~290–517).
- `tools/agent_core/session/context_ledger.py` — `memory_injected_v2_payload` (`usage_state: "estimated"` в возвращаемом dict, ~267–297).
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — `_fallback_slice` (~1284–1316), `handle` / ветка `memory.query_context` и пост-pipeline (~1496–1564); cancel path и публикация SoT.
- `tools/agent_core/runtime/agent_memory_result_v1.py` — `resolve_memory_continuation_required`, `build_agent_memory_result_v1`.
- `tools/agent_core/runtime/broker.py` — ветка `runtime.cancel_active_turn` на `service.request`.
- `tools/agent_core/runtime/agent_memory_query_pipeline.py` — W14 pipeline, `propose_links`, выставление `reason: w14_command_output_invalid` (согласование с п.2 выше).
- `tools/agent_core/runtime/agent_memory_link_candidate_validator.py`, `tools/agent_core/runtime/pag_graph_write_service.py` — валидация кандидатов связей и запись PAG.
- `tools/agent_core/runtime/agent_memory_external_events.py`, `tools/agent_core/runtime/agent_memory_terminal_outcomes.py` — внешние события и OR-013.
- `tools/agent_core/runtime/memory_journal.py` — JSONL store, `durability`, merge init-журналов.
