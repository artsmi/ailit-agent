# Test rerun after 08 (fix_by_tests): W14 broker test + env isolation

## Итог

```json
{
  "overall_status": "passed",
  "summary": "Полный pytest tests/ зелёный после очистки AILIT_WORK_ROOTS в autouse и актуализации проверки trace W14 в test_broker_work_memory_routing."
}
```

## Команда

`.venv/bin/python -m pytest tests/ -q --tb=line`

(дефолтные `addopts` из `pyproject.toml`: `-m 'not integration and not manual_model_e2e'`)

**Результат:** `544 passed, 1 skipped, 2 deselected`

## flake8

`.venv/bin/python -m flake8 tests/conftest.py tests/runtime/test_broker_work_memory_routing.py`

**Результат:** passed

## Изменения

1. **`tests/conftest.py`:** в `isolate_ailit_test_artifacts` добавлены `monkeypatch.delenv("AILIT_WORK_ROOTS")` и `delenv("AILIT_KB_NAMESPACE")` перед выставлением `AILIT_WORK_ROOT`. Иначе после тестов, где AgentWork выставляет `AILIT_WORK_ROOTS` в процессе, `primary_work_root()` продолжал брать **чужой** корень из JSON и ломались `list_dir`, `session_loop`, `read_file` и др.

2. **`tests/runtime/test_broker_work_memory_routing.py`:** контракт trace W14 — порядок после успешного `action.start`: `memory.query_context` AW→AM, ответ AM→AW с `agent_memory_result` / `memory_slice`, затем `context.memory_injected` v2 или continuation-событие.

## Дата

2026-05-01
