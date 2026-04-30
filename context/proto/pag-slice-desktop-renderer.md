# Pag-slice (desktop renderer)

## Участники

- **Инициатор:** React renderer, через `window.ailitDesktop.pagGraphSlice` (тип `PagGraphSliceFn` в `loadPagGraphMerged` / `pagGraphSessionStore.ts`).
- **Получатель:** main/IPC-адаптер (код в 1.1 **не** менялся).

## Транспорт

Preload-обёртка на Electron: JSON-ответ **как в существующем контракте** pag-slice.

## Семантика `missing_db` (нормализованно)

- Ответ с **`code: missing_db`** (или сопоставимое сообщение без кода в legacy-путях) означает: файла sqlite PAG для namespace нет / не открыт — **срез из БД пуст** не из-га ошибки чтения, а из-га отсутствия БД.
- **Renderer** не ожидает расширения JSON в 1.1: классификация `missing_db` и текстовых аналогов — в `pagGraphSessionStore.ts` (`isPagSqliteFileMissingError`).
- Full load по всем namespace, когда везде только `missing_db` и merged пуст: трактуется как **успех** full load с флагом `pagSqliteMissing: true` и `pagDatabasePresent: false` в снимке после reconcile — **не** как `loadState: "error"`.

## Trace

Инкременты `rawTraceRows` / `PagGraphSessionTraceMerge` без смены контракта; при отсутствии БД граф может наполняться из trace (см. архитектуру в [`../arch/desktop-pag-graph-snapshot.md`](../arch/desktop-pag-graph-snapshot.md)).
