# Workflow 12: PAG trace deltas + desktop graph sync (OOM fix, 10k nodes)

**Идентификатор:** `pag-trace-delta-desktop-12` (канонический файл: [`plans/12-pag-trace-delta-desktop-sync.md`](12-pag-trace-delta-desktop-sync.md); зеркало для навигации: [`plan/12-pag-trace-delta-desktop-sync.md`](../plan/12-pag-trace-delta-desktop-sync.md)).

**Статус:** **активен** — главная стратегия по [`README.md`](../README.md) до закрытия последнего этапа (G12.n) или новой постановки/research.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Зачем этот workflow

1. **OOM / перегруз кучи V8** в `ailit desktop` при открытой панели Memory 3D: полный `ailit memory pag-slice` на каждое обновление **trace** (см. обсуждение: `desktop/src/renderer/views/MemoryGraph3DPage.tsx` — эффект на `rawTraceRows` + `loadGraph()`).
2. Нет **точного инкрементального** отражения PAG в UI: нужны события **новая нода** / **новые рёбра** без полного перечитывания SQLite на каждое событие.
3. **Явная поддержка до 10 000 нод** в 3D/2D графе: сейчас срез и store могут клампить меньше (см. `tools/ailit/memory_cli.py` — лимиты; `tools/agent_core/memory/sqlite_pag.py` — `list_nodes` cap).
4. Единая модель: **глобальный синк из БД только по кнопке Refresh**; **полная загрузка** при смене чата/проекта; **дельты** в потоке trace.

---

## Положение в графе планов

- **Workflow 7** — PAG A/B/C, `ailit memory index`, SQLite store: [`plan/7-workflow-project-architecture-graph.md`](../plan/7-workflow-project-architecture-graph.md).
- **Workflow 8** — trace, broker, supervisor: [`plan/8-agents-runtime.md`](../plan/8-agents-runtime.md); durable trace: `tools/agent_core/runtime/trace_store.py` (и аналоги).
- **Workflow 9** — `ailit desktop`, IPC, `pagGraphSlice`: [`plan/9-ailit-ui.md`](../plan/9-ailit-ui.md); мост: `desktop/src/main/pagGraphBridge.ts`.
- **Workflow 10** — Context Ledger, highlights: [`plan/10-context-ledger-memory-highlights.md`](../plan/10-context-ledger-memory-highlights.md); `desktop/src/renderer/runtime/pagHighlightFromTrace.ts`.
- **Workflow 11** — global AgentMemory, journal, 3D: **закрыт** — [`plan/11-agent-memory-llm-journal.md`](../plan/11-agent-memory-llm-journal.md).
- **Workflow 12** не отменяет G7/G8/G9/G10/G11: **добавляет** контракт дельт, политику синка и фиксы производительности.

---

## Зафиксированные решения (постановка)

| # | Решение |
|---|---------|
| 1 | **MVP:** дельты — **структурированные строки trace** (тот же jsonl / тот же конвейер в desktop), **без второго файла** и без отдельного IPC-канала на первом этапе. |
| 2 | Два вида событий: **`pag.node.upsert`** и **`pag.edge.upsert`** (разные `kind` / `type` в строке trace — уточнить в G12.1, см. схему ниже). |
| 3 | **`rev` монотонный по `namespace`**. При **полном** срезе (после `pag-slice` или эквивалента) в ответе/метаданных задать **стартовый `rev`**, чтобы следующие дельты стыковались (см. G12.1). |
| 4 | **Полный глобальный синк из БД** — **только кнопка Refresh** (ручной `pag-slice` + пагинация до лимитов). **Автоматического** debounce/throttle полного среза по трассе **нет**. |
| 5 | **При смене чата/проекта** граф **загружается полностью** (один или несколько `pag-slice` с пагинацией). **Старый** граф выбрасывается, если **чат закрыт** (смена сессии / выход с контекста чата). **Переключение вкладок** UI (в т.ч. сворачивание панели Memory) **не** сбрасывает модель графа в десктопе. |
| 6 | При **рассинхроне** `rev` (пропуск, несовпадение): **toast** + предложение **Refresh** (пользователь согласовал). |
| 7 | При превышении лимита нод (10 000): **предупреждение** в UI, не молчаливый truncate. |
| 8 | **2D** (`MemoryGraphPage`) и **3D** (`MemoryGraph3DPage`) — **одинаковые правила** синка и дельт. |
| 9 | Отдельный **`contract_version` для дельт** на MVP **не** вводим; допускается **сброс старой** SQLite userspace (пользователь удалит старую базу). |

