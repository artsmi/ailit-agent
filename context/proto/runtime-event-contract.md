# Runtime compact events: whitelist (D-OBS-1)

Документ может дополняться секциями из планов W13/W14R (journal, прочие DTO). Ниже — канон **D-OBS-1** для compact-топиков AgentWork в зоне memory-path.

Нормативный whitelist строковых имён **compact**-событий (stdout JSONL / trace) для зоны **AgentWork ↔ AgentMemory** (W14): continuation второго и последующих `memory.query_context` в одном `user_turn_id`, таймаут RPC, cap, соседние диагностические события. Источники: **ТЗ** `context/artifacts/technical_specification.md` §3.2 (UC-01–UC-03, компактная наблюдаемость), **`context/artifacts/architecture.md` §5**, реализация **`tools/agent_core/runtime/subprocess_agents/work_agent.py`**.

**Правило D-OBS-1:** любое новое compact-событие в этой зоне добавляется только через обновление §5 **и** этого файла; литералы в коде **должны** совпадать с таблицей ниже **дословно** (без альтернативных синонимов в продюсере AW).

## Whitelist (дословные `event_type` / topic)

| Topic | Producer (типично) | Минимальный compact-payload | Ссылка |
|-------|--------------------|-----------------------------|--------|
| `memory.query_context.continuation` | AgentWork | `user_turn_id`, `previous_query_id`, `next_query_id`, `reason` (= `continuation`, см. ниже) | `architecture.md` §5 Event continuation; `broker-memory-work-inject.md` (W14 continuation) |

### Поле `reason` у `memory.query_context.continuation`

Допустимое значение **ровно одно**: строка `continuation` (латиница, нижний регистр). В коде AgentWork литерал синхронизирован с таблицей через константу **`_MEMORY_QUERY_CONTINUATION_REASON`** в `tools/agent_core/runtime/subprocess_agents/work_agent.py` (значение совпадает с этим абзацем дословно).
| `memory.query.timeout` | AgentWork | `query_id`, `user_turn_id`, `code` (напр. `runtime_timeout`), `timeout_s` | `architecture.md` §5 Event memory query timeout |
| `memory.query.budget_exceeded` | AgentWork | §5: `cap`, `user_turn_id`; в `work_agent.py` дополнительно `code` (`too_many_memory_queries`) | `architecture.md` §5 Event cap exceeded |
| `memory.actor_unavailable` | AgentWork | причина/ошибка без сырого prompt | `broker-memory-work-inject.md`, ветки broker/socket/SoT |
| `memory.actor_slice_used` | AgentWork | успешный непустой слайс перед инжектом | `broker-memory-work-inject.md` §Условие публикации |
| `memory.actor_slice_skipped` | AgentWork | пустой `injected_text` после успешного ответа AM | `broker-memory-work-inject.md` §Условие публикации |
| `context.memory_injected` | AgentWork | схема `context.memory_injected.v2`, в т.ч. `usage_state` | `broker-memory-work-inject.md` §Обязательная тройка |
| `memory.command.normalized` | AgentMemory (`AgentMemoryQueryPipeline` → journal) | `from_schema_version`, `to_schema_version` (= `agent_memory_command_output.v1`), опционально `from_status` (легаси до маппинга), `command_id_restored` (bool), усечённые `command` / `command_id` | `broker-memory-work-inject.md` §W14 planner canonicalization; ТЗ UC-01 |
| `memory.w14.command_id_restored` | AgentMemory (journal) | `command_id` (усечённый канонический id после восстановления из runtime trace) | ТЗ UC-02; пишется только если восстановление применено |
| `session.cancelled` | AgentWork (`SessionRunner` / cooperative path) | минимум `phase`; при cooperative cancel из `work_agent` допускается `user_turn_id`, `reason` | `architecture.md` §5 UC-05 |
| `action.cancelled` | AgentWork (`AgentWorkWorker.handle` / `_run` после отменённого turn) | `action`, `action_id`, `user_turn_id`, `reason` | `architecture.md` §5 UC-05 |

События **`memory.query_context.continuation`**, **`memory.query.timeout`**, **`memory.query.budget_exceeded`** — зона **D-OBS-1** по отношению к ТЗ §3.2 и **architecture.md** §5; остальные строки в таблице — уже используемые соседние compact-топики того же пути (не подменяют timeout/continuation).

## Запреты (не путать сценарии)

- Событие **`memory.query.timeout`** **не** эквивалентно успешному завершению memory-path. **Запрещено** трактовать timeout как **`memory.actor_slice_used`** или публиковать **`context.memory_injected`** «с успехом» вместо явной политики blocked/failure для memory-path (**architecture.md** §5, **broker-memory-work-inject.md** п.4 W14).
- **`memory.actor_slice_used`** и **`context.memory_injected`** относятся к **успешному** инжекту текста после валидного SoT `agent_memory_result` и неполого слайса; их нельзя использовать как замену записи о **`memory.query.timeout`**.

## Проверка согласованности (документарная)

После смены имён в коде или §5:

```bash
rg -n 'memory\.query\.timeout|memory\.query_context\.continuation|memory\.query\.budget_exceeded' tools/agent_core/runtime/subprocess_agents/work_agent.py context/artifacts/architecture.md context/proto/runtime-event-contract.md
```

Черновые или альтернативные имена (пример антипаттерна: `memory.query.continuation`, `memory.rpc.timeout`) в продюсере AW **не** допускаются без согласованного изменения §5 и этого whitelist.

## Связанные документы

- [`broker-memory-work-inject.md`](broker-memory-work-inject.md) — UC 2.4, тройка trace, условия `context.memory_injected` / slice skipped.
- [`context/artifacts/architecture.md`](../artifacts/architecture.md) §5 — интерфейсы и обязательные поля событий.
- [`context/artifacts/technical_specification.md`](../artifacts/technical_specification.md) §3.2 — требования к компактным событиям.
