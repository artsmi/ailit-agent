# Протокол Desktop: realtime PAG-граф и подсветка (Desktop realtime graph protocol)

> **Аннотация:** целевое поведение и контракт для внешнего клиента Desktop (Electron): процессы, каналы trace и PAG, инкременты графа, подсветка из trace, целевая конфигурация и связь с каноном AgentMemory. Общий контракт запросов и внешних событий на границе агента и памяти — в [`external-protocol.md`](external-protocol.md); настоящий документ дополняет его потоком **Desktop → broker → trace → merged PAG → 3D / highlight**.

## Status

`draft` — до явного утверждения человеком; при расхождении с кодом после approval приоритет у формулировок канона после осознанного обновления.

## Связь с исходной постановкой

Ниже — **отдельная** нумерация **desktop** OR (не смешивать с legacy OR-001…OR-015 пакета AgentMemory в [`INDEX.md`](INDEX.md)).

| ID | Формулировка требования (суть, развёрнуто) |
|----|--------------------------------------------|
| **OR-001** | Описать взаимодействие AgentWork и AgentMemory с точки зрения потоков данных: кто инициирует запросы к памяти, как это связано с trace и PAG, без смешения процессов. |
| **OR-002** | Зафиксировать отображение 3D memory в реальном времени: от событий рантайма до сцены графа (Three.js / force-graph), частоты и инварианты обновления. |
| **OR-003** | Объяснить причину существования **временных** представлений графа при построении 3D в realtime (merged vs session vs дельты, отсутствие SQLite и т.п.). |
| **OR-004** | Описать, как работает **подсветка**: от trace / фаз AgentMemory до визуального состояния узлов и рёбер. |
| **OR-005** | Дать общую структуру Desktop-приложения: main / preload / renderer, ключевые модули и границы ответственности. |
| **OR-006** | Зафиксировать объём брендбука (число файлов/разделов по инвентаризации stitch) и outcome: папка `docs/web-ui-book/` в репозитории с HTML-примерами и описанием брендбука (**документация репозитория**, не смешивать с нормативным алгоритмом памяти). |
| **OR-007** | Описать связь с **брокером**: процесс Desktop vs брокер, запуск AgentWork (не внутри Electron), подключение AgentMemory — слито по смыслу с OR-001 с акцентом на сокеты и IPC. |
| **OR-008** | Явные отсылки к уже утверждённому пакету канона AgentMemory и план дополнения **новым** документом протокола Desktop (этот файл рядом с `external-protocol.md`, запись в [`INDEX.md`](INDEX.md)). |
| **OR-009** | Целевой конфиг Desktop: каталог `~/.ailit/desktop`, один или несколько yaml, дефолты при установке, в комментариях — пути всех каталогов данных desktop (кеш, userData, trace, PAG, журнал и т.д.). |
| **OR-010** | Несколько подключённых проектов к одному чату (1–5): 3D memory и протокол должны это поддерживать; зафиксировать целевое поведение и **текущие** ограничения UI (например primary root, первый namespace для подсветки). |
| **OR-011** | Подсветка и появление новых нод **без лагов** и **без полной перерисовки** всего графа — целевые инварианты; явно развести с наблюдаемым remount виджета при смене `graph_rev` (**target vs current**). |
| **OR-012** | Изолированные проекты без общих рёбер отображаются корректно; правила компоновки в проекции 3D — в каноне. Узел показывается только при наличии пути рёбер до A-корня своего namespace; A-узлы видны всегда без рёбер (D-EDGE-GATE-1). |
| **OR-013** | После первичной загрузки структура отображаемого графа не должна «прыгать»; корректная первичная загрузка + динамика в рантайме; связь с freeze координат и remount. |
| **OR-014** | Появление ноды: **первая реальная связь к родителю** + **факт существования** узла; суммаризация **не обязательна**. Без пути рёбер до A-корня узел в 3D **не** отображается (D-EDGE-GATE-1); placeholder-узлы подсветки без рёбер на сцену 3D **не** попадают. |
| **OR-015** | Канонический протокол обновления подсветки и графа для **внешней интеграции**: типы сообщений с точки зрения рантайма, человекочитаемое объяснение для оператора. |
| **OR-016** | В том же документе — **абстрактный алгоритм** подключения Desktop к AgentMemory для realtime графа (handshake, подписки, каналы, ошибки). |
| **OR-017** | Предел **100 000** нод — **параметр конфигурации** Desktop (yaml); согласовать с текущими caps slice/UI (**current_target_mismatch** до выравнивания кода). |

