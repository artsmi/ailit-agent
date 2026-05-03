<!-- Canonical AgentMemory target algorithm — published after user approval 2026-05-03 -->
**Источник:** черновик `context/artifacts/target_doc/target_algorithm_draft.md` (Produced by: 21_target_doc_author), верификация `context/artifacts/target_doc/verification.md`.

# memory-graph-links

## memory-graph-links

### Link types (normative)

| `link_type` | Typical ends | Evidence sources allowed | Notes |
|-------------|--------------|---------------------------|-------|
| `contains` | A→B, B→B, B→C | `runtime_observed`, indexer | Иерархия дерева |
| `imports` | B→B, B→external, B→C(symbol) | `static_analysis` preferred; `llm_inferred` only with evidence | Запрещено без разрешённого импорт-механизма |
| `defines` | B→C | `static_analysis`, `runtime_observed` | |
| `calls` | C→C | `static_analysis` or reliable symbol resolution | **Forbidden** без symbol/line evidence |
| `references` | C/D/B ↔ C/B/D | textual/structural evidence | Для MD/config/tests |
| `summarizes` | D→B/C | `llm_inferred` + runtime gate | D фиксирует digest |
| `supports_answer` | B/C→D | `llm_inferred` + validation | Evidence для результата |
| `supersedes` | D→D | `runtime_observed` policy | Только если runtime явно решил замену digest |

### `link_type`: кандидат (wire) vs хранение

- **Кандидат от LLM / propose_links (wire union, согласовано с [`original_user_request.md`](../../artifacts/target_doc/original_user_request.md) §4 примером):**  
  `calls` | `imports` | `references` | `summarizes` | `supports_answer`  
  плюс, когда алгоритм явно предлагает иерархию/определения: `contains` | `defines` | `supersedes` — **только** если поле разрешено активным prompt-контрактом раунда (иначе runtime **отклоняет** кандидата как out-of-contract `link_type`).
- **Слой хранения (PAG edge kinds после валидации):** полный набор из таблицы [Link types (normative)](#link-types-normative); runtime может **принять** кандидат с узким `link_type` и записать ребро с нормализованным типом/атрибутами, не меняя пользовательский §4 для wire.

### Schema: `agent_memory_link_candidate.v1` (candidate — not DB row)

Выровнено с **обязательным примером** из [`original_user_request.md`](../../artifacts/target_doc/original_user_request.md) §4 (вложенный `evidence`, расширенный `created_by`).

**Required:**

- `schema_version`: `"agent_memory_link_candidate.v1"`.
- `link_id`: non-empty string (`candidate-…`).
- `link_type`: значение из **wire union** для данного раунда (см. подраздел выше).
- `source_node_id`, `target_node_id`: non-empty strings с префиксом уровня (`A:`, `B:`, `C:`, `D:`).
- `source_path`: relative path string under `project_root`.
- `evidence`: object — **required** для каждого кандидата, проходящего строгую валидацию на promote в граф (см. ниже nullable внутри).
- `confidence`: `high` | `medium` | `low`.
- `created_by`: `static_analysis` | `llm_inferred` | `runtime_observed` | **`user_request`**.
- `reason`: short string (human-readable, не CoT).

**Object `evidence` (required keys; значения nullable по правилам):**

- `kind`: required string; union: `line_range` | `symbol_name` | `heading_text` | `llm_summary` | `user_attached` (последний — типично при `created_by: user_request`).
- `value`: required string; **допускается** `""` только если `kind` ∈ {`user_attached`, `llm_summary`} **и** политика раунда явно разрешает пустой anchor (по умолчанию для `calls` / `imports` к файлу — **forbidden** пустой `value`).
- `start_line`: required JSON key; **nullable** (`null`) если `kind` ∈ {`symbol_name`, `heading_text`, `user_attached`, `llm_summary`} и доказуемость не привязана к диапазону строк; для `kind: line_range` — **required** int ≥ 1.
- `end_line`: required JSON key; **nullable** по тем же правилам, что `start_line`; для `line_range` — **required** int ≥ `start_line`.

**Правило `created_by: user_request`:** использовать, когда связь введена **явным** решением человека или upstream-текстом запроса (например «считай `foo.py` частью ответа для digest D:…»), а не выведена моделью; `evidence.kind` обычно `user_attached`, `value` — непустая цитата/инструкция. Runtime **обязан** всё равно проверить пути и существование узлов перед записью.

**Default / nullable (верхний уровень кандидата):**

- `target_path`: default — отсутствующий ключ трактуется как «нет отдельного target path»; иначе `null` допускается для non-file targets если политика позволяет; для file-backed target — **required** relative path string.

**Forbidden:**

- Абсолютные пути, сегменты `..`, несуществующие node ids без staged create, произвольный CoT в `reason`, promote `calls` без `evidence`, пригодного для symbol/line (см. таблицу link types).

**Minimal example (happy, compact):**

```json
{
  "schema_version": "agent_memory_link_candidate.v1",
  "link_id": "candidate-01",
  "link_type": "calls",
  "source_node_id": "C:pkg/a.go:Run",
  "target_node_id": "C:pkg/b.go:Init",
  "source_path": "pkg/a.go",
  "target_path": "pkg/b.go",
  "evidence": {
    "kind": "line_range",
    "value": "Run",
    "start_line": 12,
    "end_line": 18
  },
  "confidence": "high",
  "created_by": "llm_inferred",
  "reason": "static call at line 15"
}
```

**Low confidence:** не promote в «hard fact» рёбра; допускается advisory projection (см. **Normative target — `target_memory.graph.link_candidate_advisory.v1`** в [external-protocol.md](external-protocol.md)) только если политика версии явно разрешает.

### Реализация vs цель

**Текущий снимок:** полный набор типов из таблицы может быть не полностью materialized в коде; target-doc фиксирует **целевую** полноту. LLM не пишет в БД напрямую — только кандидаты в JSON, runtime валидирует.

---
