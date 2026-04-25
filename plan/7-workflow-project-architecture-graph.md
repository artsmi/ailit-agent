# Workflow 7: граф архитектуры проекта + GUI «ailit memory»

**Идентификатор:** `arch-graph-7` (файл `plan/7-workflow-project-architecture-graph.md`).

Документ задаёт **постановку** для итераций в `ailit-agent`: этапы → задачи → **критерии приёмки** → проверки. Цель — для **каждого проекта** (в смысле `namespace` / workdir в текущей архитектуре) иметь **PAG** (**Project Architecture Graph**) — структурированный граф «проект/папка/файл/внутренности файла», с **краткими аннотациями**, **типизированными связями**, **атрибутами** на узлах и **автоматическим** наполнением/обновлением. Отдельная пользовательская поверхность — **веб-GUI** `ailit memory`: выбор проекта, просмотр графа, переход по соседям и раскрытие атрибутов узла.

Канон процесса: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

---

## Положение в графе планов

- **Связь с M3/M4 / KB:** сегодня auto-KB пишет **лёгкие** факты (`repo_tree` = сырой `list_dir`, `repo_signals` = пути маркерных файлов) — см. `tools/agent_core/session/loop.py` (например, `repo_tree` ~L1632–1780, `repo_signals` ~L1783–1935). Это **не** граф и **не** смысловые описания «с чем связан узёл».
- **Workflow 7** добавляет **отдельный слой** — **project architecture graph** (PAG), не заменяя `kb_records` целиком: либо **расширение схемы** хранения, либо **соседняя** таблица/файл в `~/.ailit`, с явной **версией контракта** и миграциями.
- **Read/runtime primitives:** `read_symbol` / range-read уже реализованы в `tools/agent_core/tool_runtime/python_read_symbol.py`, `tools/agent_core/tool_runtime/builtins.py`, `tools/agent_core/tool_runtime/workdir_paths.py`; PAG **потребляет** эти примитивы как источник атрибутов для файлов `.py` и задел под другие языки, не дублируя парсер «втихаря».
- **Имена runtime-ролей:** в коде / UI / документации использовать **`AgentMemory`** и **`AgentWork`** как канонические названия двух постоянно взаимодействующих контекстов. Старые описательные имена вроде `ContextPAG` / `ContextWork` допустимы только как пояснение в design note, но **не** как публичное API.

---

## Порядок реализации стратегии

Эта стратегия исполняется **строго по этапам**; следующий этап стартует только после явного завершения предыдущего:

1. **G7.0** — зафиксировать design note и runtime-контракт, чтобы следующие агенты не спорили о терминах и границах.
2. **G7.1** — реализовать storage и API хранения PAG как отдельный устойчивый слой.
3. **G7.2** — реализовать индексацию, включая full-file ingest и обновление графа после изменений.
4. **G7.3** — построить GUI `ailit memory` с древовидно-графовой навигацией и JSON-export.
5. **G7.4** — встроить PAG в runtime-сессию `AgentMemory` / `AgentWork`, telemetry и fallback.

Если после завершения всех этапов понадобится развитие в сторону отдельного worker, GraphML, анимации мышления или внешних graph-tools, это оформляется **новым workflow**, а не неявным расширением текущего.

---

## Архитектурная модель PAG (A / B / C)

PAG строится как **иерархия графов** в рамках одного `namespace` проекта:

### Уровень A — Project graph

- Узел A описывает **проект/репозиторий**.
- Стабильный ключ:
  - если есть `git`: **`repo_uri + branch`**;
  - если `git` нет: **`repo_path`** (как сегодня `not_git` policy в KB).
- Атрибуты A-узла: `repo_uri`, `branch`, `commit`, `default_branch`, `repo_path`, `namespace`, `description`, `index_policy`, `last_indexed_at`, `staleness_state`.

### Уровень B — Structure graph

- Узлы B описывают **папки и файлы** проекта.
- Базовые связи:
  - **containment:** `A contains B`, `B(dir) contains B(file|dir)`;
  - **cross-links:** только `B ↔ B` (`imports`, `refers_to`, `generated_from`, `tests`, и т.п.).
- Атрибуты B-узла:
  - для **файла**: `language`, `summary`, `size_bytes`, `mtime`, `hash/light signature`, `symbol_count`, `external_dependency_count`;
  - для **папки**: `child_count`, `package_marker`, агрегаты по языкам/типам, но **без** притворства «функции папки».

### Уровень C — File internals graph

- Узлы C описывают **внутреннюю структуру файла**:
  - Python: `functions`, `classes`, `imports`;
  - C/C++: `includes`, декларации, макросы/типы по мере развития;
  - Markdown/описательные файлы: `headings`, блоки секций;
  - другие языки — через decision loop `AgentMemory`, а не через жёстко прошитый список всех парсеров в MVP.
- Базовые связи:
  - **containment:** `B(file) contains C`;
  - **cross-links:** только `C ↔ C` (`calls`, `imports_symbol`, `declares`, `includes`, `references_heading` и т.д.).

