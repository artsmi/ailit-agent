# Workflow 8: low-level agents runtime + broker supervisor

**Идентификатор:** `agents-runtime-8` (файл `plan/8-agents-runtime.md`).

Документ задаёт следующую итерацию после закрытия `Workflow 7`: перевести главный runtime `ailit` от модели «UI запускает один session loop» к модели **низкоуровневых runtime-агентов**, которые общаются через отдельный broker и наблюдаются в UI. Главный пользовательский результат: `ailit chat` становится клиентом/наблюдателем, а выполнение задачи живёт в `ailit` runtime: `AilitRuntimeSupervisor` → `AgentBroker` на чат → subprocess-agents (`AgentWork`, `AgentMemory`, тестовый `AgentDummy`).

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Положение в графе планов

- **Workflow 7 закрыт по подтверждению пользователя:** PAG, `ailit memory`, `AgentMemory` / `AgentWork` и post-edit sync считаются реализованной базой, от которой стартует текущий workflow.
- **Workflow 8 не расширяет PAG:** он выносит runtime-общение агентов, lifecycle, supervisor, broker, systemd-установку и UI trace в отдельный слой.
- **`ailit chat` больше не центр runtime:** chat остаётся Streamlit-клиентом, отправляет user prompt в broker и подписывается на trace/events.
- **Один `ailit chat` = один `AgentBroker`:** каждый chat получает свой broker и свою пару `AgentWork` / `AgentMemory`; все `AgentMemory` используют общую DB PAG/KB.
- **Supervisor как ROS-like master:** user-level `systemd` service `ailit.service` запускает локальный `AilitRuntimeSupervisor`, который принимает запросы от `ailit chat`, спавнит broker-ы, ведёт registry и healthcheck.
- **Связь one-to-many обязательна:** будущий `ProductAgent` должен управлять несколькими low-level agents через topic/action/service модель без переписывания runtime.

---

## Порядок реализации стратегии

Эта стратегия исполняется строго по этапам. После логического завершения каждого этапа выполняются проверки из этапа и создаётся отдельный коммит с префиксом `agents-runtime-8/G8.n`.

1. **G8.0** — design note, термины, контракты и системные границы.
2. **G8.1** — модели сообщений, registry и durable trace store.
3. **G8.2** — `AilitRuntimeSupervisor` + локальный API + registry broker-ов.
4. **G8.3** — `AgentBroker` как отдельный процесс и ROS-like routing (`topic` / `service` / `action`).
5. **G8.4** — subprocess agents: `AgentWork`, `AgentMemory`, внутренний `AgentDummy`.
6. **G8.5** — `MemoryGrant` enforcement: `path + lines`, `whole_file=true` только по явному grant.
7. **G8.6** — `ailit chat` как client/viewer + отдельная вкладка agent trace.
8. **G8.7** — локальная установка через `scripts/install`: `systemd --user`, `ailit.service`, journalctl, upgrade path.
9. **G8.8** — e2e сценарии, деградации и readiness для будущего `ProductAgent -> many`.

Если после G8 понадобится сетевой/distributed runtime, multi-host discovery, внешний broker или полноценный high-level `ProductAgent`, это оформляется новым workflow.

---

## Нормативная модель

### Low-level runtime agents

Low-level agent — постоянная роль внутри runtime, отвечающая за узкую часть исполнения:

- **`AgentWork`** — принимает пользовательскую задачу, планирует выполнение, вызывает tools, пишет/меняет код, но читает проектные файлы только через grants от `AgentMemory`.
- **`AgentMemory`** — владеет PAG/KB retrieval, dark zones, memory updates, staleness policy и выдаёт `MemoryGrant` с `path + lines`.
- **`AgentDummy`** — внутренний тестовый агент для проверки extension contract; пользователю не показывается как продуктовая возможность.

Не путать с high-level agents: будущий `ProductAgent` будет декомпозировать пользовательские/продуктовые цели и управлять группой low-level agents. G8 готовит substrate для этого, но не реализует полноценный high-level planner.

