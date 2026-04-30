# Тесты — ссылки на канон

Общий контур: изоляция `HOME` / `AILIT_*` в `tests/conftest.py`, маркеры и `addopts` в `pyproject.toml`, запуск из venv репозитория — см. [`../start/repository-launch.md`](../start/repository-launch.md).

## Python (`tests/`)

Изоляция артефактов, pytest, e2e — в проектных правилах workflow и в `tests/conftest.py`. Не путать с vitest desktop.

### Broker UC 2.4 (pathless `memory.query_context`, инжект) — G4 task 2.1

| Путь / смысл | Содержание |
|----------------|------------|
| `tests/runtime/test_broker_work_memory_routing.py` | Регрессия trace-тройки и `seen_memory_pair` после `work.handle_user_prompt`. |
| Связанные проверки W14 / PAG (фиксация причин и контрактов) | `tests/test_g14r11_w14_integration.py::test_w14_schema_repair_failure_returns_empty_results`; `tests/runtime/test_memory_agent_global.py::test_agent_memory_query_updates_pag_without_full_repo`; `tests/test_g13_pag_graph_write_service.py::test_rg_upsert_call_sites_match_plan_whitelist`; `tests/test_g14r11_w14_integration.py::test_w14_all_files_processes_multiple_b_not_only_readme`; `tests/test_g14r11_w14_integration.py::test_w14_normal_path_does_not_call_query_driven_pag_growth` (перечень из `change_inventory` / отчёт **11**). |

### W14 graph highlight (M1) — feature 1.2

| Путь / команда | Содержание |
|----------------|------------|
| `tests/runtime/test_w14_graph_highlight_path.py` | M1: upwalk, BFS tie-break, union без дублирования нод. |
| `tests/runtime/test_pag_graph_trace_w14_highlight.py` | Trace/shape W14 row, путь не «один лист» только, пустой `end` не даёт пустой payload в эмите. |
| `pytest tests/runtime/test_w14_graph_highlight_path.py tests/runtime/test_pag_graph_trace_w14_highlight.py -q` | Статус по `context/artifacts/reports/test_report_pipeline_task_1_2.md` (6 passed, итог pipeline 1.2). |

**Flake8:** `w14_graph_highlight_path.py`, `agent_memory_query_pipeline.py`, оба тест-файла (см. тот же отчёт).

## Desktop (Vitest)

| Область | Путь / команда |
|---------|----------------|
| PAG session store, `pagDatabasePresent`, full load | `desktop/src/renderer/runtime/pagGraphSessionStore.test.ts` |
| Прогон | `cd desktop && npm test` (или сузить до файла) |

### Memory 3D / PAG / trace / 3D визуал (Vitest) — волны W1–W5, финальный gate **11**

**Канон прогона:** `context/artifacts/reports/test_run_11_final.md` (**passed**, 2026-04-30): **9 test files**, 48 tests; логи `context/artifacts/test_run_11_final_vitest.log` / `test_run_11_final_pytest.log`.

| Путь | Содержание |
|------|------------|
| `desktop/src/renderer/runtime/memoryGraphDataKey.test.ts` | Ключ `computeMemoryGraphDataKey` без `n{nodes.length}`; смена при `loadState`, `graphRevByNamespace`, `pagDatabasePresent` (1.3 / 3.1). |
| `desktop/src/renderer/runtime/memoryGraphState.test.ts` | `mergeNodePreservingCoords` / `mergeMemoryGraph`, trace-delta + merge без сброса координат. |
| `desktop/src/renderer/runtime/pagGraphSessionStore.test.ts` | Store: full load, `pagDatabasePresent`, дедуп `warnings` по rev, интеграция с `pagGraphRevWarningFormat`. |
| `desktop/src/renderer/runtime/pagGraphTraceDeltas.test.ts` | Парсинг/применение дельт trace; тексты рассинхрона rev (`formatPagGraphRevMismatchWarning`). |
| `desktop/src/renderer/runtime/pagHighlightFromTrace.test.ts` | D-HI-1: highlight из trace → `PagSearchHighlightV1`. |
| `desktop/src/renderer/runtime/loadPagGraphMerged.test.ts` | Слияние merged при caps/лимитах. |
| `desktop/src/renderer/runtime/memoryGraph3DResolvedColors.test.ts` | Токены/цвета рёбер (task 4.1). |
| `desktop/src/renderer/runtime/memoryGraph3DLineStyle.test.ts` | Политика линий/частиц рёбер (task 4.1). |
| `desktop/src/renderer/runtime/pagGraphLimits.test.ts` | D-SCL-1: caps 20k нод / 40k рёбер, согласование с Python `pag_slice_caps` (task 5.1). |

**Команда (как в gate 11):**

```bash
cd desktop && npx vitest run \
  src/renderer/runtime/memoryGraphDataKey.test.ts \
  src/renderer/runtime/memoryGraphState.test.ts \
  src/renderer/runtime/pagGraphSessionStore.test.ts \
  src/renderer/runtime/pagGraphTraceDeltas.test.ts \
  src/renderer/runtime/pagHighlightFromTrace.test.ts \
  src/renderer/runtime/loadPagGraphMerged.test.ts \
  src/renderer/runtime/memoryGraph3DResolvedColors.test.ts \
  src/renderer/runtime/memoryGraph3DLineStyle.test.ts \
  src/renderer/runtime/pagGraphLimits.test.ts
```

**Связь с Python:** `tests/test_pag_slice_caps_alignment.py` — выравнивание чисел с `tools/agent_core/memory/pag_slice_caps.py` и `desktop/.../pagGraphLimits.ts`. W14 / broker UC 2.4 — строки выше в разделе pytest.

**Примечание:** `chatTraceAmPhase.test.ts` (task 3.2, индикатор «вспоминает») в список финального **11** не входил; при доработке 3.x можно расширить gate отдельной постановкой. Полный `npm test` desktop может задевать тесты вне этого набора (см. исторические отчёты 08/09).
