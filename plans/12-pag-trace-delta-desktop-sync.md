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
| 10 | **Product bet:** `AgentMemory` — не retrieval, а live query-driven semantic project graph builder: граф A/B/C/D дорастает во время работы `AgentWork`, а `AgentWork` получает compact graph slices вместо raw repo dumps. |
| 11 | Канон C-ноды задаёт **LLM segmentation**; AST/parser могут быть только оптимизацией или validator. Для C identity используются `stable_key` + `semantic_locator`, а `line_hint` — только cache/примерный locator. |
| 12 | `AgentMemory` обязан соблюдать **source boundary**: не анализировать cache/build/binary/dependency artifacts как исходники; исключения разрешены только по явному запросу пользователя и сначала через metadata. |
| 13 | LLM output для памяти — **result-only structured JSON**: без chain-of-thought, markdown, prose и длинных excerpts. Desktop показывает compact journal view. |
| 14 | Все memory-настройки живут в `~/.ailit/agent-memory/config.yaml`; если файла нет, `AgentMemory` создаёт его с дефолтами. Дефолт full-B ingestion: `32768` bytes + отдельный chars cap для LLM payload. |
| 15 | Pending C↔C связи не являются пользовательскими graph edges: хранить отдельно (`pag_pending_edges` или эквивалент), показывать в UI не обязательно; реальный граф отображает только resolved edges. |

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

### Product bet: live semantic project graph

`Ailit Memory` строит и поддерживает **живой семантический граф проекта** прямо во время работы агента: с language-agnostic C-level nodes, проверенными границами исходников, compact observable decisions и desktop-visible graph deltas.

`AgentMemory` — **не retrieval**. Это live, query-driven semantic project graph builder.

Граф памяти должен улучшаться по мере работы `AgentWork`:

- каждый полезный `memory.query_context` может дорастить A/B/C/D;
- каждое изменение файла может refresh-нуть затронутые C-ноды;
- каждая resolved relation становится reusable edge;
- desktop показывает рост графа через trace deltas;
- `AgentWork` получает compact graph slices, а не raw repository dumps.

### Canonical A/B/C/D semantics for memory LLM

**A / Project:** root проекта/репозитория в `namespace`. Хранит identity, branch/commit, root path, high-level summary, index policy, known top-level B, `graph_rev`.

**B / Resource:** структурный ресурс проекта: директория, файл, notebook, config, generated source artifact, package/module boundary. B описывает расположение и роль ресурса, но не заменяет внутреннюю структуру файла.

**C / Semantic Fragment:** минимальная смысловая единица внутри B: function, class, method, type/interface, config subtree, markdown heading/paragraph, SQL query, notebook cell, XML/launch/URDF block, arbitrary text chunk. C всегда имеет:

- `stable_key` — первично формируется LLM при segmentation;
- `semantic_locator` — kind/name/signature/parent/heading/json pointer/cell id/chunk fingerprint;
- `line_hint` — примерный cached locator для быстрого поиска, **не identity**;
- `content_fingerprint`, `summary`, `summary_fingerprint`, `confidence`;
- `b_node_id`, `b_fingerprint`, `extraction_contract_version`, `staleness_state`.

**D / Derived Memory:** производный reusable artifact памяти: `query_digest`, `compact_summary`, `decision_digest`, `restored_context`. D не является дочерним слоем файла и создаётся только когда результат полезен дальше текущего внутреннего шага. D обязан иметь provenance-связи на A/B/C и trace/request id.

### AgentWork ↔ AgentMemory ↔ LLM contract

`AgentWork` обращается в `AgentMemory` для пользовательского запроса или собственного tool-call запроса во время reasoning. За один user turn допускается несколько memory calls.

```text
AgentWork
  -> memory.query_context(goal, workspace_projects, budget, max_memory_turns)
    -> AgentMemory
       1. build GraphPassport: A list or A + top B
       2. call memory LLM planner with compact candidates only
       3. execute requested_reads locally with OS-level tools
       4. call memory LLM extractor/update/synth on bounded excerpts
       5. upsert A/B/C/D + resolve/persist links
       6. emit pag.node.upsert / pag.edge.upsert deltas
       7. return memory_slice + project_refs + decision_summary
```

Multi-project rule:

- если в чате активны 2+ проекта, первый LLM pass получает список A-кандидатов и выбирает project(s);
- если активен один проект, `AgentMemory` сразу даёт LLM A + top-level B/cross-links.

