# Supervisor: JSON по Unix socket

## Участники

- **Сервер:** процесс P2 (`ailit runtime supervisor`, `tools/agent_core/runtime/supervisor.py`).
- **Клиенты:** CLI (`ailit runtime status|brokers|…`), Electron main (`desktop/src/main/supervisorSocket.ts`, `registerIpc.ts`).

## Транспорт

- Unix domain socket: путь `<runtime_dir>/supervisor.sock`; `runtime_dir` = `AILIT_RUNTIME_DIR` или `XDG_RUNTIME_DIR/ailit` или `~/.ailit/runtime` (согласовано с `defaultRuntimeDir` в Electron и Python).
- Кадр: одна строка JSON запроса, завершающаяся `\n`; ответ — одна строка JSON до `\n` (см. `supervisorJsonRequest` в TypeScript).

## Команды `cmd` (обработчик Python)

Подтверждено по `supervisor.py`: `status`, `brokers`, `create_or_get_broker`, `stop_broker` (и расширения по мере эволюции кода — сверять с файлом).

Параметры для `create_or_get_broker` / `stop_broker` в IPC Electron: `chat_id`, `namespace`, `project_root` (см. `registerIpc.ts`).

## Ошибки и таймауты

- Клиенты задают таймаут (например 2000–5000 ms в Electron handlers).
- Отсутствие сокета: диагностическое сообщение в UI про `ailit runtime supervisor` и `systemctl --user status ailit.service`.

## Тесты

- E2E сценарии supervisor: например `tests/e2e/test_supervisor_g8_8.py` (переменная `AILIT_SUPERVISOR_SOCKET` в инвентаризации).
