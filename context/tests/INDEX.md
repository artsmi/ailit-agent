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

### Memory 3D layout / graph key (Vitest) — feature 1.3

| Путь / команда | Содержание |
|----------------|------------|
| `desktop/src/renderer/runtime/memoryGraphDataKey.test.ts` | Ключ `computeMemoryGraphDataKey` без `n{nodes.length}`; смена при `loadState`, `graphRevByNamespace`, `pagDatabasePresent`. |
| `desktop/src/renderer/runtime/memoryGraphState.test.ts` | `mergeNodePreservingCoords` / `mergeMemoryGraph`, trace-delta + merge без сброса координат. |
| `desktop/src/renderer/runtime/pagGraphSessionStore.test.ts` | Регресс store (связь с 1.1/1.3). |
| `cd desktop && npx vitest run src/renderer/runtime/memoryGraphDataKey.test.ts src/renderer/runtime/memoryGraphState.test.ts src/renderer/runtime/pagGraphSessionStore.test.ts` | Статус: `context/artifacts/reports/test_report_pipeline_task_1_3.md` (**25 passed**, 3 test files, exit 0). |

**Примечание:** в артефактах 08/09 полный `npm test` мог падать на тестах вне scope задачи (например `AppShell.test.tsx` / unhandled `window`). Для 1.3 DoD — целевой трёхфайловый прогон vitest выше; e2e по `task_1_3` не обязателен при согласовании 09.
