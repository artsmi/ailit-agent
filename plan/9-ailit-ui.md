# Workflow 9: `ailit desktop` — standalone UI вместо `ailit chat`

**Идентификатор:** `ailit-ui-9` (файл `plan/9-ailit-ui.md`).

Документ задаёт следующую итерацию после закрытия `Workflow 8`: заменить `ailit chat` полноценным **Linux-only Electron desktop binary**, который запускается командой `ailit desktop`, использует канонический Candy-дизайн из `/home/artem/Desktop/ айлит/stitch_example_showcase_system/`, подключается к runtime `AilitRuntimeSupervisor` / `AgentBroker` / `AgentWork` / `AgentMemory` и показывает пользователю чат, человекочитаемый диалог агентов, текущие агенты, PAG-граф и отчёты по текущей сессии.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Положение в графе планов

- **Workflow 7 закрыт:** PAG, `ailit memory`, `AgentMemory` / `AgentWork`, `pag_nodes` / `pag_edges`, `ailit memory index` и post-edit sync считаются готовой базой для UI. См. `tools/agent_core/memory/sqlite_pag.py:44-78`, `tools/ailit/memory_cli.py:35-55`, `tools/ailit/memory_app.py:186-235`.
- **Workflow 8 закрыт:** `AilitRuntimeSupervisor`, `AgentBroker`, subprocess agents, durable trace store, live trace subscription, `MemoryGrant` enforcement и `scripts/install` с `systemd --user` считаются готовым runtime substrate. См. `tools/agent_core/runtime/supervisor.py:122-193`, `tools/agent_core/runtime/broker.py:207-304`, `tools/agent_core/runtime/broker.py:396-460`, `tools/agent_core/runtime/trace_store.py:27-84`, `scripts/install:58-97`.
- **Workflow 9 не переписывает runtime:** desktop UI является клиентом/наблюдателем и отправителем user prompt в broker. Runtime остаётся источником истины для событий, trace, agents registry, PAG и tool/session execution.
- **`ailit chat` уходит из целевого UX:** Streamlit `ailit chat` может оставаться legacy/debug до отдельного удаления, но продуктовая замена — `ailit desktop`.
- **Контрольная точка обязательна:** сначала создаётся интерактивный UI/UX на mock data без runtime, пользователь смотрит и даёт фиксы; только после явного go начинается подключение runtime.
- **Расширяемость агентов обязательна:** UI не должен знать только `AgentWork` / `AgentMemory` через hardcoded ветки. В MVP показываются два агента, но новые агенты добавляются через config/registry/manifest и автоматически появляются в navigation, graph и agent dialogue.

---

## Зафиксированные решения пользователя

1. Команда запуска: **`ailit desktop`**.
2. Это полноценная замена `ailit chat` и его функций.
3. Нужен **desktop binary**, не просто локальная web-страница.
4. Платформа MVP: **Linux only**.
5. Desktop shell: **Electron**.
6. Дизайн из `/home/artem/Desktop/ айлит/stitch_example_showcase_system/` — **канон**; по нему создаётся отдельный брендбук в репозитории.
7. Диалог агентов должен быть **человекочитаемым**, как общение людей, но runtime остаётся источником структурированных событий.
8. В MVP агенты: `AgentWork` и `AgentMemory`; архитектура UI должна позволять добавлять новых агентов без переделки runtime/API/UX.
9. Memory graph показывает **только PAG**. KB/memory остаются внутри чата агента; расширение после реализации — отдельное решение.
10. PAG search highlight — только визуальный live-эффект без persistence: линии/узлы ярче и затухают примерно за 3 секунды.
11. Отчёт по текущей сессии экспортируется отдельно в **Markdown** и **JSON**.
12. Отчёт включает текущий чат, агентный диалог, PAG search events/highlights, tool logs, usage и список подключённых проектов.
13. Нужна CLI-команда **`ailit project add [path]`**. Без path команда берёт текущий `pwd`, дописывает проект в локальный конфиг и активирует его как A-layer entry для `AgentMemory`.
14. Provider/model не являются настройками проекта.
15. Несколько выбранных проектов в чате образуют общий workspace.
16. Установка идёт через `scripts/install`; после установки пользователь вызывает `ailit desktop`, и всё запускается.

---

## Текущая кодовая база: якоря

