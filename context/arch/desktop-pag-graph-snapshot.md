# Desktop: снимок PAG-графа по сессии (Memory 2D/3D)

## Назначение

Единый **снимок** `PagGraphSessionSnapshot` для одного `sessionId` агрегирует merged-граф, rev по namespace, применение trace, предупреждения и **состояние загрузки**. Потребители: `DesktopSessionContext`, `MemoryGraph3DPage` и сопутствующий runtime.

**Главные файлы:** `desktop/src/renderer/runtime/pagGraphSessionStore.ts`, `desktop/src/renderer/runtime/pagGraphObservabilityCompact.ts` (строки trace `pag_graph_rev_reconciled` / `pag_snapshot_refreshed`), `desktop/src/renderer/runtime/DesktopSessionContext.tsx`, `desktop/src/renderer/views/MemoryGraph3DPage.tsx`.

## Канон и перекрёстные ссылки

Источник решений по данному снимку и 3D-проекции: [`context/artifacts/architecture.md`](../artifacts/architecture.md) — §4 (сущность снимка, UC-04, D-EDGE-GATE-1, compact events), §5.2 (порядок **X→Y**), §9 (идемпотентность / отсутствие дублей reconcile-событий при повторном slice с тем же rev). Полные schema-like контракты compact-событий (required / nullable / forbidden, ownership) — в [`context/proto/desktop-memory-3d-observability.md`](../proto/desktop-memory-3d-observability.md) после задачи **1_2** (proto); здесь — только поведение снимка и имена для согласования с **1_2**.

### UC-04 ветка **A** (только A; B запрещена в том же payload)

- Рёбра, у которых оба конца (`source` / `target`) **не** входят во множество `id` узлов **текущей** проекции в 3D, **исключаются** из финального списка для ForceGraph **до** появления обоих концов в merged/проекции.
- **Запрещено** одновременно вводить плейсхолдер-ноды для «висячих» концов (ветка **B**) в том же payload, что и фильтр A: в каноне зафиксирована **только ветка A** (см. `architecture.md` §4 «UC-04 ветка **A**» и таблицу трассировки UC-04 в §14).

### D-EDGE-GATE-1: edge-gated проекция 3D (reachability до A-корня)

- **Назначение:** в 3D показывать только узлы, для которых уже есть **путь рёбер** в `merged` до какой-либо A-ноды. До прихода рёбер B/C/D-узлы остаются скрытыми; A-узлы видны всегда. Никаких синтетических узлов или рёбер на сцену не добавляется.
- **Алгоритм проекции** (`MemoryGraphForceGraphProjector.project`): UC-04A (`filterEdgesUc04BranchA` — отбросить рёбра без обоих концов) → `keepNodesReachableToAnyA` (BFS **неориентированно** от множества всех A-узлов входа; оставить достижимые узлы и рёбра между ними; A-узлы — всегда).
- **Область достижимости (C-SCOPE):**
  - `single` / `multi_separate`: считается в пределах одного namespace после `sliceMemoryGraphToNamespace`; A-корни — все A этого namespace.
  - `multi_unified` (режим U): считается в пределах union (`filterMemoryGraphToNamespacesUnion`); A-корни — все A любого namespace из union.
- **Если A-узлов нет:** `keepNodesReachableToAnyA` возвращает пустой граф (показывать нечего; никаких текстов-плейсхолдеров).
- **Подсветка:** placeholder-узлы из `ensureHighlightNodes` без рёбер автоматически отфильтрованы edge-gate и в 3D не видны; в 2D как списочное представление они остаются.
- **Запрещено:** вводить «синтетический корень связности» или любые другие искусственные узлы/рёбра, которых нет в PAG/`merged`. Префикс `ailit:trace-conn-root:` не используется и не должен появляться нигде в `desktop/`.

### Порядок **X→Y** (graph rev mismatch, §5.2)

Кратко (нумерация как в `architecture.md` §5.2):