---

## Схема событий trace (черновик для G12.1)

Минимальный JSON (имена полей уточняются в этапе контракта, логика — идемпотентный merge по `id`):

**`pag.node.upsert`**

- `kind`: `pag.node.upsert`
- `namespace: string`
- `rev: number` (монотонно по namespace)
- `node: { node_id, level, label|path, ... }` (совместимо с `nodeFromPag` / PAG store)

**`pag.edge.upsert`**

- `kind`: `pag.edge.upsert`
- `namespace: string`
- `rev: number`
- `edges: [{ edge_id, from_node_id, to_node_id, ... }]` (одно или несколько рёбер)

Строка должна проходить существующий trace pipeline (append durable, дедуп по ключу строки в [`DesktopSessionContext`](../desktop/src/renderer/runtime/DesktopSessionContext.tsx) — при необходимости расширить `dedupKeyForRow` / фильтр, чтобы дельты не схлопывались ошибочно).

---

## Целевая модель (компоненты)

### Runtime / AgentMemory

- После **записи** ноды/рёбра в SQLite PAG: эмит в **trace** (тот же chat/session), **минимальный** payload.
- Инкремент **`rev` по namespace** (источник: либо счётчик в store при commit, либо отдельная таблица/колонка — проектируется в G12.1).
- Не дублировать гигантские поля: короткие `title`/`path`, без raw file contents.

### `ailit memory pag-slice` (CLI) и мост

- Снять/поднять **клампы**: десктоп должен иметь возможность запросить **до 10 000** нод за вызов (и рёбра с согласованным лимитом); [`memory_cli.py`](../tools/ailit/memory_cli.py) `nlim/elim`, [`sqlite_pag.py`](../tools/agent_core/memory/sqlite_pag.py) `list_nodes` / `list_edges`.
- **Пагинация** на стороне [`loadPagGraphMerged`](../desktop/src/renderer/runtime/) (новый модуль): цикл `has_more` + offset до капа **10k нод** / **20k рёбер** (согласовано в постановке).
- [`pagGraphBridge.ts`](../desktop/src/main/pagGraphBridge.ts): увеличить `maxBuffer` под крупный stdout JSON.

### `ailit desktop`

- **Состояние графа** (2D+3D): held в React context (расширить [`DesktopSessionContext`](../desktop/src/renderer/runtime/DesktopSessionContext.tsx) или ввести узкий `PagGraphSessionContext` — решается в G12.2), ключуется **chat + namespace(s)** active workspace.
- **Обработка trace:** на строки `pag.node.upsert` / `pag.edge.upsert` — [`mergeMemoryGraph`](../desktop/src/renderer/runtime/memoryGraphState.ts) / тонкие апдейты, проверка `rev`.
- **Убрать** вызов полного **`loadGraph()`** из эффекта на каждую строку trace; **подсветка** (Context Ledger) остаётся на [`pagHighlightFromTrace`](../desktop/src/renderer/runtime/pagHighlightFromTrace.ts) без полного PAG-reload.
- **Refresh:** только полный `pag-slice` (с пагинацией) + **установка ожидаемого `rev`** из ответа (если добавлено в JSON ответа pag-slice в G12.1).
- **Смена чата/проекта:** полная загрузка (как в п.5), **сброс** `rev`/`graph` state для предыдущей сессии по правилам закрытия чата.
- **Предупреждение** при `nodes.length > MAX`.

### Ограничения и производительность 3D

