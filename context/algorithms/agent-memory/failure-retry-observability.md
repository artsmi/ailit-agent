# Ошибки, повторы, наблюдаемость и приёмка (Failure, retry, observability)

**Аннотация:** что происходит при сбоях LLM, разборе JSON, отсутствии файла и превышении лимитов; какие каналы логов существуют; как верхний `status` результата соотносится с `runtime_trace.partial_reasons`; какие тесты считаются регрессией.

**D-OBS**, **W14** — см. [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-010 | События и логи на границе с потребителями: без сырых промптов там, где канон требует компактность; согласование с [`external-protocol.md`](external-protocol.md). |
| OR-012 | Конверт `agent_memory_result.v1`: поля, статусы, компактный trace. |
| OR-013 | Поведение при невалидном JSON, неверном id узла, отклонённой связи, лимитах, отсутствии файла, неизвестном языке — в том числе наблюдаемые коды причин. |
| OR-015 | Проверяемые критерии приёмки; в каноне — явные пути и имена тестов pytest в репозитории. |

## Текущая реализация

- Repair планера: **один** дополнительный вызов LLM при части ошибок; политика `_should_repair_w14_error` отклоняет repair для некоторых текстов ошибки (например явное «должен быть только json» / «invalid json»).
- Отмена: `memory.cancel_query_context` → `MemoryQueryCancelledError` внутри pipeline → ответ с `memory_query_cancelled` (без полноценного `agent_memory_result` в успешном теле того же round — см. обработчик в `memory_agent.py`).
- **Верхний `status` и `partial_reasons` — разные поля:** `ailit/agent_memory/contracts/agent_memory_terminal_outcomes.py` поставляет строки для `AgentMemoryQueryPipelineResult.runtime_partial_reasons`, которые попадают в `agent_memory_result.v1` как `runtime_trace.partial_reasons`. Итоговое поле `status` в конверте собирает `build_agent_memory_result_v1` с приоритетом `explicit_status` (`am_v1_status` из pipeline) и whitelist-нормализацией; причины из terminal outcomes **не** подменяют верхний `status` напрямую.
- **Семантика `blocked` в коде шире целевой формулировки OR-002:** помимо сценариев «LLM недоступен / нет валидного ответа после repair», `blocked` выставляется в ветках finish-decision и assembly при пустых `selected_results`, отсутствии валидных `results` и полном отказе assembly по путям (см. `ailit/agent_memory/query/agent_memory_query_pipeline.py`). Неперехваченное исключение из `pl.run` при `memory init` может дать пользовательский `blocked` с `reason_short=runtime_error` и non-zero exit **вне** успешного envelope с полным `agent_memory_result` в том же round.
- **Внешние события в JSONL как `memory.external_event`:** в production с envelope `agent_memory.external_event.v1` пишутся только **`link_candidates`** и **`links_updated`** (ветка `propose_links` в `AgentMemoryQueryPipeline`). Остальные значения `ExternalEventType` заданы типом и модульным docstringом в `agent_memory_external_events.py`; production-вызовов `build_external_event_v1` для них нет, кроме unit-теста формы envelope (например `heartbeat`).
- **`build_external_event_v1`** не валидирует `payload` по `event_type`; запрет raw/CoT для result-type событий в docstring — политика; для durable JSONL действует `redact_journal_value` / `_SENSITIVE_KEY_PARTS` в `memory_journal.py` и отсутствие raw prompt в `log_memory_w14_command_requested`.
- **Различать:** wire `event_type` в envelope внешнего события; имена compact-событий `memory.link_candidates`, `memory.links_updated`; маркер `memory.result.returned` со whitelist статусов через `emit_memory_result_returned_marker` в `compact_observability_sink.py` (не-whitelist статус в маркере принудительно отображается как `blocked`).
- Множество имён `event_name` в журнале памяти **шире**, чем короткий каталог внешних событий D-OBS.
- Подсветка графа: stdout с именем вроде `memory.w14.graph_highlight`; в компактном файле имя может нормализоваться (например без точки в середине).
- Исторические имена тестов из старых планов (например `*_prompt_contains_*`) в репозитории **отсутствуют**; норматив — только фактические пути и имена ниже.

## Целевое поведение

### Единицы лимитов

- Строковые поля в **wire JSON** (события, `decision_summary`, причины): лимиты в **символах UTF-8** после нормализации (например NFC) или с явной factory default.
- Поля графа (`highlighted_nodes`, `links_updated.applied`): лимиты в **числе узлов/рёбер** + флаг `truncated=true` при обрезке.
- **Запрещено** смешивать токены токенизатора модели в обязательных полях публичной схемы.

### OR-002 vs факт: верхний `status` = `blocked`

**Цель (OR-002):** трактовать `blocked` как недоступность API LLM или невозможность получить валидный ответ после ограниченного repair для обязательной фазы с участием LLM.

**Факт в реализации (синхронизация с pipeline):** `blocked` в `am_v1_status` также используется при пустой finish-сборке и отказе assembly, не только при недоступности LLM. Читатель канона обязан сверять ветки статуса с `ailit/agent_memory/query/agent_memory_query_pipeline.py` и `build_agent_memory_result_v1`, а не только с OR-002.

### Матрица OR-013: условие → верхний статус (типично) → наблюдаемая причина → retry

Колонка **«Причина (`runtime_trace.partial_reasons`)»** перечисляет строки, которые попадают в компактный trace; **полный** перечень строк матрицы в коде не дублируется в `agent_memory_terminal_outcomes.py` (см. docstring модуля: часть кодов подключается в других ветках). **SoT для подключённых кодов и маппинга assembly:** `ailit/agent_memory/contracts/agent_memory_terminal_outcomes.py` (`REASON_*`, `w14_intermediate_runtime_partial_reasons`, `or013_reasons_from_assembly_reject_codes` — сейчас маппятся только `c_node_not_found` → `unknown_node_id`, `read_lines_file_not_found` → `file_missing`).

| Условие | Типичный верхний `status` | `runtime_trace.partial_reasons` (OR-013 строки, если применимо) | Retry/repair |
|---------|---------------------------|---------------------------------------------------------------------|----------------|
| HTTP/транспорт LLM недоступен после ограниченных попыток | `blocked` (цель OR-002); в CLI init возможны строки вроде `llm_unavailable` / `memory_llm_unavailable` в summary через `memory_init_cli_outcome` | не обязательно через `terminal_outcomes` | ограниченный backoff |
| LLM вернул невалидный JSON / ошибка разбора W14, repair разрешён и успешен | продолжить внутри одного `run()` | при неуспехе repair — `w14_parse_failed` | 1× repair (см. pipeline) |
| Repair запрещён или провалился | `partial` | `w14_parse_failed` | нет |
| Несуществующий id узла в плане / assembly | `partial` или `blocked` по ветке finish | `unknown_node_id` при коде assembly `c_node_not_found` | ограниченно |
| Невалидный кандидат связи | связь отклоняется, запись частичная | `link_rejected` | продолжить раунд без этой связи |
| Файл отсутствует / не читается | `partial` / `blocked` по ветке | `file_missing` при `read_lines_file_not_found` в assembly | нет |
| Язык неизвестен | `partial` (эвристический фрагмент) | строка может не проходить через `terminal_outcomes` — **verification_gap** до явной привязки в коде | нет |
| Превышены лимиты (запросы на turn, узлы, рёбра) | `partial` | `cap_exceeded` (через `w14_intermediate_runtime_partial_reasons` при `cap_exhausted`) | нет |
| Отмена по `memory.cancel_query_context` | ошибка RPC / не `ok` | не как полный успешный `agent_memory_result` в том же round | нет |
| Раунд без прогресса (FR-no-progress): ноль usable-кандидатов при ненулевом C-scope без cap | `partial` (часто вместе с терминальным путём) | `no_progress` | нет нового раунда **внутри** того же `run()`; continuation — снаружи pipeline |
| Нет данных в PAG | `partial` или рост графа по политике | `empty_graph` и др. — см. docstring `terminal_outcomes` / ветки pipeline (**verification_gap** для точной строки) | ограниченно |
| KB отсутствует на пути init | по политике транзакций init | `kb_*` (только init), не через `terminal_outcomes` | — |
| Пустые `selected_results` / нет валидных `results` / полный отказ assembly | **`blocked`** (факт pipeline, шире OR-002) | зависит от ветки | нет |

### FR-no-progress (целевое правило)

Если раунд выбрал тот же набор файлов или узлов и не добавил пригодных кандидатов, следующий раунд **запрещён** без смены входа, прогресса, лимитов или исправления ответа провайдера; иначе `partial` с причиной наблюдаемости **`no_progress`**. Подключение в рантайме: `w14_intermediate_runtime_partial_reasons` в `ailit/agent_memory/contracts/agent_memory_terminal_outcomes.py`.

### `agent_memory_result.v1` (OR-012) — каркас схемы

```json
{
  "schema_version": "agent_memory_result.v1",
  "query_id": "string, required",
  "status": "complete|partial|blocked",
  "decision_summary": "string, required, bounded utf8 chars",
  "recommended_next_step": "string, default empty",
  "results": "array, default []",
  "runtime_trace": "object, required, compact; forbidden raw prompts/secrets; partial_reasons — список OR-013 строк",
  "memory_continuation_required": "bool|null, default null — if null, key omitted"
}
```

**Элемент `results[]` (минимум):** поля `kind`, `path`, при необходимости `summary` / `read_lines` / `c_node_id` согласно сборщику finish в реализации.

**`runtime_trace` в текущей реализации:** поля вроде `steps_executed` / `final_step` задаются компактно (фиксированное представление), а не как полный счётчик шагов W14 — см. [`runtime-flow.md`](runtime-flow.md).

### Слои наблюдаемости

1. **Stdout брокера JSONL** — граф/подсветка для Desktop; внутренние имена строк мапятся на compact отдельно от envelope внешних событий.
2. **Журнал памяти** (`event_name`) — долговечный аудит с редактированием по ключам (`redact_journal_value` для чувствительных ключей).
3. **`memory.external_event` (durable)** — только `link_candidates` / `links_updated` в production; compact sink для них получает **агрегаты** (`n_cand`, `n_applied`, `n_rejected`), не полный список кандидатов.
4. **compact.log** — компактный вывод для человека в CLI; нормализация имён (`normalize_compact_event_name` где применимо); маркер `memory.result.returned` с whitelist статусов.
5. **Подробный legacy-лог** — только аудит, не D-OBS.

### Маппинг stdout → compact (внутренние имена, не wire `event_type` внешнего события)

SoT: `STDOUT_INTERNAL_TO_COMPACT_EVENT` в `ailit/agent_memory/contracts/agent_memory_external_events.py`; регрессия имени и формы `build_external_event_v1` — `ailit/agent_memory/tests/test_g14_agent_memory_external_event_mapping.py` (`test_stdout_to_compact_golden_mapping_table`, `test_build_external_event_v1_shape`).

| stdout `event_name` | compact `event` |
|---------------------|-----------------|
| `pag.node.upsert` | `memory.pag_graph` |
| `pag.edge.upsert` | `memory.pag_graph` |
| `memory.w14.graph_highlight` | `memory.w14_graph_highlight` |

### Приёмка: инвентарь pytest (OR-015)

Использовать только существующие тесты в дереве `tests/` и `ailit/agent_memory/tests/`. **Изоляция по умолчанию:** autouse `isolate_ailit_test_artifacts` в корневом `conftest.py`; тесты `memory init` часто дополнительно задают `AILIT_AGENT_MEMORY_*`, пути журнала и PAG через `monkeypatch`.

#### CLI `ailit memory init`, оркестратор, журнал VERIFY

| Путь | Примеры имён функций / назначение |
|------|-----------------------------------|
| `tests/runtime/test_memory_init_orchestrator_task_2_2.py` | `test_memory_init_orchestrator_end_to_end`; прерывание → exit **130** |
| `tests/runtime/test_memory_init_fix_uc01_uc02.py` | continuation, `partial` + exit **1**, stderr summary |
| `ailit/agent_memory/tests/test_memory_init_cli_layout.py` | `test_memory_init_journal_verify_requires_complete_marker` (VERIFY) |
| `tests/runtime/test_memory_init_t4_uc05_real_handle.py` | `test_t4_memory_init_orchestrator_exit0_real_handle_sequential_provider` |
| `tests/test_memory_cli_init_task_3_1.py` | subprocess / help / invalid path |
| `ailit/agent_memory/tests/test_memory_init_transaction_task_2_1.py` | фазы транзакции init |

#### Регрессии G14 / broker / runtime памяти

| Путь | Примеры имён функций |
|------|----------------------|
| `ailit/agent_memory/tests/test_g14r0_w14_clean_replacement.py` | `test_query_context_returns_agent_memory_result_next_to_memory_slice`, `test_legacy_requested_reads_rejected_after_clean_replacement` |
| `ailit/agent_memory/tests/test_g14r2_agent_memory_runtime_contract.py` | `test_plan_traversal_in_progress_canonicalizes_to_ok`, `test_command_output_rejects_prose_around_json` |
| `tests/test_g14r7_agent_memory_result_assembly.py` | `test_memory_result_contains_c_summary_without_raw_b_content`, `test_memory_result_read_lines_are_granted_ranges` |
| `tests/test_g14r11_w14_integration.py` | `test_w14_pipeline_emits_terminal_agent_memory_result_per_query`, `test_w14_invalid_json_does_not_grow_pag` |
| `tests/test_g14r1_agent_work_memory_query.py` | `test_memory_query_requires_subgoal_and_stop_condition`, `test_agentwork_memory_query_loop_stops_at_config_cap` |
| `tests/test_g14r_agentwork_memory_continuation.py` | `test_uc01_partial_continuation_two_memory_queries_before_tools` |
| `ailit/agent_memory/tests/test_g14_agent_memory_runtime_logs.py` | `test_memory_runtime_step_journal_has_compact_payload`, `test_agent_memory_chat_log_records_command_requested_without_raw_prompt` |
| `ailit/agent_memory/tests/test_g14_agent_memory_external_event_mapping.py` | stdout→compact, форма `agent_memory.external_event.v1` |
| `tests/runtime/test_broker_work_memory_routing.py` | broker + `_w14_trace_contract_ok` |
| `ailit/agent_memory/tests/test_g14_agent_memory_legacy_quarantine.py` | quarantine legacy C extractor |
| `ailit/agent_memory/tests/test_memory_journal.py` | redaction / durable journal (см. отчёт и grep по `redact_journal_value`) |

**Историческая заметка:** имена вроде `test_plan_traversal_prompt_contains_required_output_schema` из старых планов в репозитории **не** существуют; на них не опираться.

## Сводка implementation_backlog (см. глоссарий)

- Полная машинная трассировка **каждой** строки матрицы OR-013 к активному `REASON_*` или ветке pipeline: либо расширить `ailit/agent_memory/contracts/agent_memory_terminal_outcomes.py` и тесты, либо явно пометить непокрытые строки как `verification_gap` до построчного grep по коду.
- AgentWork / цикл инструментов: передать `grants` из ответа памяти в `MemoryGrantChecker` при создании `ToolExecutor` (сейчас checker в типичном loop не задаётся).
- Единый id узла A (см. [`memory-graph-links.md`](memory-graph-links.md)).
- Расширение D-OBS или второй каталог внутреннего журнала.
- Ручной smoke `ailit memory init ./` для полного операторского DoD, если gate **11** его не включал ([`external-protocol.md`](external-protocol.md)).

## How start-feature / start-fix must use this

- **`02_analyst`:** для статусов `complete` / `partial` / `blocked`, матрицы OR-013, различия верхнего `status` и `runtime_trace.partial_reasons`, лимитов UTF-8 и журнала — опираться на этот файл и не дублировать противоречивые правила в ТЗ.
- **`06_planner`:** задачи на наблюдаемость, repair, caps и acceptance должны ссылаться на **именованные** тесты и сценарии из таблиц ниже; FR-no-progress и OR-010 (фактические эмиттеры) — якорь для границ scope.
- **`11_test_runner`:** прогонять перечисленные pytest-пути как регрессию при изменениях pipeline, журнала, external events или сборки `agent_memory_result.v1`; ручной smoke из `external-protocol.md` — когда план или AC явно требуют операторский DoD.
- **`13_tech_writer`:** при изменении кодов причин, redaction, compact sink или матрицы OR-013 обновить этот файл и уточнение OR-010 в `INDEX.md` так, чтобы «Текущая реализация» оставалась согласована с фактическими call site.
