# Память итерации: `feature_3d_memory_layout_task_1_3`

**Связь:** feature 1.3 — стабильность 3D memory graph (renderer). См. также: [`feature_3d_memory_pag_task_1_1.md`](feature_3d_memory_pag_task_1_1.md) (PAG/снимок), [`feature_3d_memory_w14_task_1_2.md`](feature_3d_memory_w14_task_1_2.md) (W14 Python, другая ветка). Канон: [`../INDEX.md`](../INDEX.md). Источник фактов: `context/artifacts/change_inventory.md` (12).

## Задача

**Вариант A (индикатор 2.3 / m1):** измеримый `graphDataKey` **без** сегмента `n{nodes.length}`; remount `ForceGraph3D` при смене сессии / `loadState` / `graphRevByNamespace` / `pagDatabasePresent`, а не на каждой +1 ноде; **merge** PAG-данных с сохранением `x`…`fz` у существующих `id` (N→N+1); согласование `useLayoutEffect` (G16.4) с `graphDataKey` — resize/refresh не ослаблены. Python / agent runtime в 1.3 **не** менялись.

## Процессы и модули (desktop renderer)

- **`memoryGraphDataKey.ts`:** `formatGraphRevByNamespaceKey`, `MemoryGraphDataKeySnap`, `computeMemoryGraphDataKey`.
- **`memoryGraphState.ts`:** `mergeNodePreservingCoords` внутри `mergeMemoryGraph`.
- **`MemoryGraph3DPage.tsx`:** `graphDataKey` → `key={...}`; G16.4 `useLayoutEffect` + deps `graphDataKey` и `graph.nodes.length`.
- **`pagGraphSessionStore.ts`:** регресс по веткам с `pagDatabasePresent` (без смены публичного IPC).

## Поведение (зафиксировано)

- Ключ детерминирован по snap-полям; при росте графа при неизменном rev remount нод по счётчику не требуется, но refresh layout — через G16.4 и длину в deps.
- Координаты существующих нод не затираются «пустыми» полями при merge/trace upsert.

## Протоколы

- IPC PAG / trace **без** изменения контракта (только клиентский ключ и merge) — см. [`../arch/desktop-pag-graph-snapshot.md`](../arch/desktop-pag-graph-snapshot.md).

## Тесты

- `memoryGraphDataKey.test.ts`, `memoryGraphState.test.ts`, `pagGraphSessionStore.test.ts`.
- Команда и статус: `context/artifacts/reports/test_report_pipeline_task_1_3.md` (25 passed, 3 files).

## Риски / дальше

- 09 **MINOR:** при расхождении синхронизировать `developer_08_task_1_3.json` и `test_report_task_1_3.md` с зелёным `test_report_pipeline_task_1_3.md` (см. change_inventory).

## Обновлённые разделы context

- `context/arch/desktop-pag-graph-snapshot.md`, `context/arch/INDEX.md`, `context/tests/INDEX.md`, `context/INDEX.md`, `context/memories/index.md`, этот файл, `context/artifacts/tech_writer_report.md` (13).