| Область | Файл / строки | Значение для Workflow 9 |
|---------|---------------|--------------------------|
| CLI entrypoint | `tools/ailit/cli.py:132-176`, `tools/ailit/cli.py:838-868` | Сейчас `ailit chat` и `ailit memory` запускают Streamlit; нужно добавить `ailit desktop` и сохранить legacy-команды как debug/compat. |
| Runtime CLI | `tools/ailit/runtime_cli.py:18-109`, `tools/ailit/runtime_cli.py:127-195` | Уже есть `ailit runtime supervisor|status|brokers|stop-broker|broker`; desktop должен пользоваться этим substrate, а не запускать session loop напрямую. |
| Supervisor | `tools/agent_core/runtime/supervisor.py:122-193`, `tools/agent_core/runtime/supervisor.py:234-260` | Источник broker endpoint и статуса runtime для desktop. |
| Broker | `tools/agent_core/runtime/broker.py:207-304`, `tools/agent_core/runtime/broker.py:306-393`, `tools/agent_core/runtime/broker.py:396-460` | Поддерживает routing, trace append и live subscription; нужен desktop bridge поверх Unix socket. |
| Trace store | `tools/agent_core/runtime/trace_store.py:27-84` | База для agent dialogue, отчёта сессии и восстановления истории при reconnect. |
| Agent registry | `tools/agent_core/runtime/registry.py:9-62` | Основа для динамического списка агентов; Workflow 9 должен расширить metadata для UI (`display_name`, `role`, `icon`, `color`). |
| Subprocess agents | `tools/agent_core/runtime/subprocess_agents/work_agent.py:32-64`, `tools/agent_core/runtime/subprocess_agents/memory_agent.py:34-96` | MVP агенты уже имеют contract surface; UI не должен зависеть от конкретной реализации worker. |
| PAG store/export | `tools/agent_core/memory/sqlite_pag.py:44-78`, `tools/ailit/memory_export.py:12-40` | Источник данных для desktop Memory Graph и JSON export. |
| PAG runtime | `tools/agent_core/memory/pag_runtime.py:95-218` | Источник `target_file_paths`, staleness, fallback и PAG slice semantics для `AgentMemory`. |
| Config merge | `tools/ailit/merged_config.py:55-77`, `tools/ailit/merged_config.py:140-176` | Проекты добавляются не как provider/model, а как отдельный слой config/project registry. |
| Global config write | `tools/ailit/config_store.py:105-170` | Есть атомарная запись YAML; для `ailit project add` нужен отдельный writer без смешивания с provider allowlist. |
| Project config discovery | `tools/ailit/project_config_discovery.py:8-29` | Локальный `.ailit/config.yaml` уже является естественным местом для записи project registry/current project selection. |
| Installer | `scripts/install:104-163` | Нужно расширить install: Python runtime + Electron desktop dependencies/build/binary + shim `ailit desktop`. |
| Текущие зависимости | `pyproject.toml:16-26` | Python extras есть только `dev`, `chat`, `tui`; desktop потребует Node/Electron workspace вне Python extras. |

---

## Доноры и паттерны без копипаста

| Донор | Локальная ссылка | Что взять |
|-------|------------------|-----------|
| **OpenCode desktop package** | `/home/artem/reps/opencode/packages/desktop-electron/package.json:12-24`, `/home/artem/reps/opencode/packages/desktop-electron/package.json:25-56` | Разделение dev/build/package scripts, Electron runtime deps и dev deps; ориентир для `desktop/` workspace. |
| **OpenCode electron-builder** | `/home/artem/reps/opencode/packages/desktop-electron/electron-builder.config.ts:29-37`, `/home/artem/reps/opencode/packages/desktop-electron/electron-builder.config.ts:73-77` | Linux packaging targets; для MVP `ailit` фиксирует Linux target, сначала AppImage/tarball или AppImage+deb по решению этапа G9.6. |
| **OpenCode electron-vite** | `/home/artem/reps/opencode/packages/desktop-electron/electron.vite.config.ts:15-25`, `/home/artem/reps/opencode/packages/desktop-electron/electron.vite.config.ts:52-74` | Разделение main/preload/renderer и сборка renderer как отдельного web-приложения. |
| **OpenCode app providers** | `/home/artem/reps/opencode/packages/app/src/app.tsx:89-118`, `/home/artem/reps/opencode/packages/app/src/app.tsx:132-156` | App shell как композиция providers; в `ailit desktop` так же отделить runtime client, theme, project selection, report/export и graph state. |
| **OpenCode bus** | `/home/artem/reps/opencode/packages/opencode/src/bus/index.ts:24-40`, `/home/artem/reps/opencode/packages/opencode/src/bus/index.ts:82-123` | Typed pub/sub + wildcard subscriptions для UI projections; не копировать Effect stack, взять идею typed events. |
| **OpenCode session events** | `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:6-24`, `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:56-74`, `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:92-140` | Явные event types с id/timestamp/metadata; пригодно для chat transcript и report projection. |
| **ai-multi-agents event log** | `/home/artem/reps/ai-multi-agents/tools/runtime/events.py:14-36`, `/home/artem/reps/ai-multi-agents/tools/runtime/event_log.py:11-27` | Локальный append-only JSONL и event factory; схоже с текущим `JsonlTraceStore`. |
| **Graphiti queue** | `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:12-20`, `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:24-47`, `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:49-80` | Очередь по `group_id` как аналог сериализации PAG search/update по namespace/project. |
| **obsidian-memory-mcp graph contract** | `/home/artem/reps/obsidian-memory-mcp/types.ts:1-16` | Простая модель `entities` / `relations` как UX-метафора: узлы, связи, наблюдения; в `ailit` домен — PAG, не markdown vault. |
| **Candy design canonical docs** | `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_design_documentation_for_figma_cursor.md:3-13`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/candy/DESIGN.md:3-33` | Брендбук: Joyful Pop, DM Sans, `#e040a0`, pill-shapes, cards, bouncy microinteractions. |
| **Candy chat / graph HTML** | `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_design_documentation_for_figma_cursor.md:31-56`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_agent_interaction_graph_candy_style/code.html:20-29`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_agent_interaction_graph_candy_style/code.html:63-88`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_agent_interaction_graph_candy_style/code.html:112-152` | Канонические layout, sidebar, chat, graph, active glow и flow animation. |

---

## Целевая архитектура

```
scripts/install
  |
  +-- Python runtime install (как сейчас)
  +-- systemd --user: ailit.service (Workflow 8)
  +-- Electron desktop build/assets
  +-- ~/.local/bin/ailit
        |
        +-- ailit desktop
              |
              v
        Electron main process
              |
              +-- preload typed bridge (no raw Node in renderer)
              |
              v
        React/TypeScript renderer (Candy UI)
              |
              +-- DesktopRuntimeClient
              |     |
              |     +-- supervisor Unix socket
              |     +-- broker Unix socket
              |     +-- live trace subscription
              |
              +-- ProjectRegistryClient
              +-- PagGraphClient
              +-- SessionReportExporter