## Текущая реализация (наблюдаемое состояние)

Факты ниже — **наблюдаемое состояние кода** на момент фиксации канона; где расходится с целевыми требованиями — см. целевые разделы и `implementation_backlog`.

### Процессы и границы: main, брокер, supervisor, AgentWork

- **Точка входа Electron** — один main-процесс; **брокер и supervisor** — внешние Python-процессы; main открывает Unix-сокеты к supervisor и к endpoint брокера для чата.
- **AgentWork не выполняется внутри Electron.** Запросы с адресатом `AgentWork:<chat_id>` уходят на сокет брокера одной JSON-строкой; broker поднимает subprocess work-агента.
- **Два режима** на одном broker endpoint: короткий **request/response** (одна строка запроса, одна строка ответа, сокет закрывается) и **долгоживущая подписка** `subscribe_trace` (поток строк trace).
- **IPC:** preload экспонирует API в `window.ailitDesktop`; main пушит live trace в renderer через `ailit:traceRow` и события канала `ailit:traceChannel` (open/end/error).
- **`runtime_dir` для UI** в типичном flow берётся из ответа **supervisor status** (`result.runtime_dir`); guard диагностики в main привязан к `defaultRuntimeDir()` в main — при расхождении `AILIT_RUNTIME_DIR` возможен **риск** несоответствия путей (зафиксировано в failure rules).
- **Durable trace:** `<runtime_dir>/trace/trace-<safe_chat>.jsonl` (согласовано с Python `_trace_store_path`).
- **Журнал памяти для панели UI** читается отдельно: `AILIT_MEMORY_JOURNAL_PATH` или дефолт `~/.ailit/runtime/memory-journal.jsonl` — **не** привязан к `runtime_dir` сессии чата.
- **Реестр проектов:** subprocess `ailit project list --json`, не supervisor; параметр `startPath` в API сейчас **игнорируется** — gap для документа «как есть».

### Preload, renderer, сессия

- Renderer **не** открывает сокеты; конверты `RuntimeRequestEnvelope` / `RuntimeResponseEnvelope` задают поля верхнего уровня (`contract_version`, `trace_id`, `message_id`, `type`, `payload`).
- Live диалог и PAG-дельты приходят как **строки JSON в trace**; при подключении durable история мержится с live, есть **дедупликация** по ключу строки.
- Статус «идёт recall AgentMemory» в чате — **эвристика по trace** (`memory.query_context` и последующие topic-события), не отдельный канал.
- **`user_turn_id` для cancel** извлекается из последней подходящей строки `service.request` Work→AgentMemory с `memory.query_context`; если строки не было — id может быть **пустым** (текущее поведение).
- **Мультипроект:** `supervisorCreateOrGetBroker` получает `namespace` и `project_root` от **первого** выбранного `projectId`; остальные корни уходят в `workspace` user prompt. Состояние сессий UI — `localStorage` (`persistedUi`), не yaml в `~/.ailit/desktop`.

### PAG: merged, session, дельты и «временный» граф

- **SoT графа в UI** — поле `merged` в `PagGraphSessionSnapshot` (тип данных графа для 2D/3D), **per `sessionId`** в карте сессий.
- **Полный срез** собирается через IPC → `ailit memory pag-slice` (пагинация до caps), затем на merged накладывается **реплей** trace и далее **инкремент** только по новым индексам trace (**без** N× slice на каждую строку trace).
- **Дельты из trace** потребляются только как `type === "topic.publish"` с `payload.kind` ∈ `{ pag.node.upsert, pag.edge.upsert }`; для узла нужны `namespace`, `rev`, объект `node`; для рёбер — непустой массив `edges`.
- **Monotonic `rev` per namespace:** при скачке rev формируется предупреждение, но счётчик rev в UI **обновляется** (не hard-fail по умолчанию).
- **«Временность» (OR-003):** пока нет SQLite PAG (`store.sqlite3`) по namespace, full load даёт режим «БД отсутствует», **пустой merged**, поллер повторяет попытки; граф **накапливается из trace-дельт** до появления БД, затем merged **заменяется** срезом из БД + реплей trace. Это не отдельная «вторая БД», а **этап жизненного цикла** представления в UI.
- **Лимиты среза и UI (факт):** **20 000** нод / **40 000** рёбер в Desktop и Python (`pag_slice_caps`), тест выравнивания в репозитории. Параметра **100 000** в коде **нет** (**OR-017 ≠ current**).

