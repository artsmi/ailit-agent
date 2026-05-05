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

Ответ содержит срез памяти, конверт `agent_memory_result`, поле `grants` и дублирование некоторых полей (`decision_summary`, `recommended_next_step`) на верхнем уровне и внутри `agent_memory_result`. **Единый авторитет для продолжения диалога** — объект `agent_memory_result`: при конфликте с дублями наверху приоритет у него.

**Заметка для кода:** поле `grants` присутствует в ответе, но в одном из показанных путей оболочка агента **не** подключает его к проверке прав чтения файлов — это намеренно помечено как **`implementation_backlog`** до выравнивания.

### CLI

- Команда init использует цель по умолчанию на уровне продукта (константа вроде `MEMORY_INIT_CANONICAL_GOAL`).
- Итоговая сводка для пользователя использует `exit_kind` из множества `complete`, `partial`, `aborted`; отдельного видимого пользователю `blocked` в этом пути **пока нет** — расхождение с целевым UX отмечено как **`implementation_backlog`**.

### Корреляция и логи

- В журнале строки связываются с запросом брокера через `request_id`; внутри payload шагов W14 фигурирует `query_id`.
- В stdout для трассировки графа: события вроде `pag.node.upsert`, `memory.w14.graph_highlight`; компактный лог на диске может нормализовать имена событий.

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
- **`progress`:** `runtime_state` (строка из целевой машины состояний), `message` компактно.
- **`highlighted_nodes`:** `node_ids: string[]` (ограниченное число), `reason` коротко.
- **`link_candidates`:** массив `agent_memory_link_candidate.v1` **до** валидации (опционально для CLI, обязательно для Desktop при включённой функции).
- **`links_updated`:** `{ "applied": [...], "rejected": [{ "link_id", "reason"}] }`.
- **`nodes_updated`:** `{ "upserted_node_ids": [], "kind": "B|C|D" }` с лимитами.
- **`partial_result` / `complete_result` / `blocked_result`:** ссылка на финальный `agent_memory_result.v1` или подмножество + hash; **запрещено** включать сырые промпты.

### CLI `ailit memory init` (OR-011) — цель и расхождения

**Целевой UX:**

- Цель по умолчанию — константа уровня продукта; позже пользователь **может** расширить сценарий; на момент канона — только константа.
- Прогресс: stderr компактно + фазы оркестратора + тень журнала worker.
- Узлы и связи: логирование через `nodes_updated` / `links_updated` / stdout по политике лимитов.
- Итоги: видимые статусы **`complete` | `partial` | `blocked`** и согласованные коды выхода.

**Текущее расхождение:** сводка CLI использует `aborted` вместо целевого видимого `blocked` — **`implementation_backlog`**.

### Команды проверки

- Ручной smoke (после реализации целевого UX): `ailit memory init <repo>` — ожидать финальный маркер `memory.result.returned` в тени журнала и компактный лог без сырых промптов.
- Автоматические тесты: перечень имён pytest в [`failure-retry-observability.md`](failure-retry-observability.md).