### Supervisor, broker, agents

```
systemd --user: ailit.service
        |
        v
AilitRuntimeSupervisor
        |
        +-- AgentBroker(chat_id=A)
        |       +-- AgentWork:A
        |       +-- AgentMemory:A
        |       +-- AgentDummy:A (tests only)
        |
        +-- AgentBroker(chat_id=B)
                +-- AgentWork:B
                +-- AgentMemory:B

Shared local DB: PAG / KB / runtime trace / broker registry
```

`AilitRuntimeSupervisor` живёт дольше UI, принимает запросы от `ailit chat`, спавнит broker-ы и отдаёт endpoint конкретного broker. `AgentBroker` живёт в рамках chat runtime и является локальным маршрутизатором сообщений для агентов этого chat.

---

## Доноры и паттерны без копипаста

| Донор | Локальная ссылка | Что взять |
|-------|------------------|-----------|
| **OpenCode bus** | `/home/artem/reps/opencode/packages/opencode/src/bus/index.ts:24-40`, `/home/artem/reps/opencode/packages/opencode/src/bus/index.ts:82-100`, `/home/artem/reps/opencode/packages/opencode/src/bus/global.ts:1-12` | Typed pub/sub + wildcard subscriptions; отдельный global event channel для UI/наблюдателей. |
| **OpenCode session events** | `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:6-74`, `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:92-140` | Типизированные события с id/timestamp/metadata; разделение prompt/step/tool событий. |
| **ai-multi-agents runtime** | `/home/artem/reps/ai-multi-agents/tools/runtime/models.py:30-53`, `/home/artem/reps/ai-multi-agents/tools/runtime/events.py:14-49`, `/home/artem/reps/ai-multi-agents/tools/runtime/event_log.py:11-27` | Append-only JSONL event log, event factory, projection-friendly runtime events. |
| **Graphiti queue** | `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:12-20`, `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:24-47`, `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:49-80` | Очередь на `group_id`: сериализация ingest/update задач для одной группы/namespace. |
| **claude-code coordinator** | `/home/artem/reps/claude-code/coordinator/coordinatorMode.ts:29-34`, `/home/artem/reps/claude-code/coordinator/coordinatorMode.ts:116-145`, `/home/artem/reps/claude-code/tools/AgentTool/runAgent.ts:292-300`, `/home/artem/reps/claude-code/tools/AgentTool/runAgent.ts:334-359` | Координатор/worker модель, capability isolation, отдельный tool pool для subagents, trace hierarchy. |
| **ailit текущий session loop** | `tools/agent_core/session/event_contract.py:16-31`, `tools/agent_core/session/loop.py:393-413` | Уже есть `SessionEventSink` и `_emit`; G8 расширяет это до runtime trace events. |
| **ailit file tools** | `tools/agent_core/tool_runtime/builtins.py:64-109`, `tools/agent_core/tool_runtime/read_file_envelope.py:29-47` | Точка enforcement для `MemoryGrant`: `read_file` уже имеет `path`, `offset`, `limit`, meta с line range. |
| **ailit install/chat** | `scripts/install:1-11`, `scripts/install:26-36`, `scripts/install:54-71`, `tools/ailit/cli.py:132-153`, `tools/ailit/chat_app.py:1077-1203` | Installer расширяется systemd user service; chat становится client/viewer и подписчиком trace. |

ROS2 используется как архитектурная аналогия, а не зависимость: **topics** для one-to-many событий, **services** для коротких request/reply, **actions** для долгих задач с feedback/cancel/result, **namespaces** для chat/project isolation, **lifecycle** для supervisor/broker/agent states.

---

## Runtime contract `ailit_agent_runtime_v1`

### Общие поля

Каждое сообщение и событие содержит:

