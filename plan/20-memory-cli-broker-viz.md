# G20: `ailit memory` CLI — маршрут через runtime broker, визуализация по trace

**Статус:** план внедрения (код не закрыт этим файлом).  
**Цель:** все пользовательские глаголы **`ailit memory index|init|query`** выполняют работу **только** через **AgentBroker** → subprocess **AgentMemory** (как в desktop), чтобы журнал/trace и live-`subscribe_trace` отражали тот же путь, что и продуктовый runtime. Отдельно: локальная HTML-визуализация (две вкладки, brandbook, авто-браузер), подпитка событиями из broker; отключение **только флагом** `--no-memory-viz` (имя зафиксировать в реализации; синоним в help допускается).

**Non-scope (волна 1):**

- `ailit memory pag-slice` остаётся **прямым чтением SQLite** для IPC desktop (`G9.8`); перенос на broker — отдельный слайс, если понадобится единый SoT для чтения.
- Изменения **Electron / `ailit desktop`** не требуются для закрытия G20 (клиент broker уже есть в desktop).
- Новые systemd-unit и смена транспорта supervisor не входят в G20.

---

## 1. Текущая реальность (audit)

| ID | Наблюдение | Источник правды |
|----|--------------|-----------------|
| A1 | `memory index` вызывает `index_project_to_default_store` / `PagIndexer` **в процессе CLI**, SQLite PAG обновляется, **broker и trace не участвуют**. | `ailit/ailit_cli/memory_cli.py` (`cmd_memory_index`) |
| A2 | `memory init` оркестрирует PREPARE→worker→VERIFY через **`AgentMemoryWorker` in-process** (`MemoryAgentConfig`, `broker_trace_stdout=False`), конверты `memory.query_context` с `memory_init: True`. **Broker не используется.** | `ailit/agent_memory/memory_init_orchestrator.py` |
| A3 | `memory query` аналогично in-process **`AgentMemoryWorker.handle`**, continuation-раунды в цикле. **Broker не используется.** | `ailit/agent_memory/memory_query_orchestrator.py` |
| A4 | Subprocess **AgentMemory** в broker обрабатывает `service.request` с `memory.file_changed`, `memory.change_feedback`, **`memory.query_context`**; иной `service` → `unknown_service`. | `ailit/ailit_runtime/subprocess_agents/memory_agent.py` (`handle`, ~1595–1621) |
| A5 | Broker пишет каждый обработанный envelope в durable trace и **broadcast** подписчикам с первой строкой `{"cmd":"subscribe_trace"}`. | `ailit/ailit_runtime/broker.py` (`append_trace`, `_BrokerHandler`) |
| A6 | Supervisor даёт registry broker-ов (`brokers`, `create_or_get_broker`). Клиентский паттерн: Unix socket, JSON line, отдельное соединение для `subscribe_trace`. | `context/proto/supervisor-json-socket.md`, `tests/runtime/test_broker_routing.py` |

---

## 2. Команды CLI: что делают сейчас (зафиксировано)

### 2.1 `ailit memory index`

- **Вход:** `--project-root` (по умолчанию cwd), опционально `--db-path`, `--full`.
- **Действие:** инкрементальный или полный прогон **PAG indexer** в SQLite store (`PagIndexer` / `index_project_to_default_store`), вычисление namespace по корню проекта внутри индексатора.
- **Выход:** одна строка JSON в stdout (`PagIndexResult`: `ok`, `namespace`, `db_path`, `project_root`), код возврата `0` при успехе.
- **Побочные эффекты:** рост `graph_rev` в store при записи узлов/рёбер (offline writer), без trace runtime.

### 2.2 `ailit memory init <path>`

- **Вход:** обязательный корень проекта (path).
- **Действие:** деструктивная re-init памяти для PAG namespace репозитория (§4.2): транзакция журнала, фазы оркестратора, цикл **`memory.query_context`** с **`memory_init: true`** и `memory_init_round`, вызовы **`AgentMemoryWorker`** in-process до завершения/частичного/blocked; компактные логи в уникальной CLI session dir.
- **Выход:** человекочитаемый stderr + summary; код `0` / `1` / `130` по политике `memory_init_exit_code` (как в существующих тестах init).
- **Побочные эффекты:** запись PAG, journal, compact logs; **не** broker trace.

### 2.3 `ailit memory query [--project] <query_text>`

- **Вход:** текст запроса; опционально `--project` (корень), иначе cwd.
- **Действие:** цикл **`memory.query_context`** через **`AgentMemoryWorker`** in-process с continuation по `agent_memory_result.memory_continuation_required`; compact sink + session dir.
- **Выход:** stderr/summary; код возврата по `memory_init_exit_code` семантике query.
- **Побочные эффекты:** чтение/запись PAG по политике query-driven growth; **не** broker trace.

---

