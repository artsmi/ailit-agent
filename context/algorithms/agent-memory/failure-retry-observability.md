# AgentMemory: failure, retry, observability, acceptance

## Current reality

- Planner repair: **один** LLM repair call при части ошибок; `_should_repair_w14_error` отклоняет repair для строк `"must be only json"` / `"invalid json"` (`agent_memory_query_pipeline.md` F6).
- Journal `event_name` — множество имён шире D-OBS-1 (`memory_journal_trace_observability.md` F2, F11).
- Highlight: stdout `memory.w14.graph_highlight` (с точкой), compact файл `memory.w14_graph_highlight` после normalize (`memory_journal_trace_observability.md` F12).
- Тесты: имена из plan §C14R.4 `*_prompt_contains_*` **отсутствуют** в репозитории; фактические имена в `tests_plan14_alignment.md` (`tests_plan14_alignment.md` G1).

## Target behavior

### Единицы лимитов (D4)

- Строковые поля в **wire JSON** (события, `decision_summary`, reasons): лимиты в **UTF-8 символах** после нормализации NFC (или явно указанной factory default).
- Граф-facing поля (`highlighted_nodes`, `links_updated.applied`): лимиты в **количестве узлов/рёбер** + флаг `truncated=true` при crop.
- **Forbidden** смешивать tokenizer-токены в обязательных public schema полях.

### Failure / retry matrix (OR-013)

| Условие | Статус | Retry/repair | Observable reason code |
|---------|--------|--------------|--------------------------|
| LLM HTTP/transport недоступен после bounded attempts | `blocked` | bounded backoff | `llm_unavailable` |
| LLM вернул invalid JSON / W14 parse error, repair разрешён и успешен | continue | 1× repair | `w14_repair_ok` |
| Repair запрещён или провалился | `partial` | none | `w14_parse_failed` |
| Несуществующая node id в plan | `partial` или structured fix | bounded | `unknown_node_id` |
| Invalid graph link candidate | reject link | continue | `link_rejected` |
| Файл missing / unreadable | `partial` | none | `file_missing` |
| Язык unknown | `partial` (heuristic chunk) | none | `language_unknown_fallback` |
| Caps превышены (queries/turn, nodes, edges) | `partial` | none | `cap_exceeded` |
| Нет данных в PAG | запуск разрешённого growth/index **или** `partial` с reason | bounded | `empty_graph` |
| KB missing на init path | согласно transaction policy | — | `kb_*` (init only) |

### FR-no-progress (целевое правило)

Если раунд выбрал тот же набор файлов/нод и не добавил usable candidates, следующий раунд **forbidden** без смены входа/progress/caps/provider fix; иначе `partial` с `reason=no_progress`.

### `agent_memory_result.v1` (OR-012) — schema-like каркас

```json
{
  "schema_version": "agent_memory_result.v1",
  "query_id": "string, required",
  "status": "complete|partial|blocked",
  "decision_summary": "string, required, bounded utf8 chars",
  "recommended_next_step": "string, default empty",
  "results": "array, default []",
  "runtime_trace": "object, required, compact; forbidden raw prompts/secrets",
  "memory_continuation_required": "bool|null, default null — if null, key omitted"
}
```

**`results[]` элемент (минимальный контракт):** поля `kind`, `path`, опционально `summary` / `read_lines` / `c_node_id` согласно сборщику finish (`tests_plan14_alignment.md` F10).

**`blocked` semantics:** только LLM API / невалидируемый ответ после bounded repair для **обязательной** LLM фазы (`original_user_request.md`).

### Observability слои

1. **Broker stdout JSONL** — graph/highlight для Desktop.
2. **Memory journal** (`event_name`) — durable audit с redaction по ключам (`memory_journal_trace_observability.md` F6).
3. **compact.log** — CLI human sink; нормализация имён (`memory_journal_trace_observability.md` F4, F12).
4. **legacy verbose** — audit-only, не D-OBS.

### Маппинг stdout → compact (target)

Таблица обязательна в имплементации тестом или документированным golden list; пример строк:

| stdout `event_name` | compact `event` |
|---------------------|-----------------|
| `pag.node.upsert` (через wrapper) | `memory.pag_graph` |
| `memory.w14.graph_highlight` | `memory.w14_graph_highlight` |

### Acceptance: фактические pytest (не имена из plan §C14R.4)

**Норматив:** использовать только существующие имена из `tests_plan14_alignment.md`:

- `tests/test_g14r0_w14_clean_replacement.py`: `test_query_context_returns_agent_memory_result_next_to_memory_slice`, `test_legacy_requested_reads_rejected_after_clean_replacement`
- `tests/test_g14r2_agent_memory_runtime_contract.py`: `test_plan_traversal_in_progress_canonicalizes_to_ok`, `test_command_output_rejects_prose_around_json`
- `tests/test_g14r7_agent_memory_result_assembly.py`: `test_memory_result_contains_c_summary_without_raw_b_content`, `test_memory_result_read_lines_are_granted_ranges`
- `tests/test_g14r11_w14_integration.py`: `test_w14_pipeline_emits_terminal_agent_memory_result_per_query`, `test_w14_invalid_json_does_not_grow_pag`
- `tests/test_g14r1_agent_work_memory_query.py`: `test_memory_query_requires_subgoal_and_stop_condition`, `test_agentwork_memory_query_loop_stops_at_config_cap`
- `tests/test_g14r_agentwork_memory_continuation.py`: `test_uc01_partial_continuation_two_memory_queries_before_tools`
- `tests/test_g14_agent_memory_runtime_logs.py`: `test_memory_runtime_step_journal_has_compact_payload`, `test_agent_memory_chat_log_records_command_requested_without_raw_prompt`
- `tests/runtime/test_broker_work_memory_routing.py`: broker + `_w14_trace_contract_ok`
- `tests/test_g14_agent_memory_legacy_quarantine.py`: quarantine legacy C extractor

**Historical note:** имена вида `test_plan_traversal_prompt_contains_required_output_schema` из plan/14 — **не** существуют в репозитории (`tests_plan14_alignment.md` G1).

## implementation_backlog (сводка)

- CLI: отображение `blocked` vs `aborted` / exit mapping (D1).
- AgentWork: подключить `grants` к read enforcement (D2).
- Единый A node id (G-AUTH-5).
- Расширение D-OBS или второй каталог internal journal (G-AUTH-6).
- Целевой envelope `propose_links` + строгая валидация (`llm-commands.md`).

## Traceability

| ID | Источник |
|----|----------|
| OR-010–013, OR-015 | `original_user_request.md` |
| F-OBS*, F-TST* | `current_state/memory_journal_trace_observability.md`, `current_state/tests_plan14_alignment.md` |