```json
{
  "contract_version": "ailit_agent_runtime_v1",
  "runtime_id": "uuid",
  "chat_id": "uuid-or-stable-id",
  "broker_id": "broker-chat-id",
  "trace_id": "uuid",
  "message_id": "uuid",
  "parent_message_id": null,
  "goal_id": "uuid",
  "namespace": "repo-namespace",
  "from_agent": "AgentWork:chat-id",
  "to_agent": "AgentMemory:chat-id",
  "created_at": "2026-04-25T00:00:00Z"
}
```

### Topics: one-to-many

Используются для событий, на которые может подписаться несколько потребителей:

- `agent.trace`
- `agent.lifecycle`
- `memory.updated`
- `goal.started`
- `goal.finished`
- `policy.violation`

Пример:

```json
{
  "type": "topic.publish",
  "topic": "agent.trace",
  "event_name": "memory.grant.issued",
  "from_agent": "AgentMemory:chat-A",
  "payload": {
    "summary": "Issued 2 path+lines grants",
    "grant_count": 2
  }
}
```

### Services: request/reply

Используются для коротких запросов с одним адресатом, timeout и structured error:

- `memory.query_context`
- `memory.sync_changes`
- `agent.health`
- `broker.describe`

Пример:

```json
{
  "type": "service.request",
  "service": "memory.query_context",
  "request_id": "req-1",
  "from_agent": "AgentWork:chat-A",
  "to_agent": "AgentMemory:chat-A",
  "payload": {
    "intent": "explore_entrypoints",
    "need": "entrypoints and nearby modules",
    "grant_shape": "path_lines"
  }
}
```

### Actions: long-running work

Используются для долгих задач с progress/cancel/result:

- `work.handle_user_prompt`
- `memory.reindex_project`
- `memory.prepare_context`
- future: `product.execute_goal`, `test.run_plan`, `review.check_diff`

Action-события:

- `action.started`
- `action.feedback`
- `action.cancel_requested`
- `action.completed`
- `action.failed`

---

## MemoryGrant contract

`AgentWork` не имеет права читать проектные файлы без grant от `AgentMemory`.

Минимальная форма:

```json
{
  "grant_id": "grant-uuid",
  "issued_by": "AgentMemory:chat-A",
  "issued_to": "AgentWork:chat-A",
  "namespace": "repo-namespace",
  "path": "tools/ailit/cli.py",
  "ranges": [
    {"start_line": 1, "end_line": 180}
  ],
  "whole_file": false,
  "reason": "entrypoint shortlist",
  "expires_at": "2026-04-25T01:00:00Z"
}
```

Правила:

1. `path + lines` обязательны всегда.
2. `whole_file=true` допустим только как явный grant от `AgentMemory`; в этом случае ranges может содержать фактический диапазон всего файла после определения `total_lines`.
3. При отсутствии grant чтение блокируется ошибкой `memory_grant_required`.
4. Нарушение не превращается в silent fallback; UI показывает `Memory unavailable` или `MemoryGrant required`.
5. `read_file`, `read_symbol`, range-read и будущие code-read tools используют один checker.

---

## Systemd / install contract

`scripts/install` должен устанавливать не только Python venv и shim, но и local runtime service.

Целевая команда:

```bash
./scripts/install
```

Должна:

1. Установить/обновить venv как сейчас.
2. Создать/обновить `~/.local/bin/ailit`.
3. Установить user systemd unit:

```ini
[Unit]
Description=ailit runtime supervisor

[Service]
ExecStart=%h/.local/bin/ailit runtime supervisor
Restart=on-failure
Environment=AILIT_RUNTIME_DIR=%t/ailit

[Install]
WantedBy=default.target
```

4. Выполнить `systemctl --user daemon-reload`.
5. Включить и запустить сервис: `systemctl --user enable --now ailit.service`.
6. Явно напечатать пользователю:

```bash
systemctl --user status ailit.service
journalctl --user -u ailit.service -f
```