```

### Runtime/UI ownership

- **Runtime owns truth:** supervisor/broker lifecycle, agents registry, trace rows, tool/session execution, PAG data, usage, errors.
- **UI owns projection:** human-readable agent conversation, graph layout, visual highlight decay, filters, navigation, report screens, export buttons.
- **Transport owns stability:** typed IPC inside Electron, local Unix socket to Python runtime, reconnect and health states.
- **Config owns extensibility:** agent metadata and project registry are data, not hardcoded branches.

### Human-readable agent dialogue

Runtime отдаёт структурированные events/envelopes. UI строит человекочитаемую реплику из полей `from_agent`, `to_agent`, `intent`, `summary`, `payload`, `error`, `staleness`, `target_file_paths`.

Пример projection:

```json
{
  "from_agent": "AgentWork:chat-a",
  "to_agent": "AgentMemory:chat-a",
  "intent": "explore_entrypoints",
  "summary": "Нужен контекст по точкам входа проекта",
  "payload": {"level": "B", "top_k": 12}
}
```

Показывается как:

> **AgentWork:** Мне нужен контекст по точкам входа проекта. Проверь PAG и предложи релевантные файлы.

Это не отдельная «театральная» бизнес-логика runtime. Runtime сохраняет машинный протокол, UI отвечает за дружелюбную проекцию.

---

## Desktop routes / секции burger menu

1. **Чат** — пользовательский чат, замена `ailit chat`; выбор одного или нескольких проектов как общего workspace; кнопка отчёта по текущей сессии.
2. **Диалог агентов** — человекочитаемая timeline/swimlane проекция `AgentWork` ↔ `AgentMemory` и будущих агентов; JSON доступен только как раскрываемая debug-деталь.
3. **Текущие агенты** — динамический список агентов и связей из config/registry; клик по связи открывает страницу общения пары агентов.
4. **Memory Graph** — PAG-only graph; live search highlight узлов/линий с яркостью и затуханием примерно 3 секунды; без persistence highlight-state.
5. **Проекты** — список зарегистрированных проектов, активные entrypoints текущего workspace, статус PAG A-layer.
6. **Отчёты** — просмотр и экспорт текущей сессии в Markdown и JSON.
7. **Runtime status** — supervisor/broker/agents health, подсказки `systemctl --user status ailit.service` и `journalctl --user -u ailit.service -f`.

---

## Контракты данных Workflow 9

### `ailit_desktop_project_registry_v1`

Project registry не содержит provider/model. Минимальная форма в локальном config:

```yaml
projects:
  entries:
    - project_id: "uuid-or-stable-slug"
      path: "/abs/path/to/project"
      namespace: "derived-or-detected"
      title: "project folder name"
      added_at: "2026-04-25T00:00:00Z"
      active: true
  active_project_ids:
    - "uuid-or-stable-slug"
