# Тесты — индекс

Общий контур: изоляция `HOME` / `AILIT_*` в `tests/conftest.py`, маркеры и `addopts` в `pyproject.toml`, запуск из venv репозитория — см. [`../start/repository-launch.md`](../start/repository-launch.md).

## Python (`tests/`)

Изоляция артефактов, pytest, e2e — в проектных правилах workflow и в `tests/conftest.py`. Не путать с vitest desktop.

### Agent Memory CLI — `memory init` (orchestrator / transaction / compact)

| Путь / смысл | Содержание |
|----------------|------------|
| `tests/test_memory_init_cli_layout.py` | CLI: layout каталога сессии, VERIFY журнала. |
| `tests/test_memory_cli_init_task_3_1.py` | CLI: help, путь, базовый сценарий `memory init`. |
| `tests/runtime/test_memory_init_transaction_task_2_1.py` | Транзакция PAG/KB, lock, фазы `NEW`…`ABORTED`. |
| `tests/runtime/test_memory_init_orchestrator_task_2_2.py` | Оркестратор init, shadow journal → merge в канонический journal; stub `agent_memory_result` с `memory_continuation_required`. |
| `tests/runtime/test_memory_init_fix_uc01_uc02.py` | UC-01/UC-02: payload init, VERIFY/summary; gate **11** `memory_init_fix` — [`../artifacts/reports/test_report_final_11_memory_init_fix.md`](../artifacts/reports/test_report_final_11_memory_init_fix.md). |
| `tests/runtime/test_compact_observability_sink.py` | Формат строк `compact.log`, tee stderr. |
| `tests/test_agent_memory_session_log_layout_task_1_1.py` | Режимы лога сессии: `desktop` vs `cli_init` (`ailit-cli-*`, `legacy.log` / `compact.log`). |

**Команда (как в финальном `11` v2, pytest batch2):**

```bash
./.venv/bin/python -m pytest \
  tests/test_memory_init_cli_layout.py \
  tests/test_memory_cli_init_task_3_1.py \
  tests/runtime/test_memory_init_transaction_task_2_1.py \
  tests/runtime/test_memory_init_orchestrator_task_2_2.py \
  -q
```

Subset gate **11** `memory_init_fix` (pytest + flake8, см. отчёт): включает в т.ч. `tests/runtime/test_memory_init_fix_uc01_uc02.py`, `tests/test_g14r0_w14_clean_replacement.py`, `tests/test_g14r8_d_summary_after_am_result.py` — в последних у `_fake_run` добавлен keyword-only `memory_init` под сигнатуру `AgentMemoryQueryPipeline.run`.

Расширенный список путей для flake8 SoT и полный прогон **11** v2 — [`../artifacts/reports/test_runner_final_11.md`](../artifacts/reports/test_runner_final_11.md).

### W14 UC-05 — cooperative cancel (broker + trace ordering)

| Путь / смысл | Содержание |
|----------------|------------|
| `tests/test_g14r_uc05_cooperative_cancel_trace_ordering.py` | CI-инвариант: поля broker JSON (`payload.service` / `payload.action`), порядок compact-событий после cancel в сценарии с задержкой memory pipeline. |
| `AILIT_TEST_MEMORY_PIPELINE_HOLD_S` | Env для удержания pipeline в тесте cancel (изоляция через `RuntimePaths` / `BrokerConfig` — см. файл теста). |
| `desktop/src/renderer/runtime/envelopeFactory.cancel.test.ts` | Vitest: канон полей cancel-envelope для broker (`runtime.cancel_active_turn`), согласовано с `registerIpc.ts` / `preload.ts`. |

Финальный прогон **11** (W14 + Desktop): **81** pytest по `test_g14*.py` и `tests/runtime/test_broker*.py`; **13** Vitest-файлов, **82** теста; `npm run typecheck` — см. `context/artifacts/reports/test_report_11_final_w14_desktop.md`.

### G14 — внешние события AgentMemory (S2)

| Путь / смысл | Содержание |
|----------------|------------|
| `tests/test_g14_agent_memory_external_event_mapping.py` | Golden map stdout→compact и форма `build_external_event_v1` (`agent_memory.external_event.v1`). |

### Broker UC 2.4 (pathless `memory.query_context`, инжект) — G4 task 2.1

| Путь / смысл | Содержание |
|----------------|------------|
| `tests/runtime/test_broker_work_memory_routing.py` | Регрессия trace-тройки и `seen_memory_pair` после `work.handle_user_prompt`. |
| Связанные проверки W14 / PAG (фиксация причин и контрактов) | `tests/test_g14r11_w14_integration.py::test_w14_schema_repair_failure_returns_empty_results`; `tests/runtime/test_memory_agent_global.py::test_agent_memory_query_updates_pag_without_full_repo`; `tests/test_g13_pag_graph_write_service.py::test_rg_upsert_call_sites_match_plan_whitelist`; `tests/test_g14r11_w14_integration.py::test_w14_all_files_processes_multiple_b_not_only_readme`; `tests/test_g14r11_w14_integration.py::test_w14_normal_path_does_not_call_query_driven_pag_growth` (перечень из `change_inventory` / отчёт **11**). |

### W14 graph highlight (M1) — feature 1.2