- Throttle `fg.refresh()` в цикле подсветки; при большом `N` — ослабить/отключить `linkDirectionalParticles` (см. [`MemoryGraph3DPage`](../desktop/src/renderer/views/MemoryGraph3DPage.tsx)).
- `warmupTicks`/`cooldownTicks` — по необходимости снизить при 10k (подбор в G12.3).

---

## Доноры и best practices (локальные пути, без копипаста)

| Донор | Локальная ссылка | Зачем |
|-------|------------------|--------|
| Событийные графы / очереди | `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:12-80` | Сериализация обновлений per resource. |
| Простой граф-контракт | `/home/artem/reps/obsidian-memory-mcp/types.ts:1-16` | Узлы/связи, минимальные DTO. |
| Ailit broker + trace | `tools/agent_core/runtime/broker.py`, `tools/agent_core/runtime/subprocess_agents/memory_agent.py` | Куда встраивать emit дельт. |
| Ailit PAG store | `tools/agent_core/memory/sqlite_pag.py:359-442` | `list_nodes` / `list_edges`, лимиты, rev extension point. |
| Desktop 3D | `desktop/src/renderer/views/MemoryGraph3DPage.tsx`, `desktop/src/main/pagGraphBridge.ts` | Убрать hot-path `pag-slice`, IPC лимиты. |
| OpenCode session events | `/home/artem/reps/opencode/packages/opencode/src/v2/session-event.ts:6-74` | Typed event stream → UI. |

---

## Порядок реализации (этапы)

Исполнять по этапам; после логического завершения этапа — проверки, отдельный **коммит** с префиксом `g12/n` или `pag-12/G12.n`. После успешного коммита — `curl` на ntfy по [workflow](../.cursor/rules/project-workflow.mdc).

---

## G12.0 — План, README, канон

**Цель:** зафиксировать Workflow 12 как **главный** план, связать с репозиторием.

**Задачи:**

1. Добавить [`plans/12-pag-trace-delta-desktop-sync.md`](12-pag-trace-delta-desktop-sync.md) (этот документ).
2. Добавить зеркало/ссылку в [`plan/12-pag-trace-delta-desktop-sync.md`](../plan/12-pag-trace-delta-desktop-sync.md) (если не symlink).
3. Обновить [`README.md`](../README.md): таблица статуса — **Workflow 12 активен**; «Как работать» ссылается на этот план.
4. По [workflow](../.cursor/rules/project-workflow.mdc) — сжатое обновление [`context/INDEX.md`](../context/INDEX.md) или `context/proto/runtime-event-contract.md` (указать, что PAG-дельты описаны в Workflow 12; без дублирования сценариев).

**Критерии приёмки:**

- В README **первая** крупная ветка по смыслу — Workflow 12.
- План содержит этапы G12.0+ и все нюансы постановки.
- Ссылки `plan/` ↔ `plans/` работают из корня клона.

**Проверки:** ревизия markdown, `git diff` разумен.

**Коммит:** `g12/G12.0 plan: PAG trace delta + desktop sync (Workflow 12)`

---

## G12.1 — Runtime: `rev`, emit trace, расширение `pag-slice` JSON

**Цель:** монотонный **`rev` per namespace** в store; **эмит** `pag.node.upsert` / `pag.edge.upsert` в trace; ответ **pag-slice** содержит **`rev` после** полного среза (или текущий head).

**Задачи:**

1. Расширить SQLite / [`SqlitePagStore`](../tools/agent_core/memory/sqlite_pag.py): хранение/бамп `rev` (или отдельная миграция).
2. На успешных `upsert_node` / `upsert_edge` — **append trace row** (типы как в схеме выше). Роутинг: `memory_agent` / индексация — в точках, где пишется PAG.
3. [`memory_cli.py`](../tools/ailit/memory_cli.py) `_pag_slice_payload` / `cmd_memory_pag_slice`: в JSON добавить `graph_rev: number` (имя согласовать) для клиента.
4. Поднять клампы: **10 000** нод, **20 000** рёбер (и согласовать `list_nodes` cap).
5. Unit-tests: `rev` монотонность, emit вызывается, JSON pag-slice содержит `graph_rev`.