```

Правила:

1. `ailit project add` без аргумента берёт `Path.cwd()`.
2. `ailit project add PATH` нормализует absolute path.
3. Запись идёт в локальный `.ailit/config.yaml` ближайшего workspace или в явно определённый local registry, если команда вызвана вне проекта; конкретное место фиксируется в G9.3.
4. Повторный add того же path идемпотентен: обновляет `active=true`, не создаёт дубль.
5. Добавленный проект активируется как A-layer entry для `AgentMemory`: после add должен быть понятный next step `ailit memory index --project-root PATH` или автоматический index, если выбран в G9.3.
6. Несколько активных проектов в desktop-чате образуют единый workspace; все events/report rows маркируются `project_id`/`namespace`.

### `ailit_desktop_agent_manifest_v1`

Минимальная форма agent metadata:

```yaml
agents:
  entries:
    - agent_type: "AgentWork"
      display_name: "Work"
      role: "Исполняет задачу пользователя"
      icon: "terminal"
      color: "#e040a0"
      capabilities:
        - "work.handle_user_prompt"
    - agent_type: "AgentMemory"
      display_name: "Memory"
      role: "Ищет контекст в PAG и выдаёт grants"
      icon: "account_tree"
      color: "#7c52aa"
      capabilities:
        - "memory.query_context"
```

Правила:

1. UI строит меню агентов, карточки и связи из manifest + live registry.
2. Если runtime вернул агент без manifest metadata, UI показывает fallback карточку по `agent_type`, но не падает.
3. Добавление нового агента не требует новых route-specific if в renderer.
4. Agent links строятся по trace rows (`from_agent`, `to_agent`, service/action/topic), а не руками в layout.

### `ailit_desktop_trace_projection_v1`

UI projection row:

```json
{
  "kind": "agent_dialogue_message",
  "chat_id": "chat-a",
  "project_ids": ["..."],
  "from_agent": "AgentWork:chat-a",
  "to_agent": "AgentMemory:chat-a",
  "human_text": "Мне нужен контекст по точкам входа проекта.",
  "technical_summary": "memory.query_context level=B top_k=12",
  "severity": "info|warning|error",
  "raw_ref": {"trace_id": "...", "message_id": "..."}
}
```

### `ailit_desktop_pag_highlight_v1`

Live-only UI event:

```json
{
  "kind": "pag.search.highlight",
  "namespace": "...",
  "node_ids": ["B:tools/ailit/cli.py"],
  "edge_ids": ["..."],
  "reason": "AgentMemory search",
  "ttl_ms": 3000,
  "intensity": "strong"
}
```

Правила:

1. Highlight не пишется отдельным persistent state.
2. Отчёт может включать исходные `AgentMemory` search events из trace, но не обязан хранить UI animation history.
3. Визуально highlight должен быть заметен: яркая линия/узел, затем плавное затухание за ~3 секунды.

### `ailit_desktop_session_report_v1`

Report включает:

- текущий chat transcript;
- human-readable agent dialogue;
- raw trace refs;
- PAG search events/highlights source events;
- tool logs / console output summaries;
- usage/tokens/cost where available;
- список подключённых проектов (`project_id`, `namespace`, `path`);
- runtime health/fallback/errors;
- экспорт в Markdown;
- экспорт в JSON.

---

## Порядок реализации стратегии

Эта стратегия исполняется строго по этапам. После логического завершения каждого этапа выполняются проверки из этапа и создаётся отдельный коммит с префиксом `ailit-ui-9/G9.n`. После каждого успешного коммита отправляется notify по правилу [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc): `curl -d "<commit subject>" ntfy.sh/ai`. После завершения текущего задания дополнительно отправляется `curl -d "Мне нужна работа! Я выполнил последнюю задачу <commit subject>" ntfy.sh/ai`.

1. **G9.0** — design note, брендбук и desktop boundaries.
2. **G9.1** — Electron workspace + интерактивный Candy UI на mock data.
3. **G9.2** — UX checkpoint: показ пользователю, фиксы, стоп-гейт перед runtime.
4. **G9.3** — `ailit project add` и project registry.
5. **G9.4** — desktop install/build: `scripts/install` + `ailit desktop` Linux binary.
6. **G9.5** — runtime bridge: supervisor/broker connection, live trace subscription, reconnect.
7. **G9.6** — chat replacement + session report export MD/JSON.
8. **G9.7** — dynamic agents UI + human-readable agent dialogue.
9. **G9.8** — PAG Memory Graph + realtime search highlight.
10. **G9.9** — e2e, degradation, README status and release readiness.

До закрытия G9.2 и явного пользовательского go запрещено начинать G9.5–G9.8 runtime integration.

---

## Этап G9.0 — Design note, брендбук и границы

### Задача G9.0.1 — Зафиксировать product/design contract `ailit desktop`

**Содержание:** в `plan/9-ailit-ui.md` и/или отдельном ADR зафиксировать: Linux-only, Electron, `ailit desktop`, замена `ailit chat`, runtime как source of truth, UI как projection, UX checkpoint до runtime, no KB graph в Memory Graph MVP.

**Критерии приёмки:** документ явно описывает in-scope/out-of-scope, контрольную точку, runtime/UI ownership и запрет hardcoded двух агентов как долгосрочного UX.

**Проверки:** review; без кода.

### Задача G9.0.2 — Создать `design/` брендбук по Candy canonical refs

**Содержание:** каталог `design/` с Markdown brandbook: цвета, typography, spacing, radii, shadows, motion, chat components, agent graph components, PAG highlight behavior. Источники: `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_design_documentation_for_figma_cursor.md:3-61`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/candy/DESIGN.md:3-33`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_agent_interaction_graph_candy_style/code.html:20-29`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_agent_interaction_graph_candy_style/code.html:63-88`, `/home/artem/Desktop/ айлит/stitch_example_showcase_system/ai_agent_agent_interaction_graph_candy_style/code.html:112-152`.

