# `memory.query_context` для CLI `ailit memory init` (UC-03 / UC-04)

Назначение: зафиксировать контракт **init-вызова** сервиса `memory.query_context` и наблюдаемость (journal + compact), без описания нового бинарного entrypoint. Команда CLI остаётся `ailit memory init` → оркестратор → тот же `AgentMemoryWorker.handle`, что и для desktop/broker.

## Payload init (`memory_init: true`)

Источник правды по полям и отказам: `tools/agent_core/runtime/subprocess_agents/memory_agent.py` (ветка `memory.query_context`), оркестратор — `tools/agent_core/runtime/memory_init_orchestrator.py`, выбор файлов при init — `memory_init` в `tools/agent_core/runtime/agent_memory_query_pipeline.py` (`run` / `_select_b_paths_for_w14`).

| Поле | Правило |
|------|---------|
| `service` | литерал `memory.query_context` (как у любого запроса к AM). |
| `memory_init` | **строго** `true` (bool): init-режим включается только при `payload["memory_init"] is True`. |
| `goal` | Обязательная текстовая постановка; оркестратор init подставляет каноническую цель `MEMORY_INIT_CANONICAL_GOAL` (английский текст, без driver-path). Узкий init по путям **запрещён**: смысл только через `goal`. |
| `project_root` | Абсолютный корень проекта (строка); валидация доступности — до вызова worker в оркестраторе (`normalize_memory_init_root`). |
| `workspace_projects` | Список объектов с метаданными workspace (оркестратор передаёт минимум `project_id` / `namespace` для init-сессии). |
| `path`, `hint_path` | При `memory_init: true` **оба** должны быть пустыми (после `strip`). Иначе ответ `ok: false`, код `memory_init_path_forbidden`, сообщение о запрете path/hint_path для init. Для **не-init** запросов `path` / `hint_path` — подсказки к явным путям (`explicit_paths`), не заменяют текстовый `goal`. |

Явное правило: **текстовая постановка обязательна**; поля `path` / `hint_path` для init не используются и не допускаются с непустым значением.

## W14: envelope `status` и прогресс `plan_traversal` (C1, C2)

Нормативно для ответа планера в форме `agent_memory_command_output.v1` на пути `memory.query_context`, когда worker выполняет W14 (init использует тот же `handle` / pipeline — см. вводную выше).

| ID | Правило |
|----|---------|
| **C1** | Поле верхнего уровня **`status`** в envelope — только смысл **итога команды для рантайма** (валидность / допустимость / отказ): литералы **`ok`**, **`partial`**, **`refuse`**. Это **не** жизненный цикл шага плана и **не** маркер «ещё в работе». |
| **C2** | Для `command == "plan_traversal"` прогресс обхода плана выражается **`payload.is_final`**, **`payload.actions`** и остальными полями payload по схеме валидации в коде — **не** значением `in_progress` на верхнем уровне envelope. |
| Запрет | **`in_progress`** и прочие lifecycle-метки **запрещены** как top-level **`status`** W14 envelope; узкие случаи механической канонизации описаны в реализации (см. ниже), а не через расширение whitelist статусов. |

Реализация (SoT по разбору и каноникализации, без пересказа `plan/14-…`):

- текст планера и явный whitelist статусов: константа **`W14_PLAN_TRAVERSAL_SYSTEM`** в `tools/agent_core/runtime/agent_memory_query_pipeline.py`;
- парсинг envelope, whitelist top-level **`status`**, проверка **`payload.actions`** / **`payload.is_final`**: `validate_or_canonicalize_w14_command_envelope_object`, `validate_w14_command_envelope_object`, `_validate_plan_traversal_payload`, набор **`_W14_CANON_STATUSES`** в `tools/agent_core/runtime/agent_memory_runtime_contract.py`.

**Как читать ответ:** верхний **`status`** — итог команды по контракту; «ещё не финальный план» и следующие шаги — из **`payload`** (`is_final`, `actions`), а не из недопустимого top-level статуса.

## VERIFY по journal

Функция `verify_memory_init_journal_complete_marker` в `memory_init_orchestrator.py` (bounded tail read JSONL):

- ищет по журналу последнюю по `created_at` запись с `event_name == "memory.result.returned"` и совпадением `chat_id`;
- требует `payload` — объект и `payload.status == "complete"`.

Событие **`memory.result.returned`** пишется из `memory_agent.py` (`log_memory_w14_result_returned`): компактный payload (`query_id`, `status`, `result_kind_counts`, `results_total`), без сырых `results[].summary`. Для **статуса `complete`** при `session_log_mode == "cli_init"` дополнительно эмитится grep-маркер в compact sink (`CompactObservabilitySink.emit_memory_result_complete_marker` — см. `compact_observability_sink.py`).

## Логи: CLI init vs desktop

- **Desktop / обычный broker:** `MemoryAgentConfig.session_log_mode` по умолчанию `"desktop"` — плоский audit/changelog без ветки `cli_init` compact sink для memory init.
- **CLI `memory init`:** оркестратор задаёт `session_log_mode="cli_init"`, каталог сессии через `create_unique_cli_session_dir` (`…/chat_logs/ailit-cli-<suffix>/`, см. `agent_memory_chat_log.py`): внутри **legacy** и **compact** логи; compact используется для D4/UI-trace и финального блока `emit_memory_init_user_summary` (`memory_init_summary.py` → stderr).

## См. также

- Continuation / `agent_memory_result` / broker — [`broker-memory-work-inject.md`](broker-memory-work-inject.md).
- Whitelist compact-событий — [`runtime-event-contract.md`](runtime-event-contract.md).