**Критерии приёмки:**

- Дельты не теряют порядок относительно `rev` в пределах одного namespace.
- `pytest` + `flake8` по затронутым Python-файлам.

**Коммит:** `g12/G12.1 runtime: PAG rev, trace upsert events, pag-slice graph_rev`

---

## G12.2 — Desktop: state графа, apply дельт, снять OOM path

**Цель:** `DesktopSessionContext` (или вложенный context) хранит **graph + per-namespace `lastRev`**. Обработка trace-only дельт. **Полный** `pag-slice` только **Refresh** и **полная загрузка** при смене чата/проекта.

**Задачи:**

1. Модуль [`loadPagGraphMerged`](../desktop/src/renderer/runtime/) (или аналог): пагинация `pag-slice` до 10k/20k.
2. Убрать **`loadGraph()`** из hot-path `useEffect` на `rawTraceRows` в [`MemoryGraph3DPage`](../desktop/src/renderer/views/MemoryGraph3DPage.tsx); оставить highlight.
3. Подписка на trace: при `pag.node.upsert` / `pag.edge.upsert` — merge, проверка `rev` (при сбое — toast + «Refresh»).
4. **Memory 2D** — те же хуки/состояние, без расхождений.
5. Логика **закрытия чата** vs **смена вкладок** (см. таблицу постановки).
6. Vitest: счётчик вызовов `pagGraphSlice` — не растёт при N фиктивных trace rows (без Refresh).

**Критерии приёмки:**

- Без нажатия Refresh число **полных** PAG-загрузок ограничено (mount + смена чата/проекта + Refresh).
- `npm test` / `npm run typecheck` по `desktop/`.

**Коммит:** `g12/G12.2 desktop: PAG graph state, trace deltas, remove hot pag-slice`

---

## G12.3 — Лимиты UI, OOM hardening, буфер IPC

**Цель:** предупреждение при `nodes > 10_000`; throttle refresh 3D; `maxBuffer` main process; при необходимости снизить частицы/тики симуляции.

**Задачи:**

1. Константы `MEM3D_PAG_MAX_*` (уже в постановке) — единый импорт 2D/3D.
2. [`pagGraphBridge`](../desktop/src/main/pagGraphBridge.ts) — `maxBuffer`.
3. UI banner/toast «граф у лимита».
4. Профилактика OOM: throttle rAF, опционально облегчение при `N > 2000`.

**Проверки:** vitest (политика вызовов), ручной smoke `ailit desktop` (коротко в плане, не блокирует CI).

**Коммит:** `g12/G12.3 desktop: PAG 10k caps, OOM hardening, IPC buffer`

---

## G12.4 — Интеграция тестов и документация `context/*`

**Цель:** e2e-light или unit glue; обновить канон [`context/`](../context/INDEX.md) (кратко: PAG дельты = trace, `graph_rev` в pag-slice).

**Задачи:**

1. При необходимости — `tests/test_memory_pag_slice.py` + desktop tests на пагинацию.
2. `context/proto/runtime-event-contract.md` (или аналог): секция PAG graph trace events.
3. Закрытие: README обновить «G12.n закрыт» (когда этап последний готов).

**Проверки:** `pytest`, `eslint`/`tsc` по проекту.

**Коммит:** `g12/G12.4 tests and context: PAG delta contract`

---

## Non-goals (Workflow 12)

- Отдельный **файл** дельт (вне trace) — не в MVP (возможен follow-up).
- **contract_version** полей дельт — не в MVP.
- Синхронная репликация PAG на remote — вне scope.

---

## Критерий закрытия Workflow 12

- G12.0–G12.4 выполнены, тесты зелёные, README отмечает **закрытие** Workflow 12.
- OOM при нормальной длинной сессии с Memory 3D **не воспроизводится** на сценарии «стрим трассы + дельты».
- Пользователь может удерживать **до 10 000** нод с предупреждением у капа и ручным Refresh для полного согласования с БД.
