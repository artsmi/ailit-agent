# test_report: fix Pytest five / broker `seen_memory_pair`

- **Статус:** прогон выполнен локально, exit code 0 (5/5 + полный файл broker)
- **Исправление:** `AgentMemory` — для запроса `memory.query_context` в схеме v1 **без** явного `path`/`hint_path` в envelope, если после пайплайна `memory_slice` остаётся с пустым `injected_text` (в т.ч. при `w14_contract_failure` или после `finish_decision` с пустым текстом), к слайсу **мерджится** непустой `injected_text` из `_fallback_slice` (G13.2), метаданные слайса сохраняются.

## Команды прогона (факт)

```bash
cd /home/artem/reps/ailit-agent
.venv/bin/python -m pytest tests/runtime/test_broker_work_memory_routing.py -vv
# exit 0 — 2 passed

.venv/bin/python -m pytest \
  tests/runtime/test_broker_work_memory_routing.py::test_broker_routes_memory_service_and_work_action \
  tests/runtime/test_memory_agent_global.py::test_agent_memory_query_updates_pag_without_full_repo \
  tests/test_g13_pag_graph_write_service.py::test_rg_upsert_call_sites_match_plan_whitelist \
  tests/test_g14r11_w14_integration.py::test_w14_all_files_processes_multiple_b_not_only_readme \
  tests/test_g14r11_w14_integration.py::test_w14_normal_path_does_not_call_query_driven_pag_growth \
  -v --tb=short
# exit 0 — 5 passed

.venv/bin/flake8 tools/agent_core/runtime/subprocess_agents/memory_agent.py
# exit 0
```

## Ожидаемый смысл теста broker

Цепочка: `work.handle_user_prompt` → `memory.query_context` (v1, subgoal `hi`, без `path` в envelope) → в trace есть ответ `AgentMemory:global` → `AgentWork:chat-a` с `memory_slice`, и `topic.publish` / `context.memory_injected` / `usage_state: estimated`. Ранее при `w14_contract_failure` или `w14_finish` с пустым assembly-текстом фоллбек на непустой `injected_text` не применялся; post-guard для pathless v1 устраняет разрыв.

## Изменённые файлы

- `tools/agent_core/runtime/subprocess_agents/memory_agent.py`
- `context/artifacts/reports/test_report_fix_pytest_five.md`