### 3D pipeline: частота, force-graph, риски полной пересборки

- Данные 3D — из `merged`; инкремент merge сохраняет координаты узлов там, где входящая дельта не задаёт валидные `x/y/z/fx/fy/fz` (**`mergeNodePreservingCoords`**).
- **Ключ React для `ForceGraph3D`** включает сериализацию **`graphRevByNamespace`**. Успешная PAG-дельта обновляет `rev` → обычно меняется ключ → **remount** экземпляра force-graph (новый цикл WebGL / warmup / freeze), хотя **данные** в store обновляются инкрементально.
- **Подсветка** обновляется отдельным путём: `fg.refresh()` с throttle на тяжёлых графах — **без** смены ключа графа.
- После первого `onEngineStop` вызывается **freeze** координат (`fx/fy/fz`); при **новом** монтировании виджета цикл freeze начинается заново.
- **Проекция (D-EDGE-GATE-1):** фильтр «висячих» рёбер (UC-04A) → **reachability-keep** до любой A-ноды в области рендера (single/separate — namespace; unified — union namespaces). A-узлы видны всегда; B/C/D — только если есть путь рёбер до какой-либо A. Никаких синтетических узлов или рёбер на сцену не добавляется. Достижимость считается **неориентированно** (направление `from→to` рёбер не учитывается).

### Подсветка из trace

- Основной канал W14: `topic.publish` с `event_name === "memory.w14.graph_highlight"`, внутренний `schema === ailit_memory_w14_graph_highlight_v1`, непустые `node_ids` и/или `edge_ids` (после trim на стороне producer).
- Дополнительно: `context.memory_injected`, `context.compacted`, `context.restored` → та же нормализованная модель подсветки; **минимально потребляемые поля** — см. таблицу ниже (согласованы с семантикой выделения узлов в [`external-protocol.md`](external-protocol.md), раздел «Внешние события (OR-010) — типы», `highlighted_nodes`).
- **Store merge** использует `lastPagSearchHighlightFromTraceAfterMerge`, чтобы не сбрасывать подсветку при неизменном хвосте trace; страница 3D при изменении `rawTraceRows` **сканирует trace** заново — зафиксированы **два пути** чтения highlight (**verification_gap** для строгого единообразия).
- **`ensureHighlightNodes`** добавляет **placeholder-узлы** без рёбер для id из highlight в `merged` (используется 2D как список, без edge-gate). В 3D такие узлы **не** попадают на сцену из-за D-EDGE-GATE-1: без пути до A они отфильтрованы проекцией. Подсветка визуально применяется только к узлам, прошедшим edge-gate.
- **Ограничение:** 3D подсветка фильтрует по **`namespaces[0]`** — для нескольких namespace в одном чате highlight может не совпасть с не-первым проектом (**implementation_backlog** относительно OR-010).

### Конфиг и пути данных (факт)

- Каталога **`~/.ailit/desktop`** и desktop-yaml в коде **нет**; первый запуск UI — **localStorage**.
- Запись на диск из main: `trace/*.jsonl` под `runtime_dir`, пара `chat_logs/<safe_chat>/ailit-desktop-full.log` + `ailit-desktop-compact.log` (события trace в renderer и source=D для merge/PAG) и (verbose AgentMemory) `chat_logs/<safe_chat>/<safe_chat>.log` — корень `chat_logs` как у Python `default_chat_logs_dir` (`AILIT_AGENT_MEMORY_CHAT_LOG_DIR` или `~/.ailit/agent-memory/chat_logs`); save dialog; PAG путь через CLI/env **без** отдельного desktop-конфига.
- Electron `userData`/cache **не** выведены одним вызовом в main; `scripts/reinstall` перечисляет **кандидатов** каталогов для очистки; `appId` сборки — `dev.ailit.desktop`.

## Целевое поведение

**Актор:** внешний клиент Desktop (Electron UI) как потребитель **broker trace**, **PAG slice** и **memory journal**; рантайм Python (supervisor, broker, AgentWork, AgentMemory) как producer событий.

