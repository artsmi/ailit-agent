# Test Report: task_3_1 (W14 AgentWork↔AgentMemory, gate)

## Контекст

- **Статус:** passed
- **Режим:** developer
- **Task:** `context/artifacts/tasks/task_3_1.md`
- **Wave:** 3
- **Ветка:** `fix/desktop_memory` (gate не включает `npm test` / Vitest в `desktop/`).

## Команды

### Command 1 — pytest (целевой набор task_3_1)

```bash
cd /home/artem/reps/ailit-agent && .venv/bin/python -m pytest \
  tests/test_g14r1_agent_work_memory_query.py \
  tests/test_g14r_agentwork_memory_continuation.py \
  tests/test_g14r11_w14_integration.py \
  tests/test_work_agent_singleflight.py \
  -q
```

**Статус:** passed  
**Exit code:** 0  
**Лог:** `context/artifacts/reports/test_run_11_3_task_3_1.log` (тот же прогон с `-v`)

**Сводка:** 25 passed.

### Command 2 — flake8 (Python, затронутые коммитами относительно merge-base с `origin/fix/desktop_memory`)

Список файлов из `git diff --name-only $(git merge-base HEAD origin/fix/desktop_memory)..HEAD -- '*.py'`:

- `tools/agent_core/runtime/subprocess_agents/work_agent.py`
- `tools/agent_core/runtime/broker.py`
- `tools/agent_core/runtime/agent_memory_result_v1.py`
- `tools/agent_core/runtime/agent_memory_ailit_config.py`
- `tests/test_g14r1_agent_work_memory_query.py`
- `tests/test_g14r_agentwork_memory_continuation.py`
- `tests/test_g14r11_w14_integration.py`
- `tests/test_work_agent_singleflight.py`

```bash
cd /home/artem/reps/ailit-agent && .venv/bin/flake8 \
  tools/agent_core/runtime/subprocess_agents/work_agent.py \
  tools/agent_core/runtime/broker.py \
  tools/agent_core/runtime/agent_memory_result_v1.py \
  tools/agent_core/runtime/agent_memory_ailit_config.py \
  tests/test_g14r1_agent_work_memory_query.py \
  tests/test_g14r_agentwork_memory_continuation.py \
  tests/test_g14r11_w14_integration.py \
  tests/test_work_agent_singleflight.py
```

**Статус:** passed  
**Exit code:** 0  

*(Первый прогон до правки E501 в `test_work_agent_singleflight.py` давал EXIT:1 по E501; после правки — EXIT:0.)*

### Command 3 — D-OBS-1 (литералы compact-событий в `work_agent.py`)

Каноническая команда gate (из постановки):

```bash
rg -n 'memory\.query\.timeout|memory\.query_context\.continuation|memory\.query\.budget_exceeded' \
  tools/agent_core/runtime/subprocess_agents/work_agent.py
```

**Факт выполнения в среде разработчика:** бинарь `rg` (ripgrep) **не установлен** → exit **127** (сообщение shell о `snap`/`apt install ripgrep`).

**Эквивалент для фактической сверки (POSIX `grep`, exit 0):**

```bash
grep -nE 'memory\.query\.timeout|memory\.query_context\.continuation|memory\.query\.budget_exceeded' \
  tools/agent_core/runtime/subprocess_agents/work_agent.py
```

Вывод:

```
339:_MEMORY_QUERY_TIMEOUT_EVENT: Final[str] = "memory.query.timeout"
341:    "memory.query_context.continuation"
496:                    event_type="memory.query.budget_exceeded",
```

**Сверка с `context/artifacts/architecture.md` §5:** топики `memory.query_context.continuation`, `memory.query.timeout`, `memory.query.budget_exceeded` — **совпадает** (дословные имена).

**Сверка с `context/proto/runtime-event-contract.md`:** whitelist для D-OBS-1 — **совпадает**; расхождений имён нет.

## UC-02 A1 (обязательная строка критерия task_3_1)

**N/A** — отдельная обработка «late AM после локального timeout» (корреляция позднего ответа по `query_id`) в объёме волны 1 **не реализована**; зафиксировано как out-of-scope с **детерминированным discard** при таймауте (возврат без успешного memory-path, compact-событие timeout). Цитата из `context/artifacts/tasks/task_1_1.md`:

> **Late response:** если в рамках задачи добавляется обработка ответа после локального timeout — корреляция по `query_id`, без смешения с новым turn (архитектура §9); **иначе явно зафиксировать «out of scope» в отчёте и оставить детерминированный discard.**

Поведение таймаута в коде: `_WorkChatSession._request_memory_slice` — `TimeoutError` / `runtime_timeout` → `_publish_memory_query_timeout(...)` → `return None` (`tools/agent_core/runtime/subprocess_agents/work_agent.py`).

## Ручной smoke (architecture §10)

Стенд desktop недоступен в CI; автотесты выше (в т.ч. UC-01 continuation и W14 integration) = gate.

## Результаты

- Всего проверок: 3 (pytest; flake8; D-OBS-1 сверка имён)
- Passed: 3
- Failed: 0
- Blocked by environment: 0

## Упавшие проверки

Нет.

## Заблокировано окружением

Нет.

## Verification Gaps

- Ручной trace на desktop-стенде не выполнялся; ограничение окружения, не waiver DoD без согласования — регрессия покрыта автотестами перечисленных файлов.

## Итог

passed