7. Повторный install должен быть idempotent upgrade: unit обновляется, venv обновляется, service restart/reload выполняется без ручных действий.

Для окружений без systemd install должен не падать неясно, а печатать понятную диагностику и команду ручного запуска `ailit runtime supervisor`.

---

## Этап G8.0 — Design note и границы

### Задача G8.0.1 — Зафиксировать low-level runtime terminology

**Содержание:** design note внутри этого workflow или отдельный `docs/` ADR: `AilitRuntimeSupervisor`, `AgentBroker`, `AgentWork`, `AgentMemory`, `AgentDummy`, low-level vs high-level agents, topics/services/actions, lifecycle states.

**Критерии приёмки:** документ явно запрещает смешивать `ProductAgent` с `AgentWork`/`AgentMemory`; есть схемы для one chat / multiple chats / future ProductAgent.

**Проверки:** review; без кода.

**Коммит:** `agents-runtime-8/G8.0 design runtime agent substrate`.

### Задача G8.0.2 — Зафиксировать transport decisions

**Содержание:** supervisor API по Unix socket; broker и agents как subprocess; сообщения JSON lines или length-prefixed JSON; UI подписывается на trace через broker/supervisor API. Для MVP транспорт локальный, не сетевой.

**Критерии приёмки:** описаны reconnect, timeout, cancel, broker crash, `AgentMemory` crash, `Memory unavailable`.

**Проверки:** review; без кода.

---

## Этап G8.1 — Models, registry, trace store

### Задача G8.1.1 — Dataclasses для runtime contract

**Содержание:** модуль `tools/agent_core/runtime/` с типизированными dataclasses: `RuntimeIdentity`, `AgentId`, `AgentMessage`, `TopicEvent`, `ServiceRequest`, `ServiceResponse`, `ActionStart`, `ActionFeedback`, `ActionResult`, `RuntimeErrorEnvelope`, `MemoryGrant`.

**Критерии приёмки:** сериализация в JSON без потери обязательных полей; validation ошибок; все базовые элементы и returns типизированы.

**Проверки:** `pytest tests/...runtime...`; `flake8 tools/agent_core/runtime tests/...`.

### Задача G8.1.2 — Agent registry и capability registry

**Содержание:** Python registry агентов: `agent_type`, `agent_instance_id`, `chat_id`, `capabilities`, `service_handlers`, `topic_subscriptions`, `action_handlers`.

**Критерии приёмки:** можно зарегистрировать `AgentDummy` без изменения UI/session loop; registry экспортирует список агентов для broker и UI.

**Проверки:** unit-тест registry; `flake8`.

### Задача G8.1.3 — Durable trace store

**Содержание:** append-only JSONL или SQLite+JSONL projection в `~/.ailit/state/runtime/`; trace rows должны быть пригодны для UI graph и CLI inspection.

**Критерии приёмки:** запись/чтение `agent.trace`; фильтры по `chat_id`, `broker_id`, `agent_instance_id`, `namespace`, `goal_id`.

**Проверки:** unit-тест append/read/filter; `pytest`; `flake8`.

---

## Этап G8.2 — AilitRuntimeSupervisor

### Задача G8.2.1 — CLI `ailit runtime supervisor`

**Содержание:** добавить CLI subgroup `ailit runtime supervisor|status|brokers|stop-broker`; supervisor слушает Unix socket в `$XDG_RUNTIME_DIR/ailit/supervisor.sock` или `$AILIT_RUNTIME_DIR/supervisor.sock`.

**Критерии приёмки:** `ailit runtime status` показывает supervisor endpoint, uptime, broker count; при недоступности печатает понятную ошибку.

**Проверки:** CLI unit/smoke через subprocess с temp runtime dir; `flake8 tools/ailit tools/agent_core/runtime`.

### Задача G8.2.2 — Broker registry и lifecycle

**Содержание:** supervisor создаёт broker на `create_or_get_broker(chat_id, project_root, namespace)`, хранит registry, healthcheck, last_seen, endpoint.

