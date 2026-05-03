# AgentMemory: memory graph links (typed, evidence-backed)

## Current reality

- PAG: `SqlitePagStore`, рёбра `pag_edges` с `edge_class` / `edge_type`; известный паттерн: containment `contains`, provenance `derived_from` для D→B/C (`pag_kb_memory_state_models.md` F6, F9).
- Очередь кандидатов: `pag_pending_edges` / `PagPendingLinkClaim` (`pag_kb_memory_state_models.md` F6).
- Риск: два шаблона **A** `node_id` (`A:{namespace}` в W14 materialize vs `PagIndexer._a_node_id` с repo_uri/branch) — **дрейф** (`pag_kb_memory_state_models.md` F5, G1).

## Target behavior

### Принцип разделения ролей

- **LLM** возвращает только **candidates** в закрытом JSON (см. схему ниже).
- **Runtime** валидирует: существование `source_node_id` / `target_node_id`, типы уровней A/B/C/D, evidence, запрет на `..` и absolute paths в полях путей, политику confidence, лимиты числа рёбер за раунд.
- Запись в SQLite — **только** после успешной валидации или постановки в `pag_pending_edges` как advisory по политике.

### Канонические типы связей (OR-007)

Допустимые значения `link_type` (целевой набор из постановки):

| `link_type` | Обычный source→target | Примечание |
|-------------|------------------------|------------|
| `contains` | A→B, B→B, B→C (иерархия) | Baseline в текущем PAG. |
| `imports` | B→B, B→external, B→C (symbol import) | Требуется evidence импорта. |
| `defines` | B→C | Файл/модуль определяет semantic chunk. |
| `calls` | C→C | **Только** при symbol/static evidence (`original_user_request.md`). |
| `references` | C/D/B между собой для доков/конфигов/тестов | Текстовый/структурный evidence. |
| `summarizes` | D→B/C | D фиксирует вывод по evidence. |
| `supports_answer` | B/C→D или к финальному результату | Evidence для ответа. |
| `supersedes` | D→D | Только если runtime явно решил обновить digest/query memory. |

**Baseline текущего кода:** `derived_from` (provenance) остаётся поддерживаемым как **отдельный** `edge_type` до миграции схемы; target-doc требует маппинга legacy→канон в `implementation_backlog`, если строки в БД не совпадают 1:1 с таблицей выше.

### Confidence / source (required rules)

Допустимые `created_by` / `source_kind` (объединённая семантика):

- `static_analysis` — парсер/индексатор; **может** давать hard facts для `imports`/`defines`/`calls` при наличии evidence.
- `runtime_observed` — индексация, материализация, детерминированные правила.
- `llm_inferred` — только candidates → validation; при `confidence=low` по умолчанию **forbidden** promote в hard fact без human/policy gate (advisory pending или reject).

### Schema-like: link candidate (wire from LLM)

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

**Forbidden в candidate:** absolute paths, `..` segments, произвольные URL без whitelist policy, raw file dumps, секреты.

### Validation matrix (кратко)

| Нарушение | Действие runtime |
|-----------|------------------|
| Неизвестный `link_type` | reject candidate, compact reason, continue if possible |
| Несуществующий node id | reject, optional structured correction к LLM **только** если не превышен repair budget (`failure-retry-observability.md`) |
| `calls` без symbol evidence | reject |
| low confidence при policy | pending edge или reject |

### Единый A node id (target)

**Норматив:** один канонический шаблон `A` id на пару `(namespace, repo_identity)` для всех entrypoints; расхождение indexer vs W14 — **`implementation_backlog`** с миграцией (`pag_kb_memory_state_models.md` G1, synthesis G-AUTH-5).

## Traceability

| Source | Раздел |
|--------|--------|
| `original_user_request.md` §4 | типы связей, candidate JSON |
| `current_state/pag_kb_memory_state_models.md` | baseline PAG |
| `synthesis.md` G-AUTH-2 | расширение typed graph |
