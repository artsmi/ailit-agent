```json
{
  "overall_status": "passed",
  "summary": "После 08: полный pytest tests/ — 544 passed (см. test_run_11_final_w14_rerun.md). Первоначальный прогон Command 2: failed из-за утечки AILIT_WORK_ROOTS между тестами; исправлено в conftest."
}
```

# Test Runner Report: final_11 (W14 AgentWork↔AgentMemory)

## Контекст

- Режим: `final_11`
- Wave: N/A
- Task: N/A (финальная верификация после волн 1–3, ветка W14)
- База diff для flake8: `origin/fix/desktop_memory` → `HEAD` (коммит базы: `391c6719b4a6f1440b052aa286d1018787a7125b`)

## Команды

### Command 1 — минимальный регресс W14

`.venv/bin/python -m pytest tests/test_g14r1_agent_work_memory_query.py tests/test_g14r_agentwork_memory_continuation.py tests/test_g14r11_w14_integration.py tests/test_work_agent_singleflight.py -q --tb=short`

**Статус:** passed  
**Лог:** `context/artifacts/reports/test_run_11_final_w14_min.log`

### Command 2 — полный `tests/` без integration/live (через addopts)

Точная команда: `.venv/bin/python -m pytest tests/ -q --tb=line`

В репозитории в `pyproject.toml` задано `addopts = "-m 'not integration and not manual_model_e2e'"`, поэтому отдельный `-m "not integration"` не требуется — integration и `manual_model_e2e` уже исключаются по умолчанию.

**Статус:** failed  
**Лог:** `context/artifacts/reports/test_run_11_final_w14_full.log`

### Command 3 — flake8 по изменённым `.py` в диапазоне ветки

`git diff --name-only origin/fix/desktop_memory...HEAD -- '*.py'` → затем `.venv/bin/python -m flake8 <список файлов>`

Изменённые файлы:

- `tests/test_g14r11_w14_integration.py`
- `tests/test_g14r1_agent_work_memory_query.py`
- `tests/test_g14r_agentwork_memory_continuation.py`
- `tests/test_work_agent_singleflight.py`
- `tools/agent_core/runtime/agent_memory_ailit_config.py`
- `tools/agent_core/runtime/agent_memory_result_v1.py`
- `tools/agent_core/runtime/broker.py`
- `tools/agent_core/runtime/subprocess_agents/work_agent.py`

**Статус:** passed  
**Лог:** `context/artifacts/reports/test_run_11_final_w14_flake8.log`

### Объединённый лог

Полный stdout объединённых прогонов: `context/artifacts/reports/test_run_11_final_w14.log`

## Результаты

- Всего проверок (команд): 3
- Passed: 2
- Failed: 1
- Blocked by environment: 0

## Упавшие проверки (Command 2)

| Тест | Кратко | Вероятная причина |
|------|--------|-------------------|
| `tests/runtime/test_broker_work_memory_routing.py::test_broker_routes_memory_service_and_work_action` | `assert False` (стр. 236) | test / code |
| `tests/test_list_dir_vcs.py::test_list_dir_git_shows_immediate_children` | ожидание `README.md` в детях | test |
| `tests/test_list_dir_vcs.py::test_list_dir_project_root_hides_dot_git` | `NotADirectoryError: .git` | test / environment |
| `tests/test_list_dir_vcs.py::test_list_dir_nested_subdir_still_hides_git_folder` | `NotADirectoryError: pkg` | test |
| `tests/test_provider_contract.py::test_mock_write_file_session_roundtrip` | файл не создан | test / code |
| `tests/test_read_file_donor_parity.py::test_builtin_read_file_includes_meta` | `FileNotFoundError` a.txt | test |
| `tests/test_read_symbol_and_read_dup.py::test_read_symbol_top_level_function` | `ok` false, read error | test / code |
| `tests/test_session_loop.py::test_loop_injects_pag_slice_when_available` | генератор не нашёл ожидаемое | test |
| `tests/test_session_loop.py::test_loop_pag_sync_after_write_file` | `assert None is not None` | test |
| `tests/test_session_loop.py::test_loop_two_write_file_one_user_turn` | `FileNotFoundError` a.txt | test |
| `tests/test_session_loop.py::test_loop_auto_kb_search_rate_limited_emits_event` | `assert False` | test |
| `tests/test_tool_runtime_stage4_gate.py::test_read_write_destructive_scenario` | неожиданный `error` на read | test |

Детали трассировок — в полном логе Command 2; часть падений указывает на несогласованные пути/`AILIT_WORK_ROOT` и фиктивные деревья без ожидаемой структуры `.git` (классификация уточняется по логу разработчиком **08**).

## Заблокировано окружением

Нет.

## Verification Gaps

- Live/integration: не запускались (deselected по маркерам).
- Расширенный прогон не дал зелёного полного `tests/`; минимальный W14-набор зелёный.

## Итог

`failed`