**Критерии приёмки:** два разных chat_id получают два разных broker; повторный запрос chat_id возвращает существующий broker; dead broker помечается `failed`.

**Проверки:** unit-тест lifecycle; smoke с temp dir; `pytest`.

### Задача G8.2.3 — Журналирование supervisor

**Содержание:** stdout/stderr структурированы для journalctl; process.start/stop, broker.spawned, broker.failed, request errors без секретов.

**Критерии приёмки:** `journalctl --user -u ailit.service -f` показывает понятные строки lifecycle; sensitive payloads redacted.

**Проверки:** unit-тест redaction; ручной сценарий systemd после G8.7.

**Коммит:** `agents-runtime-8/G8.2 add runtime supervisor`.

---

## Этап G8.3 — AgentBroker process

### Задача G8.3.1 — Broker subprocess entrypoint

**Содержание:** `ailit runtime broker --chat-id ... --namespace ... --project-root ...`; broker открывает локальный endpoint и регистрируется в supervisor.

**Критерии приёмки:** supervisor spawn создаёт живой broker; broker graceful shutdown по команде supervisor.

**Проверки:** subprocess smoke; `pytest`; `flake8`.

### Задача G8.3.2 — Routing: topic/service/action

**Содержание:** внутри broker реализовать:

- `publish(topic, event)` для one-to-many;
- `request(service, payload)` для one-to-one request/reply;
- `start_action(action, payload)` для long-running задач с feedback/cancel/result.

**Критерии приёмки:** `AgentDummy` получает topic broadcast; service request возвращает response; action отдаёт feedback и final result; UI subscriber получает все trace events.

**Проверки:** unit-тесты router; async/subprocess smoke.

### Задача G8.3.3 — Broker trace projection

**Содержание:** broker пишет все сообщения в trace store и дополнительно отдаёт live subscription для `ailit chat`.

**Критерии приёмки:** по одному trace можно восстановить user prompt → Work → Memory → grants → read → answer.

**Проверки:** snapshot-тест JSONL rows; `pytest`.

**Коммит:** `agents-runtime-8/G8.3 add agent broker routing`.

---

## Этап G8.4 — Subprocess agents

### Задача G8.4.1 — Общий subprocess protocol

**Содержание:** единый protocol adapter для агентов: launch, stdin/stdout JSON messages, heartbeat, shutdown, structured errors.

**Критерии приёмки:** агент можно запустить отдельно под broker; broken JSON не валит broker; heartbeat timeout переводит agent в `unavailable`.

**Проверки:** unit + subprocess tests; `flake8`.

### Задача G8.4.2 — AgentMemory worker

**Содержание:** вынести `AgentMemory` в subprocess worker. На этом этапе допустим adapter поверх существующего PAG/KB API, но public contract уже service/action/topic.

**Критерии приёмки:** `memory.query_context` возвращает `MemoryGrant`; `memory.sync_changes` пишет trace; при падении возвращается `Memory unavailable`, raw fallback не включается.

**Проверки:** smoke с temp DB; `pytest`; `flake8`.

### Задача G8.4.3 — AgentWork worker

**Содержание:** `AgentWork` принимает `work.handle_user_prompt`, обращается к `AgentMemory` за context/grants, выполняет session/tool loop через broker-mediated runtime.

**Критерии приёмки:** happy path entrypoint question проходит через Work→Memory; первая попытка raw read без grant невозможна.

**Проверки:** e2e mock-provider smoke; `pytest`; `flake8`.

### Задача G8.4.4 — AgentDummy internal test agent

**Содержание:** внутренний агент только для тестов extension contract: echo service, topic subscriber, short action with feedback.

**Критерии приёмки:** добавляется через registry без специальных if в UI, broker или trace projection.

**Проверки:** unit/e2e test extension contract.

**Коммит:** `agents-runtime-8/G8.4 add subprocess agents`.

