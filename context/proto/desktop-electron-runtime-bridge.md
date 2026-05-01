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

### Cooperative Stop (UC-05)

Транспорт тот же, что для `work.handle_user_prompt`: **`ailit:brokerRequest`** (`registerIpc.ts` → `brokerJsonRequest`).

| Поле | Значение |
|------|----------|
| Envelope `type` | `service.request` |
| `to_agent` | `AgentWork:<chat_id>` (или иной адресат; broker распознаёт по полю ниже) |
| `payload.service` | `runtime.cancel_active_turn` (канон плана волны 4, вариант A) |
| `payload.action` | то же логическое имя — **допускается** для совместимости с ранним текстом этого файла |
| `payload.chat_id` | идентификатор чата (совпадает с envelope `chat_id`) |
| `payload.user_turn_id` | корреляция turn (как в `memory.query_context` / `work_agent.py`) |

Семантика: идемпотентный cooperative cancel активного user-turn (доставка в AgentWork, отмена pending memory-path); UI дополнительно пишет терминальную строку trace `session.cancelled` (см. `DesktopSessionContext.tsx`). Жёсткий `supervisorStopBroker` после cancel остаётся fallback-сбросом сессии broker для чата. Renderer сначала резолвит workspace строго (`pickWorkspace`); если broker уже подключён, а строгий выбор пуст (например устаревшие `projectIds` в UI-сессии), для **только** cancel-запроса допускается fallback на первую запись `projectRegistry`, чтобы не терять cooperative путь и не опираться только на `stop_broker`.

## Семантика PAG slice

Формат ответа CLI — см. [`pag-slice-desktop-renderer.md`](pag-slice-desktop-renderer.md) и типы `PagGraphSliceResult` в `pagGraphBridge.ts`.

## Переменные окружения

- `AILIT_RUNTIME_DIR` — общий с Python supervisor.
- `AILIT_CLI` — явный путь к CLI для dev.
