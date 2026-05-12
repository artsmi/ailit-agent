# Протокол команд LLM для AgentMemory (LLM command protocol)

**Аннотация:** здесь зафиксировано, что именно модель может вернуть в JSON, что запрещено, и чем владеет рантайм. Сначала читайте словесное описание ролей; схемы JSON — внизу разделов.

Термины: **конверт команды** (envelope), **действия планера**, **W14**, **CoT** — см. [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-006 | Описать протокол команд от рантайма к LLM: какие команды бывают, что на входе и выходе, что запрещено и обязательно; привести примеры восстановления после невалидного ответа; явно разделить ответственность рантайма и модели. |

## Текущая реализация

- Имена команд **конверта** (`AgentMemoryCommandName` в `agent_memory_runtime_contract.py`): `plan_traversal`, `summarize_c`, `summarize_b`, `finish_decision`, **`propose_links`** (wire batch `agent_memory_link_candidate.v1`, см. [`memory-graph-links.md`](memory-graph-links.md) и `AgentMemoryQueryPipeline`).
- Продуктовый путь `memory.query_context` реализован **только** через `AgentMemoryQueryPipeline` (W14). Цикл **G13** в виде `AgentMemoryLLMLoop` (`memory_llm.py`) в этот путь **не** входит.
- Первый раунд планера использует системный промпт **только** под команду `plan_traversal`.
- Для `plan_traversal` список допустимых **действий** в payload ограничен: например `list_children`, `get_b_summary`, `get_c_content`, `decompose_b_to_c`, `summarize_b`, `finish`. Рантайм собирает пути из действий, где есть поле `path`, без полного перечисления всех видов действий вручную.
- **Исправление ответа (repair):** при ошибке разбора `W14CommandParseError` допускается не более **одного** дополнительного вызова LLM для исправления формата; в журнале это фаза `planner_repair`. Отдельного имени команды конверта `repair_invalid_response` в ответе модели **нет** — это режим работы рантайма, а не публичное имя команды.
- Для внутренних ответов `summarize_c` / `summarize_b` — отдельный repair с фазами `summarize_c_repair` / `summarize_b_repair`, разбор с ослабленной проверкой конверта планера и проверкой ожидаемой команды.
- Валидация payload жёстко покрывает `plan_traversal` и `finish_decision`; для `summarize_*` как **верхнеуровневого** конверта планера проверка ограничена (источник риска рассогласования с целевым каноном).

## Целевое поведение

### Владение данными

**Рантайм владеет:** доступом к БД, обходом, чтением файлов (по grants и политике), записью уровней A/B/C/D, валидацией идентификаторов, путей и связей, лимитами и повторами, внешними событиями, финальным ответом потребителю.

**LLM владеет:** только JSON-решениями внутри разрешённых схем: куда идти дальше, какие узлы релевантны, кандидаты связей, нужна ли сводка, готовность к завершению, краткий текст решения.

### Два уровня «команд»

1. **Команда-конверт** — поле верхнего уровня `command` ∈ { `plan_traversal`, `finish_decision`, целевой **`propose_links`** } (и внутренние фазы, не являющиеся отдельным публичным именем repair-конверта).
2. **Действия планера** — только внутри `plan_traversal.payload.actions[]` с полем `action` из фиксированного whitelist.

**Норматив:** ответы `summarize_c` / `summarize_b` как **верхнеуровневый** конверт планера в целевом поведении **запрещены** — эти режимы выполняются как **внутренние фазы** рантайма после материализации и индексации, чтобы не оставлять дыр в валидации конверта.

### Команда `propose_links` (расширение OR-006, D-PROPOSE-LINKS-1)

**Назначение:** раунд LLM, в котором модель предлагает кандидатов связей для последующей проверки S1/S3 и записи через графовый сервис (см. F-L1, F-L5 в [`memory-graph-links.md`](memory-graph-links.md)). Прямая запись в SQLite из ответа модели **запрещена**.

**Вход (от рантайма):** компактный контекст: выбранные `node_id`, краткие сводки или хэши, ограниченные пути, лимиты (в т.ч. **128** wire / **64** S3 — D-LIMITS-1).

**Выход (норматив, D-PROPOSE-LINKS-1):** **не** автономный документ «только `agent_memory_link_batch.v1`». Ожидается **полный конверт W14** `agent_memory_command_output.v1` с полями верхнего уровня как у остальных команд планера, в частности:

- **`command`:** литерал **`propose_links`**.
- **`payload`:** объект, из которого рантайм извлекает кандидатов по одному из поддерживаемых ключей:
  - **`candidates`:** массив объектов схемы `agent_memory_link_candidate.v1`, **или**
  - **`link_batch`:** объект с полем **`candidates`** — тот же массив (эквивалентная форма для совместимости).

Иные корневые формы (например JSON, где корень — только массив кандидатов без `command` / `schema_version` конверта), считаются **невалидными** для production-пути: разбор и repair следуют общим правилам W14 в [`failure-retry-observability.md`](failure-retry-observability.md).

**Do not implement this as:** описывать успешный ответ `propose_links` как автономный **`agent_memory_link_batch.v1`** без оболочки **`agent_memory_command_output.v1`** — это противоречит D-PROPOSE-LINKS-1 и разбору в pipeline.

**Запрещено:** произвольные поля доступа к файловой системе и инструментам, выполнение shell, абсолютные пути, сырой файл целиком.

### Пример: каркас ответа `propose_links` (D-PROPOSE-LINKS-1)

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command_id": "string, required, non-empty",
  "command": "propose_links",
  "payload": {
    "candidates": [
      {
        "schema_version": "agent_memory_link_candidate.v1",
        "link_id": "example-1",
        "link_type": "references",
        "source_node_id": "…",
        "target_node_id": "…",
        "target_external_ref": null,
        "source_path": "src/a.py",
        "target_path": "src/b.py",
        "evidence": { "kind": "line_range", "value": "…", "start_line": 1, "end_line": 2 },
        "confidence": "medium",
        "created_by": "llm_inferred",
        "reason": "short human reason"
      }
    ]
  },
  "status": "ok",
  "legacy": "forbidden unless explicitly allowed by migration policy"
}
```

Эквивалентно поле **`payload.link_batch.candidates`** может заменить **`payload.candidates`** при том же конверте.

### Режим исправления невалидного ответа

**Норматив для документации:** фаза **`planner_repair`**; машинное поле `command` в ответе LLM **не** принимает значение `repair_invalid_response`. Внешние клиенты видят события или trace с видом действия вроде `planner_repair`.

### Схема: каркас конверта W14 (упрощённо)

```json
{
  "schema_version": "agent_memory_command_output.v1",
  "command_id": "string, required, non-empty",
  "command": "plan_traversal|finish_decision|propose_links",
  "payload": "object, required, shape depends on command",
  "status": "ok|partial|refuse",
  "legacy": "forbidden unless explicitly allowed by migration policy"
}
```

**Норматив по полю `status`:** допустимый whitelist top-level для W14 envelope — **`ok` \| `partial` \| `refuse`**; значение вроде **`in_progress`** из ответа LLM **не** является разрешённым смыслом top-level статуса конверта. Для **`plan_traversal`** прогресс раунда читается из **`payload.is_final`** и содержимого **`payload.actions`**, а не из отдельного «статуса работы» на корне JSON. Каноникализация легаси-строк выполняется в `validate_or_canonicalize_w14_command_envelope_object`.

**Запрещённые поля в JSON, предназначенном для LLM:** сырые промпты, chain-of-thought, секреты, полные дампы файлов вне выбранных окон строк.

### Пример смысла: успех и невалидный ответ

- **Успех:** модель возвращает валидный JSON `plan_traversal` → рантайм материализует данные → внутренние фазы сводки → завершение.
- **Невалидный ответ и восстановление:** при классе ошибки, допускающем repair, — один вызов исправления → повторный разбор; при повторном провале — `partial` с причиной вроде `w14_parse_failed` (подробности в [`failure-retry-observability.md`](failure-retry-observability.md)).

## How start-feature / start-fix must use this

- **`02_analyst`:** для любой задачи с участием LLM в памяти использовать этот файл как SoT по **именам команд конверта**, whitelist `status`, запрету top-level `summarize_*` как публичного ответа планера и по правилу D-PROPOSE-LINKS-1 для `propose_links`.
- **`06_planner`:** декомпозировать изменения по шагам Target flow из `runtime-flow.md`, но **контракт JSON** для ответа модели — отсюда; не планировать отдельный «массив кандидатов без envelope» как допустимый production-wire.
- **`11_test_runner`:** регрессии W14 и разбор конверта — по путям и именам из [`failure-retry-observability.md`](failure-retry-observability.md) и существующим `test_g14*`; при смене схемы envelope добавить или обновить проверки согласно плану, а не только по тексту примеров JSON здесь.
- **`13_tech_writer`:** при смене `AgentMemoryCommandName`, repair-политики или полей envelope обновить этот файл и перекрёстные ссылки в `prompts.md` / `memory-graph-links.md` в том же изменении канона.