---

## Этап G8.5 — MemoryGrant enforcement

### Задача G8.5.1 — Grant checker для file/read tools

**Содержание:** общий checker в tool runtime для `read_file`, `read_symbol`, range-read. Проверяет `path`, `offset`, `limit` против активных grants текущего `AgentWork`.

**Критерии приёмки:** чтение без grant блокируется `memory_grant_required`; чтение вне line range блокируется; `whole_file=true` разрешает полный файл только при явном grant.

**Проверки:** unit tests на ranges/whole_file/expired grant; `flake8`.

### Задача G8.5.2 — Интеграция с SessionRunner / tool registry

**Содержание:** runtime context передаёт active grants в tool layer без глобальных mutable hacks; `SessionRunner` не знает конкретный класс `AgentMemory`, только grant provider/checker.

**Критерии приёмки:** Work не может обойти Memory через прямой `read_file`; policy violation попадает в trace и UI.

**Проверки:** e2e mock-provider scenario; `pytest`; `flake8`.

### Задача G8.5.3 — Dark zone и Memory unavailable

**Содержание:** если `AgentMemory` stale/missing/unavailable, broker не разрешает raw read; пользователю показывается structured error с recovery hint.

**Критерии приёмки:** падение `AgentMemory` даёт `Memory unavailable`, а не silent fallback.

**Проверки:** fault-injection test.

**Коммит:** `agents-runtime-8/G8.5 enforce memory grants`.

---

## Этап G8.6 — `ailit chat` как runtime client + trace tab

### Задача G8.6.1 — Chat boot через supervisor

**Содержание:** при старте chat создаёт/получает broker через supervisor. Если supervisor недоступен, показывает инструкцию `systemctl --user status ailit.service`.

**Критерии приёмки:** chat не запускает runtime напрямую; user prompt уходит в broker action `work.handle_user_prompt`.

**Проверки:** Streamlit-adapter unit или smoke; `pytest`; `flake8`.

### Задача G8.6.2 — Отдельная вкладка Agent Trace

**Содержание:** в `ailit chat` добавить вкладку trace: список broker/chat/AgentMemory, live timeline, graph view `agent -> agent`, фильтры `chat_id`, `agent_instance_id`, `namespace`, `goal_id`.

**Критерии приёмки:** если открыто несколько chats, UI показывает их все и умеет выбрать конкретный `AgentMemory`; trace устойчив к добавлению нового агента.

**Проверки:** presenter tests для trace rows; ручной Streamlit scenario.

### Задача G8.6.3 — UI redaction и payload preview

**Содержание:** UI показывает summary и redacted JSON; full sensitive payload не попадает в browser без явного debug режима.

**Критерии приёмки:** KB/tool args redacted; file content не дублируется в trace tab.

**Проверки:** unit tests redaction.

**Коммит:** `agents-runtime-8/G8.6 connect chat to broker`.

---

## Этап G8.7 — Installer + systemd service

### Задача G8.7.1 — Расширить `scripts/install`

**Содержание:** install генерирует `~/.config/systemd/user/ailit.service`, делает `systemctl --user daemon-reload`, `enable --now`, restart при upgrade. Для `dev` unit указывает на repo venv; для `prod` — на prod venv/shim.

**Критерии приёмки:** повторный `./scripts/install` обновляет service; в stdout есть команды `systemctl --user status ailit.service` и `journalctl --user -u ailit.service -f`.

**Проверки:** shell/unit smoke в temp HOME с dry-run режимом; `shellcheck` если доступен; ручной install на Linux systemd.

### Задача G8.7.2 — CLI doctor для runtime service

**Содержание:** `ailit doctor` или `ailit runtime doctor` проверяет service file, supervisor socket, broker registry, journalctl command hints.

**Критерии приёмки:** диагностика отличает service missing / inactive / socket missing / broker failed.

**Проверки:** unit tests doctor states; manual systemd scenario.

