# test_report task_4_1

## Команды

- `pytest -q tests/test_g14r11_w14_integration.py tests/test_g14r2_agent_memory_runtime_contract.py tests/test_g14r_agentwork_memory_continuation.py tests/test_g14r7_agent_memory_result_assembly.py tests/runtime/test_broker_work_memory_routing.py tests/runtime/test_broker_coverage.py tests/test_g14r_uc05_cooperative_cancel_trace_ordering.py`
- `flake8 tests/test_g14r_uc05_cooperative_cancel_trace_ordering.py tools/agent_core/runtime/broker.py tools/agent_core/runtime/subprocess_agents/work_agent.py tools/agent_core/runtime/subprocess_agents/memory_agent.py tools/agent_core/runtime/agent_memory_query_pipeline.py tools/agent_core/runtime/subprocess_agents/work_orchestrator.py`

## Результат

- Все перечисленные тесты: **passed** (50).
- flake8 по путям из секции «Команды» (включая `tests/test_g14r_uc05_cooperative_cancel_trace_ordering.py`): **ok**.

## UC-05

Канонический модуль: `tests/test_g14r_uc05_cooperative_cancel_trace_ordering.py`.

- `test_w14_uc05_cancel_during_memory_query_no_zombie_final_or_completed` — broker subprocess, `AILIT_TEST_MEMORY_PIPELINE_HOLD_S`, инвариант trace.
- `test_w14_uc05_cancel_before_memory_returns_without_hang` — отмена до memory-query без зависания.