### Правило рёбер

Чтобы не путать **вложенность** и **семантические** ссылки, фиксируются два класса рёбер:

1. **Containment edges** — разрешены только `A -> B` и `B -> C`, плюс `B(dir) -> B(child)`.
2. **Cross-links** — только внутри своего уровня: `A ↔ A`, `B ↔ B`, `C ↔ C`.

Это позволяет сохранить требование пользователя «ссылки только между элементами одного уровня», не ломая иерархию `A contains B`, `B contains C`.

---

## Доноры (анализ; без копипаста кода)

Ориентиры — только идеи и пути к локальным клонам (подставьте свои, см. [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc)). Ниже приведены **конкретные локальные референсы**, чтобы следующие агенты могли брать паттерны без догадок:

| Репозиторий | Путь (пример) | Что взять для PAG + GUI |
|-------------|-----------------|-------------------------|
| **Graphiti** | `/home/artem/reps/graphiti` | Время-зависимые графы, **сущности ↔ релевантный текст**, hybrid retrieval — как **модель данных** «узел + доказательства + рёбра»; не копировать стек БД. См. `/home/artem/reps/graphiti/examples/quickstart/README.md:72-79`, `/home/artem/reps/graphiti/examples/quickstart/README.md:119-128`. |
| **obsidian-memory-mcp** | `/home/artem/reps/obsidian-memory-mcp` | **Навигация** и `[[links]]` — метафора **кликабельного графа** в UI: узел → соседи, боковая панель с метаданными; простой donor-format `entities[] + relations[]`. См. `/home/artem/reps/obsidian-memory-mcp/types.ts:1-16`, `/home/artem/reps/obsidian-memory-mcp/README.md:29-35`, `/home/artem/reps/obsidian-memory-mcp/README.md:97-109`. |
| **Hindsight** | `/home/artem/reps/hindsight` | API **вне** чата для осмотра/записи — паттерн для `ailit memory` как **отдельного** интерфейса, не обязательно внутри `ailit chat`. |
| **Letta** | `/home/artem/reps/letta` | **Memory blocks** / явные блоки state — **не** смешивать PAG с «системным промптом»; PAG = **карта кода**, не session-RAM. См. `README.md` (`memory_blocks`, stateful agents). |
| **claude-code** | `/home/artem/reps/claude-code` | Обход репо, file tools и давление больших entrypoint-файлов — **дисциплина** индексации и необходимость декомпозиции. См. `/home/artem/reps/claude-code/README.md:51-56`. |
| **OpenCode** | `/home/artem/reps/opencode` | Разделение агентных ролей и режимов — ориентир для явного runtime-контракта и отдельного read/plan слоя поверх одного продукта. См. `/home/artem/reps/opencode/README.md:100-113`. |

**Вывод для `ailit`:**

1. PAG = **локальный, объяснимый, версионируемый** граф (SQLite/JSONL рядом с существующим KB), с **визуализацией** в браузере.
2. Как у доноров, нам нужен **не просто storage**, а **контракт retrieval**: узел, соседи, короткое объяснение, затем drill-down.
3. В отличие от доноров, `ailit` должен фиксировать это как **протокол между двумя агентами** (`AgentMemory` / `AgentWork`), а не как набор неявных эвристик в одном prompt.
4. Базовый portable/exchange-format для MVP — **JSON-контракт PAG**, вдохновлённый donor-структурами `entities/relations` и `node/edge/attributes`; `GraphML` и внешние graph-tools — отдельная будущая фича.

---

## Что уже есть (якорь)

| Механизм | Где | Отношение к PAG |
|----------|-----|-----------------|
| `kb_records` + `kb_write_fact` / `kb_search` / `kb_fetch` | `agent_core.memory.sqlite_kb`, `kb_tools` | Текстовые факты, не топология. |
| auto-KB `repo_tree` / `repo_signals` | `SessionRunner` в `loop.py` | Сырьё структуры, **без** рёбер и без атрибутов «функции в файле». |
| `namespace_for_repo` / `detect_repo_context` | `agent_core` + session | **Ключ проекта** для PAG — тот же namespace, что и у KB. |
| `ailit chat` (Streamlit) | `tools/ailit/chat_app.py` | Паттерн **второго** Streamlit-приложения: `ailit memory` по аналогии с `_cmd_chat`. |
| CLI `ailit kb …` | `tools/ailit/kb_cli.py` | Место рядом для `ailit memory` **list projects / export / doctor**. |

---

## Runtime-модель: AgentMemory + AgentWork

### Общая идея

В runtime работают **два постоянно связанных агента**:

1. **`AgentWork`** — решает пользовательскую задачу, формирует ответ, вызывает file/shell/KB tools.
2. **`AgentMemory`** — управляет PAG: индексирует, выбирает слой, возвращает аннотации узлов, решает нужно ли углубиться до следующего уровня, и **всегда** сохраняет обновления в реальный граф.