**Критерии приёмки:** брендбук содержит design tokens и правила применения, но не копирует весь HTML как продуктовый код; есть ссылки на канонические дизайн-артефакты; brandbook является источником для frontend tokens.

**Проверки:** review; без кода.

**Коммит:** `ailit-ui-9/G9.0 document desktop ui contract`.

---

## Этап G9.1 — Electron workspace + mock UI

### Задача G9.1.1 — Создать desktop workspace

**Содержание:** добавить `desktop/` или `apps/desktop/` с Electron + React + TypeScript + Vite/electron-vite. Разделить `main`, `preload`, `renderer`. Renderer не получает прямой доступ к Node APIs; всё через typed preload bridge.

**Критерии приёмки:** `npm run dev` или выбранная команда запускает Electron window; renderer показывает shell; main/preload/renderer собираются отдельно; нет runtime connection.

**Проверки:** `npm run typecheck`; `npm run lint` если настроен; `npm run build`; `python3 -m flake8` не требуется, если Python не менялся.

### Задача G9.1.2 — Реализовать Candy UI shell на mock data

**Содержание:** sidebar/burger navigation, top bar, chat route, agents dialogue route, current agents route, Memory Graph route, Projects route, Reports route, Runtime Status route. Mock data должны покрывать: два проекта, `AgentWork`, `AgentMemory`, одна связь Work→Memory, PAG nodes/edges, tool logs, usage, report export preview.

**Критерии приёмки:** пользователь может кликать по всем секциям; layout соответствует Candy brandbook; route state не теряется при переключении; mock graph показывает active edge и search highlight decay.

**Проверки:** frontend unit/render tests, если выбран test runner; ручной сценарий `npm run dev`.

### Задача G9.1.3 — Mock report export MD/JSON

**Содержание:** в UI реализовать кнопки export Markdown и export JSON на mock session report. Файлы можно сохранять через Electron dialog или download-like flow, выбранный для Linux MVP.

**Критерии приёмки:** экспортируемые mock MD/JSON содержат chat, agent dialogue, PAG search source events, tool logs, usage и projects list.

**Проверки:** unit test serializer; manual export.

**Коммит:** `ailit-ui-9/G9.1 add mock electron desktop ui`.

---

## Этап G9.2 — UX checkpoint и фиксы до runtime

### Задача G9.2.1 — Подготовить UX demo build без runtime

**Содержание:** собрать интерактивный UI на mock data: `ailit desktop` может ещё не быть production-командой, но должен быть понятный dev/demo запуск. Все runtime-зависимые места явно помечены mock state.

**Критерии приёмки:** демо открывается на Linux; можно пройти сценарии: чат → отчёт → диалог агентов → текущие агенты → связь Work/Memory → Memory Graph → search highlight.

**Проверки:** `npm run build`; ручной UX сценарий; screenshots/video optional.

### Задача G9.2.2 — Пользовательский показ и список фиксов

**Содержание:** показать UI пользователю, собрать замечания, внести UX/brand fixes в рамках mock UI. Этот этап является единственной контрольной точкой перед runtime.

**Критерии приёмки:** пользователь явно подтверждает, что можно переходить к runtime integration; нерешённые UX замечания либо закрыты, либо перенесены в отдельный список accepted follow-ups.

**Проверки:** review; manual scenario повторён после фиксов.

### Задача G9.2.3 — Stop gate

**Содержание:** перед G9.5 агент обязан остановиться и зафиксировать в сообщении/коммите, что runtime integration не начата без go. Если go не получен, продолжать только mock UI/design fixes.

**Критерии приёмки:** в итоговом сообщении этапа есть явная фраза: `G9.2 UX checkpoint закрыт, runtime integration разрешён/не разрешён`.

**Проверки:** review.

**Коммит:** `ailit-ui-9/G9.2 finalize ux checkpoint`.

---

## Этап G9.3 — `ailit project add` и project registry

### Задача G9.3.1 — Спроектировать project registry schema

**Содержание:** зафиксировать, где хранится registry: локальный `.ailit/config.yaml` текущего workspace или отдельный файл под `.ailit/` / global state. Предпочтение: локальная `.ailit/config.yaml` для `ailit project add` из проекта, с возможностью global list для desktop recent projects. Provider/model не входят в project settings.

**Критерии приёмки:** schema соответствует `ailit_desktop_project_registry_v1`; несколько проектов в одном workspace описаны как общий workspace; namespace/project_id обязательны в events/report.

**Проверки:** review; без кода.

### Задача G9.3.2 — CLI `ailit project add [path]`

