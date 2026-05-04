# AgentMemory: LLM command protocol (runtime vs LLM)

## Current reality

- Реестр имён **envelope** команд: `plan_traversal`, `summarize_c`, `summarize_b`, `finish_decision` (`AgentMemoryCommandName`, `agent_memory_query_pipeline.md` F1).
- Первый планерский раунд использует system prompt **только** под `plan_traversal` (`agent_memory_query_pipeline.md` F1).
- Для `plan_traversal` payload действий whitelist: `list_children`, `get_b_summary`, `get_c_content`, `decompose_b_to_c`, `summarize_b`, `finish` (`agent_memory_query_pipeline.md` F2). Runtime **агрегирует пути** из actions с полем `path` без полного switch по `action` (`agent_memory_query_pipeline.md` F2).
- Repair: при `W14CommandParseError` — не более **одного** LLM repair; фаза журнала `planner_repair`; отдельного envelope имени `repair_invalid_response` **нет** (`agent_memory_query_pipeline.md` F6). Для **внутренних** ответов `summarize_c` / `summarize_b` — отдельный repair с compact-фазой `summarize_c_repair` / `summarize_b_repair`, разбор с `enforce_planner_envelope=False` и проверкой ожидаемого `command`.
- `_validate_command_payload` строго покрывает `plan_traversal` и `finish_decision`; для `summarize_*` как **верхнеуровневого** planner envelope валидация payload **ограничена** (`agent_memory_query_pipeline.md` G1).

## Target behavior

### Владение данными

**Runtime владеет:** доступом к БД, обходом, чтением файлов (по grants/policy), записью A/B/C/D, валидацией ids/paths/links, caps/retry, внешними событиями, финальным ответом.

**LLM владеет:** только JSON-решениями внутри разрешённых схем: куда идти дальше, какие ноды релевантны, candidates links, нужен ли summary, finish readiness, compact decision text.

### Два уровня «команд»

1. **Envelope command** — поле верхнего уровня W14 `command` ∈ { `plan_traversal`, `summarize_c`, `summarize_b`, `finish_decision`, **целевой** `propose_links` }.
2. **Planner actions** — только внутри `plan_traversal.payload.actions[]` с полем `action` из фиксированного whitelist (см. current reality).

**Норматив:** `summarize_c` / `summarize_b` как ответ **планера** на верхнем уровне — **forbidden** в target (избежать дыры валидации); эти режимы выполняются как **внутренние фазы** runtime после materialize/index (`agent_memory_query_pipeline.md` F8, G1).

### Целевая команда `propose_links` (расширение OR-006)

**Назначение:** отдельный LLM round, который возвращает **только** массив `link_candidate` объектов (`memory-graph-links.md`), без записи в БД.

**Вход (от runtime):** компактный контекст: выбранные `node_id`, краткие summary/hashes, ограниченные пути, caps.

**Выход:** `schema_version=agent_memory_link_batch.v1`, массив candidates.

**Forbidden:** произвольные filesystem/tool поля, shell execution, абсолютные пути, сырой файл целиком.

### `repair_invalid_response` как режим, не как публичное имя envelope

**Норматив для документации:** фаза **`planner_repair`**; machine поле `command` в ответе LLM **не** использует значение `repair_invalid_response` (согласовано с фактом кода, `agent_memory_query_pipeline.md` F6). Внешние клиенты видят только события/trace с `action_kind=planner_repair` / аналог.

### Схема: W14 envelope (упрощённый каркас)

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command_id": "string, required, non-empty",
  "command": "plan_traversal|finish_decision|propose_links",
  "payload": "object, required, shape depends on command",
  "status": "ok|partial|refused|in_progress",
  "legacy": "forbidden unless explicitly allowed by migration policy"
}
```

**Forbidden поля в LLM-facing JSON:** raw prompts, chain-of-thought, secrets, полные дампы файлов вне выбранных line windows.

### Пример happy path / invalid+recovery (смысл)

- **Happy:** LLM возвращает валидный `plan_traversal` JSON → runtime materialize → internal summarize → finish.
- **Invalid+recovery:** невалидный JSON при классе ошибки, допускающем repair → один repair call → повторный parse; при повторном провале → `partial` с `reason=w14_parse_failed` (детали в `failure-retry-observability.md`).

## Traceability

| ID | Источник |
|----|----------|
| OR-006 | `original_user_request.md` §3 |
| F-PL-1…2 | `current_state/agent_memory_query_pipeline.md` |
| D3 repair | `synthesis.md` Requirements for 21 |