Для MVP `AgentMemory` фиксируется как **in-process runtime-слой внутри текущего runtime**, а не как отдельный process/worker. Вынесение в subprocess допускается только как следующий workflow после стабилизации контракта.

Канонический источник истины — **внутренний runtime API** между `AgentMemory` и `AgentWork`. Tool-обёртки (`pag_*`) допустимы как адаптеры, debug-слой или внешний transport, но не как обязательная форма исполнения LLM.

### Обязанности `AgentWork`

- принимает пользовательский запрос;
- ставит `AgentMemory` как **task**, так и **explore**-запросы, например «какие точки входа в проект», «какие файлы релевантны этому изменению», «какие модули рядом с entrypoint»;
- формирует запросы к `AgentMemory` в терминах **потребности в контексте**:
  - «дай слой A»;
  - «мало контекста, раскрой узлы B»;
  - «нужны внутренности файла, раскрой уровень C для конкретных B-узлов»;
- принимает PAG-срез и решает:
  - уже отвечать;
  - запросить дополнительный slice;
  - перейти к `read_file` / `read_symbol` / `kb_fetch`.
- получает от `AgentMemory` **точный набор файлов** или узлов, по которым надо работать дальше;
- после изменения файлов передаёт обратно в `AgentMemory` **точные диапазоны строк изменений** (`changed_ranges`) и список затронутых путей для инкрементального обновления графа.

### Обязанности `AgentMemory`

- хранит PAG в актуальном состоянии;
- решает **чем индексировать и что игнорировать**;
- принимает goal + уже известные факты и определяет **следующий рекомендуемый шаг анализа** (`recommended_next_step`);
- по умолчанию возвращает **только аннотацию смежных узлов** запрошенного уровня;
- на уровне C может использовать **LLM-решение о языке/формате файла**, а не жёстко ограниченный список встроенных парсеров;
- для каждого индексируемого файла работает в модели **full-file ingest**: файл целиком загружается на уровне `AgentMemory`, после чего внутренне может дробиться на чанки/сегменты, но контрактно считается, что индексируется **весь файл**, включая очень большие текстовые файлы;
- по контракту извлекает и/или описывает:
  - внешние зависимости файла;
  - функции, классы, секции, импорты и другие C-элементы;
  - summary файла/узла в форме, пригодной для GUI и runtime-retrieval;
- принимает от `AgentWork` обновления по `changed_ranges` и выполняет точечный re-index затронутых узлов/рёбер;
- уважает policy:
  - `.gitignore`;
  - явные ignore-примеры в prompt (`.obj`, `.venv`, `__pycache__`, `node_modules`, бинарные артефакты и др.);
  - caps по памяти окна, количеству одновременных файлов, узлов и байтам ответа, но **не** как повод пропускать большой текстовый файл целиком.

### Передача данных между агентами

Контракт межагентного обмена должен быть **структурированным**, а не «натуральным языком в стену». Минимум:

- `request_id`
- `namespace`
- `goal`
- `query_kind` (`task|explore|sync`)
- `level` (`A|B|C`)
- `selected_node_ids`
- `known_facts`
- `limits`
- `changed_ranges`
- `response.kind`
- `response.nodes`
- `response.edges`
- `response.hints`
- `response.target_file_paths`
- `response.recommended_next_step`
- `response.staleness`

Обмен может быть реализован как:

1. **внутренний runtime API** (каноническая форма, обязательна для MVP);
2. **tool-протокол** (`pag_*` tools) с отдельным orchestration layer как опциональный adapter/debug-слой;
3. в перспективе — как отдельный subprocess/worker `AgentMemory`, если обновление PAG станет долгим.

---

## Целевое поведение (сводка)

1. **Узел графа** — путь **относительно work_root** (или `path` + `kind: project|dir|file|symbol`), стабильный `node_id` в namespace проекта.
2. **Краткое описание** — 1–3 предложения или title+summary, заполняемые через `AgentMemory`; для MVP допускается сочетание статики + LLM-описания, но для индексируемых файлов summary и внешние зависимости должны строиться **автоматически**, без ручного редактирования.
3. **Рёбра** разделяются на:
   - **containment**: `A contains B`, `B contains B`, `B contains C`;
   - **cross-links**: `imports`, `refers_to`, `calls`, `includes`, `tests`, и т.п.
4. **Атрибуты узла (JSON, версия схемы `ailit_pag_node_attrs_v1`):**
   - **A/project:** namespace, repo context, branch/commit/path, summary, index policy;
   - **B/file:** `symbols`, `size_bytes`, `external_dependency_count`, `summary`, freshness info;
   - **B/dir:** `child_count`, package markers, aggregates;
   - **C:** функции/классы/декларации/заголовки/инклуды — по типу файла.
5. **Автообновление / инкрементальность:**
   - если есть `git` — главным fingerprint служит **commit** (и при необходимости file hash/mtime ниже по слоям);
   - если `git` нет:
     - для A/B — **список файлов** с учётом границ индексации;
     - для C — `size_bytes` + извлечённые структурные метрики (`symbol_count`, `external_dependency_count`, и др.), полученные при раскрытии узла;
   - ручной/CI entrypoint: `ailit memory index --project-root PATH` (полный/инкремент).