| Путь / команда | Содержание |
|----------------|------------|
| `tests/runtime/test_w14_graph_highlight_path.py` | M1: upwalk, BFS tie-break, union без дублирования нод. |
| `tests/runtime/test_pag_graph_trace_w14_highlight.py` | Trace/shape W14 row, путь не «один лист» только, пустой `end` не даёт пустой payload в эмите; **`test_python_forbids_pag_graph_rev_reconciled_literal`** — в `memory_agent.py` и `pag_graph_trace.py` нет строки `pag_graph_rev_reconciled` (**D-PROD-1**, dual-write с renderer запрещён). |
| `pytest tests/runtime/test_w14_graph_highlight_path.py tests/runtime/test_pag_graph_trace_w14_highlight.py -q` | Gate W14 для итерации Memory 3D: **7** тестов (M1 + trace + запрет literal в Python); исторический отчёт 1.2 — `context/artifacts/reports/test_report_pipeline_task_1_2.md` (6 passed). |

**Flake8:** `w14_graph_highlight_path.py`, `agent_memory_query_pipeline.py`, оба тест-файла (см. тот же отчёт).

## Desktop (Vitest)

### Финальный Vitest gate — ТЗ §5.0 (Definition of Done)

**UC-03 и UC-06 не считаются закрытыми без обязательных автотестов из ТЗ** (цитата §5.0): для UC-03 — сценарий store / Refresh / Н1–Н2; для UC-06 — Vitest на отсутствие recall-текста в `MemoryGraph3DPage` и тест проекции фазы чата (ротация / синий токен). Финальный gate в `context/tests/INDEX.md` **расширяется** в той же итерации, без отсылки к «решению владельца» как к барьеру.

**Канон прогона (Wave 5, task 4_1):** **12 test files**, **80 tests** — см. `context/artifacts/reports/test_report_task_4_1.md`.

| Путь | Содержание |
|------|------------|
| `desktop/src/renderer/runtime/memoryGraphDataKey.test.ts` | Ключ `computeMemoryGraphDataKey` без `n{nodes.length}`; смена при `loadState`, `graphRevByNamespace`, `pagDatabasePresent`. |
| `desktop/src/renderer/runtime/memoryGraphState.test.ts` | `mergeNodePreservingCoords` / `mergeMemoryGraph`, trace-delta + merge без сброса координат. |
| `desktop/src/renderer/runtime/pagGraphSessionStore.test.ts` | UC-03: store, full load, `pagDatabasePresent`, дедуп `warnings` по rev, интеграция с `pagGraphRevWarningFormat`, Refresh / Н1–Н2. |
| `desktop/src/renderer/runtime/pagGraphTraceDeltas.test.ts` | Парсинг/применение дельт trace; тексты рассинхрона rev (`formatPagGraphRevMismatchWarning`). |
| `desktop/src/renderer/runtime/pagHighlightFromTrace.test.ts` | D-HI-1: highlight из trace → `PagSearchHighlightV1` (расширенные сценарии §4). |
| `desktop/src/renderer/runtime/loadPagGraphMerged.test.ts` | Слияние merged при caps/лимитах. |
| `desktop/src/renderer/runtime/memoryGraphForceGraphProjection.test.ts` | UC-04 / task 2_2: фильтр рёбер, `ensureTraceConnectivity`, merge→проекция. |
| `desktop/src/renderer/runtime/memoryGraph3DResolvedColors.test.ts` | Токены/цвета рёбер 3D. |
| `desktop/src/renderer/runtime/memoryGraph3DLineStyle.test.ts` | Политика линий/частиц рёбер (ТЗ §4). |
| `desktop/src/renderer/runtime/pagGraphLimits.test.ts` | D-SCL-1: caps 20k нод / 40k рёбер, согласование с Python `pag_slice_caps`. |
| `desktop/src/renderer/runtime/chatTraceAmPhase.test.ts` | UC-06: проекция фазы Agent Memory — ротация фраз, токен синего, без дублирования логики broker (task 3_1 / 3_2). |
| `desktop/src/renderer/views/MemoryGraph3DPage.test.tsx` | UC-06: в DOM под корнем 3D-панели нет recall-whitelist и `BROKER_MEMORY_RECALL_UI_LABEL` (task 3_1). |

**Команда (полный gate §5.0):**

```bash
cd desktop && npx vitest run \
  src/renderer/runtime/memoryGraphDataKey.test.ts \
  src/renderer/runtime/memoryGraphState.test.ts \
  src/renderer/runtime/pagGraphSessionStore.test.ts \
  src/renderer/runtime/pagGraphTraceDeltas.test.ts \
  src/renderer/runtime/pagHighlightFromTrace.test.ts \
  src/renderer/runtime/loadPagGraphMerged.test.ts \
  src/renderer/runtime/memoryGraphForceGraphProjection.test.ts \
  src/renderer/runtime/memoryGraph3DResolvedColors.test.ts \
  src/renderer/runtime/memoryGraph3DLineStyle.test.ts \
  src/renderer/runtime/pagGraphLimits.test.ts \
  src/renderer/runtime/chatTraceAmPhase.test.ts \
  src/renderer/views/MemoryGraph3DPage.test.tsx
```

**Связь с Python:** `tests/test_pag_slice_caps_alignment.py` — выравнивание чисел с `tools/agent_core/memory/pag_slice_caps.py` и `desktop/.../pagGraphLimits.ts`. W14 / broker UC 2.4 — строки выше в разделе pytest.

Другие Vitest-файлы в пакете `desktop` (ledger, shell, state и т.д.) **не входят** в этот gate; при изменении контрактов §5.0 gate расширяют осознанно и обновляют эту таблицу и команду.

**Связанные разделы:** [`../INDEX.md`](../INDEX.md), [`../start/INDEX.md`](../start/INDEX.md), [`../proto/INDEX.md`](../proto/INDEX.md), [`../arch/INDEX.md`](../arch/INDEX.md), [`../modules/INDEX.md`](../modules/INDEX.md).