**Содержание:** добавить subgroup `ailit project add [path]`. Без path используется `Path.cwd()`. Команда нормализует путь, создаёт/обновляет local config, активирует проект и печатает: `project_id`, `path`, `namespace`, next command для PAG index или результат auto-index, если выбран auto-index.

**Критерии приёмки:** повторный add идемпотентен; invalid path даёт exit code 2 и понятную ошибку; provider/model не меняются; `ailit config show` не раскрывает секреты и не ломается от новой секции.

**Проверки:** `PYTHONPATH=tools python3 -m pytest -q tests/...project... tests/...config...`; `python3 -m flake8 tools/ailit tests/...`.

### Задача G9.3.3 — Активация A-layer в AgentMemory

**Содержание:** после add проект должен быть видим как A-layer entry для `AgentMemory`: либо команда запускает `ailit memory index --project-root PATH`, либо desktop/runtime показывает state `needs_index` и предлагает index. Решение фиксируется в задаче; silent missing PAG запрещён.

**Критерии приёмки:** desktop Projects route видит добавленный проект; `AgentMemory`/PAG status различает `indexed`, `needs_index`, `stale`, `missing`.

**Проверки:** CLI smoke с temp HOME/temp project; PAG index smoke; flake8.

**Коммит:** `ailit-ui-9/G9.3 add project registry cli`.

---

## Этап G9.4 — Desktop install/build и команда `ailit desktop`

### Задача G9.4.1 — CLI `ailit desktop`

**Содержание:** добавить команду `ailit desktop`, которая запускает установленный Electron binary или dev fallback. Если binary отсутствует, команда печатает понятную диагностику: повторить `./scripts/install`, проверить desktop build path.

**Критерии приёмки:** после install команда доступна из любого каталога; exit code и stderr понятны при missing binary; команда не запускает Streamlit.

**Проверки:** CLI unit/smoke; `python3 -m flake8 tools/ailit tests/...`.

### Задача G9.4.2 — Расширить `scripts/install`

**Содержание:** install ставит Python runtime как сейчас, systemd service как G8 и desktop dependencies/build/assets. Для Linux MVP фиксируется один primary artifact: AppImage или tarball; если выбирается `.deb`, это отдельный target. Install должен быть idempotent.

**Критерии приёмки:** `./scripts/install dev` готовит dev desktop запуск; `./scripts/install` готовит production `ailit desktop`; повторный install обновляет desktop assets и service без ручных действий; в stdout есть desktop check command.

**Проверки:** install dry-run tests; shellcheck если доступен; ручной Linux smoke.

### Задача G9.4.3 — Desktop packaging config

**Содержание:** добавить electron-builder/electron-vite config для Linux. Взять паттерны из `/home/artem/reps/opencode/packages/desktop-electron/electron-builder.config.ts:29-37`, `/home/artem/reps/opencode/packages/desktop-electron/electron-builder.config.ts:73-77`, но зафиксировать Linux-only и product name `ailit`.

**Критерии приёмки:** build artifact создаётся в predictable path; build не включает secrets; renderer assets упакованы; binary стартует на Linux.

**Проверки:** `npm run build`; `npm run package:linux` или выбранная команда; manual launch.

**Коммит:** `ailit-ui-9/G9.4 install desktop launcher`.

---

## Этап G9.5 — Runtime bridge

### Задача G9.5.1 — DesktopRuntimeClient для supervisor

**Содержание:** Electron main/preload bridge вызывает supervisor Unix socket API: status, brokers, create_or_get_broker, stop_broker. Renderer получает typed responses и health state.

**Критерии приёмки:** Runtime Status route показывает supervisor status; при недоступном supervisor UI показывает команды `systemctl --user status ailit.service` и `journalctl --user -u ailit.service -f`; нет зависания renderer.

**Проверки:** TypeScript unit tests для client; Python runtime smoke с temp runtime dir; manual service scenario.

### Задача G9.5.2 — Broker connection и live trace subscription

**Содержание:** desktop получает broker endpoint для `chat_id`, отправляет runtime envelopes и подписывается на live trace через `{"cmd":"subscribe_trace"}`. При reconnect UI дочитывает durable trace и переподписывается.

**Критерии приёмки:** live trace rows появляются в UI без refresh; broker restart не ломает приложение; duplicate events не дублируются в projection.

**Проверки:** integration test с temp runtime supervisor/broker; renderer projection tests.

### Задача G9.5.3 — Runtime event normalization

**Содержание:** TypeScript слой нормализует `ailit_agent_runtime_v1` rows в UI store: chat events, agent messages, tool events, PAG events, usage events, errors.

**Критерии приёмки:** неизвестный event type не валит UI; raw row сохраняется как debug ref; sensitive payload redacted по умолчанию.

**Проверки:** snapshot tests на trace rows из `tests/runtime/test_runtime_e2e_g8_8.py`-style fixtures.

**Коммит:** `ailit-ui-9/G9.5 connect desktop runtime bridge`.

---