6. **GUI:** команда `ailit memory` → Streamlit: выбор **проекта** (список namespace / недавние workdir из `~/.ailit/state` или scan KB meta), **граф**, **панель узла** — title, description, JSON атрибуты, исходящие/входящие рёбра.
7. **Конфиденциальность и policy:** уважать `.gitignore`, применять жёсткий prompt-policy индексации для `AgentMemory` (игноры: `.obj`, `.venv`, `__pycache__`, бинарные файлы, lock/cache каталоги, `node_modules`, build artifacts). Для очень больших **текстовых** файлов стратегия — whole-file ingest + внутреннее chunk/streaming-разбиение, а не полный skip.
8. **Поведение по умолчанию:** `AgentWork` сначала запрашивает у `AgentMemory` **первый слой** релевантных узлов/аннотаций A/B/C; затем решает, достаточно ли информации, или нужно раскрыть 1..N узлов глубже; только потом — file/KB tools.
9. **Guided exploration:** `AgentMemory` возвращает не только узлы, но и `recommended_next_step`/`target_file_paths`, чтобы `AgentWork` понимал, что смотреть дальше и какие файлы считать канонически релевантными.
10. **Post-edit sync:** после успешных изменений `AgentWork` обязан передать в `AgentMemory` затронутые файлы и диапазоны строк для инкрементального обновления PAG.

---

## Контракты данных (черновик для G7.1)

- **`ailit_pag_store_v1`:** путь `~/.ailit/state/pag/{namespace_slug}/` или таблица `pag_nodes` / `pag_edges` в **отдельном** sqlite от `kb.sqlite3` (рекомендация: **отдельный** файл `pag-{namespace}.sqlite` или единый `~/.ailit/pag/store.sqlite` с полем `namespace` — зафиксировать в G7.1).
- **Совместимость с KB:** опциональная **ссылка** `kb_record_id` на человеко-записанные факты, если дублирование текста нежелательно.
- **События JSONL (опционально):** `pag.index.started` / `pag.index.finished` / `pag.node.updated` / `agent_memory.requested` / `agent_memory.responded` — для `ailit session`-стиля диагностики.

### Обязательные поля `pag_nodes`

- `namespace`
- `node_id`
- `level` (`A|B|C`)
- `kind`
- `path`
- `title`
- `summary`
- `attrs_json`
- `fingerprint`
- `staleness_state`
- `source_contract`
- `updated_at`

### Обязательные поля `pag_edges`

- `namespace`
- `edge_id`
- `edge_class` (`containment|cross_link`)
- `edge_type`
- `from_node_id`
- `to_node_id`
- `confidence`
- `source_contract`
- `updated_at`

---

## Runtime API PAG / межагентный контракт

Минимальный протокол должен быть **контрактом между `AgentMemory` и `AgentWork`**, а не просто набором util-функций. Ниже описана **каноническая runtime-форма**; при необходимости она может зеркалироваться в tools, но не заменяется ими. Базовые операции:

### 1. `pag_projects_list`

Возвращает A-узлы (проекты), доступные в PAG.

Пример ответа:

```json
{
  "kind": "pag_projects_list_v1",
  "projects": [
    {
      "namespace": "github.com_org_repo_main",
      "node_id": "A:github.com/org/repo@main",
      "title": "repo main",
      "summary": "Python backend + CLI",
      "staleness_state": "fresh"
    }
  ]
}
```

### 2. `pag_layer_get`

Возвращает **первый слой** релевантных узлов указанного уровня (`A|B|C`) и их краткие аннотации.

Использование: `AgentWork` начинает почти всегда с этой операции, а не с `grep`.

### 3. `pag_nodes_expand`

Принимает 1..N `node_id` и раскрывает их содержимое. Для MVP **разрешены смешанные запросы**: в одном вызове можно просить раскрытие нескольких узлов и нескольких уровней (`B` + `C`), если это нужно для точной постановки `AgentWork`.

- для A — дочерние B-узлы;
- для B(file|dir) — дети/соседи B и при необходимости C;
- для C — детальные атрибуты и смежные C-узлы.

### 4. `pag_node_attrs`

Возвращает **полные атрибуты** одного узла для боковой панели GUI или для точечного решения `AgentWork`.

### 5. `pag_index`

Запускает полный/инкрементальный re-index.

### 6. `pag_sync_changes`

`AgentWork` передаёт затронутые пути и `changed_ranges`, а `AgentMemory` точечно пересчитывает summary, C-узлы и рёбра, не ожидая полного re-index всего проекта.

### 7. `pag_query_explain`

Отладочная операция: почему `AgentMemory` предложил именно эти узлы, а не другие.

### Пример runtime-цикла

Пользователь: «Где точка входа, какие модули рядом и какие файлы надо менять?»

