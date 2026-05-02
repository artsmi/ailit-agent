# Feature: memory init fix (UC-03 / VERIFY / UX summary)

## Контекст

Итерация по `context/artifacts/plan.md` (fix memory init); инвентаризация: `context/artifacts/change_inventory.md`.

## Что изменилось в поведении

- Init payload `memory.query_context`: при `memory_init === true` непустые `path`/`hint_path` → `memory_init_path_forbidden`; узкий init по путям не допускается.
- Pipeline: флаг `memory_init` в walk/выборе путей W14; корректировки fallback/post-pipeline для init (см. код).
- Оркестратор CLI init: continuation до VERIFY `memory.result.returned` + `payload.status=complete` или лимит раундов; детерминированный stderr-summary через `memory_init_summary.py`.

## Затронутые зоны кода

- `tools/agent_core/runtime/memory_init_orchestrator.py`, `memory_init_summary.py`, `agent_memory_query_pipeline.py`, `subprocess_agents/memory_agent.py`.

## Канон

- [`../proto/memory-query-context-init.md`](../proto/memory-query-context-init.md) — UC-03/04 init, VERIFY, `cli_init` vs desktop.
- Continuation / `agent_memory_result`: перекрёстно с [`../proto/broker-memory-work-inject.md`](../proto/broker-memory-work-inject.md).

## Тесты

- Новый: `tests/runtime/test_memory_init_fix_uc01_uc02.py`; обновлены orchestrator- и G14-регрессии (см. `context/tests/INDEX.md`).
- Финальный gate **11** по отчёту `context/artifacts/reports/test_report_final_11_memory_init_fix.md`; полный `pytest tests/` в тот же Command не входил — см. gap в inventory.

## Риски / внимание

- При релизе — при необходимости отдельный full-suite прогон вне subset gate.

**Оглавление:** [`index.md`](index.md) · [`../INDEX.md`](../INDEX.md)