1. **X:** успешный ответ slice (IPC) для namespace **N** с извлекаемым `graph_rev_slice` и телом графа.
2. **Y1:** в том же цикле merge store атомарно: обновить `merged` / координаты, затем **`graphRevByNamespace[N] = graph_rev_slice` до** применения trace-дельт, сравнивающих «ожидаемый следующий rev» с rev из trace.
3. **Y2:** применить trace-дельты по **N** уже против нового базового rev.
4. **Z:** при ложном mismatch при равных источниках — дефект порядка; исправление без «залипания» UI.
5. **Refresh:** повтор full load → очистка rev-warnings по канону → emit **`pag_snapshot_refreshed`** → при необходимости **`pag_graph_rev_reconciled`** с `reason_code=user_refresh` (детали полей — proto).

Негативные сценарии Н1/Н2 и лимиты предупреждений — в том же §5.2 и в тестах store (`pagGraphSessionStore.test.ts`).

### Refresh, очистка предупреждений и compact events (согласование с 1_2)

- Поведение снимка при **Refresh** / **`afterFullLoad`:** реплей trace на merged + `graphRevByNamespace` из среза начинается с **пустого** списка предупреждений; согласованные rev не добавляют новый рассинхрон, устаревшие rev-mismatch **не** переносятся из предыдущего снимка (полная замена пути full load — см. ниже в разделе про `warnings`).
- **Observability (имена зафиксированы для волны 1, совпадают с `tasks/task_1_2.md`):** после **успешного** Refresh full load renderer эмитит **`pag_snapshot_refreshed`**; при необходимости фиксации rev в журнале — **`pag_graph_rev_reconciled`**. По **D-PROD-1** (план/proto **1_2**) **единственный** продюсер `pag_graph_rev_reconciled` — **renderer**; Python не дублирует emit этого события для desktop-trace того же цикла.
- Частота и идемпотентность: не плодить reconcile при повторном slice с тем же rev — см. `architecture.md` §9; точные правила дебаунса — в proto-файле observability.

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

## 3D UI: ветки и проекция

`MemoryGraph3DPage.tsx` — проекция `loadState`, `pagDatabasePresent` и `merged` в режимы: loading, error, empty при отсутствии БД, trace-only, empty, ready. Проекция рёбер в ForceGraph следует **UC-04 ветка A** + **D-EDGE-GATE-1** (см. раздел «Канон» выше); реализация — `desktop/src/renderer/runtime/memoryGraphForceGraphProjection.ts` (`MemoryGraphForceGraphProjector.project` = `filterEdgesUc04BranchA` → `keepNodesReachableToAnyA`).

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

- **Финальный gate §5.0 (итерация Memory 3D / PAG):** **12** файлов Vitest, **80** тестов — команда и таблица в [`../tests/INDEX.md`](../tests/INDEX.md); сводный отчёт финального `11` при наличии — `context/artifacts/reports/test_run_11_final.md` (если артефакт отсутствует в клоне, источником команд остаётся `INDEX.md`).
- `pagGraphSessionStore.test.ts` — `pagDatabasePresent`, full load, `applyIncremental`, дедуп `warnings` по rev, сценарий «Refresh» с согласованным срезом (регресс по 1.1/1.3); покрывает контракты `pagGraphRevWarningFormat` через store.
- `pagGraphTraceDeltas.test.ts`, `pagHighlightFromTrace.test.ts`, `loadPagGraphMerged.test.ts`, `memoryGraph3DResolvedColors.test.ts`, `memoryGraph3DLineStyle.test.ts`, `pagGraphLimits.test.ts` — trace, highlight, merge, 3D визуал рёбер, caps (см. INDEX).
- `memoryGraphDataKey.test.ts` (1.3 / 3.1) — вариант A: в ключе нет шаблона `n<число>`; смена ключа при `loadState`, `graphRevByNamespace`, `pagDatabasePresent`.
- `memoryGraphState.test.ts` (1.3) — merge без сброса координат; trace/upsert не стирает `x`/`y`/`z` у существующих.

Исторический прогон только трёх файлов (1.3) — `context/artifacts/reports/test_report_pipeline_task_1_3.md`. Полный `npm test` desktop может задевать другие пакеты (см. `context/tests/INDEX.md`).

## Открыто

- Копия для баннера при missing PAG (OQ2) — placeholder до продуктового согласования.
- Отдельный unit-тест на поллер в отчётах 09 не требовался как блокер.
