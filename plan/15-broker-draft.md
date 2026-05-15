# Черновик workflow 15: broker / runtime supervisor (наброски)

**Идентификатор:** `broker-runtime-15-draft` (файл `plan/15-broker-draft.md`).

**Статус:** **черновик** — зафиксировать текущую картину и разрывы по итогам обсуждения; **не** входит в корневой `README.md` до утверждения и замены на нормативный `plan/15-….md`.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## 1. Зачем этот документ

- Единое место для **фактов о текущем рантайме** (supervisor, broker, trace, subprocess-агенты) и **границ с памятью/PAG/KB**.
- Основа для будущего **нормативного** плана 15 (этапы, ID контрактов, тесты, anchors) по правилам workflow.

---

## 2. Термины

| Термин | Смысл в репозитории |
|--------|---------------------|
| **runtime_dir** | Каталог сокетов и durable trace JSONL; выбирается `default_runtime_dir()` / `AILIT_RUNTIME_DIR`. |
| **Supervisor** | Процесс `AilitRuntimeSupervisor`, слушает `supervisor.sock`, держит **in-memory** реестр брокеров. |
| **Broker** | Процесс `AgentBroker` на один `chat_id`, слушает `brokers/broker-<safe>.sock`. |
| **Subprocess-агенты** | `AgentWork`, `AgentMemory`, тестовый `AgentDummy`; stdin/stdout JSON-lines, контракт `ailit_agent_runtime_v1`. |
| **Durable trace** | `trace/trace-<safe_chat_id>.jsonl` под `runtime_dir`, append-only. |
| **Толстый слой memory** | Модули в `tools/agent_core/runtime/*` вокруг AgentMemory (пайплайны, PAG, W14) — **не** отдельные сетевые демоны. |

---

## 3. Выбор `runtime_dir` (в т.ч. `/run/user/<uid>/ailit`)

**Правило (Python + desktop TS):**

1. `AILIT_RUNTIME_DIR` (непустой) — абсолютный путь.
2. Иначе `XDG_RUNTIME_DIR/ailit` — на типичной user-сессии Linux ≈ **`/run/user/<uid>/ailit`**.
3. Иначе `~/.ailit/runtime`.

**Источник истины в коде:** `tools/agent_core/runtime/paths.py` (`default_runtime_dir`, `RuntimePaths`); зеркало: `desktop/src/main/defaultRuntimeDir.ts`.

**Свойства:** под `XDG_RUNTIME_DIR` обычно tmpfs — уместно для **сокетов**; данные могут **исчезать** при смене сессии/ребуте.

**C.1 (не путать):** путь журнала AgentMemory по умолчанию — `~/.ailit/runtime/memory-journal.jsonl` (`memory_journal.default_memory_journal_path`) — **это не** тот же каталог, что `XDG/ailit`, пока явно не задан `AILIT_MEMORY_JOURNAL_PATH`.

---

## 4. Содержимое `runtime_dir` (канон)

| Путь | Назначение |
|------|------------|
| `supervisor.sock` | Unix stream: один JSON-запрос на строку → один JSON-ответ. |
| `brokers/broker-<safe>.sock` | Endpoint брокера для `chat_id`; `safe` = alnum + `-` + `_`. |
| `trace/trace-<safe>.jsonl` | Durable trace: строки = JSON (envelopes, `topic.publish`, и т.д.). |

**D.1:** PAG/KB/глобальный журнал **не** обязаны лежать здесь; источник — `AILIT_PAG_DB_PATH`, `AILIT_KB_DB_PATH`, `AILIT_MEMORY_JOURNAL_PATH` и т.д.

**D.2:** Персистентного файла реестра брокеров **нет** — только RAM супервизора.

---

## 5. Процессы и иерархия

```text
ailit runtime supervisor
    -> AilitRuntimeSupervisor (supervisor.sock)
          -> spawn AgentBroker (subprocess) на chat_id
                -> broker-<safe>.sock
                -> лениво: AgentWork, AgentMemory, AgentDummy
```

**Команда спавна брокера (внутренняя):** `python -m agent_core.runtime.broker` с `--runtime-dir`, `--socket-path`, `--chat-id`, `--namespace`, `--project-root` — см. `BrokerProcessManager` в `supervisor.py`.

**Implementation anchors (текущие):** `supervisor.py`, `broker.py`, `paths.py`, `trace_store.py`, `models.py`, `subprocess_agents/{work_agent,memory_agent,dummy_agent}.py`, `tools/ailit/runtime_cli.py`, `tools/ailit/chat_app.py` (runtime toggle), `desktop/.../defaultRuntimeDir.ts`.

