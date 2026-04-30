# test_report: fix Pytest five / broker `seen_memory_pair`

## Верификация 08 (2026-04-30, fix `w14_command_output_invalid` vs `path_hint_fallback`)

- **Статус набора из 5 тестов + `test_w14_schema_repair_failure_returns_empty_results` + файл broker:** **passed** (exit 0)
- **Статус полного `pytest` по репозиторию:** **passed** — 535 passed, 1 skipped, 2 deselected (exit 0)
- **flake8** `memory_agent.py`: exit 0

### Команды прогона (факт, агент 08)

```bash
cd /home/artem/reps/ailit-agent

.venv/bin/python -m pytest \
  tests/runtime/test_broker_work_memory_routing.py::test_broker_routes_memory_service_and_work_action \
  tests/runtime/test_memory_agent_global.py::test_agent_memory_query_updates_pag_without_full_repo \
  tests/test_g13_pag_graph_write_service.py::test_rg_upsert_call_sites_match_plan_whitelist \
  tests/test_g14r11_w14_integration.py::test_w14_all_files_processes_multiple_b_not_only_readme \
  tests/test_g14r11_w14_integration.py::test_w14_normal_path_does_not_call_query_driven_pag_growth \
  tests/test_g14r11_w14_integration.py::test_w14_schema_repair_failure_returns_empty_results \
  -v --tb=short
# exit 0 — 6 passed (пять из постановки + регрессия W14 schema repair)

.venv/bin/python -m pytest tests/runtime/test_broker_work_memory_routing.py -vv
# exit 0 — 2 passed
# лог: context/artifacts/reports/test_run_task_2_1_pytest_five_plus_schema.log

.venv/bin/python -m pytest -q
# exit 0 — полный прогон
# лог: context/artifacts/reports/test_run_task_2_1_full_pytest.log

.venv/bin/flake8 tools/agent_core/runtime/subprocess_agents/memory_agent.py
# exit 0
# лог: context/artifacts/reports/test_run_task_2_1_flake8.log
```

---

## История исправления (08): pathless stub / `seen_memory_pair` / W14 reason

- **Pathless v1:** для `memory.query_context` без явного `path` в envelope при пустом `injected_text` мерджится stub из `_fallback_slice` (G13.2), метаданные слайса сохраняются.
- **Регрессия 11:** при `w14_contract_failure` и `reason == w14_command_output_invalid` (двойной провал schema repair) полная замена слайса на `_fallback_slice` больше **не** выполняется — сохраняется телеметрия `w14_command_output_invalid`. Для прочих `w14_contract_failure` с непустым путём (например invalid JSON в broker) по-прежнему применяется path-based fallback с `node_ids` / `injected_text`.

## Изменённые файлы (коммит)

- `tools/agent_core/runtime/subprocess_agents/memory_agent.py`
- `context/artifacts/reports/test_report_fix_pytest_five.md`
- `context/artifacts/reports/test_run_task_2_1_*.log`
- `context/artifacts/developer_08_task_2_1_w14_reason.json`
