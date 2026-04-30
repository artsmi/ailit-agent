# Память итерации: `feature_3d_memory_pag_task_1_1`

**Связь:** feature 1.1, PAG / Memory 3D desktop. Другие записи: [`index.md`](index.md). Канон: [`../INDEX.md`](../INDEX.md). Источник фактов: `context/artifacts/change_inventory.md` (12).

## Задача

Различение **«PAG БД ещё не создана»** vs **ошибка чтения** vs **пусто с данными из trace**; флаг в снимке; поллер без накопления `loadError` при `missing_db`; ветвление 3D UI.

## Процессы и модули

- **Renderer:** `pagGraphSessionStore.ts` (`PagGraphSessionSnapshot.pagDatabasePresent`, `PagGraphSessionFullLoad`, reconcile / `applyIncremental`), `DesktopSessionContext.tsx` (`awaitingPagSqlite`, поллер `PAG_SQLITE_RETRY_MS` = 2500 ms), `MemoryGraph3DPage.tsx` (ветки `missingPagEmpty` / `missingPagTrace` / empty / ready, ключ `pd`).

## Поведение (зафиксировано)

- `pagDatabasePresent === false` + `loadState === "ready"` — ожидание появления sqlite, **не** ошибка загрузки.
- `loadState === "error"` — реальные сбои чтения, отличимы от missing.
- `missingPagTrace` — нет БД, но merged не пуст (trace); `missingPagEmpty` — нет нод/линков.
- Поллер: при `pagSqliteMissing` **не** пишет `loadError` на каждом тикe.

## Протоколы

- IPC `pag-slice` **без** изменения JSON-контракта; семантика `missing_db` в [`../proto/pag-slice-desktop-renderer.md`](../proto/pag-slice-desktop-renderer.md).

## Тесты

- `pagGraphSessionStore.test.ts` — зелёный scope по отчёту 09; полный `npm test` может требовать разграничения с `AppShell.test.tsx`.

## Риски / дальше

- OQ2: текст баннера missing PAG — placeholder.
- Можно позже: unit на поллер; явный assert на `sessionId` при появлении БД (сейчас косвенно).

## Обновлённые разделы context

- `context/arch/desktop-pag-graph-snapshot.md`, `context/proto/pag-slice-desktop-renderer.md`, `context/tests/INDEX.md`, этот файл, `context/INDEX.md`.