1. `AgentWork` -> `AgentMemory`: `pag_projects_list`, затем `pag_layer_get(level=A, query_kind=explore)`.
2. `AgentMemory` возвращает 1..N A/B-узлов, summary проекта, `target_file_paths` и `recommended_next_step`.
3. `AgentWork` понимает, что нужен A->B->C drill-down: вызывает смешанный `pag_nodes_expand([...])` для набора B-узлов и выбранных C-раскрытий.
4. `AgentMemory` возвращает shortlist файлов, их внешние зависимости и внутренние сущности (`functions`, `classes`, `imports`, секции).
5. `AgentWork` работает только с этим точным набором файлов; при необходимости дополнительно читает исходники.
6. После изменения файлов `AgentWork` вызывает `pag_sync_changes(changed_ranges=...)`.
7. `AgentMemory` обновляет PAG и только затем следующий runtime-шаг использует свежий срез.
8. Только если PAG-среза мало или confidence низкий, `AgentWork` идёт в `read_file(offset, limit)` / `kb_fetch`.

### Сравнение с донорами

- **Graphiti:** похожа идея `search -> nodes/edges -> rerank`, но у нас retrieval должен быть явно оформлен как runtime-контракт между агентами, без внешней graph DB как обязательного требования.
- **obsidian-memory-mcp:** близок UX «узел -> связи -> детали», но у нас домен — **код**, а не markdown-vault.
- **Letta:** похоже разделение «stateful memory» и execution, но у нас `AgentMemory` не должен разрастаться в универсального AI-секретаря; его роль уже — PAG + retrieval policy.

---

## Этап G7.0 — Design note + риск-ревью (без кода)

### Design note (канон терминов и границ)

Цель G7.0 — зафиксировать **нормативные определения**, чтобы следующие агенты не спорили о терминах, уровне абстракции и о том, «кто за что отвечает» в runtime.

#### Глоссарий (нормативно)

- **PAG (Project Architecture Graph)**: *устойчивый* (persisted) граф архитектуры **одного** проекта/`namespace`, состоящий из узлов и рёбер, с версией схемы и staleness-политикой. PAG предназначен для guided exploration (shortlist файлов/узлов) и GUI.
- **Project / namespace**: *единица изоляции* данных PAG и KB. Все ключи (`node_id`, `edge_id`) интерпретируются **внутри** `namespace`.
- **Уровни A/B/C**:
  - **A**: проект (repo/workdir) как единый узел-контейнер.
  - **B**: структура проекта (директории/файлы).
  - **C**: внутренности файла (символы/секции/декларации/импорты и т.п.).
- **Containment edges**: иерархические связи «содержит» (`A->B`, `B(dir)->B(child)`, `B(file)->C`).
- **Cross-links**: семантические ссылки **внутри одного уровня** (`A↔A`, `B↔B`, `C↔C`), например `imports`, `refers_to`, `calls`, `tests`.
- **Node attributes (`attrs_json`)**: сериализованные атрибуты узла (версионируемая схема `ailit_pag_node_attrs_v1`), предназначены для runtime-retrieval и GUI (панель узла), а не для «внутреннего промпта» как единственного источника истины.
- **Staleness**: состояние актуальности узла/графа относительно источника (git commit / список файлов / fingerprint). Staleness — **часть контракта**, а не эвристика «на глаз».
- **Whole-file ingest (текстовые файлы)**: контрактное правило: для индексируемого **текстового** файла `AgentMemory` индексирует **весь файл**, даже если он большой; оптимизация допускается через внутреннее chunk/streaming-разбиение, но не через silent-skip файла.

#### Границы ответственности (нормативно)

- **`AgentWork`**:
  - отвечает за *решение пользовательской задачи* и итоговый ответ;
  - использует PAG как **первый** источник guided exploration (когда доступен и свежий);
  - после изменений передаёт `changed_ranges`/пути для инкрементального обновления.
- **`AgentMemory`**:
  - отвечает за *актуальность* PAG, индексацию и retrieval policy;
  - выдаёт `nodes/edges/attrs` + `recommended_next_step` + **точный** `target_file_paths`;
  - определяет staleness, confidence и причины fallback.
- **KB**:
  - текстовые факты/заметки/сигналы; **не** заменяет PAG и **не** обязан содержать топологию.
- **`repo_tree` / `repo_signals` (auto-KB)**:
  - сырьё структуры и маркеры; **не** является PAG и не должен трактоваться как «граф».

#### Инварианты (чтобы не спорить дальше)

1. **Не смешивать уровни рёбер:** containment и cross-links остаются раздельными классами рёбер.
2. **Cross-links только внутри уровня:** нельзя делать `B(file) -> C(symbol)` как cross-link; это всегда containment `B contains C`.
3. **PAG — persisted слой:** PAG хранится отдельно и версионируется; runtime не полагается на «память чата» как на единственный storage.
4. **Shortlist важнее полного дампа:** ответы `AgentMemory` ограничены лимитами; вместо «всё сразу» возвращается top‑K + `recommended_next_step`.
5. **Большие текстовые файлы не пропускаются молча:** допускается деградация качества извлечения, но не silent-skip.

