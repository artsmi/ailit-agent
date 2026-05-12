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
- Wire-команда **`propose_links`:** кандидаты `agent_memory_link_candidate.v1` проходят **`AgentMemoryLinkCandidateValidator`** (`tools/agent_core/runtime/agent_memory_link_candidate_validator.py`); применимые рёбра пишутся через **`PagGraphWriteService`** (`pag_graph_write_service.py`), а не напрямую из ответа LLM.
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

### Схемоподобно: кандидат связи (wire от LLM)

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
| Неизвестный `link_type` | отклонить кандидата, компактная причина, продолжить если возможно |
| Несуществующий id узла | отклонить; структурированное исправление к LLM **только** если не исчерпан бюджет repair ([`failure-retry-observability.md`](failure-retry-observability.md)) |
| `calls` без symbol-доказательства | отклонить |
| low confidence при политике | pending edge или отклонение |

### Единый идентификатор узла A (цель)

**Норматив:** один канонический шаблон id узла **A** на пару `(namespace, идентичность репозитория)` для всех точек входа; расхождение индексатора и W14 — **`implementation_backlog`** с миграцией.