`AgentMemory` читает файлы локально; LLM не вызывает file tools и не получает full repo. Raw B отдаётся полностью только если он text-like, не artifact и проходит budget.

### AgentMemory config

Путь по умолчанию:

```text
~/.ailit/agent-memory/config.yaml
```

Если файла нет, `AgentMemory` создаёт его с дефолтными значениями:

```yaml
memory:
  llm:
    max_full_b_bytes: 32768
    max_full_b_chars: 32768
    max_turns: 4
    max_selected_b: 8
    max_c_per_b: 40
    max_reads_per_turn: 8
    max_summary_chars: 160
    max_reason_chars: 80
    max_decision_chars: 240
  d_policy:
    max_d_per_query: 1
    min_linked_nodes: 2
    allowed_kinds:
      - query_digest
      - compact_summary
      - decision_digest
      - restored_context
  artifacts:
    allow_explicit_artifact_content: true
```

`max_full_b_bytes` используется для предфильтра raw file; `max_full_b_chars` — для decoded LLM payload.

### Source boundary prompt contract

Memory LLM анализирует только source-owned project materials:

- source code, tests, fixtures, handwritten docs;
- config/build/deploy manifests;
- schemas, examples, templates, launch/domain text files, если они maintained in repo.

Forbidden artifacts:

- dependency dirs: `node_modules`, `vendor`, `.venv`, `venv`, `site-packages`;
- caches: `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.cache`;
- VCS/tool internals: `.git`, `.hg`, `.svn`, `.idea`, `.vscode`, если пользователь явно не просит;
- build outputs: `build`, `dist`, `out`, `target`, `cmake-build-*`, `install`, `log`;
- compiled/binary objects: `*.pyc`, `*.pyo`, `*.o`, `*.obj`, `*.so`, `*.dll`, `*.dylib`, `*.a`, `*.lib`, `*.class`, `*.jar`, `*.wasm`;
- bundles/minified assets: `*.min.js`, `*.bundle.js`, source maps, coverage reports;
- lock/cache/data dumps, кроме явного запроса про dependency resolution/generated state.

Правила:

1. Не выбирать forbidden materials для semantic analysis.
2. Не создавать C-ноды из forbidden materials.
3. Не выводить поведение проекта из artifacts.
4. Если forbidden path попал в candidates, вернуть его в `excluded_nodes[]` с короткой причиной.
5. Если пользователь явно спросил artifact, сначала анализировать metadata: path, size, mtime, known producer. Content читать только если иначе нельзя ответить.
6. Предпочитать source B, которые generate/configure/document artifact, а не сам artifact.

Контракт исполняется дважды: механический фильтр в `AgentMemory` до LLM и structured `excluded_nodes[]` от LLM, если artifact всё же попал в prompt.

### Result-only LLM output contract

Memory LLM возвращает только compact structured JSON:

- без chain-of-thought, reasoning notes, markdown, prose outside JSON;
- без raw source excerpts, если schema явно не требует;
- `summary` max 160 chars, `reason/why` max 80 chars, `decision` max 240 chars;
- unknown enum/path из forbidden artifacts отклоняется local validator;
- retry делается только при schema-invalid JSON; длинные поля локально режутся, запрещённые paths отклоняются.

Planner schema:

```json
{
  "schema": "agent_memory.planner_result.v1",
  "action": "select|read|stop",
  "selected": [{"id": "B:README.md", "why": "overview", "p": 1}],
  "exclude": [{"id": "B:__pycache__/x.pyc", "why": "cache artifact"}],
  "reads": [{"path": "README.md", "mode": "full_text", "max_chars": 12000}],
  "stop": "need_reads|ready|no_source_candidates|budget_exhausted",
  "decision": "Read project overview and CLI entrypoint."
}
```

Extractor schema:

```json
{
  "schema": "agent_memory.extractor_result.v1",
  "source": "B:README.md",
  "nodes": [
    {
      "level": "C",
      "kind": "md_section",
      "stable_key": "md_section:Workflow",
      "title": "Workflow",
      "semantic_locator": {"heading_path": ["Workflow"]},
      "line_hint": {"start": 20, "end": 44},
      "summary": "Explains plan, checks, commits and notification workflow.",
      "confidence": 0.95
    }
  ],
  "link_claims": [],
  "decision": "Extracted workflow section."
}
```

### Universal C extraction and refresh

Основной путь C-разбиения — LLM segmentation of B:

