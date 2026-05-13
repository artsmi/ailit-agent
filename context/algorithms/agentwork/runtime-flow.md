# Поток выполнения AgentWork

Документ описывает **фактический путь кода** на момент синхронизации с репозиторием. Якорные модули: `ailit/ailit_runtime/subprocess_agents/work_agent.py`, `work_orchestrator.py`, `ailit/ailit_runtime/broker.py` (spawn).

## Запуск процесса

`AgentBroker.spawn_work()` стартует Python-подпроцесс с `-m agent_core.runtime.subprocess_agents.work_agent`, передаёт `--chat-id`, `--broker-id`, `--broker-socket-path`, `--namespace` и опционально `--workspace-config`.

Процесс читает **stdin построчно**: каждая непустая строка — JSON `RuntimeRequestEnvelope`. Неверный `contract_version` отбрасывается. Ответ — одна JSON-строка в stdout.

## Типы входящих сообщений

### `action.start` с `work.handle_user_prompt`

1. Извлекается `prompt`, список `project_roots` из payload (или из broker workspace file, иначе `cwd`).
2. Если уже есть живой поток на этот prompt — ответ `agent_busy`.
3. Иначе стартуется фоновый `threading.Thread`, который вызывает `_WorkChatSession.run_user_prompt`, а `handle` сразу возвращает envelope «принято» (асинхронная модель относительно UI).

### `service.request`

- **`work.perm_mode_choice`**: сопоставление `gate_id`, запись выбора режима в KB (если включена), `Event.set()` для снятия блокировки классификатора.
- **`work.approval_resolve`**: approve/reject для ASK на инструмент.
- Отмена активного хода: action / service `runtime.cancel_active_turn` с проверкой `chat_id` и `user_turn_id`.

## Внутри одного user prompt (`run_user_prompt`)

Порядок шагов стабилен:

1. **История**: добавляется user-сообщение; счётчик ходов; новый `user_turn_id`; сброс `_memory_queries_in_turn`.
2. **Первый ход чата**: при необходимости подмешиваются system-hints инструментов (`inject_tool_hints_before_first_user`), включая KB-first, если в merge-конфиге включена секция `memory` (`memory_kb_first_enabled`).
3. **Событие** `action.started` для `work.handle_user_prompt`.
4. **D-context**: попытка восстановить последний D-level compact в thread сообщений (один раз на `d_node_id`).
5. **AgentMemory RPC**: цикл `_request_memory_slice` (см. `kb-and-memory-layers.md`). Результат — опциональное system-сообщение `agent_memory_slice` или отсутствие инъекции при ошибках/budget.
6. **Провайдер и реестр инструментов**: `_ProviderAssembler` (DeepSeek / Kimi / mock), `_RegistryAssembler` (builtin + bash + при `memory.enabled` — KB tools с `AILIT_KB_NAMESPACE`).
7. **PermissionEngine** базовый (часто allow на всё; уточнение на уровне SessionRunner).
8. **Уведомление о записи файлов**: `file_changed_notifier` шлёт `memory.change_feedback` в AgentMemory через тот же Unix-сокет брокера.
9. **SessionRunner** без оркестратора только как исполнитель; сверху оборачивается `WorkTaskOrchestrator`.
10. **Perm-5 (опционально)**: если `AILIT_WORK_AGENT_PERM` truthy и не multi-agent bypass — `PermModeTurnCoordinator.resolve_turn`; при `not_sure` публикуется `session.perm_mode.need_user_choice` и поток ждёт до 600 с выбора из UI.
11. **SessionSettings**: `max_turns` очень большой, streaming, `perm_tool_mode`, `compact_to_memory_enabled=True`, `pag_runtime_enabled=False` для этого пути.
12. **Оркестратор**: `WorkTaskOrchestrator.run(WorkTaskRequest(...))` — классификация, план, выполнение, verify, repair.
13. **Постобработка**: из истории удаляются сообщения `agent_memory_slice` перед сохранением состояния сессии; публикуется `assistant.final` при успехе.

## Завершение и ошибки

- Исключения в worker ловятся: `assistant.final` с текстом ошибки и `action.failed`.
- Кооперативная отмена: проверки в цикле памяти и итог `cancelled` в результате хода.

## Связь с другими пакетами канона

- Контракт запроса памяти от AgentWork к AgentMemory: пакет **`../agent-memory/`** (`external-protocol.md`, схема `agent_work_memory_query.v1`).
- Broker и маршрутизация: `context/proto/` и планы рантайма при необходимости.
