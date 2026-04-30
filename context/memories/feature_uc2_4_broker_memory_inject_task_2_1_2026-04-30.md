# Память итерации: `feature_uc2_4_broker_memory_inject_task_2_1_2026-04-30`

**Связь:** G4 / task **2.1**, ТЗ UC 2.4 — broker trace после `work.handle_user_prompt`: pathless v1 `memory.query_context`, непустой `memory_slice.injected_text` при `ok: true`, публикация Work `context.memory_injected` v2 с `usage_state: estimated`. См. также W14 pipeline: [`feature_3d_memory_w14_task_1_2.md`](feature_3d_memory_w14_task_1_2.md). Канон: [`../INDEX.md`](../INDEX.md). Источник фактов: `context/artifacts/change_inventory.md` (12).

## Задача

Обеспечить регрессию `test_broker_work_memory_routing.py` (в т.ч. `seen_memory_pair`) без ослабления assert: Memory возвращает непустой `injected_text` в pathless сценарии; Work и контракт публикации инжекта не менялись.

## Процессы и модули

- **`AgentMemory:global` / `memory_agent.py`:** единственный изменённый продуктовый модуль итерации — `handle` после `AgentMemoryQueryPipeline.run`: условный path-fallback; запрет полной замены слайса на path-based `_fallback_slice` при `reason == w14_command_output_invalid`; для pathless v1 — merge stub `injected_text` из `_fallback_slice` в существующий dict слайса.
- **`AgentMemoryQueryPipeline`:** источник `w14_command_output_invalid`; в коммитах 2.1 не менялся.
- **`AgentWork` / `work_agent.py`:** граница `context.memory_injected` только при непустом `injected_text` — без правок в 2.1.

## Поведение (зафиксировано)

- Pathless v1 + пустой текст после pipeline → **merge**, не «слепая» замена всего `memory_slice`, чтобы сохранить телеметрию pipeline (`w14_contract_failure`, `partial`, `reason`, …).
- При `w14_contract_failure` и **`w14_command_output_invalid`** полная подмена на path-fallback-слайс **отключена**; для прочих `w14_contract_failure` с путём path-fallback сохраняется.

## Протоколы

- Broker / Work / Memory / инжект: [`../proto/broker-memory-work-inject.md`](../proto/broker-memory-work-inject.md).

## Тесты

- `tests/runtime/test_broker_work_memory_routing.py` — основной приёмочный trace.
- Перечень W14/PAG регрессий из инвентаризации 12 — в [`../tests/INDEX.md`](../tests/INDEX.md) (раздел task 2.1).
- Итог **11:** см. `context/artifacts/reports/test_runner_11_task_2_1_final_11.json`, `test_report_fix_pytest_five.md` (артефакты; часть файлов в `context/artifacts/` может быть локальной из-за `.gitignore`).

## Коммиты-якоря (разработка)

- `03bfe2b` — pathless, непустой `injected_text` (UC 2.4).
- `bbaca51` — не затирать `w14_command_output_invalid` path-fallback-слайсом.

## Обновлённые разделы context (writer 13)

- `context/proto/broker-memory-work-inject.md`, индексы `context/proto/INDEX.md`, `context/arch/system-elements.md`, `context/arch/INDEX.md`, `context/tests/INDEX.md`, `context/INDEX.md`, `context/memories/index.md`, этот файл.