## Этап G9.6 — Chat replacement и session report

### Задача G9.6.1 — Chat route как замена `ailit chat`

**Содержание:** пользовательский prompt из desktop отправляется как `action.start` / `work.handle_user_prompt` в broker. UI показывает assistant deltas/final messages, tool output preview, errors, stop/cancel где runtime поддерживает cancel.

**Критерии приёмки:** happy path с mock provider/runtime проходит через supervisor→broker→AgentWork; desktop показывает ответ и trace; Streamlit `ailit chat` не участвует.

**Проверки:** e2e desktop-runtime smoke; unit tests serializers/projections; flake8 для Python bridge changes.

### Задача G9.6.2 — Workspace projects selection

**Содержание:** в chat route можно выбрать один или несколько проектов из registry; выбранные проекты передаются в runtime как общий workspace context. Все report/trace projections маркируются project_id/namespace.

**Критерии приёмки:** два проекта могут быть активны в одном chat; UI явно показывает active projects; отправка prompt без проекта даёт понятную подсказку.

**Проверки:** UI state tests; CLI project registry tests.

### Задача G9.6.3 — Session report MD/JSON

**Содержание:** собрать report из chat transcript, agent dialogue projection, PAG search source events, tool logs, usage, connected projects, runtime health/errors. Реализовать экспорт в Markdown и JSON как разные функции.

**Критерии приёмки:** MD читаем человеком; JSON соответствует `ailit_desktop_session_report_v1`; экспорт не содержит file body/secrets без явного debug mode.

**Проверки:** serializer unit tests; snapshot MD/JSON; manual export.

**Коммит:** `ailit-ui-9/G9.6 replace chat and export reports`.

---

## Этап G9.7 — Dynamic agents UI и человекочитаемый dialogue

### Задача G9.7.1 — Agent manifest/config

**Содержание:** добавить config/manifest слой для agent metadata (`agent_type`, `display_name`, `role`, `icon`, `color`, `capabilities`). Runtime registry остаётся источником live availability; manifest — источник presentation defaults.

**Критерии приёмки:** `AgentWork` и `AgentMemory` отображаются из manifest/registry; добавление тестового `AgentDummy` или нового агента не требует новых UI route branches.

**Проверки:** unit tests manifest parser; UI render test with unknown agent fallback.

### Задача G9.7.2 — Human dialogue projection

**Содержание:** преобразовывать service/action/topic trace rows в человекочитаемые карточки и реплики. Runtime отдаёт structured events; UI строит human_text. Raw JSON доступен только под expander/debug.

**Критерии приёмки:** пользователь видит понятный разговор `AgentWork` ↔ `AgentMemory`; errors/staleness/fallback показаны человеческим языком; raw JSON не является основным UX.

**Проверки:** projection snapshot tests на memory.query_context, MemoryGrant, work.handle_user_prompt, runtime_timeout, memory_unavailable.

### Задача G9.7.3 — Current agents и agent links

**Содержание:** секция текущих агентов показывает nodes/links из registry + trace. Клик по связи открывает страницу общения этой пары агентов.

**Критерии приёмки:** Work→Memory link открывает их dialogue; будущие links появляются автоматически; inactive/failed agents имеют видимый status.

**Проверки:** UI tests graph/link selection; integration trace fixture.

**Коммит:** `ailit-ui-9/G9.7 add dynamic agents dialogue`.

---

## Этап G9.8 — PAG Memory Graph и realtime search highlight

### Задача G9.8.1 — PAG graph client

**Содержание:** desktop читает PAG data через Python API/CLI/bridge, не напрямую через unsafe renderer file access. Источник: `SqlitePagStore` / export helpers. Graph показывает levels A/B/C, node panel, attrs, neighbours.

**Критерии приёмки:** выбранный проект показывает PAG graph; empty/missing/stale states понятны; KB не показывается как graph.

**Проверки:** Python API tests; frontend graph fixtures; manual `ailit memory index` → desktop graph.

### Задача G9.8.2 — Search highlight events

**Содержание:** из `AgentMemory` search/response events формировать `ailit_desktop_pag_highlight_v1` UI events. Узлы/линии подсвечиваются ярко и затухают примерно за 3 секунды.

**Критерии приёмки:** при поиске AgentMemory пользователь визуально замечает подсветку; highlight не сохраняется как persistent state; повторные events обновляют TTL/intensity.

**Проверки:** animation/state unit tests; manual runtime search scenario.

### Задача G9.8.3 — Graph performance и limits

**Содержание:** top-K/pagination/filter по namespace/level/kind; большой PAG не должен заморозить renderer. Для больших графов сначала показывается slice, затем expand.

**Критерии приёмки:** graph route устойчив на PAG с тысячами узлов; есть фильтры A/B/C; renderer не получает гигантский full dump без лимита.

**Проверки:** fixture performance smoke; frontend tests for pagination/filter.

**Коммит:** `ailit-ui-9/G9.8 add pag graph highlights`.

---

