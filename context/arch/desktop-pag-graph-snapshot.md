# Desktop: снимок PAG-графа по сессии (Memory 2D/3D)

## Назначение

Единый **снимок** `PagGraphSessionSnapshot` для одного `sessionId` агрегирует merged-граф, rev по namespace, применение trace, предупреждения и **состояние загрузки**. Потребители: `DesktopSessionContext`, `MemoryGraph3DPage` и сопутствующий runtime.

**Главные файлы:** `desktop/src/renderer/runtime/pagGraphSessionStore.ts`, `desktop/src/renderer/runtime/DesktopSessionContext.tsx`, `desktop/src/renderer/views/MemoryGraph3DPage.tsx`.

## `pagDatabasePresent` (задача 1.1)

- **`true`** (дефолт в `createEmptyPagGraphSessionSnapshot`) — по крайней мере один запрошенный namespace вернул данные среза из БД, либо full load ещё не дал сценария «только missing».
- **`false`** — на последнем **успешном** full load по **всем** запрошенным namespace был лишь ответ `missing_db` (или совместимая эвристика по тексту), и merged из БД пуст.

Full load: `PagGraphSessionFullLoad.run` — при полностью пустом merged из-за `missing_db` по всем namespace возвращается `ok: true` с `pagSqliteMissing: true` (не путать с `loadState: "error"`).

Классификация: `isPagSqliteFileMissingError` (код `missing_db` и строковые аналоги в `pagGraphSessionStore.ts`).

## `awaitingPagSqlite` и поллер

В `DesktopSessionContext.tsx`:

- `awaitingPagSqlite === true`, если в снимке `loadState === "ready"` и **`!pagDatabasePresent`** (источник — `pagGraphBySession`, отдельный дублирующий флаг не используется).
- При `awaitingPagSqlite`: `setInterval` с периодом **`PAG_SQLITE_RETRY_MS` = 2500 ms** для повторного full load.
- При ответе с `pagSqliteMissing` — **тихий** return без записи `loadError` (поллер не засоряет ошибками).
- При `!r.ok` — фиксация `loadState: "error"` и `loadError` (однократно по смыслу сценария, не на каждом тикe при missing sqlite).

## 3D UI: ветки

`MemoryGraph3DPage.tsx` — проекция `loadState`, `pagDatabasePresent` и `merged` в режимы: loading, error, empty при отсутствии БД, trace-only, empty, ready.

## Стабильный ключ remount 3D и merge координат (задача 1.3)

**Индикатор/вариант A (измеримый, §2.3 / m1 в постановке):** строка `graphDataKey` для remount `ForceGraph3D` **не** содержит сегмента `n{merged.nodes.length}`; remount по смене **сессии** (`activeSessionId`), `loadState`, нормализованного `graphRevByNamespace`, `pagDatabasePresent` — а не на каждой дельте +1 ноды.

**Источник ключа:** `desktop/src/renderer/runtime/memoryGraphDataKey.ts`

- `MemoryGraphDataKeySnap` — срез полей: `loadState`, `pagDatabasePresent`, `graphRevByNamespace` (локальный контракт ключа, без полного `PagGraphSessionSnapshot`).
- `formatGraphRevByNamespaceKey` — детерминированная сериализация map (сортировка `k:v`, join `|`).
- `computeMemoryGraphDataKey({ activeSessionId, snap })` — сегменты из snap; при `snap === null` — префикс с `-none-pdx-`; **без** длины `nodes`.

**UI:** `MemoryGraph3DPage.tsx` — `graphDataKey` в `useMemo` из `computeMemoryGraphDataKey` и `pagGraph.activeSnapshot` (только нужные поля), `key={graphDataKey}` на контейнере графа. **G16.4** (`useLayoutEffect` для refresh/resize): в зависимостях — `memoryPanelOpen`, `graph.nodes.length`, `viewSize`, **`graphDataKey`**. Длина `graph.nodes` в deps **вместе** с ключом **без** `n` в самом ключе даёт refresh при росте графа при неизменном rev.

**Merge PAG-данных:** `mergeMemoryGraph` в `memoryGraphState.ts` через `mergeNodePreservingCoords`: при upsert, если у входящей ноды нет валидного числа по полю координаты, сохраняется прежнее **конечное** значение (`x`, `y`, `z`, `fx`, `fy`, `fz`) — N→N+1 без «обнуления» layout существующих `id` пустыми полями из trace/инкремента.

**IPC / main (1.3):** не менялся; только renderer-ключ и merge.

## IPC / main

Контракт вызова `window.ailitDesktop.pagGraphSlice` и JSON ответа **в рамках 1.1 не менялся**; различие «нет sqlite» обрабатывается в renderer.

## Тесты

- `pagGraphSessionStore.test.ts` — `pagDatabasePresent`, full load, `applyIncremental` (регресс по 1.1/1.3).
- `memoryGraphDataKey.test.ts` (1.3) — вариант A: в ключе нет шаблона `n<число>`; смена ключа при `loadState`, `graphRevByNamespace`, `pagDatabasePresent`.
- `memoryGraphState.test.ts` (1.3) — merge без сброса координат; trace/upsert не стирает `x`/`y`/`z` у существующих.

Целевой прогон vitest (3 файла) и метрики — `context/artifacts/reports/test_report_pipeline_task_1_3.md`. Полный `npm test` desktop может задевать другие пакеты (см. `context/tests/INDEX.md`).

## Открыто

- Копия для баннера при missing PAG (OQ2) — placeholder до продуктового согласования.
- Отдельный unit-тест на поллер в отчётах 09 не требовался как блокер.
