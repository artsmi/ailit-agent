# Broker trace: AgentWork ↔ AgentMemory и `context.memory_injected` (UC 2.4)

## Участники

- **Broker** (P3): Unix socket на `BrokerConfig.socket_path`; процессы `AgentWork:<chat_id>`, `AgentMemory:global`.
- **Trace store:** JSONL (`trace_store_path`), строки = события рантайма.

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
- `tools/agent_core/runtime/subprocess_agents/memory_agent.py` — `_fallback_slice` (~1284–1316), `handle` / ветка `memory.query_context` и пост-pipeline (~1496–1564).
- `tools/agent_core/runtime/agent_memory_query_pipeline.py` — выставление `reason: w14_command_output_invalid` (без изменений в task 2.1; согласование семантики с п.2 выше).