## Этап G9.9 — E2E, деградации, README и readiness

### Задача G9.9.1 — E2E: install → project add → desktop → runtime

**Содержание:** Linux сценарий: `./scripts/install dev`, `ailit project add`, `ailit memory index`, `ailit desktop`, prompt, agent dialogue, report export.

**Критерии приёмки:** сценарий проходит на mock provider; desktop не требует ручного запуска Streamlit; runtime service диагностируется в UI.

**Проверки:** e2e pytest/subprocess где возможно; manual Linux smoke.

### Задача G9.9.2 — Failure scenarios

**Содержание:** supervisor down, broker crashed, AgentMemory unavailable, missing PAG, stale PAG, missing desktop binary, invalid project path, report export IO error.

**Критерии приёмки:** UI показывает recovery hints, не stack trace; `Memory unavailable` не превращается в silent raw-read fallback; project add errors имеют exit code 2.

**Проверки:** fault-injection tests; UI error state tests.

### Задача G9.9.3 — README status и эксплуатация

**Содержание:** обновить README кратко: Workflow 9, `ailit desktop`, `ailit project add`, install, service status, desktop troubleshooting. Не дублировать весь workflow.

**Критерии приёмки:** README указывает текущий workflow и команды; `.cursor/rules/project-workflow.mdc` остаётся каноном workflow.

**Проверки:** review.

### Задача G9.9.4 — Release readiness checklist

**Содержание:** checklist перед закрытием Workflow 9: builds, tests, manual UX, Linux binary, install idempotency, report export, no secrets in trace/report, dynamic agents smoke.

**Критерии приёмки:** чеклист полностью закрыт или открытые пункты перенесены в новый workflow; текущий workflow не расширяется самовольно.

**Проверки:** полный доступный test suite + manual.

**Коммит:** `ailit-ui-9/G9.9 finalize desktop readiness`.

---

## Общие проверки перед каждым коммитом

После задач с Python-кодом:

```bash
PYTHONPATH=tools python3 -m pytest -q <затронутые tests>
python3 -m flake8 <затронутые tools/tests>
```

После задач с frontend/desktop-кодом:

```bash
cd desktop
npm run typecheck
npm run lint
npm run build
```

Если выбран другой package manager или команды отличаются, они фиксируются в `desktop/package.json`, а план обновляется перед реализацией соответствующего этапа.

После задач с packaging/install:

```bash
./scripts/install dev
ailit runtime status
ailit project add
ailit desktop
```

Для systemd/runtime:

```bash
systemctl --user status ailit.service
journalctl --user -u ailit.service -n 100 --no-pager
```

Если e2e или systemd checks не могут быть выполнены в окружении, агент обязан явно написать причину и выполнить доступные unit/smoke проверки.

После каждого успешного коммита:

```bash
curl -d "<commit subject>" ntfy.sh/ai
```

После завершения текущего задания:

```bash
curl -d "Мне нужна работа! Я выполнил последнюю задачу <commit subject>" ntfy.sh/ai
```

`<commit subject>` подставляется явно текстом, без shell substitution.

---

## Риски и митигации

| Риск | Митигация |
|------|-----------|
| Electron workspace резко усложнит репозиторий | Изолировать в `desktop/`, Python runtime не смешивать с renderer; typed IPC через preload. |
| UI начнёт зависеть от двух конкретных агентов | Manifest + registry + trace links; `AgentWork`/`AgentMemory` только seed data MVP. |
| Runtime integration сломает UX до согласования | Жёсткий G9.2 stop gate: сначала mock UI, показ, фиксы, затем runtime. |
| `scripts/install` станет хрупким из-за Node deps | Idempotent install, dry-run tests, понятная диагностика missing node/npm/binary; Python install не должен ломаться из-за desktop optional failure без явного решения. |
| PAG graph будет слишком большим | Slice-first, filters, pagination, expand-on-demand, лимиты на payload. |
| Trace/report утечёт secrets или file body | Redaction by default; report содержит summaries/refs/tool metadata, не body файлов без debug mode. |
| Несколько проектов смешают контекст | Каждый event/report row маркируется `project_id`/`namespace`; UI показывает active projects. |
| Highlight станет шумом | Только AgentMemory search events; яркий эффект с decay ~3s; no persistence. |
| Legacy `ailit chat` и desktop начнут расходиться | Desktop становится product UI; Streamlit остаётся debug/legacy до отдельного workflow удаления. |

---

## Открытые вопросы

На момент фиксации плана дополнительных вопросов нет. Решения пользователя из раздела «Зафиксированные решения пользователя» считаются каноном для Workflow 9.

---

## Статус

**Workflow 9 согласован как постановка для следующей ветки после закрытия Workflow 8.** Реализация начинается с G9.0. Каждый этап закрывается проверками, отдельным коммитом с префиксом `ailit-ui-9/G9.n` и notify по правилам [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc). Runtime integration начинается только после закрытия G9.2 и явного пользовательского go.
