# Внешний протокол AgentMemory: кто вызывает, какие данные и события (External protocol)

**Аннотация:** этот файл про **границу системы**: оболочка агента, CLI и клиенты брокера. Внутренний порядок шагов рантайма — в [`runtime-flow.md`](runtime-flow.md).

**SoT** (единый авторитетный источник для продолжения сценария) и другие сокращения — в [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-004 | Зафиксировать контракт инициаторов (оболочка агента, CLI, клиент брокера): поля запроса, `query_id`, `user_turn_id`, namespace, корень проекта, лимиты; схемоподобное описание JSON. |
| OR-010 | Внешние события: heartbeat, прогресс, выделенные узлы, кандидаты и обновления связей, partial/complete/blocked; компактные правила логов. |
| OR-011 | CLI `ailit memory init`: запрос по умолчанию, прогресс, логи узлов и связей, семантика кода выхода. |
| OR-012 | Согласовать с конвертом `agent_memory_result.v1` и полями, видимыми потребителю. |

## Текущая реализация

### Как устроен путь «оболочка агента → брокер → память»

Оболочка агента не вызывает модуль памяти напрямую в одном процессе. **Брокер** запускает отдельный процесс памяти и обменивается с ним **строками JSON** (формат JSON Lines): по одному JSON-объекту на строку.

Запрос к сервису памяти имеет вид `memory.query_context`. В теле задаётся версия схемы `agent_work_memory_query.v1` и обязательные поля версии v1. Дополнительно инициатор может передать `query_kind` и `level` как **подсказки** из произвольного словаря; парсер v1 их не валидирует строго.

**Жёсткие флаги payload (факт кода `AgentMemoryWorker.handle`):**

- Если `memory_init` строго **`true`**, поля `path` и `hint_path` в envelope **должны быть пустыми**; иначе ответ `ok: false`, `code: memory_init_path_forbidden` (узкий init только через `goal`).
- Поле **`requested_reads`** в клиентском payload при включённом флаге чистой замены W14 отклоняется целиком: `ok: false`, `code: legacy_contract_rejected` (см. `w14_clean_replacement` в коде).
- Для v1-запроса без явного `project_root` worker может подставить корень из **`broker_workspace`** конфига подпроцесса; если список **`workspace_projects`** в payload пуст, worker может синтезировать его из записей workspace-файла брокера (массив объектов с `namespace` и `project_root`).

Ответ содержит срез памяти, конверт `agent_memory_result`, поле `grants` и дублирование некоторых полей (`decision_summary`, `recommended_next_step`) на верхнем уровне и внутри `agent_memory_result`. **Единый авторитет для продолжения диалога** — объект `agent_memory_result`: при конфликте с дублями наверху приоритет у него.

**Отмена:** второй сервис в том же процессе — **`memory.cancel_query_context`** с тем же `query_id`, что у активного запроса; при успешной отмене pipeline прерывается, в ответе `memory.query_context` — ошибка `memory_query_cancelled`.

**Заметка для кода:** поле `grants` заполняется worker (в т.ч. `_grants_for_am_read_lines` при терминальном W14-finish), но **`ToolExecutor` в основном цикле сессии** (`session/loop.py`) создаётся без `MemoryGrantChecker`, то есть выданные гранты **не** автоматически сужают `read_file` / `read_symbol` — это по-прежнему **`implementation_backlog`** до явного подключения в AgentWork.

### CLI

- Команда init использует цель по умолчанию на уровне продукта (`MEMORY_INIT_CANONICAL_GOAL` в оркестраторе).
- Видимый итог и код выхода согласованы с OR-011 через единый модуль `tools/agent_core/runtime/memory_init_cli_outcome.py`: терминальный статус **`complete` \| `partial` \| `blocked`**; `complete` → exit **0**; `partial` / `blocked` без аварии → **1**; прерывание (SIGINT) → **130**; инфраструктурный сбой → **2**. Сводка на stderr строится с `exit_kind` из того же трёхзначного набора (`memory_init_summary.py`).

### Корреляция и логи

- В журнале строки связываются с запросом брокера через `request_id`; внутри payload шагов W14 фигурирует `query_id`.
- В stdout для трассировки графа: события вроде `pag.node.upsert`, `memory.w14.graph_highlight`; нормализованные имена для `compact.log` и дискриминанты внешнего конверта **`agent_memory.external_event.v1`** — SoT в `tools/agent_core/runtime/agent_memory_external_events.py` (golden map stdout→compact, см. [`failure-retry-observability.md`](failure-retry-observability.md)).

## Целевое поведение

### Инициаторы

| Инициатор | Транспорт | Обязательные корреляторы |
|-----------|-----------|-------------------------|
| Оболочка агента (AgentWork) | stdin/stdout брокера к подпроцессу памяти | `user_turn_id`, `query_id`, `namespace`, `project_root` |
| CLI `ailit memory init` | in-process worker | синтетический `query_id` на раунд оркестратора, `namespace` из определения репозитория, нормализованный `project_root` |
| Другой клиент брокера | как AgentWork | должен повторять контракт v1 |

### Схемоподобно: `agent_work_memory_query.v1` (фрагмент)

```json
{
  "service": "memory.query_context",
  "schema_version": "agent_work_memory_query.v1",
  "subgoal": "string, required, natural language memory-only goal",
  "user_turn_id": "string, required",
  "query_id": "string, required, unique per sub-goal round",
  "project_root": "string, required, absolute normalized",
  "namespace": "string, required",
  "expected_result_kind": "string, required, whitelist per parser",
  "known_paths": "array[string], required, may be empty",
  "known_node_ids": "array[string], required, may be empty",
  "stop_condition": { "max_rounds": "int", "allow_partial": "bool" },
  "query_kind": "string|omit — advisory from initiator, not validated by v1 parser",
  "level": "string|omit — advisory"
}
```

**Запрещено смешивать** полную пользовательскую задачу «сделай всё» без декомпозиции: AgentMemory решает только **подцель памяти** (memory subgoal), а не end-to-end задачу агента.

### Несколько запросов на один user turn

Инициатор **может** отправить серию `memory.query_context` с разными `query_id` для продолжения; действует лимит запросов на один `user_turn_id` (например конфигурация `memory.runtime.max_memory_queries_per_user_turn` с разумными границами).

### Приоритет дубликатов полей

**Норматив:** при конфликте верхнего уровня и `agent_memory_result` для continuation/decisions — **источник истины = `agent_memory_result`**; верхнеуровневые поля — зеркало для UX/наследия (по умолчанию должны совпадать; расхождение — дефект реализации).

### Внешние события (OR-010) — типы

Каждое событие: `schema_version: agent_memory.external_event.v1`, поля:

```json
{
  "schema_version": "agent_memory.external_event.v1",
  "event_type": "heartbeat|progress|highlighted_nodes|link_candidates|links_updated|nodes_updated|partial_result|complete_result|blocked_result",
  "query_id": "string, required",
  "timestamp": "string, required, RFC3339",
  "payload": "object, required",
  "truncated": "bool, default false",
  "units": "utf8_chars|node_count|edge_count, required for size-related fields"
}
```

**Долговечные vs эфемерные:** `heartbeat`, детальный `progress` — эфемерные; финальные `complete_result` / `blocked_result` / `partial_result` — долговечные на пути результата/журнала.

#### Кратко по обязательным полям payload

- **`heartbeat`:** `session_alive=true`.
- **`progress`:** `runtime_state` — компактная строка фазы (в реализации W14 часто операционные имена вроде `llm_await`, `w14_intermediate_slice`; целевой канон допускает выравнивание с машиной состояний из [`runtime-flow.md`](runtime-flow.md)); `message` компактно.
- **`highlighted_nodes`:** `node_ids: string[]` (ограниченное число), `reason` коротко.
- **`link_candidates`:** массив `agent_memory_link_candidate.v1` **до** валидации (опционально для CLI, обязательно для Desktop при включённой функции).
- **`links_updated`:** `{ "applied": [...], "rejected": [{ "link_id", "reason"}] }`.
- **`nodes_updated`:** `{ "upserted_node_ids": [], "kind": "B|C|D" }` с лимитами.
- **`partial_result` / `complete_result` / `blocked_result`:** ссылка на финальный `agent_memory_result.v1` или подмножество + hash; **запрещено** включать сырые промпты.

### CLI `ailit memory init` (OR-011) — цель и проверка

**Целевой UX:**

- Цель по умолчанию — константа уровня продукта; на момент канона сценарий init не подменяет её произвольным `goal` из CLI без отдельной политики продукта.
- Прогресс: stderr компактно + фазы оркестратора + тень журнала worker.
- Узлы и связи: логирование через `nodes_updated` / `links_updated` / stdout по политике лимитов.
- Итоги: видимые статусы **`complete` | `partial` | `blocked`** и согласованные коды выхода (`memory_init_cli_outcome.py`).

**Verification gap (ручной smoke):** полный ручной прогон `ailit memory init <repo>` в конкретном gate может быть не запрошен; автоматическое доказательство — pytest/flake8 из отчёта **11**, не заменяет операторский smoke для DoD.

### Команды проверки

- Ручной smoke (после реализации целевого UX): `ailit memory init <repo>` — ожидать финальный маркер `memory.result.returned` в тени журнала и компактный лог без сырых промптов.
- Автоматические тесты: перечень имён pytest в [`failure-retry-observability.md`](failure-retry-observability.md).
