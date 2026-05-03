<!-- Canonical AgentMemory target algorithm — published after user approval 2026-05-03 -->
**Источник:** черновик `context/artifacts/target_doc/target_algorithm_draft.md` (Produced by: 21_target_doc_author), верификация `context/artifacts/target_doc/verification.md`.

# external-protocol

## external-protocol

### Слои (T1)

| Слой | Канал | Redaction | Потребитель |
|------|-------|-----------|-------------|
| A — Compact | `compact.log`, stderr tee | плоские scalar поля | CLI grep, оператор |
| B — Journal | JSONL `ailit_memory_journal_v1` | key-based redact | audit, verify init |
| C — Rich stdout | `emit_pag_graph_trace_row` | **нет** journal redact | Desktop/broker |

### События (schema-like sketches)

Метки **Current** / **Normative target** согласованы с [`synthesis.md`](../../artifacts/target_doc/synthesis.md) D1–D3: текущий код vs целевой контракт без смешения имен.

#### `memory.runtime.step` (journal) — **Current**

- **Event type:** `memory.runtime.step` (строка `event_name` в `ailit_memory_journal_v1`).
- **Payload schema (замкнутый producer-contract):** объект с **ровно** ключами:
  - `step_id` (**required** string; в коде режется до ≤220 символов — см. `tools/agent_core/runtime/subprocess_agents/memory_agent.py`, `log_memory_w14_runtime_step`);
  - `state` (**required** string);
  - `next_state` (**required** string);
  - `action_kind` (**required** string);
  - `query_id` (**required** string);
  - `counters` (**required** object; **default** пустой `{}`, если счётчиков нет — в коде строится пустой dict).
- **Normative rule (MINOR-2, один выбор):** **дополнительные top-level ключи в `payload` запрещены** для producer-путей AgentMemory: `log_memory_w14_runtime_step` собирает только перечисленные поля (нет merge произвольных extras). Общий `MemoryJournalStore.append` **не** фильтрует неизвестные ключи для всех событий — поэтому **strict validators** интеграции должны **отклонять** строки журнала с лишними ключами в этом payload, если событие заявлено как исходящее из AgentMemory. Правило **«forward-compatible: неизвестные ключи игнорировать»** для этого события **не** принимается: иначе расходимость с фактическим closed-dict producer и тестами размера payload (`tests/test_g14_agent_memory_runtime_logs.py`, `test_memory_runtime_step_journal_has_compact_payload`). См. также `current_state/agent_memory_journal_trace_chat_events.md` F3.
- **Compact human message:** `summary` строки журнала: `w14 runtime step` (короткая фиксация перехода).
- **Journal / log allow vs forbid:** разрешены только перечисленные поля + redaction по ключам как для любой journal строки; **forbidden** — произвольные большие тексты файлов в `counters` (тест ограничивает глубину строк).

#### `memory.result.returned` (journal + compact marker)

- **Required:** `query_id`, `status` (`complete|partial|blocked`), `result_kind_counts` (object, default `{}`), `results_total` (int).
- **Forbidden:** вложенные полные тексты summaries (см. G14 лог тесты).

#### `memory.slice.returned` (journal)

- **Required:** `partial` (bool), `recommended_next_step` (string), `estimated_tokens` (int), `compact` (object).
- **Default:** `compact.selected` — сокращённые id.

#### `memory.pag_graph` (compact) / stdout trace

- **Required:** `op`, `namespace`, `rev`, `request_id` (для compact line).
- **Rich stdout:** полный `inner_payload` — может быть большим (**известный риск**).

#### `memory.w14_graph_highlight`

- **Required:** счётчики `n_node`, `n_edge`, `w14_command`, `query_id`.
- **Purpose:** UI подсветка активного подграфа.

#### `memory.query.budget_exceeded` (Work emitter)

- **Required:** `code: too_many_memory_queries`, `cap` (int), `user_turn_id`.
- **Forbidden:** трактовать как ответ AgentMemory envelope.

---

<a id="normative-target-graph-streams"></a>

### **Current** — node upsert / materialization (journal + stdout)

#### `memory.index.node_updated` (journal)

- **Event type:** `memory.index.node_updated`.
- **Row-level (рядом с `payload`):** `node_ids` — **required** tuple/list (может быть один id); `edge_ids` — **default** пусто.
- **Payload schema:**
  - `namespace` (**required** string);
  - `selected_paths` (**required** list of strings, **default** `[]` если нет выбранных путей — не использовать `null` для «пусто»);
  - `reason` (**required** string; machine-oriented reason, например `w14_materialize_b` — см. `agent_memory_query_pipeline.py` / `memory_agent.py`).
