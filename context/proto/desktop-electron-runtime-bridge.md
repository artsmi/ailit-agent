# Desktop Electron ↔ Python runtime

## Участники

- **Electron main** (P4): `desktop/src/main/registerIpc.ts`, сокеты в `supervisorSocket.ts`, `brokerSocket.ts`, `pagGraphBridge.ts`.
- **Renderer:** подписки на trace и прочие каналы через preload/main.
- **Внешний процесс CLI** (P1): вызывается через `child_process.execFile` для изолированных операций (не замена долгоживущего broker).

## Каналы

| Канал | Механизм | Назначение |
|-------|----------|------------|
| Supervisor API | Unix socket `supervisor.sock`, JSON строками | `status`, `brokers`, `create_or_get_broker`, `stop_broker` (IPC handlers `ailit:supervisor*`). |
| Broker API | Unix socket по `endpoint` (`unix://…`), JSON строка запроса | `ailit:brokerRequest` — делегирование в broker процесс. |
| PAG slice | `execFile(ailit, ['memory','pag-slice',…])`, stdout | `runPagGraphSlice` в `pagGraphBridge.ts`; бинарь из `AILIT_CLI` или `ailit` в `PATH`. |
| Trace JSONL | чтение файлов под `runtimeDir/trace/` | `readDurableTraceRows`, broadcast в renderer (`ailit:traceRow`). |

## Семантика PAG slice

Формат ответа CLI — см. [`pag-slice-desktop-renderer.md`](pag-slice-desktop-renderer.md) и типы `PagGraphSliceResult` в `pagGraphBridge.ts`.

## Переменные окружения

- `AILIT_RUNTIME_DIR` — общий с Python supervisor.
- `AILIT_CLI` — явный путь к CLI для dev.