**Цель:** оператор и интегратор понимают, **какие сообщения** приходят в trace, **когда**, с **какими обязательными полями**, и **как клиент** подключается к AgentMemory/PAG для realtime графа и подсветки, не читая исходники.

**Связь с каноном памяти:** общий контракт запросов/событий на границе агента и памяти — в [`external-protocol.md`](external-protocol.md); настоящий документ **дополняет** его потоком **Desktop → broker → trace → merged PAG → 3D/highlight**, без дублирования противоречий полей `user_turn_id` / `query_id` / namespace.

## Target flow: типы сообщений и событий

### Разделение каналов (нормативно для интегратора)

| Канал | Назначение | Транспорт (текущий Desktop) |
|-------|------------|-----------------------------|
| **Broker request/response** | Команды AgentWork, ответы сервисов | Одна JSON-строка в/из Unix-сокета broker, сокет закрывается |
| **Trace subscription** | Поток наблюдаемости диалога и PAG | Долгоживущий сокет к тому же endpoint, первая строка `{"cmd":"subscribe_trace"}\n`, далее строки JSON |
| **Durable trace** | История для reconnect и дедупа | Файл JSONL под `runtime_dir/trace/` |
| **PAG slice** | Полный срез графа из SQLite | Subprocess `ailit memory pag-slice` из main, не напрямую из renderer |
| **Memory journal** | События worker памяти для панели | Отдельный JSONL, чтение через IPC, не поток broker trace |

### События trace, влияющие на **граф** (merged)

**Когда:** после операций AgentMemory, которые меняют PAG; строка попадает в trace брокера и в durable JSONL.

**Форма (логическая):** `type === "topic.publish"` (topic чата), полезная нагрузка с `payload.kind`:

| `payload.kind` | Обязательные поля (нормативно для consumer) | Запрещено |
|----------------|---------------------------------------------|-----------|
| `pag.node.upsert` | `namespace`: non-empty string; `rev`: integer ≥ 1; `node`: объект узла с стабильным id | Пустой `namespace`; `rev` без монотонной семантики per namespace (producer обязан соблюдать; consumer фиксирует warning policy) |
| `pag.edge.upsert` | `namespace`; `rev`; `edges`: non-empty array рёбер с валидными концами | Пустой `edges` |

**Default / nullable:** поля внутри `node`/`edges` — по контракту PAG в каноне памяти; для UI достаточно id и связности для отображения; **суммаризация текста узла не обязательна** для появления узла (OR-014).

### События trace для **подсветки**

| `event_name` (в publish) | Условие | Обязательные поля для UI |
|--------------------------|---------|---------------------------|
| `memory.w14.graph_highlight` | `schema === ailit_memory_w14_graph_highlight_v1` | `namespace`; непустой `node_ids` и/или `edge_ids` после нормализации; `ttl_ms` optional, cap 60000, default при отсутствии — 3000 ms на стороне UI |
| `context.memory_injected` | см. минимум ниже | Минимум для внешнего потребителя: `namespace` (non-empty string, если подсветка привязана к namespace); `node_ids: string[]` и/или `edge_ids: string[]` — после нормализации хотя бы один массив **non-empty**; опционально `ttl_ms` с тем же cap/default, что у W14; опционально `project_refs: object[]` — только если id извлекаются из ссылок вместо прямых массивов (тогда парсер обязан выдать непустые `node_ids` и/или `edge_ids`). |
| `context.compacted` | то же | То же минимум. |
| `context.restored` | то же | То же минимум. |

**Связь с внешним протоколом:** семантика списка узлов для подсветки согласована с типом **`highlighted_nodes`** в [`external-protocol.md`](external-protocol.md) (`node_ids`, компактный `reason`); для строк trace форма может быть вложена в payload topic-publish, но **интегратор обязан извлечь** перечисленные поля или эквивалент после нормализации.

**Forbidden для канона observability в trace:** сырые промпты, chain-of-thought, полные дампы файлов — как в [`external-protocol.md`](external-protocol.md).

### События, не являющиеся PAG/highlight, но важные для UX

- **`service.request` / ответы** Work↔Memory с `memory.query_context` — для статуса recall в чате и для извлечения `user_turn_id` (cancel).
- **Synthetic UI rows** (например фазы recall, `session.cancelled`) — могут дописываться в trace через Desktop; интегратор внешнего клиента должен учитывать дедупликацию.