#### Не-цели G7 (явно)

- не строим «полный LSP/IDE» и не гарантируем 100% точность resolution для импортов/вызовов в MVP;
- не вводим обязательную внешнюю graph DB «веб‑масштаба»;
- не делаем ручное редактирование узлов/summary в текущем workflow;
- не выносим `AgentMemory` в отдельный процесс в MVP (это возможный следующий workflow).

### Runtime-контракт `AgentMemory` ↔ `AgentWork` (v1, нормативный)

Ниже — минимальный контракт обмена, который считается **каноническим** независимо от транспорта (in-process API / tools-adapter / будущий worker).

#### Общие требования к запросам/ответам

- **Структурированный обмен** (JSON-структуры), без «стены текста» как единственного протокола.
- **Явная версия контракта**: `contract_version = "ailit_pag_runtime_v1"`.
- **Идемпотентность** для операций чтения: одинаковый запрос при одинаковом состоянии PAG даёт эквивалентный ответ (с учётом `staleness`).
- **Лимиты**: каждый запрос содержит `limits` (top‑K узлов, max bytes, max nodes/edges, timeout_ms).
- **Ошибки и деградация**: ответ всегда содержит `staleness` и (если применимо) `fallback_reason`.

#### Минимальная форма запроса

```json
{
  "contract_version": "ailit_pag_runtime_v1",
  "request_id": "uuid",
  "namespace": "…",
  "goal": "…",
  "query_kind": "task|explore|sync",
  "level": "A|B|C",
  "selected_node_ids": [],
  "known_facts": [],
  "limits": {
    "top_k_nodes": 30,
    "top_k_edges": 80,
    "max_bytes": 120000,
    "timeout_ms": 15000
  },
  "changed_ranges": []
}
```

#### Минимальная форма ответа

```json
{
  "contract_version": "ailit_pag_runtime_v1",
  "request_id": "uuid",
  "kind": "layer_get|nodes_expand|node_attrs|projects_list|index|sync_changes|query_explain",
  "nodes": [],
  "edges": [],
  "hints": [],
  "target_file_paths": [],
  "recommended_next_step": "…",
  "staleness": {
    "state": "fresh|stale|missing|low_confidence",
    "reason": "…",
    "confidence": 0.0
  },
  "fallback_reason": null
}
```

#### `changed_ranges` (нормативно)

- Используется `AgentWork` → `AgentMemory` в `sync`‑запросах после правок.
- Формат (минимум): `{ "path": "rel/path", "start_line": 10, "end_line": 42 }`.
- Семантика: диапазоны **1‑based**, `end_line` включительно; файл интерпретируется как текст (для бинарных — только `path` без ranges, с причиной).

### Задача G7.0.1 — Зафиксировать ERD и формат рёбер

**Содержание:** 1–2 страницы: ERD, уровни `A/B/C`, список типов containment/cross-link рёбер, правила `node_id` при `not_git`, whole-file ingest для больших файлов, канонические имена `AgentMemory` / `AgentWork`, JSON-first exchange-format по мотивам доноров `/home/artem/reps/graphiti/examples/quickstart/README.md:72-79`, `/home/artem/reps/graphiti/examples/quickstart/README.md:119-128`, `/home/artem/reps/obsidian-memory-mcp/types.ts:1-16`.

**Критерии приёмки:** ревью в PR; ссылка на этот § и доноров-таблицу; явное **не**-цели (no full LSP, no web-scale graph DB).

**Проверки:** ревью; без кода.

### Задача G7.0.2 — Зафиксировать межагентный контракт

**Содержание:** отдельный design note по взаимодействию `AgentMemory` / `AgentWork`: in-process runtime API, очередность запросов, mixed `B+C`-expand, точный список файлов в ответе, `recommended_next_step`, `changed_ranges`, кто владеет staleness policy и как логируются обмены в JSONL.

**Критерии приёмки:** документ описывает happy-path `explore -> shortlist files -> edit -> sync`, timeout/cancel, fallback к file tools и кто инициирует `pag_index`.

**Проверки:** ревью; без кода.

---

## Этап G7.1 — Хранение PAG (SQLite + миграции)

### Задача G7.1.1 — Схема `pag_nodes` / `pag_edges` + миграции

**Содержание:** модуль в `tools/agent_core/` (или `tools/ailit/pag/`) с `CREATE TABLE`, первичные ключи `(namespace, node_id)` или `node_uid`, индексы по `path`, `kind`, `level`, `edge_class`, `staleness_state`.

**Критерии приёмки:** unit-тест на вставку/чтение; `flake8`, `pytest` (по согласованной политике — тест обязателен для схемы).

### Задача G7.1.2 — API: upsert node/edge, list by namespace, delete stale

**Содержание:** чистый слой без Streamlit: функции для индексатора, `AgentMemory` и GUI. API должен поддерживать `projects_list`, `layer_get`, `nodes_expand`, `node_attrs`, `mark_stale`, `delete_stale`.

**Критерии приёмки:** idempotent re-index; удаление устаревших узлов при `--full`.

