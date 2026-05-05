# Ошибки, повторы, наблюдаемость и приёмка (Failure, retry, observability)

**Аннотация:** что происходит при сбоях LLM, разборе JSON, отсутствии файла и превышении лимитов; какие каналы логов существуют; какие тесты считаются доказательством соответствия.

**D-OBS**, **W14** — см. [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-010 | События и логи на границе с потребителями: без сырых промптов там, где канон требует компактность; согласование с [`external-protocol.md`](external-protocol.md). |
| OR-012 | Конверт `agent_memory_result.v1`: поля, статусы, компактный trace. |
| OR-013 | Поведение при невалидном JSON, неверном id узла, отклонённой связи, лимитах, отсутствии файла, неизвестном языке. |
| OR-015 | Проверяемые критерии приёмки; в каноне — явные имена тестов pytest в репозитории. |

## Текущая реализация

- Repair планера: **один** дополнительный вызов LLM при части ошибок; политика функции «разрешать ли repair» отклоняет repair для некоторых текстов ошибок (например явное «должен быть только json» / «invalid json»).
- Множество имён `event_name` в журнале памяти **шире**, чем короткий каталог внешних событий D-OBS.
- Подсветка графа: stdout с именем вроде `memory.w14.graph_highlight`; в компактном файле имя может нормализоваться (например без точки в середине).
- Исторические имена тестов из старых планов (например `*_prompt_contains_*`) в репозитории **отсутствуют**; норматив — только фактические имена ниже.

## Целевое поведение

### Единицы лимитов

- Строковые поля в **wire JSON** (события, `decision_summary`, причины): лимиты в **символах UTF-8** после нормализации (например NFC) или с явной factory default.
- Поля графа (`highlighted_nodes`, `links_updated.applied`): лимиты в **числе узлов/рёбер** + флаг `truncated=true` при обрезке.
- **Запрещено** смешивать токены токенизатора модели в обязательных полях публичной схемы.

### Матрица ошибок и повторов (OR-013)

| Условие | Статус | Retry/repair | Код причины для наблюдаемости |
|---------|--------|--------------|-------------------------------|
| HTTP/транспорт LLM недоступен после ограниченных попыток | `blocked` | ограниченный backoff | `llm_unavailable` |
| LLM вернул невалидный JSON / ошибка разбора W14, repair разрешён и успешен | продолжить | 1× repair | `w14_repair_ok` |
| Repair запрещён или провалился | `partial` | нет | `w14_parse_failed` |
| Несуществующий id узла в плане | `partial` или структурированное исправление | ограниченно | `unknown_node_id` |
| Невалидный кандидат связи | отклонить связь | продолжить | `link_rejected` |
| Файл отсутствует / не читается | `partial` | нет | `file_missing` |
| Язык неизвестен | `partial` (эвристический фрагмент) | нет | `language_unknown_fallback` |
| Превышены лимиты (запросы на turn, узлы, рёбра) | `partial` | нет | `cap_exceeded` |
| Нет данных в PAG | разрешённый рост/индекс **или** `partial` с причиной | ограниченно | `empty_graph` |
| KB отсутствует на пути init | по политике транзакций | — | `kb_*` (только init) |

### FR-no-progress (целевое правило)

Если раунд выбрал тот же набор файлов или узлов и не добавил пригодных кандидатов, следующий раунд **запрещён** без смены входа, прогресса, лимитов или исправления ответа провайдера; иначе `partial` с `reason=no_progress`.

### `agent_memory_result.v1` (OR-012) — каркас схемы

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

**Элемент `results[]` (минимум):** поля `kind`, `path`, при необходимости `summary` / `read_lines` / `c_node_id` согласно сборщику finish в реализации.

**Семантика `blocked`:** только недоступность API LLM или невозможность получить валидный ответ после ограниченного repair для **обязательной** фазы с участием LLM (согласовано с OR-002).

### Слои наблюдаемости

1. **Stdout брокера JSONL** — граф/подсветка для Desktop.
2. **Журнал памяти** (`event_name`) — долговечный аудит с редактированием по ключам.
3. **compact.log** — компактный вывод для человека в CLI; нормализация имён событий.
4. **Подробный legacy-лог** — только аудит, не D-OBS.

### Маппинг stdout → compact (цель)

Таблица должна быть зафиксирована в реализации тестом или документированным списком; пример:

| stdout `event_name` | compact `event` |
|---------------------|-----------------|
| `pag.node.upsert` (через обёртку) | `memory.pag_graph` |
| `memory.w14.graph_highlight` | `memory.w14_graph_highlight` |

### Приёмка: фактические тесты pytest (OR-015)

Использовать только существующие тесты в дереве `tests/`:

- `tests/test_g14r0_w14_clean_replacement.py`: `test_query_context_returns_agent_memory_result_next_to_memory_slice`, `test_legacy_requested_reads_rejected_after_clean_replacement`
- `tests/test_g14r2_agent_memory_runtime_contract.py`: `test_plan_traversal_in_progress_canonicalizes_to_ok`, `test_command_output_rejects_prose_around_json`
- `tests/test_g14r7_agent_memory_result_assembly.py`: `test_memory_result_contains_c_summary_without_raw_b_content`, `test_memory_result_read_lines_are_granted_ranges`
- `tests/test_g14r11_w14_integration.py`: `test_w14_pipeline_emits_terminal_agent_memory_result_per_query`, `test_w14_invalid_json_does_not_grow_pag`
- `tests/test_g14r1_agent_work_memory_query.py`: `test_memory_query_requires_subgoal_and_stop_condition`, `test_agentwork_memory_query_loop_stops_at_config_cap`
- `tests/test_g14r_agentwork_memory_continuation.py`: `test_uc01_partial_continuation_two_memory_queries_before_tools`
- `tests/test_g14_agent_memory_runtime_logs.py`: `test_memory_runtime_step_journal_has_compact_payload`, `test_agent_memory_chat_log_records_command_requested_without_raw_prompt`
- `tests/runtime/test_broker_work_memory_routing.py`: broker + `_w14_trace_contract_ok`
- `tests/test_g14_agent_memory_legacy_quarantine.py`: quarantine legacy C extractor

**Историческая заметка:** имена вроде `test_plan_traversal_prompt_contains_required_output_schema` из старых планов в репозитории **не** существуют; на них не опираться.

## Сводка implementation_backlog (см. глоссарий)

- CLI: видимый `blocked` vs `aborted` / сопоставление кода выхода.
- AgentWork: подключить `grants` к проверке чтения файлов.
- Единый id узла A (см. [`memory-graph-links.md`](memory-graph-links.md)).
- Расширение D-OBS или второй каталог внутреннего журнала.
- Целевой конверт `propose_links` и строгая валидация ([`llm-commands.md`](llm-commands.md)).