## Абстрактный алгоритм подключения Desktop к AgentMemory/PAG/trace

Ниже — **платформенно-абстрактная** последовательность; конкретный Electron IPC — частный случай.

1. **Resolve runtime:** получить `runtime_dir` единообразно для main и supervisor (целевое правило: один `AILIT_RUNTIME_DIR`; **допуск расхождения** — только как явно описанный риск с приоритетом ответа supervisor для UI).
2. **Supervisor handshake:** убедиться, что `supervisor.sock` доступен; запросить `status`, получить `runtime_dir` для сессии.
3. **Broker attach:** `create_or_get_broker` для `chat_id` с **primary** `namespace` и `project_root` (целевое: явная модель primary vs список workspace для 1–5 проектов).
4. **Загрузить durable trace:** прочитать JSONL с начала, построить массив строк, применить правила дедупликации.
5. **Подписаться на live trace:** открыть потоковое соединение к broker endpoint, отправить команду subscribe, для каждой новой строки: append + dedup.
6. **Инициализировать PAG session store:** для активной UI-сессии создать snapshot; выполнить **full load** через slice по всем релевантным namespace; если БД отсутствует — перейти в режим **trace-only accumulation** с поллером появления БД.
7. **Replay:** применить все PAG-дельты из trace к merged в порядке индексов; применить highlight из trace; зафиксировать `lastAppliedTraceIndex` и `graphRevByNamespace`.
8. **Инкремент:** на каждое расширение trace применять только новые строки как дельты; обновлять highlight; **не** вызывать full slice на каждую строку.
9. **3D render (D-EDGE-GATE-1):** спроецировать merged: UC-04A (отбросить рёбра без обоих концов) → reachability-keep до любой A-ноды области (single/separate — namespace; unified — union). A-узлы остаются всегда; узлы без пути до A не попадают в `graphData`. Никаких синтетических узлов/рёбер. Подсветка применяется через **лёгкий refresh** к узлам, прошедшим edge-gate, без смены ключа `ForceGraph3D` (см. OR-011/013).
10. **Reconnect:** при обрыве trace channel — exponential backoff с нижней границей (например 800 ms), повтор шагов 4–5 для хвоста durable + live.
11. **Memory journal (опционально для панели):** polling отдельного файла с фильтром по `chat_id` — не смешивать с PAG merge.

**Ошибки:** broker/supervisor возвращают `ok: false` с строкой ошибки; trace channel сообщает `error`/`end` — клиент обязан перейти в partial reconnect path.

## Целевые требования пользователя (нормативный блок)

Эти правила — **target** для продукта; расхождения с текущим кодом помечены в Acceptance и backlog.

1. **OR-010 Multi-project:** в одном чате допускается **от 1 до 5** подключённых проектов; граф и подсветка должны быть определены для **каждого** выбранного namespace **или** для явно выбранного «primary» namespace; текущее ограничение «только `namespaces[0]` для 3D highlight» — **не целевое**.
2. **OR-011 Производительность UI:** подсветка и добавление новых нод **не должны** требовать полной перерисовки всего графа на каждое событие; **целевой** инвариант: инкрементальные обновления данных + визуальный refresh без remount всего WebGL-контекста при типичной PAG-дельте.
3. **OR-012 Изоляция:** проекты без общих рёбер отображаются **корректно**; синтетические узлы/рёбра в проекции **запрещены** (D-EDGE-GATE-1). Изолированные подграфы без пути до A-корня в 3D не показываются; изолированность нескольких A между собой — допустима (каждая A — самостоятельный корень).
4. **OR-013 Стабильность структуры:** после первичной загрузки координаты и топология **не должны** непрогнозируемо «прыгать» при обычных дельтах; динамика в рантайме — через инкременты и фиксацию layout (freeze) по правилам канона.
5. **OR-014 Появление ноды (D-EDGE-GATE-1):** узел уровня B/C/D отображается в 3D только при наличии **пути рёбер** в `merged` до какой-либо A-ноды того же namespace (или union для multi_unified); A-узлы видны всегда, без рёбер. **Наличие суммаризации не обязательно**. Placeholder-узлы подсветки на сцену 3D **не** попадают, пока не появится связность с A.
6. **OR-017 Лимит узлов:** **`max_nodes` default = 100000** в конфигурации Desktop yaml (и согласованный лимит slice/Python); до реализации — **current_target_mismatch** с 20k/40k.