---

## Этап G7.2 — Индексация (MVP: дерево + policy + C-level через AgentMemory)

### Задача G7.2.1 — Сканер дерева + `.gitignore`

**Содержание:** обход в глубину, фильтр по `.gitignore` и явной policy ignore-list (`.obj`, `.venv`, `__pycache__`, бинарники, cache/build directories, `node_modules`). Узлы `dir`/`file` с `dir_contains`. Для очень больших **текстовых** файлов сканер не делает skip по одному факту размера, а передаёт файл в `AgentMemory` на whole-file ingest с внутренним chunk/streaming-анализом.

**Критерии приёмки:** на fixture-репо — ожидаемое количество узлов; крупные каталоги режутся cap-ами с логом; большой текстовый файл попадает в PAG и получает summary/attrs вместо полного пропуска.

### Задача G7.2.2 — C-level extraction через `AgentMemory`

**Содержание:** `AgentMemory` должен решать, **как** извлекать C-уровень в зависимости от типа файла:

- Python: `functions` / `classes` / imports, предпочтительно через совместимость с read-6 `read_symbol`;
- C/C++: `includes`, декларации, типы;
- Markdown / docs: headings и ключевые секции;
- другие типы — best-effort через policy prompt и file tools.

MVP допускает качественный Python-first путь, но контракт должен быть **мультиязычным**, чтобы расширение происходило без пересборки общей модели данных. Для индексируемого файла `AgentMemory` читает **весь файл целиком**, а затем строит summary, список внешних зависимостей и набор C-сущностей, пригодный для GUI и guided exploration.

**Критерии приёмки:** атрибуты файла содержат C-level сущности и внешние зависимости; папка — **не** содержит псевдо-«функции»; policy prompt для `AgentMemory` описывает игноры, whole-file ingest и лимиты окна/ответа.

### Задача G7.2.3 — Import-рёбра (Python, MVP)

**Содержание:** разрешение `from X import Y` / `import X` в пределах work_root — **лучшее** разрешение (best-effort), циклы допустимы, нерешённые — edge `refers_to` в `?` или пропуск с телеметрией.

**Критерии приёмки:** на мини-проекте 2–3 пакета — рёбра визуально осмыслены.

### Задача G7.2.4 — CLI `ailit memory index`

**Содержание:** `ailit memory index --project-root PATH [--full] [--json]`; использует `AILIT_KB`/`namespace` в духе merge (согласовать с `load_merged_ailit_config`) и пишет состояние стейлнесса/реорганизации графа.

**Критерии приёмки:** exit code 0, запись PAG, краткий stdout.

### Задача G7.2.5 — Инкрементальность и реорганизация графа

**Содержание:** зафиксировать, как определяется устаревание:

- `git`-проекты: commit/fingerprint как верхнеуровневый индикатор;
- `not_git`:
  - A/B: снимок списка файлов в границах индексации;
  - C: `size_bytes` + структурные признаки, полученные при раскрытии/анализе.

При изменении структуры папок должен пересобираться containment-граф и помечаться stale/removed history. После edit-flow `AgentWork` обязан передавать в `AgentMemory` затронутые пути и `changed_ranges`, чтобы индексация изменений работала без полного re-index.

**Критерии приёмки:** переименование/удаление папки не оставляет сиротских рёбер в активном срезе GUI.

---

## Этап G7.3 — GUI (Streamlit)

### Задача G7.3.1 — `ailit memory` (subprocess `streamlit run` как `ailit chat`)

**Содержание:** `tools/ailit/cli.py` + `tools/ailit/memory_app.py`: страница выбора **проекта** (dropdown из namespace с данными PAG + «проиндексировать новый путь»).

**Критерии приёмки:** запуск в dev; README § «установка» — extra `[memory]` по аналогии с `[chat]` при необходимости.

### Задача G7.3.2 — Визуализация графа

**Содержание:** выбрать библиотеку (см. **Риски**); взаимодействие: клик по узлу → **панель** атрибутов, список соседей, явное отображение уровня (`A/B/C`), древовидно-графовая структура с хорошим UX по мотивам Obsidian, кнопка «показать path в OS» (optional). Архитектурно предусмотреть, что эта подсистема позже сможет показывать realtime-анимацию мыслительного процесса `ailit` и переиспользоваться как подсистема анализа больших данных, но брендинг и анимации **не входят** в MVP.

**Критерии приёмки:** ручной сценарий: индекс → открыть GUI → увидеть >5 узлов и рёбра; можно раскрывать/сворачивать структуру без падения на пустом проекте.

### Задача G7.3.3 — Экспорт

**Содержание:** кнопка `Export JSON` для обмена; JSON должен совпадать с контрактом G7.1/G7.4 и быть пригодным как внутренний donor-style exchange-format. `GraphML` и внешние graph-tools — отдельный будущий workflow.

**Критерии приёмки:** один скачиваемый JSON-артефакт, совместимый с контрактом G7.1.

---

## Этап G7.4 — Интеграция с сессией и runtime-агентами

