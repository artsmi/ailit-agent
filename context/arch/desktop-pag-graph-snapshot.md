# Desktop: снимок PAG-графа по сессии (Memory 2D/3D)

## Назначение

Единый **снимок** `PagGraphSessionSnapshot` для одного `sessionId` агрегирует merged-граф, rev по namespace, применение trace, предупреждения и **состояние загрузки**. Потребители: `DesktopSessionContext`, `MemoryGraph3DPage` и сопутствующий runtime.

**Главные файлы:** `desktop/src/renderer/runtime/pagGraphSessionStore.ts`, `desktop/src/renderer/runtime/DesktopSessionContext.tsx`, `desktop/src/renderer/views/MemoryGraph3DPage.tsx`.

## D-HI-1: highlight из trace (задача 2.1)

- Единый визуальный канал: `PagSearchHighlightV1` и маппинг строк ledger / W14 в `desktop/src/renderer/runtime/pagHighlightFromTrace.ts` (`highlightFromTraceRow`).
- Итог по сессии: `lastPagSearchHighlightFromTrace` — по порядку trace побеждает **последнее** ненулевое событие после фильтра namespace внутри маппера (не только «хвост» массива).
- Слияние в merged: `PagGraphSessionTraceMerge.applyHighlightFromTraceRows`; при инкременте без новых trace-строк снимок не пересчитывается (`applyIncremental`, architecture §4.3 — анти-мигание).
- 2D/3D UI берёт тот же `lastPagSearchHighlightFromTrace` из `rawTraceRows`, без второго параллельного стека в React вне этого правила.

## `warnings` и `graph_rev` (задача 1.1, D-GR-1)

- **Текст рассинхрона rev** формируется в `pagGraphTraceDeltas.ts` через `formatPagGraphRevMismatchWarning` из **`desktop/src/renderer/runtime/pagGraphRevWarningFormat.ts`** и **включает `namespace`**, чтобы различать одинаковые пары чисел у разных namespace и не плодить неразличимые баннеры. В форматтере: экранирование `»` в имени namespace для стабильного парсинга, ключ дедупа `\u001f`-разделённый, разбор legacy-сообщений без namespace.
- **Дедупликация** в снимке: перед выдачей наружу список предупреждений проходит `dedupePagGraphSnapshotWarnings` из того же модуля (импорт в `pagGraphSessionStore.ts`) — по ключу `(namespace, expected_next_rev, trace_rev)` для строк рассинхрона rev и по **точному совпадению текста** для прочих строк (в т.ч. предупреждение о тяжёлом merged). Модуль **обязан** поставляться в репозитории вместе с импортёрами: без него сборка/renderer падает на чистом clone.
- **Refresh / `afterFullLoad`:** реплей trace на merged + `graphRevByNamespace` из среза начинается с пустого списка предупреждений; при согласованных rev новые рассинхроны не добавляются, устаревшие предупреждения не переносятся из предыдущего снимка (полная замена пути full load в контексте вызывающего кода).

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

## Стабильный ключ remount 3D и merge координат (задача 1.3, стабилизация 3.1)

**Индикатор/вариант A (измеримый, §2.3 / m1 в постановке):** строка `graphDataKey` для remount `ForceGraph3D` **не** содержит сегмента `n{merged.nodes.length}`; remount по смене **сессии** (`activeSessionId`), **фазы** загрузки для ключа, нормализованного `graphRevByNamespace`, `pagDatabasePresent` — а не на каждой дельте +1 ноды.

**Источник ключа:** `desktop/src/renderer/runtime/memoryGraphDataKey.ts`