## 3. Целевые контракты (решения)

| ID | Контракт |
|----|-----------|
| D1 | Любой из **`index` / `init` / `query`** в режиме по умолчанию **обязан** завершать полезную работу **только** после успешного RPC на **broker Unix socket** к subprocess **AgentMemory** (или явной цепочке supervisor→broker, если broker ещё не поднят — см. D4). In-process **`AgentMemoryWorker`** из CLI для этих глаголов **запрещён** (anti-pattern ниже). |
| D2 | Транспорт запроса к broker: **одна строка** JSON `RuntimeRequestEnvelope` + `\n`; ответ — одна строка `RuntimeResponseEnvelope` + `\n` (как сейчас в `AgentBroker`). |
| D3 | **`memory index`** в целевом состоянии маппится на новый **`service.request`** с полем `service` (точное имя выбрать в реализации, например **`memory.index_project`**) и payload: `project_root`, `full`, опционально `db_path` / ссылка на store resolution policy, `request_id`. Обработчик в **AgentMemory subprocess** вызывает тот же кодовый путь, что сегодня CLI (вынести общую функцию из `memory_cli` / indexer), чтобы PAG и `graph_rev` совпадали с A1. |
| D4 | **Разрешение broker endpoint:** (1) флаг **`--broker-socket`** = путь к Unix socket файла; или (2) **`--runtime-dir`** + **`--broker-chat-id`** + вызов supervisor `brokers` / при отсутствии — `create_or_get_broker` с `namespace` + `project_root` из команды. Политика «создавать ли broker из CLI» — **fail-fast**, если не передан явный socket и broker не найден (сообщение: поднять supervisor и desktop/CLI create). *Альтернатива «auto create»* — только если явно добавлен флаг `--ensure-broker` (по умолчанию **off**, чтобы не плодить broker в CI). |
| D5 | **Визуализация:** при отсутствии `--no-memory-viz` CLI поднимает локальный HTTP-сервер, открывает браузер; фоновый поток держит второе соединение **`subscribe_trace`** к **тому же** broker socket; UI агрегирует релевантные строки trace (whitelist имён событий / типов envelope — зафиксировать в коде и здесь в G20.6). Заполнение геометрии 3D при нехватке полей в trace — **гибрид**: редкий опрос `pag-slice` по `namespace` (read-only, не замена SoT событий). |
| D6 | Opt-out визуализации и лишних соединений: **только** флаг **`--no-memory-viz`** (без env-переменной). |
| D7 | **`init` и `query`** остаются на **`service` = `memory.query_context`** с существующими полями (`memory_init`, `goal`, `workspace_projects`, …); меняется только **транспорт** (broker вместо in-process worker). Логика continuation на стороне CLI: читать ответ broker, при `memory_continuation_required` слать **следующий** `service.request` с новым `message_id` / раундом по текущим правилам оркестраторов. |
| D8 | Идентичность `chat_id` / `trace_id` / `broker_id` в envelope должны быть **согласованы** с broker config (`BrokerConfig.chat_id`, `broker_id` в ответах). Для CLI-сессии использовать стабильный `chat_id` из флага или сгенерированный `cli-memory-<uuid>` и передавать его во все RPC одной сессии команды. |

---

## 4. Anti-patterns

- **Не** оставлять «тихий» in-process `AgentMemoryWorker` для `init`/`query` при отсутствии флага: это дублирует код и ломает цель G20 (A2–A3).
- **Не** слать index только в trace как «событие» без записи PAG в AgentMemory: визуализация не заменяет SoT графа.
- **Не** подключать `subscribe_trace` к supervisor socket (там нет subscribe) — только к **broker** socket.
- **Не** использовать env `AILIT_MEMORY_NO_GRAPH` — пользователь выбрал **только флаг** (D6).

---

## 5. Трассировка: этап → обязательные ID