### Задача G7.4.1 — `AgentMemory` / `AgentWork`: первый слой PAG по умолчанию

**Содержание:** при `memory.enabled` `AgentWork` по умолчанию начинает не с `grep`, а с запроса к `AgentMemory` на первый PAG-slice (узлы уровня A/B/C по интенту). Это правило действует и для обычных task-вопросов, и для explore-вопросов вида «какие точки входа в проект». `AgentWork` затем решает: достаточно ли аннотаций, или нужен drill-down на 1..N узлов.

**Критерии приёмки:** e2e smoke или JSONL-наблюдение: в сценариях «как устроен проект / где точка входа / какие модули связаны» первый шаг — PAG, а не raw `grep`, если индекс свежий.

### Задача G7.4.2 — Shortlist файлов и post-edit sync

**Содержание:** `AgentMemory` возвращает `AgentWork` точный список релевантных файлов/узлов и `recommended_next_step`; после изменений `AgentWork` обязан отправить в `AgentMemory` `changed_ranges`, чтобы тот обновил граф без полного прохода.

**Критерии приёмки:** после runtime-изменения видны обновлённые summary/edges затронутых файлов; цепочка `shortlist -> edit -> sync` восстанавливается по логам.

### Задача G7.4.3 — Fallback и договор о деградации

**Содержание:** если PAG stale/missing/low-confidence, `AgentWork` должен уметь корректно откатиться к KB + file tools. Это не считается ошибкой; ошибка — если fallback неявен и пользователь не понимает, почему граф не использован.

**Критерии приёмки:** в логах видно, почему PAG был/не был использован (`agent_memory.responded`, `staleness_state`, `fallback_reason`).

### Задача G7.4.4 — JSONL и telemetry runtime-протокола

**Содержание:** отдельные события для межагентного протокола: `agent_memory.requested`, `agent_memory.responded`, `agent_work.pag_slice_used`, `agent_work.pag_slice_rejected`, `agent_work.files_shortlisted`, `agent_memory.synced_changes`.

**Критерии приёмки:** по одному логу можно восстановить цепочку «вопрос пользователя -> какие узлы предложил `AgentMemory` -> какие файлы были shortlisted -> что выбрал `AgentWork` -> какие строки изменились -> почему пошёл в `read_file`/`kb_fetch`».

---

## Риски и границы

| Риск | Митигация |
|------|-----------|
| OOM / время на крупных mono-repo | whole-file ingest делать через chunk/streaming, ограничивать окна анализа и параллелизм, а не пропускать большие текстовые файлы целиком. |
| Дублирование `repo_tree` | в UI явно: «сырой list» (KB) vs «PAG-граф»; не писать дубль в `kb` без нужды. |
| Зависимости граф-UI | зафиксировать в `pyproject` extra `[memory]`; lock версий. |
| not_git / path-namespace | `node_id` = нормализованный relpath; в доке — примеры как read-6 R4.2. |
| LLM-аннотации уровня B/C дают шум | policy prompt, confidence, TTL/review, fallback к raw file tools. |
| Первый слой PAG сам становится слишком большим | top-K, max bytes ответа, explicit pagination в `AgentMemory`, плюс `recommended_next_step` вместо «вывалить всё сразу». |

---

## Проверки (общие)

- `flake8` + `pytest` на затронутых пакетах после каждой крупной задачи.
- Ручной: `ailit memory index` → `ailit memory` → визуальный чек-лист из G7.3.2.

---

## Статус

**Workflow согласован на уровне стратегии:** решения по runtime-контракту, mixed-requests, full-file ingest, GUI и JSON-export зафиксированы. Реализация начинается **только** после явного go по этапам (G7.0 → G7.1 → …) и отдельных коммитов с префиксом `arch-graph-7/...` / `G7.n`.

---

## Зафиксированные решения после согласования

1. `AgentMemory` в первой итерации — **in-process runtime-слой** внутри текущего runtime; выделение в отдельный worker отложено.
2. Канонические runtime-роли документа и кода: **`AgentMemory`** и **`AgentWork`**.
3. В MVP поддерживаются только **автоматически** сгенерированные summary/атрибуты узлов; ручное редактирование не входит в текущий workflow.
4. GUI ориентируется на **древовидно-графовый UX**, близкий по ощущению к Obsidian; realtime-анимация мышления и брендинг — будущий этап.
5. Для очень больших текстовых файлов используется **full-file ingest** на стороне `AgentMemory` с внутренним chunk/streaming-анализом; цель — получить описание внешних зависимостей и внутренних сущностей по единому контракту, а не пропустить файл.
6. `AgentWork` может задавать `AgentMemory` как task-, так и explore-вопросы; `AgentMemory` должен направлять исследование, возвращать точный shortlist файлов и рекомендованный следующий шаг.
7. Mixed-requests (`B` + `C` в одном запросе) разрешены уже в MVP.
8. После изменений `AgentWork` обязан передавать `AgentMemory` точные диапазоны строк и затронутые пути для инкрементального обновления PAG.