---

## 6. Протокол супервизора

- Транспорт: `supervisor_request()` — connect → send JSON line + `\n` → recv JSON line.
- `cmd`: `status`, `brokers`, `create_or_get_broker` (`chat_id`, `namespace`, `project_root`), `stop_broker` (`chat_id`).

**Файл:** `tools/agent_core/runtime/supervisor.py`.

---

## 7. Протокол брокера

- `ThreadingMixIn` + Unix server на `socket_path` брокера.
- Спец-строки: `ping` → `pong`; `{"cmd":"subscribe_trace"}` — долгая подписка, пуш JSONL-строк trace.
- Иначе: строка = `RuntimeRequestEnvelope` → `RuntimeResponseEnvelope` (см. `broker.py` → `AgentBroker.handle_request`).

Маршрутизация: `topic.publish` (fan-out), `service.request` (по эвристике `to_agent`), `action.start` (в т.ч. дефолт `work.handle_user_prompt` → AgentWork).

---

## 8. Subprocess-агенты: транспорт stdin/stdout

- **Запрос:** `RuntimeRequestEnvelope.from_json_line` на stdin.
- **Ответ с ожиданием:** JSON с полем `ok` → брокер матчит `message_id` в `queue`.
- **События без `ok`:** брокер трактует как исходящий envelope, пишет в trace и в live-подписчики (см. `_AgentProcess._read_loop` в `broker.py`).

**AgentWork:** `work.handle_user_prompt` — фоновый thread + стрим `topic.publish` (assistant / action).  
**AgentMemory:** `memory.query_context` и PAG-наблюдаемость; graph trace — `emit_pag_graph_trace_row` (stdout).  
**AgentDummy:** только тесты, чистый request/response.

---

## 9. Контракт `ailit_agent_runtime_v1`

- `CONTRACT_VERSION` в `tools/agent_core/runtime/models.py`.
- `MemoryGrant`, `agent_work_memory_query.v1` / `parse_agent_work_memory_query_v1` — для Work↔Memory.

**UI-заметка (Streamlit):** в `_send_work_prompt_to_broker` зашит `created_at` фиксированной строкой — при аудите времени **не** считать эталоном; для плана 15: либо **исправить** на `RuntimeNow`, либо **явно** пометить как advisory.

---

## 10. `AgentRegistry` (разрыв)

- Код `tools/agent_core/runtime/registry.py` реализует структуру реестра агентов для UI/брокера.
- **Факт:** в `AgentBroker` / supervisor **не подключён** (по коду — использование в основном в тестах `test_registry*.py`).

**A.1 (audit):** либо интегрировать в hot path + UI, либо зафиксировать как **заготовку** и убрать путаницу в нормативном плане.

---

## 11. `broker_placeholder`

- `broker_placeholder.py` — минимальный сокет для healthcheck/ранних тестов; **не** продуктовый путь.

---

## 12. Тесты и изоляция

- Корневой `conftest.py` — `isolate_ailit_test_artifacts`: `AILIT_RUNTIME_DIR` в `tmp_path`, плюс PAG/KB/journal/config — чтобы не трогать `~/.ailit` и `/run/user/...`.

---

## 13. Systemd (установка)

- Ожидаемо: `Environment=AILIT_RUNTIME_DIR=%t/ailit` → согласовано с `default_runtime_dir` (см. `context/proto/install.md`, `tests/test_install_systemd_g8_7.py`).

---

## 14. Вопросы к полноценному plan/15 (после утверждения черновика)

1. **C.1 / журнал vs runtime_dir:** явная политика: держать journal в home, в state, или под `%t/ailit` (и риск потери).
2. **A.1 / AgentRegistry:** интеграция или удаление из публичного `__all__` / доков.
3. **Персистентный supervisor state:** нужен ли файл registry после рестарта (сейчас **нет**).
4. **Нормативные этапы (Gx.y):** контракты сокетов, exact tests, anti-patterns «параллельный модуль без anchors» — по чек-листу `project-workflow.mdc`.
5. **E2E / ручной smoke:** сценарий «supervisor → broker → chat prompt → tail trace».

---

## 15. Следующий шаг

После согласования: заменить этот черновик на **нормативный** `plan/15-….md` с таблицей трассировки ID → этап, **тогда** при необходимости добавить ссылку в корневой `README.md` (по отдельной задаче).
