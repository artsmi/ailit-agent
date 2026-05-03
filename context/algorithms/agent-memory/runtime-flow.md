<!-- Canonical AgentMemory target algorithm — published after user approval 2026-05-03 -->
**Источник:** черновик `context/artifacts/target_doc/target_algorithm_draft.md` (Produced by: 21_target_doc_author), верификация `context/artifacts/target_doc/verification.md`.

# runtime-flow

## Current Reality Summary

Факты сведены из отчётов `19_current_repo_researcher` и synthesis `20` (см. `context/artifacts/target_doc/current_state/*.md`, `synthesis.md`).

| Область | Краткий факт | Evidence (отчёт / synthesis) |
|---------|--------------|------------------------------|
| Entrypoints | `AgentMemoryWorker.handle`; subprocess `memory_agent.main()`; broker `AgentBroker.handle_request`; CLI init — **in-process** worker | `agent_memory_entrypoints_and_cli_init.md` F1 |
| CLI init success gate | Journal `memory.result.returned` с `payload.status == "complete"` для `chat_id`; не произвольный `blocked` в summary | entrypoints F5 |
| Нет `heartbeat` event | Liveness = compact stderr, `orch_memory_init_*`, `memory.runtime.step`, shadow journal | entrypoints F4; journal F9 |
| AW handoff | Payload: `memory_slice` + `agent_memory_result` рядом; SoT continuation — `agent_memory_result` | `agent_memory_agentwork_handoff.md` F2 |
| Budget cap | `memory.query.budget_exceeded`, **без** RPC и без envelope `blocked` от AM | handoff F8, G1; synthesis P4 |
| Pipeline depth | Один основной `plan_traversal` + ≤1 repair; нет внутреннего planner loop в одном `run` | `agent_memory_query_pipeline_runtime.md` F1 |
| Команды enum | Только `plan_traversal`, `summarize_c`, `summarize_b`, `finish_decision` | pipeline F2 |
| `stop_condition` v1 | Парсится, **не** передаётся в `pl.run` | pipeline F6; synthesis P2 |
| `agent_memory_commands.py` | **Отсутствует** в репозитории | pipeline F11; synthesis P1 |
| KB в query path | **Не пишется** в worker/pipeline; init очищает KB namespace | `agent_memory_pag_kb_state_models.md` F5 |
| A node id drift | `PagIndexer` vs `AgentMemoryQueryPipeline._materialize_b_paths` — разные шаблоны A id | pag F9; synthesis P6 |
| Grants | AM формирует `grants`; `work_agent.py` **не** потребляет | handoff F10; synthesis D2 |
| Journal redaction | Key-based `redact_journal_value`; stdout trace **без** того же redact | `agent_memory_journal_trace_chat_events.md` F1, F7 |
| План §G14R.3 имена тестов | Часть имён **только** в `plan/14`, не в `tests/` | `agent_memory_tests_and_plan14_contracts.md` F14 |

## Target Behavior

**Нормативно (цель продукта):** AgentMemory принимает bounded memory query, читает/пишет PAG в рамках политики namespace, опционально взаимодействует с KB в будущих версиях, вызывает LLM только через закрытый JSON-протокол, валидирует все graph mutations, эмитирует наблюдаемые события по уровням (compact / journal / rich stream), возвращает `agent_memory_result.v1`. Статус `blocked` допускается **только** при недоступности LLM API или невозможности получить валидный ответ LLM после bounded repair/retry; иначе — `complete` или `partial` с `reason` и `recommended_next_step`.

**Текущий снимок (реализация):** один проход W14 в `AgentMemoryQueryPipeline.run` с synthetic `finish_decision` на промежуточном пути; `stop_condition` из v1 не ограничивает pipeline; `max_turns` в лимитах не останавливает цикл внутри `run`; cap на число queries за turn enforced на стороне AgentWork, не как `blocked` от AM.

## Target Flow

1. **Intake:** валидировать transport, сервис `memory.query_context`, режим init (`memory_init: true` строго), запрет `path`/`hint_path` при init (proto UC-03).
2. **Identity:** принять `query_id`, `user_turn_id`, `namespace` (default `"default"` если пусто после strip), `project_root` (абсолютный канонический путь на стороне инициатора).
3. **Short-circuits:** выключенная LLM policy → deterministic fallback; mechanical slice если применимо; пустой `project_root` → bounded partial/blocked по политике.
4. **Planner round (W14):** system prompt `plan_traversal`; один HTTP completion; распарсить `agent_memory_command_output.v1` или извлечь JSON (legacy extract path — не считать строгим W14).
5. **Bounded repair:** при `W14CommandParseError` и разрешённой эвристике — **не более одного** дополнительного LLM вызова `_repair_w14_command_output`; иначе partial с `w14_contract_failure` / reject path.
6. **Branch:** если `command == finish_decision` → assembler finish; иначе `plan_traversal` + `payload.actions` whitelist runtime → `_run_w14_action_runtime` → подвызовы `summarize_c` / `summarize_b` через `AgentMemorySummaryService` → при необходимости synthetic `finish_decision` (`_finish_from_candidates`).
7. **Graph writes:** только через `PagGraphWriteService` / разрешённые offline writers; валидация путей (запрет abs и `..` в результатах — см. тесты G14R.7).
8. **D-nodes:** `DCreationPolicy.maybe_upsert_query_digest` после успешного finish path (фактический порядок см. `test_g14r8_d_summary_after_am_result.py`).
9. **Result assembly:** `build_agent_memory_result_v1` + `resolve_memory_continuation_required` в worker.
10. **Continuation:** на уровне **AgentWork** или **MemoryInitOrchestrator** (много раундов), не как бесконечный внутренний цикл одного `run`.

### Normative runtime state machine (цель)

Состояния (логические, не обязаны 1:1 совпадать со строками journal сегодня): `intake` → `db_snapshot` → `plan` → `execute_actions` → `summarize` → `links_validate` → `finish` → `emit_result` → `terminal`. Переходы обязаны иметь **прогресс** (изменение frontier, новых узлов/рёбер, или явного terminal reason). Повтор того же шага без изменения inputs/state — **запрещён** без смены параметров.

### Current implementation snapshot

- `RUNTIME_STATES` / `_RUNTIME_EDGES` в `agent_memory_runtime_contract.py` существуют, но pipeline в основном логирует строки вида `llm_await`, `w14_command_parsed` без `assert_runtime_state_transition` на просмотренном пути (`agent_memory_query_pipeline_runtime.md` F10).
- Внутри одного `run` нет цикла «снова plan_traversal» после успешного первого ответа (F1).

## State Lifecycle

| Сущность | Ключ | Операции |
|----------|------|----------|
| PAG SQLite | `(namespace, node_id)` | upsert nodes/edges; namespace partition |
| KB SQLite | `namespace` | init: `delete_all_for_namespace`; query path: **no write today** |
| Journal JSONL | `chat_id`, события | durable audit; redact on append |
| CLI session | `cli_session_dir` | `compact.log`, `legacy.log` (verbose), shadow journal |
| Broker stdout | topic publish | rich graph trace без journal redaction |

**Известный gap:** два шаблона A id (`PagIndexer` vs pipeline materialize) — target-doc требует будущего **единого генератора**; до исправления допускается сосуществование записей с разными A keys под одним namespace (риск для containment) — см. `agent_memory_pag_kb_state_models.md` F9.

---