### Задача G8.7.3 — Документация install/update

**Содержание:** README кратко показывает install, service status, journalctl log, upgrade через повторный install.

**Критерии приёмки:** README не дублирует весь workflow, но содержит команды эксплуатации.

**Проверки:** review.

**Коммит:** `agents-runtime-8/G8.7 install runtime service`.

---

## Этап G8.8 — E2E сценарии и readiness для ProductAgent

### Задача G8.8.1 — E2E: one chat, Work/Memory

**Содержание:** mock-provider сценарий: prompt → broker → AgentWork → AgentMemory → MemoryGrant → read allowed range → answer.

**Критерии приёмки:** trace содержит все ключевые события; `AgentWork` не читает вне grant.

**Проверки:** e2e pytest marker или smoke script.

### Задача G8.8.2 — E2E: multiple chats, shared DB

**Содержание:** два chat/broker runtime, два `AgentMemory`, общий PAG/KB store, UI/API list показывает оба.

**Критерии приёмки:** можно выбрать конкретный `AgentMemory`; trace фильтруется по chat/agent/namespace.

**Проверки:** subprocess e2e with temp dirs.

### Задача G8.8.3 — E2E: one-to-many ProductAgent readiness

**Содержание:** без полноценного `ProductAgent` реализовать тестовый сценарий: dummy orchestrator публикует `goal.started`, несколько agents получают topic, один action выполняется с feedback/cancel.

**Критерии приёмки:** one-to-many работает без специальных if; trace graph показывает fan-out.

**Проверки:** unit/e2e broker routing.

### Задача G8.8.4 — Failure scenarios

**Содержание:** падение supervisor, broker, AgentMemory, broken agent JSON, timeout, cancel.

**Критерии приёмки:** errors structured; UI показывает понятные сообщения; `Memory unavailable` не приводит к raw-read fallback.

**Проверки:** fault-injection tests.

**Коммит:** `agents-runtime-8/G8.8 finalize runtime e2e`.

---

## Общие проверки перед каждым коммитом

Минимум после каждой задачи с кодом:

```bash
PYTHONPATH=tools python3 -m pytest -q <затронутые tests>
python3 -m flake8 <затронутые tools/tests>
```

Для этапов с CLI/subprocess:

```bash
PYTHONPATH=tools python3 -m pytest -q tests/e2e/ -m e2e
```

если окружение готово. Если e2e не может быть запущен из-за внешних зависимостей, агент обязан явно написать причину и выполнить доступные unit/smoke проверки.

Для systemd этапа:

```bash
./scripts/install dev
systemctl --user status ailit.service
journalctl --user -u ailit.service -n 100 --no-pager
ailit runtime status
```

---

## Риски и митигации

| Риск | Митигация |
|------|-----------|
| Ранний broker-process усложнит MVP | Сначала локальный Unix socket, JSON messages, single-user runtime; без сетевого discovery. |
| systemd недоступен | Installer печатает понятную диагностику и ручной fallback `ailit runtime supervisor`; tests используют dry-run. |
| AgentMemory падение блокирует работу | Это ожидаемое поведение: показываем `Memory unavailable`, raw-read не включаем. |
| Trace протечёт содержимым файлов | Redaction по умолчанию; file body не пишется в trace, только path/ranges/meta. |
| Несколько AgentMemory пишут в одну DB | Очередь/lock по `namespace`, как Graphiti queue per group_id; write operations serialized. |
| UI начнёт знать конкретные агенты | Trace tab строится из registry/events, не из hardcoded `AgentWork`/`AgentMemory` branches. |
| ProductAgent позже потребует one-to-many | Уже в G8.3 есть topics/actions; G8.8 проверяет fan-out через dummy orchestrator. |

---

## Статус

**Workflow 8 согласован как следующий текущий workflow после закрытия Workflow 7.** Реализация начинается с G8.0. Каждый этап закрывается проверками и отдельным коммитом по правилам [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).
