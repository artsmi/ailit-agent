# AgentMemory: целевой runtime flow

## Current reality

Сводка по отчётам `19` (без чтения product source в рамках роли `21`):

- Два транспорта: broker → subprocess `memory_agent`; CLI `ailit memory init` — **in-process** worker (`agent_memory_entrypoints_cli.md` F1–F4).
- Pipeline W14: первый раунд планера под `plan_traversal`; команды `AgentMemoryCommandName`: `plan_traversal`, `summarize_c`, `summarize_b`, `finish_decision` (`agent_memory_query_pipeline.md` F1).
- `RUNTIME_STATES` / `assert_runtime_state_transition` **существуют** в контракте, но pipeline в показанном пути **не assert-ит** переходы; шаги журналируются как `memory.runtime.step` со свободными строками (`agent_memory_query_pipeline.md` F4, F3).
- Рост PAG `_grow_pag_for_query` на основном LLM-пути **не** вызывается из `_run_w14_action_runtime`; есть в `_fallback_without_llm` (`agent_memory_query_pipeline.md` F7).
- KB на пути `memory.query_context` в worker **не** используется; KB участвует в init transaction (`pag_kb_memory_state_models.md` F4).

## Target behavior

### Нормативное решение (D3 из synthesis)

**Источник истины для продуктового поведения:** явная **целевая state machine** с именованными состояниями и допустимыми переходами. Событие журнала `memory.runtime.step` **обязано** содержать поля `state` и `next_state`, которые либо:

- совпадают с узлами целевого графа состояний, **либо**
- помечены как `legacy_journal_free_text` только во время migration window (по умолчанию **forbidden** для нового кода после выравнивания).

Таблица D-OBS-1 в `context/proto/runtime-event-contract.md` трактуется как **broker-facing subset** compact-событий AgentWork↔AgentMemory, **не** как полный whitelist всех `event_name` в `MemoryJournalStore` (`memory_journal_trace_observability.md` F11). Полный перечень internal journal имён — отдельный каталог в `failure-retry-observability.md`.

### Целевые состояния (высокий уровень)

1. **`intake`** — принят envelope, извлечены `query_id`, `user_turn_id`, `namespace`, `project_root`, caps; запрет на произвольные path из NL без нормализации (идея donor: scope не из NL alone, `claude_code_agent_memory_ownership.md`).
2. **`db_preflight`** — открытие/проверка PAG path, readyness SQLite; при фатальной ошибке БД → `blocked` только если невозможно продолжить **после** bounded recovery (обычно это инфраструктурный сбой; для отсутствия файла проекта — `partial` с reason).
3. **`slice_select`** — выбор стартового slice (cache/mechanical, или пустой graph).
4. **`planner_round`** — LLM round для envelope-команды планера (`plan_traversal` или целевой `propose_links` на отдельном раунде, см. `llm-commands.md`).
5. **`planner_repair`** — **внутренняя фаза** bounded repair (не отдельное имя `command` в envelope в текущем коде; синтез F-PL-2). Максимум **один** дополнительный LLM вызов repair после `W14CommandParseError`, с gate `_should_repair_w14_error`.
6. **`w14_action_materialize`** — материализация B/A, `contains`, индексация C, typed edges по правилам `memory-graph-links.md`.
7. **`summarize_phase`** — внутренние LLM вызовы `summarize_c` / `summarize_b` как подкоманды (не отдельный planner round), с лимитами и явной политикой ошибок (ошибка summary **не** переводит весь запрос в `blocked`, если остаётся полезный результат → `partial`). Ответы проходят `validate_or_canonicalize_w14_command_envelope_object` (как у планера, UC-01); при сохраняемом `W14CommandParseError` — не более **одного** repair-вызова с фазой compact `summarize_c_repair` / `summarize_b_repair` и разбором с `enforce_planner_envelope=False`. Журнал `memory.command.normalized` при фактической канонизации; compact `w14_summarize_{c|b}_parse_ok` после успешной валидации envelope+payload до записи в PAG.
8. **`link_apply`** — применение **только** runtime-validated link candidates (LLM не пишет в БД напрямую).
9. **`finish_assembly`** — `finish_decision`, сборка `agent_memory_result.v1`, grants (см. `external-protocol.md`), D digest при политике продукта.
10. **`result_emit`** — journal `memory.result.returned`, stdout/highlight topics, ответ initiator.

### Bounded partial / запрет циклов

- Повтор того же выбора файлов/нод без новых usable candidates **forbidden** без смены входа, курсора прогресса, caps или исправления ответа LLM (см. `failure-retry-observability.md` FR-no-progress).
- Неограниченный обход дерева, неограниченное создание рёбер, «успех» без полезного результата — **forbidden** (anti-pattern в draft).

### Статусы завершения (OR-002)

| Статус | Когда |
|--------|--------|
| `complete` | Достаточно evidence для subgoal; finish policy satisfied. |
| `partial` | Полезный результат частично; caps; missing file; invalid link rejections; summary failures с остаточным контекстом; planner parse fallback. |
| `blocked` | **Только** если недоступен LLM API **или** невозможно получить **валидный** LLM ответ для обязательной фазы после **bounded** repair/retry согласно `failure-retry-observability.md`. |

## Traceability

| Fact ID | Отчёт |
|---------|--------|
| F-CLI-1…3 | `current_state/agent_memory_entrypoints_cli.md` |
| F-PL-1…4, F10 | `current_state/agent_memory_query_pipeline.md` |
| F-PAG-1…4 | `current_state/pag_kb_memory_state_models.md` |