## Целевая схема конфигурации `~/.ailit/desktop`

**Статус относительно кода:** `implementation_backlog` — каталог и yaml **отсутствуют** в репозитории; ниже — **целевой** контракт для install и runtime.

### Размещение файлов

- **Корень:** `~/.ailit/desktop/` (или `$AILIT_HOME/desktop/` если задан единый дом ailit).
- **Базовые файлы (предложение):**
  - `config.yaml` — основные ключи UI и лимиты.
  - `paths.yaml` — опционально; явные overrides путей (для корпоративных установок).
- **Кодировка:** UTF-8; комментарии в YAML разрешены для документирования путей.

### Пример целевого `config.yaml` (с комментариями-путями)

```yaml
# Desktop UI configuration (TARGET — не реализовано в коде полностью)
version: 1

# Максимум узлов графа в UI/slice pipeline (default 100000 per OR-017)
max_nodes: 100000
max_edges: 200000  # согласовать с политикой slice; must align with Python caps after change

# Primary namespace policy для multi-project: explicit | first_selected
highlight_namespace_policy: explicit

# Тайминги UI (optional defaults)
trace_reconnect_min_ms: 800
memory_journal_poll_ms: 2000

# --- Пути данных (комментарии = документация для оператора) ---
# runtime_dir:
#   Источник истины для сессии: ответ supervisor status (result.runtime_dir).
#   Дефолт резолва без env: XDG_RUNTIME_DIR/ailit или ~/.ailit/runtime
# trace_dir:
#   {runtime_dir}/trace/trace-<safe_chat>.jsonl
# chat_logs_root:
#   AILIT_AGENT_MEMORY_CHAT_LOG_DIR или ~/.ailit/agent-memory/chat_logs (как Python default_chat_logs_dir)
# desktop_graph_logs:
#   {chat_logs_root}/<safe_chat>/ailit-desktop-full.log
#   {chat_logs_root}/<safe_chat>/ailit-desktop-compact.log
# agent_memory_verbose_log:
#   {chat_logs_root}/<safe_chat>/<safe_chat>.log  (memory.debug.verbose=1)
# memory_journal_file:
#   $AILIT_MEMORY_JOURNAL_PATH или ~/.ailit/runtime/memory-journal.jsonl
# pag_sqlite:
#   Дефолт CLI: ~/.ailit/pag/store.sqlite3 (см. install канона ailit)
# electron_userdata:
#   Каталог Chromium/Electron userData (localStorage UI) — dev.ailit.desktop на Linux;
#   точный путь: app.getPath('userData') (verification_gap без лога)
# electron_cache:
#   Поддерево userData/Chromium cache — политика Electron по умолчанию
# desktop_assets:
#   Иконки и статика — внутри пакета AppImage, не ~/.ailit
```

### Политика при превышении `max_nodes`

- **Required:** UI обязан показать предупреждение и **не** заявлять полноту графа.
- **Default:** применить caps на slice и визуализацию согласованно (один источник правды для Desktop и `pag_slice_caps` в Python).
- **Forbidden:** молчаливое обрезание без observability.

## Брендбук и `docs/web-ui-book/` (документация репозитория)

**Это не часть нормативного алгоритма памяти.** Визуальные токены и HTML-референсы живут в **`docs/web-ui-book/`** в репозитории; канон алгоритмов только **отсылает** к книге для цветов/типографики.

### Синхронизация с публикацией канона

**Обязательное правило:** при публикации или существенном обновлении материалов пакета `context/algorithms/agent-memory/` (включая этот файл и [`INDEX.md`](INDEX.md) по Desktop) каталог **`docs/web-ui-book/`** должен оставаться **согласованным эталоном** UI: при изменении stitch-экспорта выполняют повторное копирование дерева из авторитетного пути разработчика в `docs/web-ui-book/`, обновляют [`docs/web-ui-book/SOURCE.md`](../../../docs/web-ui-book/SOURCE.md) (дата и при необходимости путь источника) и проверяют [`docs/web-ui-book/INDEX.md`](../../../docs/web-ui-book/INDEX.md). Так фиксируется исходное требование: книга переносится в репозиторий **вместе с** фиксацией канона в `context/algorithms/`, а не отдельным «забытым» шагом.

### Факты по инвентаризации stitch