1. Если B text-like и `size_bytes <= max_full_b_bytes`, `AgentMemory` передаёт полный B в memory LLM один раз.
2. Если B больше лимита, `AgentMemory` строит mechanical chunk catalog без semantic assumptions: line windows, headings, notebook cells, JSON/YAML top-level blocks, XML elements, blank-line blocks.
3. LLM выбирает chunks/excerpts и возвращает C-ноды, summaries и link claims.
4. C-разбиение кешируется по `B.fingerprint`; повторная segmentation запрещена, пока fingerprint не изменился.
5. AST/parser extraction может использоваться только как оптимизация или validator, но не как источник истины.

При изменении файла C identity держится на `stable_key + semantic_locator`; `line_hint` используется только для быстрого remap:

1. `AgentMemory` сначала проверяет старый `line_hint`.
2. Если semantic locator не найден, расширяет окно `+20`, `+50`, `+100` строк.
3. Если не найдено, ищет по semantic signature/name в файле или chunk catalog.
4. Если найдено в новом месте, обновляет `line_hint`, `b_fingerprint`, `content_fingerprint`, `staleness_state=fresh`.
5. Если не найдено или произошёл split/merge/signature change, C получает `needs_llm_remap`, и LLM update pass получает только old C summary + changed window + nearby candidates.

### AgentWork file change event

После успешной правки файла `AgentWork` отправляет в `AgentMemory` событие:

```json
{
  "schema": "memory.file_changed.v1",
  "chat_id": "chat-1",
  "turn_id": "turn-1",
  "namespace": "project-ns",
  "project_root": "/repo",
  "changes": [
    {
      "path": "src/service.py",
      "operation": "modified",
      "changed_ranges": [{"new_lines": [425, 445]}]
    }
  ],
  "source": "AgentWork"
}
```

`AgentWork` передаёт path/operation/available ranges. Fingerprints и окончательный remap считает `AgentMemory`, потому что он владеет PAG.

Если разработчик руками перенёс функцию, а `line_hint` устарел:

1. `AgentWork` спрашивает `memory.query_context` про `handle_request`.
2. `AgentMemory` находит C по `stable_key=function:handle_request`, читает старый `line_hint`.
3. В старом диапазоне функции нет; `AgentMemory` расширяет окно и ищет semantic signature.
4. Функция найдена в новом месте; `line_hint` обновляется без full-B LLM pass.
5. `AgentMemory` эмитит `pag.node.upsert`, возвращает `AgentWork` актуальный slice.
6. После правки `AgentWork` отправляет `memory.file_changed.v1`.
7. `AgentMemory` refresh-ит affected C, обновляет summary через small LLM update pass и резолвит link claims.

### C↔C link claims and pending resolver

LLM обнаруживает связи для любого языка/формата, но не пишет финальные DB edges напрямую. Она возвращает `link_claims[]`:

```json
{
  "from": {"node_id": "C:src/a.c#function_a"},
  "relation": "calls",
  "target": {
    "name": "function_b",
    "kind": "function",
    "path_hint": "src/b.c",
    "language": "c"
  },
  "confidence": 0.82
}
```

MVP relation types:

- `calls`;
- `imports_symbol`;
- `references`;
- `documents`;
- `configures`;
- `tests`.

`AgentMemory` resolver:

1. ищет C по exact `path_hint + title/name`;
2. затем по `kind + title/name` в namespace;
3. если найден один target — создаёт real `pag_edges` edge;
4. если target не найден или неоднозначен — сохраняет pending relation в `pag_pending_edges` (или эквивалент), но не показывает как real graph edge;
5. когда новая C-нода появляется позже, resolver поднимает pending relation в real edge и эмитит `pag.edge.upsert`.

### D creation policy

D создаётся только если результат reusable beyond current internal step.

Создавать D:

- итоговый `memory.query_context`, если есть useful synthesis для `AgentWork`;
- compact/session summary;
- важный decision digest;
- результат, который реально вставлен в prompt;
- synthesis, который связывает несколько A/B/C и экономит будущие чтения.

Не создавать D:

- на каждый planner/extractor call;
- на промежуточный выбор B;
- на rejected candidates;
- на short failed attempts;
- на одноразовое чтение файла без итогового вывода.

Перед созданием D применяется policy:

- минимум `min_linked_nodes` связанных A/B/C или один крупный A-level synthesis;
- summary не пустой и не дублирует существующий D по fingerprint;
- результат возвращён `AgentWork` или помечен reusable;
- `kind` входит в allowlist;
- лимит `max_d_per_query`, по дефолту 1.