- **Compact human message:** `summary`: `query-driven PAG node updated`.
- **Journal allow vs forbid:** allow id + relpaths + reason; **forbidden** raw file bytes, CoT, prompts.

#### `pag.node.upsert` (stdout `topic.publish` / broker trace) — **Current**

- **Event type:** строка `event_name` = `pag.node.upsert` внутри envelope `emit_pag_graph_trace_row` (`tools/agent_core/runtime/pag_graph_trace.py`).
- **Inner payload schema:**
  - `kind` (**required**, literal `pag.node.upsert`);
  - `namespace` (**required** string);
  - `rev` (**required** int, при ошибке parse в compact — 0);
  - `node` (**required** object) — полный dict узла PAG (**большой**; риск PII/размера — см. journal report F7).
- **Compact projection:** `memory.pag_graph` compact line — только `op=node`, `namespace`, `rev`, `request_id` (без полного `node`).
- **Stdout allow vs forbid:** allow полный `node` для Desktop; **forbidden** считать этот канал redacted как journal.

---

### **Current** — edge create (stdout); reject — **Normative target**

#### `pag.edge.upsert` (stdout) — **Current**

- **Event type:** `pag.edge.upsert`.
- **Inner payload schema:**
  - `kind` (**required**, literal `pag.edge.upsert`);
  - `namespace` (**required** string);
  - `rev` (**required** int);
  - `edges` (**required** list of edge dicts; минимум один элемент для single-edge callback, иначе пустой list для batch).
- **Compact human message:** нет отдельной compact-строки для edge (в отличие от node) — потребитель **stdout** или verbose audit (`memory.pag_graph` в chat debug).
- **Stdout allow vs forbid:** allow полные рёбра для визуализации; **forbidden** journal-default без политики размера.

#### `target_memory.graph.edge_rejected.v1` — **Normative target** (имя **TBD** до реализации; не найдено как отдельный durable event в текущем grep)

- **Event type (target):** `target_memory.graph.edge_rejected.v1` (или эквивалент с префиксом продукта после `start-feature`).
- **Payload schema:**
  - `query_id` (**required** string);
  - `namespace` (**required** string);
  - `candidate_link_id` (**required** string);
  - `link_type` (**required** string);
  - `reject_code` (**required** string, например `missing_evidence`, `bad_path`, `unknown_node`);
  - `detail` (**required** non-empty string, если `reject_code` непустой);
  - `source_node_id`, `target_node_id` (**required** strings).
- **Journal allow vs forbid:** **allow** compact запись (без полного исходного candidate JSON); **forbidden** raw LLM блок целиком.
- **Current gap:** отказ link-кандидата сейчас отражается преимущественно через trace/reason внутри runtime, без отдельного унифицированного события — внедрение события — задача `start-feature`.

---

### **Normative target** — link candidate advisory stream

#### `target_memory.graph.link_candidate_advisory.v1` — **Normative target**

- **Event type (target):** `target_memory.graph.link_candidate_advisory.v1`.
- **Payload schema:**
  - `query_id` (**required** string);
  - `stage` (**required** string: `proposed` | `promoted` | `rejected`);
  - `candidate` (**required** object): подмножество или полный `agent_memory_link_candidate.v1` без больших вложенных текстов — **forbidden** включать `value` длиннее политики (например >2k символов) в journal-копии; в stdout trace — по отдельной политике размера.
  - `advisory_reason` (**required** non-empty string при `stage=rejected`; при `stage=promoted` — **`null`** или `""` по политике версии; ключ **обязан** присутствовать).
- **Compact human message:** одна строка: `link_candidate stage=rejected type=calls id=candidate-01 reason=missing_evidence`.
- **Journal allow vs forbid:** allow усечённый candidate + codes; **forbidden** CoT, raw prompts.
- **Current:** отдельного имени события **нет**; low-confidence / отбрасывание отражаются косвенно (логика runtime + partial result). Выравнивание с [`original_user_request.md`](../../artifacts/target_doc/original_user_request.md) §7 — через введение этого события.

### Heartbeat (норматив vs текущий снимок)

- **Норматив:** если продукт требует явный heartbeat, вводится отдельное ephemeral событие с дискриминатором `type` и bounded payload (design note: discriminated union + durable vs ephemeral separation — см. donor opencode, **не копировать имена**).
- **Текущий снимок:** heartbeat отсутствует; liveness = continuous compact + runtime steps.