- **Путь источника на машине разработчика:** `/home/artem/Desktop/айлит/stitch_example_showcase_system/`
- **Объём:** **8 файлов**, **4 верхнеуровневых папки**
- **3× HTML** (`code.html` в папках экранов), **2× Markdown** (брендбук Candy + дизайн-док для Figma/Cursor), **3× PNG** превью, **0** отдельных `.css` (стили — **Tailwind CDN** + inline config, частично `<style>` и внешние шрифты)
- **Логические разделы:** (A) токены Candy `candy/DESIGN.md`; (B) спецификация экранов `ai_agent_design_documentation_for_figma_cursor.md` (блоки 1–5); (C) три экрана: UI library, agent interaction graph, minimalist chat

### Содержимое `docs/web-ui-book/` в репозитории

Зеркало stitch (имена папок сохранены): `candy/`, три каталога `ai_agent_*_candy_style/` с `code.html` и `screen.png`, корневой `ai_agent_design_documentation_for_figma_cursor.md`. Навигация и правило синхронизации — в [`docs/web-ui-book/INDEX.md`](../../../docs/web-ui-book/INDEX.md); происхождение — [`docs/web-ui-book/SOURCE.md`](../../../docs/web-ui-book/SOURCE.md). Политика CDN/vendoring — `implementation_backlog`, если нужен офлайн-просмотр без внешних URL.

## Commands

### Manual smoke (оператор)

- Запустить Desktop, открыть чат, убедиться в потоке trace (нет бесконечного reconnect без причины).
- Открыть 3D memory, выполнить сценарий с живым чатом; проверить по compact-сообщениям / trace наличие `pag.node.upsert` / `pag.edge.upsert` при изменении PAG.
- Проверить подсветку: наличие `memory.w14.graph_highlight` в trace при активном W14.

**Признаки успеха smoke (компактно, проверяемо):**

- В trace или compact UI-log есть хотя бы одна строка с `type === "topic.publish"` и **`payload.kind`** ∈ `{ "pag.node.upsert", "pag.edge.upsert" }` после сценария, который меняет PAG (не только пустой merged).
- Для подсветки W14: **`event_name === "memory.w14.graph_highlight"`** на той же логической строке publish (или эквивалент после нормализации), с **`schema === ailit_memory_w14_graph_highlight_v1`** и непустым **`node_ids` и/или `edge_ids`** в payload после trim.
- Дополнительно для контекстных событий: при сценарии injection/compaction/restore — **`event_name`** ∈ `{ "context.memory_injected", "context.compacted", "context.restored" }` и извлечённые **`namespace` + `node_ids` и/или `edge_ids`** по минимуму из раздела «События trace для подсветки».

**Blocked by environment:** без running supervisor/broker и модели провайдера полный smoke невозможен — пометить `blocked_by_environment` в отчёте тестирования.

## Observability

| Событие / артефакт | Обязательный compact payload | Кто потребляет |
|--------------------|------------------------------|----------------|
| Trace row push | `chatId`, тип строки, `message_id` где применимо | Desktop renderer |
| PAG delta applied | namespace, rev, счётчики узлов/рёбер (без сырых тел файлов) | UI store, optional compact trace hooks |
| Highlight applied | источник события (W14/context), ttl, число id | 3D view |
| Rev mismatch | namespace, ожидаемое vs фактическое rev | UI warning banner / trace warning |
| Trace channel | open/end/error | Session reconnect logic |

**Forbidden:** логировать полные промпты или секреты в каналах UI.

## Failure and retry rules

- **FR1 (trace reconnect):** при `error`/`end` канала trace — обязательна задержка перед повторной подпиской (**default** минимум 800 ms в текущем коде); **forbidden** бесконечный tight loop без backoff.
- **FR2 (rev gap):** при скачке `rev` consumer **default** — warning + продолжение с новым rev; **target option** — режим hard-stop инкрементов до `pag_snapshot_refreshed` (требует явного решения в feature).
- **FR3 (sqlite missing):** режим trace-only **partial**; UI обязан периодически опрашивать появление БД (**default** интервал поллера 2500 ms в текущем коде как факт).
- **FR4 (runtime_dir mismatch):** если supervisor status и main default расходятся, diagnostic append и trace read могут разойтись — **target:** единый `AILIT_RUNTIME_DIR`; до этого — documented risk.
- **FR5 (cancel без user_turn_id):** если в trace нет корректной строки `memory.query_context`, cancel может быть **partial**; **target:** рантайм обязан всегда эмитить непустой `user_turn_id` для активного turn.