| Этап | Обязательные описания/выводы (ID) |
|------|-----------------------------------|
| G20.1 | A1–A6 задокументированы; список новых/изменяемых файлов согласован. |
| G20.2 | D2, D4, D8: общий модуль **broker JSON client** (connect, send request, read one line, optional `subscribe_trace` reader) с таймаутами; переиспользование в CLI и тестах. **Anchors:** новый модуль под `ailit/ailit_cli/` или `ailit/ailit_runtime/`, `tests/runtime/test_broker_routing.py` как референс поведения. **Сделано (2026-05-14):** `ailit/ailit_cli/broker_json_client.py` (`BrokerJsonRpcClient`, `BrokerTraceSubscriber`, `BrokerTraceBackgroundCapture`, `resolve_broker_socket_for_cli`, `call_on_trace_capture`); `tests/runtime/test_broker_routing.py` вызывает `call_on_trace_capture`. |
| G20.3 | D1, D7: `memory query` через broker; удаление/обход in-process пути по умолчанию; сохранение exit codes и stderr UX. **Anchors:** `memory_query_orchestrator.py`, `memory_cli.py`, `cli.py` argparse. **Сделано (2026-05-14):** обязательные `--broker-chat-id`, опционально `--broker-socket` / `--memory-runtime-dir`; `MemoryQueryOrchestrator.run(broker_invoke=…, broker_chat_id=…)`; клиент перенесён в `ailit_runtime/broker_json_client.py`, shim `ailit_cli/broker_json_client.py`. |
| G20.4 | D1, D3: новый `memory.index_project` (имя финализировать) в `memory_agent.py` + реализация в worker/общем helper; `cmd_memory_index` только вызывает broker RPC. **Anchors:** `memory_cli.py`, `memory_agent.py`, `pag_indexer.py`. |
| G20.5 | D1, D7: `memory init` через broker + continuation loop в CLI (логика раундов как сейчас, транспорт заменить). **Anchors:** `memory_init_orchestrator.py`, `memory_cli.py`. |
| G20.6 | D5, D6: HTTP server + статика (две вкладки, brandbook `design/BRANDBOOK_CANDY.md`), `webbrowser.open`, `subscribe_trace` consumer; гибрид `pag-slice` при необходимости. **Anchors:** `memory_cli.py`, новый каталог static (например `ailit/ailit_cli/static/memory_viz/`). |
| G20.7 | Регрессия: pytest по затронутым модулям + flake8; новые тесты **только если постановка явно расширена** (пользовательский запрет на произвольные тесты по умолчанию — см. user rules); минимум расширить существующие broker/memory тесты, если добавляется сервис. **Проверка:** `rg` что `AgentMemoryWorker(` не вызывается из `memory_query_orchestrator` / `memory_init_orchestrator` в prod-пути (whitelist тестовых модулей оформить в комментарии этапа). |

**Зависимости:** G20.2 до G20.3–G20.5; G20.3–G20.5 можно параллелить после контракта имени `memory.index_project`; G20.6 зависит от G20.2 и любого RPC, генерирующего trace (хотя бы `query`).

---

## 6. Exact tests / static checks (минимум при реализации)

- `tests/runtime/test_broker_routing.py` — не ломать сценарий `subscribe_trace` + `service.request`.
- Новый тест **по согласованию постановки:** e2e-light tmp broker + вызов функции «как CLI» для `memory.index_project` и проверка записи в SQLite + строка в trace (имя теста зафиксировать в коммите G20.4).
- `flake8` на всех новых/изменённых `.py`.

---

## 7. Observability (кратко)

- Каждый broker RPC для memory CLI уже попадает в `append_trace` (запрос и ответ) — визуализатор читает тот же поток, что desktop durable trace.
- Дополнительно (по необходимости): один компактный `topic.publish` от CLI с `event_name` вида `memory_cli_command_started` **запрещён** как замена D1 (не дублировать события без RPC); если нужен маркер фазы, использовать поля в существующих compact-событиях memory worker.

---

## 8. Manual smoke (после кода)

1. `ailit runtime supervisor` в отдельном терминале; создать broker (`ailit runtime brokers` / desktop project / `create_or_get_broker`).
2. `ailit memory query "…" --broker-socket …` без `--no-memory-viz` — браузер, на trace появляются ответы AgentMemory.
3. `ailit memory index --project-root …` — те же проверки + рост узлов в 3D/вкладке ноды.
4. `ailit memory init ./proj` — завершение сценария, trace содержит раунды init.
5. Повтор с `--no-memory-viz` — нет listen-порта, нет `webbrowser.open`.

---

## 9. Definition of Done (G20)

- Три глагола **только** через broker subprocess path при default flags.
- Документированный флаг **`--no-memory-viz`**; нет env opt-out.
- План выполнен по таблице §5; ограничения §1 non-scope соблюдены.

---

## 10. Связь с каноном

- Runtime broker/supervisor: `plan/8-agents-runtime.md`, `context/proto/supervisor-json-socket.md`, `context/proto/desktop-electron-runtime-bridge.md` (раздел broker; CLI становится таким же классом клиентов, как main process для изолированных вызовов — но теперь для memory не in-process worker).
- PAG / memory алгоритмы: `context/algorithms/agent-memory/INDEX.md` (не менять семантику init/query, только транспорт).

---

## 11. Donor ref (идея, не копипаст)

| Donor file | Строки (инклюзив) | Зачем |
|------------|-------------------|--------|
| `/home/artem/reps/ailit-agent/tests/runtime/test_broker_routing.py` | 68–120 | Паттерн Unix broker + `subscribe_trace` + `service.request` в тестах. |
| `/home/artem/reps/ailit-agent/ailit/ailit_runtime/broker.py` | 637–702 | Обработчик сокета: `ping`, `subscribe_trace`, envelope. |