`D.fingerprint = sha256(kind + normalized_summary + sorted(linked_node_ids))`. Если такой D уже есть, новый D не создаётся: обновить `last_used_at` / usage edge.

### Desktop compact memory journal

Desktop journal показывает compact view:

- `task`, `action`, `selected`, `exclude`, `reads`, `decision`;
- counts/hash/locators для excerpts;
- node/edge ids, `graph_rev`, `partial`, `recommended_next_step`;
- без chain-of-thought и без raw excerpts по умолчанию.

Raw excerpts допускаются только в debug/diagnostic режиме с лимитами и redaction.

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
| Graphiti pending graph updates | `/home/artem/reps/graphiti/mcp_server/src/services/queue_service.py:12-80` | Queue/group-id pattern для resolver jobs по namespace/project. |
| Obsidian memory graph | `/home/artem/reps/obsidian-memory-mcp/types.ts:1-16` | Простая модель observations/relations для D и pending link claims. |

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

## G12.5 — AgentMemory config and result-only LLM contracts

**Цель:** добавить global config `~/.ailit/agent-memory/config.yaml`, result-only prompt contracts, source boundary validation и compact journal payloads.

**Задачи:**

1. Ввести `AgentMemoryConfig` с автосозданием `~/.ailit/agent-memory/config.yaml`, если файла нет.
2. Дефолты: `max_full_b_bytes=32768`, `max_full_b_chars=32768`, `max_turns=4`, `max_selected_b=8`, `max_c_per_b=40`, `max_reads_per_turn=8`.
3. Описать/реализовать prompt policy: no reasoning output, JSON only, short fields, enum validation.
4. Source boundary filter: mechanical pre-filter + LLM `exclude[]` contract.
5. Compact journal view: хранить/показывать task/action/selected/exclude/reads/decision, без raw excerpts по умолчанию.

**Критерии приёмки:**

- При первом старте `AgentMemory` создаёт config с дефолтами.
- Invalid JSON от LLM приводит к retry; слишком длинные fields режутся local validator; forbidden paths отклоняются.
- Journal compact view не содержит chain-of-thought и raw excerpts.

**Проверки:** `pytest` + `flake8` по затронутым Python-файлам.

**Коммит:** `g12/G12.5 memory config and result-only LLM contracts`

---

## G12.6 — Universal LLM C segmentation and source boundaries

**Цель:** сделать LLM segmentation каноном C-нod для любых text-like B, сохранив AST/parser только как optimization/validator.

**Задачи:**

1. Ввести `planner_input/result`, `extractor_input/result`, `update_input/result`, `synth_input/result` DTO.
2. Full-B ingestion: если B text-like, source-owned и `size_bytes <= max_full_b_bytes`, передавать decoded text в LLM один раз.
3. Для больших B строить mechanical chunk catalog без semantic assumptions.
4. C schema: `stable_key`, `semantic_locator`, `line_hint`, `content_fingerprint`, `summary_fingerprint`, `b_fingerprint`, `extraction_contract_version`.
5. Поддержать markdown paragraphs/sections, config blocks, XML/launch/URDF blocks, notebook cells, arbitrary text chunks как C.
6. Исключить artifacts из C extraction; при explicit artifact query читать metadata first.

**Критерии приёмки:**

- `.py`, `.md`, `.yaml/.json`, `.xml/.launch/.urdf` и неизвестный text-like файл могут получить C-ноды через LLM.
- `__pycache__`, build/cache/binary artifacts не получают C-ноды.
- C summary краткий, stable_key первично формируется LLM.

**Проверки:** `pytest` + `flake8` по затронутым Python-файлам.

**Коммит:** `g12/G12.6 memory: universal LLM C segmentation`

---

## G12.7 — AgentWork file-change events and C remap

**Цель:** после успешных правок `AgentWork` сообщает `AgentMemory` об изменениях, а `AgentMemory` refresh-ит B/C по semantic identity, не по lines.

**Задачи:**

1. Добавить событие/запрос `memory.file_changed.v1`: `chat_id`, `turn_id`, `namespace`, `project_root`, `changes[] {path, operation, changed_ranges}`.
2. `AgentWork` отправляет событие после успешного write/edit; fingerprints считает `AgentMemory`.
3. `AgentMemory` обновляет B fingerprint и remap-ит C по `stable_key + semantic_locator`.
4. `line_hint` использовать как cache: сначала старый range, затем расширения `+20`, `+50`, `+100`, затем file/chunk search.
5. Если remap не удался, помечать C как `needs_llm_remap` и вызывать small update pass с old summary + changed window + nearby candidates.
6. Эмитить `pag.node.upsert` для обновлённых C и staleness events для исчезнувших/needs_remap C.

