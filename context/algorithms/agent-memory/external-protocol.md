# Внешний протокол AgentMemory: кто вызывает, какие данные и события (External protocol)

**Аннотация:** граница системы: **инициаторы** (оболочка агента через брокер, CLI, другие клиенты брокера), **построчный JSON** между родителем и подпроцессом памяти, **отмена** по side-channel, **коды выхода CLI** и **сигнал сбоя** `memory.actor_unavailable` у AgentWork при `ok: false` от memory RPC. Внутренний порядок шагов конвейера — в [`runtime-flow.md`](runtime-flow.md).

**SoT** и сокращения — в [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-004 | Инициаторы: поля запроса, `query_id`, `user_turn_id`, namespace, корень проекта, лимиты; схемоподобное описание JSON. |
| OR-010 | Внешние события: каталог типов, компактные правила; **фактический** объём journal vs расширенный enum в коде — см. подраздел ниже. |
| OR-011 | CLI `ailit memory init`: запрос по умолчанию, прогресс, семантика кода выхода. |
| OR-012 | Согласование с конвертом `agent_memory_result.v1` для потребителя. |

## Текущая реализация

### Инициаторы и транспорт (факт кода)

| Инициатор | Транспорт до `AgentMemoryWorker` | Как родитель получает trace vs ответ RPC |
|-----------|-----------------------------------|------------------------------------------|
| Оболочка агента (AgentWork) | Брокер пишет в **stdin** подпроцесса `memory_agent` строки JSON (`RuntimeRequestEnvelope`); воркер читает построчно | **stdout** подпроцесса: сначала могут идти строки **без** ключа `ok` (исходящие события / trace), затем **одна** строка ответа с полем **`ok`** (форма ответа RPC). Брокер в `_read_loop` различает их по наличию `ok`. |
| CLI `ailit memory init` / `memory query` | **In-process:** `MemoryInitOrchestrator` / `MemoryQueryOrchestrator` вызывают `worker.handle` без subprocess pipe | Нет разделения stdout trace/RPC у CLI; stderr-сводка и exit — через `memory_init_cli_outcome` / аналог. |
| Другой клиент брокера | Как AgentWork | Как AgentWork. |

**Корреляция RPC:** в запросе и ответе используется **`message_id`**; брокер сопоставляет ответ ожидающему вызову по нему (см. `make_response_envelope` в `tools/agent_core/runtime/models.py`).

### Построчный протокол stdin → child

- Родитель отправляет **ровно одну** JSON-строку на запись в stdin + перевод строки (`to_json_line`).
- Воркер в `_stdin_reader` вызывает `RuntimeRequestEnvelope.from_json_line`. При **невалидном JSON**, исключении парсинга или **несовпадении `contract_version`** с ожидаемой константой строка **отбрасывается** (`continue`): **ни одной** строки ответа на эту строку в stdout **не** пишется (**молчаливый drop**).
- **Следствие для наблюдателя:** с точки зрения ожидающего RPC родитель не отличает drop от «воркер ещё думает» без таймаута; при таймауте брокер возвращает ошибку с кодом **`runtime_timeout`** (см. ниже).

### Отмена: `memory.cancel_query_context` (side-channel)

- Строка stdin, у которой в payload указан сервис **`memory.cancel_query_context`** с тем же **`query_id`**, что у активного запроса, **не** ставится в очередь jobs: вызывается in-process отмена пайплайна (**кооперативная**).
- Воркер **не** шлёт отдельную строку stdout-envelope «ответ на cancel».
- Успешная отмена приводит к тому, что активный `memory.query_context` завершается с ошибкой вида **`memory_query_cancelled`** в нормальном ответном envelope (после прерывания `handle`), а не к молчаливому drop.

### stdout child → parent: trace и финальный ответ

- Во время `handle` при включённом trace (дефолт `broker_trace_stdout=True` в конфиге агента памяти) в stdout могут уходить **дополнительные** JSON-объекты (например `type: topic.publish`) **до** финальной строки ответа RPC. У них **нет** ключа **`ok`**.
- Финальная строка после обработки запроса — словарь с **`ok`** (успех или контрактная ошибка воркера).
- **Запрещено** для автора регрессий: полагать «ровно одна строка stdout на один stdin-запрос» без учёта trace.

### Контрактные ошибки vs crash подпроцесса

- Ошибки, обработанные внутри `AgentMemoryWorker.handle` (неизвестный сервис, отмена, валидация v1, запрет `memory_init` + непустые пути и т.д.), возвращаются как **`ok: false`** + структурированное **`error`** в той же финальной строке stdout.
- **Необработанное исключение** из `handle` в subprocess **не** обёрнуто универсальным `try/except` вокруг вызова в `main` так, чтобы гарантированно записать `ok: false` на stdout: процесс может завершиться **без** финальной строки ответа.
- У брокера stderr подпроцесса памяти направлен в **`DEVNULL`**: диагностика по stderr с родителя **недоступна**; снаружи видны таймаут, «процесс не жив», код выхода процесса (если есть), отсутствие строки с `ok`.

### Брокер: таймаут и недоступность

- Если ожидаемая строка ответа с `ok` не приходит до лимита ожидания (**`queue.Empty`**), брокер возвращает вызывающему **`ok: false`**, **`error.code: runtime_timeout`**.
- Если процесс памяти **не жив** до отправки запроса — **`agent_unavailable`**.
- Сопоставление ответа с ожидающим RPC — по **`message_id`**, поэтому промежуточные trace-строки **не должны** содержать поле `ok` (иначе риск ошибочной маршрутизации).

### AgentWork при `ok: false` от memory RPC

- В `tools/agent_core/runtime/subprocess_agents/work_agent.py`, функция **`_request_memory_slice`**: при ответе брокера с **`ok` не истинно** (в типичной ветке сбоя memory RPC) публикуется событие **`memory.actor_unavailable`** с **`reason: memory_query_failed`** и компактным **`error`** в payload.
- Это **внешний сигнал** для сессии агента: он **не** заменяет полный `agent_memory_result.v1` в пользовательском чате как будто запрос памяти успешно вернул срез.

### Поля payload `memory.query_context` (жёсткие правила worker)

- Если `memory_init` строго **`true`**, поля `path` и `hint_path` в envelope **должны быть пустыми**; иначе **`ok: false`**, **`code: memory_init_path_forbidden`**.
- При включённом флаге чистой замены W14 поле **`requested_reads`** в клиентском payload **отклоняется** целиком: **`ok: false`**, **`code: legacy_contract_rejected`**.
- Для v1 без явного `project_root` worker может подставить корень из **`broker_workspace`**; при пустом `workspace_projects` в payload worker может синтезировать список из workspace-файла брокера.

### Ответ и SoT для продолжения диалога

Ответ содержит срез памяти, конверт `agent_memory_result`, поле `grants` и дублирование части полей на верхнем уровне. **Единый авторитет для продолжения** — объект **`agent_memory_result`**; при конфликте с дублями наверху приоритет у него.

**Заметка для кода:** `ToolExecutor` в основном цикле сессии создаётся без `MemoryGrantChecker`; выданные гранты **не** сужают `read_file` / `read_symbol` автоматически — это **`implementation_backlog`** до явного подключения в AgentWork.

### CLI: коды выхода `ailit memory init`

- Модуль **`tools/agent_core/runtime/memory_init_cli_outcome.py`**: терминальный статус сессии **`complete` \| `partial` \| `blocked`**; приоритет класса прерывания: **SIGINT → exit 130**; **инфраструктурный сбой → 2**; **`complete` → 0**; **`partial` / `blocked` без аварии инфраструктуры → 1** (и иные не-complete без interrupt — по политике оркестратора).
- **Пустой path** в CLI даёт **exit 2** до оркестратора (ошибка использования).
- Сводка на stderr строится с **`exit_kind`** из того же трёхзначного набора (`memory_init_summary.py`).

### Маппинг «сессия CLI» при `ok` воркера

- При **`out["ok"] is not True`** оркестратор вызывает **`terminal_status_worker_not_ok`** → терминальный статус **`partial`** или **`blocked`** по коду/сообщению ошибки.
- При успехе учитывается **`agent_memory_result.status`** и журнал (для init — политика `agent_memory_v1_status_from_envelope` и связанные проверки).

### Корреляция и логи

- В журнале строки связываются с запросом брокера через **`request_id`**; внутри payload шагов W14 фигурирует **`query_id`**.
- Имена compact-событий и golden map stdout→compact — SoT в `tools/agent_core/runtime/agent_memory_external_events.py`; детали маркеров и OR-013 — в [`failure-retry-observability.md`](failure-retry-observability.md).

### Внешние события OR-010: каталог vs production journal

**Для человека:** в типах и docstring перечислен широкий набор `event_type` (включая heartbeat, progress, финальные result-type). В **production** как запись журнала **`memory.external_event`** с envelope **`agent_memory.external_event.v1`** по факту вызовов эмитятся в основном потоке только события ветки **`propose_links`**: **`link_candidates`** и **`links_updated`**. Остальные литералы **не** следует считать обязательными эмиттерами в journal до появления call site в коде.

**Технический контракт (journal, факт):**

- **Required emitters (production path `memory.query_context` + propose_links):** `link_candidates`, `links_updated` (когда ветка выполняется).
- **Default для прочих типов из enum:** не ожидать строку `memory.external_event` в journal как доказательство жизни сессии без отдельного call site.

Форма envelope (поля `schema_version`, `event_type`, `query_id`, `timestamp`, `payload`, …) остаётся общей для типов; для result-type событий в политике запрещены сырой промпт и CoT — см. журнал и redaction в `tools/agent_core/runtime/memory_journal.py`.

## Целевое поведение

### Инициаторы (нормативная матрица)

| Инициатор | Транспорт | Обязательные корреляторы |
|-----------|-----------|-------------------------|
| Оболочка агента (AgentWork) | stdin/stdout брокера к подпроцессу памяти | `user_turn_id`, `query_id`, `namespace`, `project_root` (в payload v1), `message_id` в envelope |
| CLI `ailit memory init` | in-process worker | синтетический `query_id` на раунд оркестратора, `namespace` из определения репозитория, нормализованный `project_root` |
| Другой клиент брокера | как AgentWork | должен повторять контракт v1 |

### Технический контракт: строка stdin (RPC)

**Required:**

- Одна строка = один JSON-объект `RuntimeRequestEnvelope` с валидным `contract_version` и полями маршрутизации, включая **`message_id`**.

**On violation:**

- Строка отбрасывается без stdout-ответа (**silent drop**); родитель при ожидании ответа по **`message_id`** может получить **`runtime_timeout`**.

**Forbidden (для клиента):**

- Считать, что брокер вернёт отдельный diagnostic JSON на каждую битую строку stdin.

### Технический контракт: строки stdout (ответ)

**Required для завершения RPC:**

- Ровно одна финальная строка с объектом, у которого есть **`ok`**, и которая парсится как ответное envelope с тем же **`message_id`**, что в запросе.

**Allowed до финала:**

- Произвольное число строк **без** `ok` — trace / topic.publish.

**Forbidden:**

- Помещать **`ok`** в промежуточные trace-строки (ломает диспетчеризацию брокера).

### Технический контракт: cancel

**Required:**

- Сервис **`memory.cancel_query_context`** на stdin с непустым **`query_id`**, совпадающим с активным запросом.

**Default:**

- Ответной envelope-строки на сам cancel **нет**; результат отмены виден в завершении **`memory.query_context`** (`memory_query_cancelled`).

### Технический контракт: схема `agent_work_memory_query.v1` (фрагмент)

```json
{
  "service": "memory.query_context",
  "schema_version": "agent_work_memory_query.v1",
  "subgoal": "string, required, natural language memory-only goal",
  "user_turn_id": "string, required",
  "query_id": "string, required, unique per sub-goal round",
  "project_root": "string, required, absolute normalized",
  "namespace": "string, required",
  "expected_result_kind": "string, required, whitelist per parser",
  "known_paths": "array[string], required, may be empty",
  "known_node_ids": "array[string], required, may be empty",
  "stop_condition": { "max_rounds": "int", "allow_partial": "bool" },
  "query_kind": "string|omit — advisory from initiator, not validated by v1 parser",
  "level": "string|omit — advisory"
}
```

**Запрещено смешивать** полную пользовательскую задачу без декомпозиции: AgentMemory решает только **подцель памяти**, не end-to-end задачу агента.

### Несколько запросов на один user turn

Инициатор **может** отправить серию `memory.query_context` с разными `query_id`; действует лимит запросов на один `user_turn_id` (конфигурация вида `memory.runtime.max_memory_queries_per_user_turn` с разумными границами).

### Приоритет дубликатов полей

**Норматив:** при конфликте верхнего уровня и `agent_memory_result` для continuation/decisions — **SoT = `agent_memory_result`**; верхнеуровневые поля — зеркало для UX; расхождение — дефект реализации.

### Внешние события (OR-010) — форма envelope (норматив)

Каждое событие в типе: `schema_version: agent_memory.external_event.v1`, поля:

```json
{
  "schema_version": "agent_memory.external_event.v1",
  "event_type": "heartbeat|progress|highlighted_nodes|link_candidates|links_updated|nodes_updated|partial_result|complete_result|blocked_result",
  "query_id": "string, required",
  "timestamp": "string, required, RFC3339",
  "payload": "object, required",
  "truncated": "bool, default false",
  "units": "utf8_chars|node_count|edge_count, required for size-related fields"
}
```

**Долговечные vs эфемерные (цель):** heartbeat и детальный progress — эфемерные; финальные result-type — долговечные на пути результата/журнала, **если** для них существует emitter. **Факт сейчас** для journal — см. подраздел «Внешние события OR-010» в **Текущая реализация**.

#### Кратко по обязательным полям payload (цель, где тип эмитится)

- **`heartbeat`:** `session_alive=true`.
- **`progress`:** `runtime_state`, `message` компактно.
- **`highlighted_nodes`:** `node_ids: string[]`, `reason`.
- **`link_candidates`:** кандидаты **до** S3-валидации (в production при `propose_links`).
- **`links_updated`:** `{ "applied": [...], "rejected": [{ "link_id", "reason"}] }`.
- **`nodes_updated`:** `{ "upserted_node_ids": [], "kind": "B|C|D" }` с лимитами.
- **`partial_result` / `complete_result` / `blocked_result`:** без сырых промптов и CoT.

### CLI `ailit memory init` (OR-011) — цель и проверка

**Целевой UX:**

- Цель по умолчанию — константа уровня продукта; init не подменяет её произвольным `goal` из CLI без политики продукта.
- Прогресс: stderr компактно + фазы оркестратора + тень журнала worker.
- Итоги: статусы **`complete` \| `partial` \| `blocked`** и согласованные коды выхода (`memory_init_cli_outcome.py`).

**Verification gap:** полный ручной smoke в конкретном gate может быть не запрошен; автоматическое доказательство — pytest из раздела **Commands**.

## Examples

### Example 1: Happy path — subprocess, trace, затем RPC

Пользовательский сценарий (AgentWork): брокер отправляет одну валидную строку `memory.query_context` в stdin. Воркер во время `handle` пишет в stdout одну или несколько строк **без** `ok` (trace), затем финальную строку с **`ok: true`** и `agent_memory_result` в payload. Брокер направляет trace в обработчик исходящих событий, а финальную строку возвращает вызывающему RPC по **`message_id`**.

### Example 2: Partial / наблюдаемость — молчаливый drop или таймаут

Оператор или тест отправляет в stdin строку с опечаткой JSON или неверным `contract_version`. Воркер **не** пишет ответ на эту строку. Ожидающий RPC на стороне брокера по таймауту получает **`ok: false`**, **`error.code: runtime_timeout`**. Это **не** то же самое, что контрактная ошибка внутри `handle` (там будет **`ok: false`** с иным `code` в финальной строке).

### Example 3: Failure — AgentWork и `memory.actor_unavailable`

Запрос памяти через брокер завершается с **`ok: false`** (например недоступность процесса или ошибка RPC). `work_agent._request_memory_slice` публикует **`memory.actor_unavailable`** с **`reason: memory_query_failed`**. Пользователь видит внешний сигнал сбоя, а не полный успешный `agent_memory_result.v1` как результат чтения памяти.

## Commands

### Pytest (контракт stdout / envelope / CLI)

```bash
cd /home/artem/reps/ailit-agent
.venv/bin/python -m pytest tests/test_g14_agent_memory_external_event_mapping.py -q
.venv/bin/python -m pytest tests/runtime/test_memory_init_orchestrator_task_2_2.py -q
.venv/bin/python -m pytest tests/runtime/test_memory_init_fix_uc01_uc02.py -q
```

**Expected:** тесты проходят; первый файл — маппинг stdout→compact / форма envelope; остальные — CLI exit и оркестратор init (in-process `handle`).

### Manual smoke (продукт)

```bash
ailit memory init ./
```

**Expected:** при полном успехе exit `0`; при `partial`/`blocked` без инфраструктурной аварии — не `0` по таблице выше; прерывание Ctrl+C — `130` там, где оркестратор классифицирует interrupt.

## Observability

- **Broker / subprocess:** различать **trace-строки** (нет `ok`) и **RPC-ответ** (есть `ok`); не использовать stderr воркера у брокера (DEVNULL).
- **Journal:** `request_id`, `query_id`, строки `memory.request.received`, `memory.slice.returned`, `memory.result.returned` — внутри процесса воркера.
- **Сбой для AgentWork:** topic **`memory.actor_unavailable`** с **`reason: memory_query_failed`** при `ok: false` от memory RPC (см. `work_agent.py`).

## Failure and retry rules

- **FR-EXT-1:** Повтор той же битой stdin-строки без изменений **не** обязан давать ответ; диагностика — исправить JSON / `contract_version` / поля envelope.
- **FR-EXT-2:** Таймаут брокера (**`runtime_timeout`**) при отсутствии финальной строки с `ok` — **required** поведение; нельзя описывать его как «воркер всегда отвечает ok:false на битую строку».
- **FR-EXT-3:** Необработанное исключение в subprocess может дать **отсутствие** финальной строки; снаружи это сходно с таймаутом с точки зрения RPC, но отличается от контрактного `ok: false`.
- **FR-EXT-4:** Cancel — **не** RPC с ответной строкой; ожидать отмену по завершению **`memory.query_context`** с **`memory_query_cancelled`**.
- **FR-EXT-5:** При `ok: false` от memory в AgentWork **required** внешний сигнал **`memory.actor_unavailable`** (как минимум в описанной ветке `work_agent`); нельзя подменять это полным v1 в чате без отдельного контракта продукта.

## Acceptance criteria

1. Читатель различает **транспорт subprocess** (многострочный stdout) и **in-process CLI**.
2. Описаны **silent drop**, **cancel side-channel**, **`runtime_timeout`**, **`agent_unavailable`**, **`message_id`**, **DEVNULL stderr**.
3. Разделены **контрактный `ok: false`** и **crash без строки ответа**.
4. Описан путь **AgentWork** → **`memory.actor_unavailable`** при сбое memory RPC.
5. Таблица кодов выхода CLI согласована с `memory_init_cli_outcome.py` и пустым path → **2**.
6. OR-010: явно разведены **каталог типов** и **фактические journal-эмиттеры** (`link_candidates`, `links_updated`).
7. Команды pytest указывают на существующие тесты репозитория.

## Do not implement this as

- **DNI-EXT-1:** Утверждать «ровно одна строка stdout на один stdin-запрос» без учёта trace.
- **DNI-EXT-2:** Ожидать отдельный stdout-envelope на **`memory.cancel_query_context`** как на обычный RPC.
- **DNI-EXT-3:** Считать, что stderr подпроцесса памяти доступен брокеру для диагностики (сейчас DEVNULL).
- **DNI-EXT-4:** Требовать отдельную строку `memory.external_event` для **каждого** литерала `ExternalEventType` в production journal без call site.
- **DNI-EXT-5:** Описывать сбой memory RPC в AgentWork только как «пустой ответ», игнорируя **`memory.actor_unavailable`**.

## How start-feature / start-fix must use this

- **`02_analyst`** читает этот файл до `technical_specification.md`, если задача касается границы процессов, брокера, CLI init/query или сигналов AgentWork при сбое памяти.
- **`06_planner`** трассирует задачи к строкам **Текущая реализация**, **Failure and retry rules** и **Acceptance criteria**; отдельный файл плана под `plan/17-*.md` не используется — последовательность слайсов задаётся из этого канона и постановки задачи, без расширения scope без явного плана в `plan/`.
- **`11_test_runner`** проверяет команды из раздела **Commands** или помечает blocked по окружению с причиной.
- **`13_tech_writer`** обновляет этот файл только если меняется продуктовый протокол stdin/stdout, cancel, брокера или маппинг CLI/AgentWork.
