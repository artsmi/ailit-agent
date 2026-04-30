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

## Additive IPC: верхнеуровневый `graph_rev` (согласование X→Y)

По `context/artifacts/architecture.md` §5.1–5.2 main/адаптер может добавить **опциональное** верхнеуровневое поле ответа **`graph_rev`** (целое), дублирующее или выравнивающее rev из тела среза для устранения гонок при парсинге.

- **Правило:** поле **optional**; при отсутствии ключа — **default** для потребителя: извлекать rev только из существующего вложенного тела JSON (текущее поведение 1.1).
- **Nullable:** если ключ присутствует, значение — целое; **`null` на корне для этого поля не вводить** (либо целое, либо отсутствие ключа).
- **Совместимость JSON 1.1 / IPC:** только **additive** ключ на корне ответа; типы и обязательность уже существующих полей **не** меняются; клиенты, не знающие поля, игнорируют его (forward-compatible).
- **Версия N:** renderer **может** после согласованного bump протокола ожидать наличие `graph_rev` на корне для фиксации шага X до trace-merge; до bump не обязателен.

Компактные события наблюдаемости после merge (`pag_graph_rev_reconciled` и др.) — в [`desktop-memory-3d-observability.md`](desktop-memory-3d-observability.md); emit **не** является частью ответа pag-slice IPC.