## Examples

### Example 1: Happy path — realtime граф и подсветка

Пользователь открыл Desktop, выбрал один проект и чат. Supervisor создал broker endpoint. Клиент загрузил durable trace, подписался на live stream, выполнил PAG full load из SQLite, применил реплей дельт. Во время диалога AgentMemory публикует `pag.node.upsert` и `pag.edge.upsert`; merged обновляется инкрементально; на экране 3D появляются новые узлы. Затем приходит `memory.w14.graph_highlight` с id узлов — подсветка обновляется через refresh, TTL истекает и подсветка гаснет.

### Example 2: Partial path — нет SQLite и лимиты

Пользователь открыл память до готовности PAG БД: merged пустой, граф накапливается из trace-дельт. После появления `store.sqlite3` клиент заменяет merged полным срезом и реплеем trace. Отдельно: merged достиг порога **текущих** caps 20k/40k — UI показывает предупреждение о большом графе; **целевое** поведение при 100k — после `implementation_backlog`.

### Example 3: Failure path — обрыв trace channel

После сетевого сбоя или перезапуска broker сокет подписки закрывается; UI получает `ailit:traceChannel` с `end` или `error`, увеличивает счётчик reconnect, ждёт **не менее** минимальной задержки, перечитывает durable JSONL и открывает новую подписку. Если broker недоступен после N попыток — отображается ошибка сессии; граф остаётся в последнем согласованном merged (не silent corruption).

## Acceptance criteria

1. Документ описывает **все** desktop OR-001…OR-017 в явных разделах или таблице связи; нет «молчаливых» пропусков.
2. Явно разведены **target** требования OR-010–014, OR-017 и **current** факты (20k/40k, remount по rev, `namespaces[0]`, отсутствие `~/.ailit/desktop`).
3. Перечислены **типы trace-событий** для графа и подсветки с обязательными полями и forbidden для секретов/промптов.
4. Абстрактный алгоритм подключения покрывает handshake, durable+live trace, full load, replay, инкремент, reconnect.
5. Каталог `docs/web-ui-book/` не смешан с нормативным алгоритмом памяти, содержит фактические HTML/MD/PNG и `INDEX.md`/`SOURCE.md`; правило синхронизации с публикацией канона в `context/algorithms/agent-memory/` зафиксировано выше.
6. Есть ссылки на существующий канон пакета ([`external-protocol.md`](external-protocol.md), [`INDEX.md`](INDEX.md)) без путей к временным артефактам pipeline.

## Do not implement this as

- **DNI-1:** Новый модуль графа, не подключённый к trace → merged → 3D (отдельный «второй SoT»).
- **DNI-2:** Полный `pag-slice` на каждую строку trace в steady state.
- **DNI-3:** Подсветка только из memory journal без trace (потеря W14 в realtime).
- **DNI-4:** Утверждение, что OR-017 уже выполнен в коде при caps 20k/40k.
- **DNI-5:** Публикация брендбука внутри `context/algorithms/agent-memory/` как нормативного алгоритма.

## How start-feature / start-fix must use this

- **`02_analyst`** обязан прочитать этот документ перед `technical_specification.md`, если задача касается Desktop, trace, PAG merge, 3D или подсветки.
- **`06_planner`** трассирует задачи к шагам **Target flow** и **Acceptance criteria**; отдельные slices для yaml (`~/.ailit/desktop`) и для remount/key — по рекомендациям synthesis.
- **`08_developer`** не меняет caps Python/Desktop без согласованного обновления канона и теста выравнивания.
- **`11_test_runner`** верифицирует команды из раздела Commands или помечает `blocked_by_environment`; для main IPC — учитывает `verification_gap` (нет pytest на Electron main в общем дереве).
- **`13_tech_writer`** обновляет опубликованный канон только при **намеренном** изменении целевого поведения; брендбук — только под `docs/web-ui-book/`.

## Глоссарий (фрагмент для этого протокола)

- **merged:** единый in-memory граф UI после slice + trace merge.
- **primary namespace:** namespace, выбранный для create broker (сейчас — от первого проекта).
- **rev:** монотонный счётчик версии PAG per namespace в дельтах trace.
