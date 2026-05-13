# Граф памяти: типы связей и кандидаты от LLM (Memory graph links)

**Аннотация:** здесь зафиксировано, какие **рёбра** допустимы между узлами A/B/C/D, как передаётся **уверенность** и **доказательство**, и почему только рантайм пишет в базу после проверки.

Сокращения уровней узлов и термин **LLM** — по смыслу; **`implementation_backlog`** — в [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-003 | Обход дерева и связи графа уровней A/B/C/D; связи с типом и доказательством; рантайм валидирует, модель только предлагает кандидатов. |
| OR-007 | Явный набор типов связей из постановки пользователя с полями confidence и источника (кто или что породило связь). |

## Текущая реализация

- Хранилище PAG: SQLite, рёбра в таблице с полями класса и типа; распространённый паттерн — `contains` и провенанс `derived_from` для D→B/C.
- Промежуточный **`plan_traversal`** в W14: после выбора путей рантайм **материализует** узлы B и иерархию `contains` в `_run_w14_action_runtime` (`agent_memory_query_pipeline.py`), затем индексатор и сводки; это не отдельный «тихий» side-channel.
- Wire-команда **`propose_links`:** кандидаты `agent_memory_link_candidate.v1` проходят **`AgentMemoryLinkCandidateValidator`** (`ailit/agent_memory/agent_memory_link_candidate_validator.py`); применимые рёбра пишутся через **`PagGraphWriteService`** (`pag_graph_write_service.py`), а не напрямую из ответа LLM.
- **Риск:** два шаблона идентификатора узла уровня **A** (в материализации W14 и в индексаторе) — возможный **дрейф** идентификаторов; целевое поведение — один канонический шаблон на пару `(namespace, идентичность репозитория)` (**`implementation_backlog`** с миграцией).

## Целевое поведение

### Принцип разделения ролей

- **LLM** возвращает только **кандидатов** в закрытом JSON (схема ниже).
- **Рантайм** проверяет: существование `source_node_id` / `target_node_id`, типы уровней A/B/C/D, доказательства, запрет на `..` и абсолютные пути в полях путей, политику confidence, лимиты числа рёбер за раунд.
- Запись в SQLite — **только** после успешной проверки или постановки в очередь advisory по политике.

### Канонические типы связей (OR-007)

Допустимые значения `link_type` (целевой набор из постановки):

| `link_type` | Обычный source→target | Примечание |
|-------------|------------------------|------------|
| `contains` | A→B, B→B, B→C (иерархия) | Базовый тип в текущем PAG. |
| `imports` | B→B, B→external, B→C (импорт символа) | Нужно доказательство импорта. |
| `defines` | B→C | Файл/модуль определяет семантический фрагмент. |
| `calls` | C→C | **Только** при статическом или явном symbol-доказательстве (требование постановки: не выдумывать вызовы). |
| `references` | C/D/B между собой для доков/конфигов/тестов | Текстовое или структурное доказательство. |
| `summarizes` | D→B/C | D фиксирует вывод по доказательству. |
| `supports_answer` | B/C→D или к финальному результату | Доказательство для ответа. |
| `supersedes` | D→D | Только если рантайм явно решил обновить digest/память запроса. |

**Базовая линия кода:** тип `derived_from` (провенанс) остаётся поддерживаемым отдельно от таблицы выше до миграции схемы; если строки в БД не совпадают 1:1 с каноном — **`implementation_backlog`**.

### Правила confidence и источника

Допустимые `created_by` / `source_kind` (объединённая семантика):

- `static_analysis` — парсер/индексатор; **может** давать жёсткие факты для `imports`/`defines`/`calls` при наличии доказательства.
- `runtime_observed` — индексация, материализация, детерминированные правила.
- `llm_inferred` — только кандидаты → проверка; при `confidence=low` по умолчанию **запрещено** повышать до жёсткого факта без политики или человека (advisory pending или отклонение).

### Схемоподобно: кандидат связи (элемент массива внутри `propose_links.payload`)

Каждый кандидат приходит **внутри** конверта W14 с `command=propose_links` (см. [`llm-commands.md`](llm-commands.md), D-PROPOSE-LINKS-1), а не как корневой массив без envelope.

```json
{
  "schema_version": "agent_memory_link_candidate.v1",
  "link_id": "string, non-empty, unique within response batch",
  "link_type": "contains|imports|defines|calls|references|summarizes|supports_answer|supersedes",
  "source_node_id": "string, required",
  "target_node_id": "string, required unless link_type semantics allow external target",
  "target_external_ref": "string|null, default null, required null for internal targets",
  "source_path": "string, repo-relative, required",
  "target_path": "string|null, default null",
  "evidence": {
    "kind": "line_range|symbol_name|heading_text|import_statement|llm_summary",
    "value": "string, required, bounded by caps.policy.link_evidence_chars",
    "start_line": "int|null, default null",
    "end_line": "int|null, default null"
  },
  "confidence": "high|medium|low",
  "created_by": "static_analysis|llm_inferred|runtime_observed",
  "reason": "string, required, human-short, bounded"
}
```

**Запрещено в кандидате:** абсолютные пути, сегменты `..`, произвольные URL без политики whitelist, сырые дампы файлов, секреты.

### Матрица проверки (кратко)

| Нарушение | Действие рантайма |
|-----------|-------------------|
| Неизвестный `link_type` | отклонить кандидата с компактной причиной; остальные кандидаты батча обрабатываются по порядку, пока не исчерпаны лимиты S3 |
| Несуществующий id узла | отклонить; структурированное исправление к LLM **только** если не исчерпан бюджет repair ([`failure-retry-observability.md`](failure-retry-observability.md)) |
| `calls` без symbol-доказательства | отклонить |
| low confidence при политике | см. F-L3: для `llm_inferred` + `low` — **не** отклонение по этому признаку, а pending-claim |

### Двухуровневая валидация S1 и S3 (F-L1)

**Слой для человека:** сначала рантайм отсекает заведомо неверную форму и размер полезной нагрузки `propose_links` без полного разбора семантики графа; затем отдельный валидатор проверяет каждого кандидата как ребро PAG. Это снимает путаницу «одна функция всё решила».

**Технический контракт**

| Уровень | Где в коде (SoT) | Что проверяется |
|---------|------------------|-----------------|
| **S1** | грубая форма `propose_links` в контракте рантайма (`_validate_propose_links_payload` в модуле контракта AgentMemory) | допустимая форма `payload`, извлечение кандидатов в wire-список, лимит **128** на извлечение (см. D-LIMITS-1) |
| **S3** | `AgentMemoryLinkCandidateValidator.process_batch` | полная семантика кандидата: узлы, типы уровней, доказательства, лимит **64** кандидатов на S3-раунд; **единственный** production call site полной проверки в pipeline |

### Лимиты wire и S3-батча (D-LIMITS-1, F-L2)

**Слой для человека:** лимиты **разные**: сначала модель может прислать до 128 объектов в полезной нагрузке, из которых рантайм строит wire-список; затем на один проход S3 валидатора допускается не более 64 кандидатов. Превышение второго лимита даёт наблюдаемую причину **`round_limit_exceeded`**, а не «тихое» обрезание без следа.

**Технический контракт**

- **128 (wire extract):** верхняя граница числа кандидатов, извлекаемых из ответа LLM в структуру wire (`_wire_link_candidates_from_propose_payload`). Лишнее за пределами 128 **не** попадает в S3.
- **64 (S3 batch):** верхняя граница кандидатов, переданных в `process_batch` за один вызов; остаток обрабатывается политикой «round limit».
- **Журнал `link_candidates` (pre-validation):** внешнее событие до S3 может быть **усечено** по политике компактности; флаг/счётчики усечения должны быть согласованы с разделом наблюдаемости в [`failure-retry-observability.md`](failure-retry-observability.md) (truncation, не полный дамп batch).

### Политика pending и внешних ссылок (F-L3)

**Слой для человека:** низкая уверенность у вывода модели **не** означает автоматический discard: для связей, помеченных как выведенные LLM, низкий confidence ведёт в очередь **pending**, а не в жёсткое отклонение. Импорт с внешним ref без URL-whitelist в валидаторе тоже уходит в pending, а не в «немой» accept.

**Технический контракт**

- При **`confidence=low`** и **`created_by=llm_inferred`**: разрешённая запись — **`insert_pending_link_claim`**; запрещено трактовать это сочетание как безусловный reject только из-за `low`.
- Для **`link_type=imports`** при **непустом** `target_external_ref`: исход к **pending** (нет проверки содержимого ref по URL-whitelist в текущем валидаторе).
- **Цель / backlog:** если продукту нужен строгий URL-whitelist для внешних ref, это **`implementation_backlog`** поверх текущего факта кода.

### Отклонения и статус раунда (F-L4)

**Слой для человека:** отклонённый кандидат фиксируется в журнале и в полезной нагрузке события об обновлении связей; если в батче был хотя бы один reject, верхний статус результата памяти для этого раунда — **`partial`**, а не «тихий» `complete`.

**Технический контракт**

- Журнал: событие вида **`memory.link_rejected`** (компактная причина, без сырого ответа модели).
- Внешнее событие **`links_updated`**: в `payload` присутствует структура **`rejected`** с перечнем отклонённых элементов (bounded).
- **`runtime_partial_reasons`:** при любом reject в батче включается строка **`link_rejected`**.
- **`am_v1_status`:** **`partial`**, если reject произошёл в батче (согласовано с матрицей OR-013 в [`failure-retry-observability.md`](failure-retry-observability.md)).

### Цепочка pipeline → валидатор → запись (F-L5)

**Слой для человека:** ответ модели не пишет SQLite напрямую: pipeline извлекает кандидатов, S3 валидирует, применимые рёбра попадают в сервис записи графа. Текст канона здесь и в [`llm-commands.md`](llm-commands.md) описывает одну и ту же цепочку.

**Технический контракт**

1. Разбор **полного W14 envelope** с `command=propose_links` (см. D-PROPOSE-LINKS-1 в `llm-commands.md`).
2. **S1** — извлечение и грубая проверка, обрезка по 128.
3. Эмиссия **pre-validation** внешнего события `link_candidates` (с усечением по политике).
4. **S3** — `process_batch` до 64 кандидатов, решения accept / pending / reject.
5. Запись применимых рёбер через **`PagGraphWriteService`**, не прямым SQL из ответа LLM.
6. Эмиссия **`links_updated`** и сборка **`agent_memory_result.v1`** с учётом F-L4.

### Единый идентификатор узла A (цель)

**Норматив:** один канонический шаблон id узла **A** на пару `(namespace, идентичность репозитория)` для всех точек входа; расхождение индексатора и W14 — **`implementation_backlog`** с миграцией.

## How start-feature / start-fix must use this

- **`02_analyst`:** для связей PAG, типов `link_type`, confidence, S1/S3 и цепочки F-L5 брать контракты из этого файла; не смешивать с протоколом stdin/stdout брокера из `external-protocol.md`.
- **`06_planner`:** нарезка работ по валидатору, лимитам 128/64, `PagGraphWriteService` и pending/reject — с явной трассировкой к OR-003 / OR-007 и к D-LIMITS-1 в связке с `llm-commands.md`.
- **`11_test_runner`:** при правках графа или `propose_links` проверять тесты на кандидатов, внешние события `link_candidates` / `links_updated` и сборку результата (имена — в [`failure-retry-observability.md`](failure-retry-observability.md) и существующих `test_g14*`).
- **`13_tech_writer`:** при смене схемы кандидата, типов рёбер или политики evidence обновить этот файл и согласовать формулировку с D-PROPOSE-LINKS-1 в `llm-commands.md` без расхождения «массив vs envelope».
