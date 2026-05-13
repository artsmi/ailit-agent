# События и интеграции

Неполный перечень типов `topic.publish` / событий, которые эмитит AgentWork или которые важны для Desktop trace. Точный список расширяется вместе с кодом; при расхождении приоритет у call site в `work_agent.py` и `work_orchestrator.py`.

## Жизненный цикл действия

| `event_type` | Когда |
|--------------|--------|
| `action.started` | Начало `work.handle_user_prompt` с `action_id`, `user_turn_id`. |
| `action.failed` | Непойманное исключение в worker. |
| `assistant.final` | Успешное завершение или финальная ошибка в тексте. |
| `assistant.delta` / `assistant.thinking` | Стриминг токенов (привязка `message_id` к текущему ассистентскому сообщению). |
| `tool.call_started` / `tool.call_finished` | Инструменты SessionRunner. |
| `bash.*` | Запуск shell через bash runner. |

## Память и контекст

| `event_type` | Когда |
|--------------|--------|
| `memory.actor_unavailable` | Нет сокета, ошибка RPC, нет `agent_memory_result`, нет словаря `memory_slice`. |
| `memory.query.budget_exceeded` | Достигнут `max_memory_queries_per_user_turn`. |
| `memory.query.timeout` | Таймаут ожидания ответа брокера по памяти. |
| `memory.query_context.continuation` | Запланирован повторный запрос памяти в том же ходе. |
| `memory.actor_slice_used` / `memory.actor_slice_skipped` | Slice применён или пропущен (пустой injected text). |
| `context.memory_injected` | Компактный ledger-payload для UI/аналитики. |
| `context.restored` / `context.restore_failed` | D-level compact восстановлен или ошибка. |

## Режим инструментов и approvals

| `event_type` | Когда |
|--------------|--------|
| `session.perm_mode.need_user_choice` | Классификатор вернул `not_sure`; ждётся `work.perm_mode_choice`. |
| `session.perm_mode.settled` | Режим определён (классификатор или пользователь). |
| События `session.waiting_approval` | Из SessionRunner; оркестратор блокируется на `wait_for_approval` до `work.approval_resolve`. |

## Микро-оркестратор

| `event_type` | Когда |
|--------------|--------|
| `work.micro_plan.compact` | JSON плана для отображения в UI. |
| `work.verify.finished` | Итог pytest/flake8 gate. |
| `work.phase.started` / `work.phase.finished` | Границы фаз classify / micro_plan / execute / verify / repair. |

## Внешние сервисы

- **`memory.change_feedback`** отправляется как `service.request` к `AgentMemory:global`, не как `topic.publish` из work_agent (но попадает в общий протокол брокера на стороне получателя).

## Интеграция с Desktop

UI должен:

1. Подписаться на trace и показывать стрим по `assistant.delta`.
2. Обрабатывать `session.perm_mode.need_user_choice` → модалка → RPC `work.perm_mode_choice`.
3. Обрабатывать `session.waiting_approval` → UI approve → `work.approval_resolve`.
4. Опционально визуализировать `work.micro_plan.compact` и `work.verify.finished`.