- `MemoryGraphDataKeySnap` — срез полей: `loadState`, `pagDatabasePresent`, `graphRevByNamespace` (локальный контракт ключа, без полного `PagGraphSessionSnapshot`).
- `graphLoadPhaseForDataKey` — для ключа: `idle` / `loading` / `ready` → одна фаза **`live`**, отдельно только **`error`** (задача 3.1: нет лишнего remount при refresh PAG при неизменном rev/pd).
- `formatGraphRevByNamespaceKey` — детерминированная сериализация map (сортировка `k:v`, join `|`).
- `computeMemoryGraphDataKey({ activeSessionId, snap })` — сегменты из snap; при `snap === null` — префикс с `-none-pdx-`; **без** длины `nodes`; в строке ключа фаза `live`/`error`, не сырой `loadState`.

**Refresh PAG:** в `DesktopSessionContext.tsx` при старте full load для уже существующего снимка сессии `loadState: "loading"` выставляется **поверх** предыдущего снимка (сохраняются `merged`, `graphRevByNamespace`, предупреждения и т.д.), чтобы ключ и сцена не «обнулялись» до ответа slice.

**UI:** `MemoryGraph3DPage.tsx` — `graphDataKey` в `useMemo` из `computeMemoryGraphDataKey` с зависимостями по **полям ключа** (`loadState`, `pagDatabasePresent`, сигнатура rev), а не от счётчика нод; `key={graphDataKey}` на `ForceGraph3D`. **G16.4** (`useLayoutEffect` для refresh/resize): в зависимостях — `memoryPanelOpen`, `graph.nodes.length`, `viewSize`, **`graphDataKey`**. Длина `graph.nodes` в deps **вместе** с ключом **без** `n` в самом ключе даёт refresh при росте графа при неизменном rev.

**Merge PAG-данных:** `mergeMemoryGraph` в `memoryGraphState.ts` через `mergeNodePreservingCoords`: при upsert, если у входящей ноды нет валидного числа по полю координаты, сохраняется прежнее **конечное** значение (`x`, `y`, `z`, `fx`, `fy`, `fz`) — N→N+1 без «обнуления» layout существующих `id` пустыми полями из trace/инкремента.

**IPC / main (1.3):** не менялся; только renderer-ключ и merge.

## IPC / main

Контракт вызова `window.ailitDesktop.pagGraphSlice` и JSON ответа **в рамках 1.1 не менялся**; различие «нет sqlite» обрабатывается в renderer.

## Тесты

- **Финальный gate итерации Memory 3D (волны W1–W5):** девять файлов Vitest и команда — в [`../tests/INDEX.md`](../tests/INDEX.md) и `context/artifacts/reports/test_run_11_final.md` (48 tests passed).
- `pagGraphSessionStore.test.ts` — `pagDatabasePresent`, full load, `applyIncremental`, дедуп `warnings` по rev, сценарий «Refresh» с согласованным срезом (регресс по 1.1/1.3); покрывает контракты `pagGraphRevWarningFormat` через store.
- `pagGraphTraceDeltas.test.ts`, `pagHighlightFromTrace.test.ts`, `loadPagGraphMerged.test.ts`, `memoryGraph3DResolvedColors.test.ts`, `memoryGraph3DLineStyle.test.ts`, `pagGraphLimits.test.ts` — trace, highlight, merge, 3D визуал рёбер, caps (см. INDEX).
- `memoryGraphDataKey.test.ts` (1.3 / 3.1) — вариант A: в ключе нет шаблона `n<число>`; смена ключа при `loadState`, `graphRevByNamespace`, `pagDatabasePresent`.
- `memoryGraphState.test.ts` (1.3) — merge без сброса координат; trace/upsert не стирает `x`/`y`/`z` у существующих.

Исторический прогон только трёх файлов (1.3) — `context/artifacts/reports/test_report_pipeline_task_1_3.md`. Полный `npm test` desktop может задевать другие пакеты (см. `context/tests/INDEX.md`).

## Открыто

- Копия для баннера при missing PAG (OQ2) — placeholder до продуктового согласования.
- Отдельный unit-тест на поллер в отчётах 09 не требовался как блокер.