**Критерии приёмки:**

- Перенос функции руками в другую часть файла не ломает `memory.query_context`: C находится по semantic locator, `line_hint` обновляется.
- Обычная правка функции не отправляет весь B в LLM, если affected C remap успешен.
- Full-B повторяется только для нового B, отсутствующего C-разбиения, малого файла после structural rewrite или explicit policy.

**Проверки:** `pytest` + `flake8` по затронутым Python-файлам.

**Коммит:** `g12/G12.7 memory: file change events and semantic C remap`

---

## G12.8 — C link claims, pending resolver, real graph edges

**Цель:** LLM обнаруживает C↔C link claims для любого языка/формата, а `AgentMemory` превращает их в реальные DB edges только после resolver validation.

**Задачи:**

1. Поддержать relation types MVP: `calls`, `imports_symbol`, `references`, `documents`, `configures`, `tests`.
2. LLM возвращает `link_claims[]` с `from`, `relation`, `target {name, kind, path_hint, language}`, `confidence`.
3. Resolver ищет target C по exact path+name, затем по kind+name в namespace.
4. При single match — писать real `pag_edges` и эмитить `pag.edge.upsert`.
5. При no/ambiguous match — писать `pag_pending_edges` или эквивалент; pending не обязан отображаться в desktop graph.
6. При появлении новой C resolver повторно проверяет pending и поднимает resolved links в real edges.

**Критерии приёмки:**

- C/go/python/md/config связи могут появляться через LLM claims без language-specific hardcode.
- UI показывает только resolved real edges; pending не создаёт псевдоноды в графе.
- При появлении ранее отсутствующей C pending relation превращается в `pag.edge.upsert`.

**Проверки:** `pytest` + `flake8` по затронутым Python-файлам.

**Коммит:** `g12/G12.8 memory: C link claims and pending resolver`

---

## G12.9 — D creation policy and memory slice synthesis

**Цель:** создать контролируемую D-политику: D только для reusable artifacts, итоговый `memory_slice` содержит compact A/B/C/D, а не внутренние planner/extractor шаги.

**Задачи:**

1. Ввести `DCreationPolicy`: `max_d_per_query`, `min_linked_nodes`, allowed kinds, fingerprint dedupe.
2. Создавать D только для reusable query digest / compact summary / decision digest / restored context.
3. Не создавать D для каждого planner/extractor call, rejected candidates, failed attempts и одноразовых reads.
4. `D.fingerprint = sha256(kind + normalized_summary + sorted(linked_node_ids))`; при дубле обновлять usage metadata, не создавать новую D.
5. `memory_slice` возвращает A+B backbone, выбранные C, релевантные D, `project_refs[]`, `estimated_tokens`, `partial`, `recommended_next_step`, `decision_summary`.
6. Desktop compact journal показывает D creation gate: `created|reused|skipped` + короткая причина.

**Критерии приёмки:**

- Один `memory.query_context` создаёт не больше одного D по дефолту.
- Внутренние LLM calls видны в compact journal, но не засоряют graph D-нodами.
- Повторный похожий query переиспользует существующий D по fingerprint.

**Проверки:** `pytest` + `flake8` по затронутым Python-файлам.

**Коммит:** `g12/G12.9 memory: D policy and compact slice synthesis`

---

## Non-goals (Workflow 12)

- Отдельный **файл** дельт (вне trace) — не в MVP (возможен follow-up).
- **contract_version** полей дельт — не в MVP.
- Синхронная репликация PAG на remote — вне scope.
- Remote/shared memory и MCP-синхронизация semantic graph — вне scope Workflow 12.
- Backfill старого PAG не планируется: допускается удалить старую SQLite userspace перед новой C-моделью.

---

## Критерий закрытия Workflow 12

- G12.0–G12.9 выполнены, тесты зелёные, README отмечает **закрытие** Workflow 12.
- OOM при нормальной длинной сессии с Memory 3D **не воспроизводится** на сценарии «стрим трассы + дельты».
- Пользователь может удерживать **до 10 000** нод с предупреждением у капа и ручным Refresh для полного согласования с БД.
- `AgentMemory` строит live semantic project graph: query-driven A/B/C/D growth, semantic C remap после file changes, resolved C↔C edges и compact observable decisions в desktop.
