# Desktop: паттерн 3dmvc и инварианты графа (Graph + 3dmvc)

> **Аннотация:** кто владеет merged/trace, как данные доходят до `ForceGraph3D`, какие инварианты **View** обязательны (без мигания, без orphan-узлов в scene graph по умолчанию), политика подсветки 2D/3D и типичные ошибки реализации.

## Статус

`approved` — вместе с пакетом **2026-05-12**.

## Связь с исходной постановкой

Релевантны **OR-002**, **OR-003**, **OR-004**, **OR-012** из [`INDEX.md`](INDEX.md): поток 3dmvc, отсутствие изолированных узлов в scene graph при default, стабильность View, согласованность подсветки с архитектурным снимком PAG.

## Архитектура 3dmvc

Оператору и агентам `start-feature` нужна одна линия ответственности: всё, что приходит из памяти (trace, PAG slice по IPC, merge), **сначала** нормализуется в слое **Model/Controller** в renderer-процессе; **View** (страницы вроде `MemoryGraph3DPage` и проекторы к `ForceGraph3D`) получает только подготовленный **scene graph DTO** (узлы, рёбра, атрибуты для layout и отдельные каналы подсветки по правилам ниже).

### Роли слоёв

| Слой | Назначение | Якорные зоны в коде (ориентиры для плана) |
|------|------------|-------------------------------------------|
| **Model** | Устойчивое состояние сессии: merged PAG + память, снимки для UI (`PagGraphSessionSnapshot.merged`), фазы загрузки. | `pagGraphSessionStore`, `loadPagGraphMerged`, `PagGraphSessionFullLoad`, `mergeMemoryGraph`. |
| **Controller** | IPC/trace, политики slice, highlight из trace vs snapshot, решения «что передать в проекцию», throttle бюджетов refresh. | `memoryGraphState`, `applyHighlightFromTraceRows`, `ensureHighlightNodes`, `pagHighlightFromTrace`, gating W14. |
| **View** | Рендер и ввод: **scene graph** + явные side-channel данные; View **не** пересобирает merged из сырого trace для 3D. | `MemoryGraph3DPage`, `MemoryGraphForceGraphProjector`, ref на `ForceGraph3D`, throttled `fg.refresh()`. |

**D-MVC-1:** вход trace и PAG по IPC обрабатывается в renderer store / контексте сессии — это **Model/Controller** относительно страницы 3D как **View**.

### Технический контракт: граница M/C → View

**Required:**

- View-компонент графа принимает **scene graph**: узлы и рёбра для layout плюс **отдельно** сигнал подсветки, если она не сводится к полям узла в списке сцены.
- Любое изменение merged/slice/highlight для Memory graph (2D/3D) проходит через M/C (store → при необходимости проекция → props графа).

**Forbidden (целевой 3D и 2D Memory graph):**

- View читает «истину» подсветки из полного потока trace / `rawTraceRows`, минуя единый контроллер highlight и снимок `searchHighlightsByNamespace`.

**Default:**

- main отдаёт slice и durable trace; **сборка merged** остаётся в renderer, если отдельное решение не сдвигает границу (**OR-006**).

---

## Инварианты View

### Политика без мигания и батчинг (**OR-004**)

**Required:**

- Полный remount `ForceGraph3D` **не** является ответом на каждое монотонное изменение rev: политика ключа согласована с **`computeMemoryGraphDataKey`** — **без** сериализации `graphRevByNamespace` в ключ (**D-KEY-1**, **OR-011**, тест **`TC-3D-UC04-03`**).
- Обновления подсветки — через **ref** и **throttled** `fg.refresh()` с верхней границей частоты (числа — в коде `pagGraphLimits` и плане внедрения).

**Forbidden:**

- Подмена **OR-004** полным пересозданием графа там, где достаточно инкрементального обновления DTO при неизменном ключе монтирования.

### OR-003 и узлы степени 0

**OR-003:** в отображаемом наборе scene graph View **не** показывает узлы без инцидентных рёбер (степень 0 в переданном edge-list), если не активирован явный waiver **D-ORPHAN-C** (см. [`glossary.md`](glossary.md)).

**Поведение репозитория (после слайса G1, default D-ORPHAN-B):** `MemoryGraphForceGraphProjector.project` строит **N_scene** / **E_scene** для `ForceGraph3D` в фиксированном порядке: нормализация концов рёбер → UC-04A (`filterEdgesUc04BranchA`) → **`filterDegreeZeroNodesDOrphanB`** (степень по уже отфильтрованным рёбрам; узлы степени 0 и висячие концы исключаются из списка узлов и рёбер сцены). **Model/Controller** по-прежнему может наполнять `PagGraphSessionSnapshot.merged` **суперсетом** (в т.ч. highlight-only узлы для 2D и trace-merge); отличие **N_scene** от этого суперсета задаётся только выходом `project`, а не копированием `merged.nodes` в View. Подсветка для 3D читается из **`searchHighlightsByNamespace`** снимка (side-channel), а не из полного trace на странице: узел может быть «hot» в канале подсветки и при этом **отсутствовать** в **N_scene**, если для него нет рёбер после UC-04A — без автодобавления фантомных узлов в node-list сцены. Перед props `ForceGraph3D` обязателен вызов `project` (или эквивалент с тем же порядком шагов).

**D-ORPHAN-A (non-default):** см. [`glossary.md`](glossary.md); активация только если в плане внедрения или approval записан явный выбор **A** и отказ от обязательности **B** для релиза, с приёмкой predicate **OR-003**.

**D-ORPHAN-C:** placeholder-узел без рёбер в node-list — **только** с named waiver в human approval; **запрещён** как «тихий» default.

### Технический контракт: predicate OR-003

**Required (target):** ∀`v` ∈ `N_scene` ∃ ребро в `E` с концом `v` (степень в индуцированном подграфе ≥ 1), если **D-ORPHAN-C** не активирован документированно.

**Default:** **D-ORPHAN-B** (в коде — `filterDegreeZeroNodesDOrphanB` внутри `MemoryGraphForceGraphProjector.project`); **D-ORPHAN-A** не эквивалентен default до явного слайса.

**Forbidden:** документировать **D-ORPHAN-C** как неявный компромисс без строки waiver.

---

## Highlight policy (**OR-012**, **D-HI-OWN-1**)

**3D (G1):** источник истины подсветки на странице — **`snap.searchHighlightsByNamespace`** (снимок сессии), а не параллельный разбор полного trace / `rawTraceRows` в React для решения «кого подсветить».

**2D (G3):** то же правило для live glow: `MemoryGraphPage` читает **`snap.searchHighlightsByNamespace[ns0]`**, а не полный trace на View как SoT.

**OR-012:** один highlight controller в M/C для 2D и 3D: обе панели берут подсветку из **`searchHighlightsByNamespace`** снимка на View; семантика trace→DTO остаётся в store / `pagHighlightFromTrace` / merge, без второй ветки парсинга trace только для 2D.

**Связь с arch:** [`../../arch/desktop-pag-graph-snapshot.md`](../../arch/desktop-pag-graph-snapshot.md) описывает снимок и merge; правило side-channel для подсветки совпадает для 2D и 3D.

| Потребитель | Required source | Forbidden drift |
|-------------|-----------------|-----------------|
| 3D View | `searchHighlightsByNamespace` + согласованный M/C (`pagHighlightFromTrace` / W14 gating пишут в снимок) | Прямой разбор полного trace в странице для highlight |
| 2D View | `searchHighlightsByNamespace` (по активному namespace) + тот же M/C | Прямой разбор полного trace в странице для highlight |

---

## Performance (**D-PERF-1**)

Три проверяемых класса причин симптома «виснет»:

1. **Линейный trace replay** после full load — кандидат на CPU spikes; benchmark в репо может отсутствовать — измерения как backlog.
2. **Частые `fg.refresh()`** — нагрузка WebGL; обязателен throttle и верхняя частота.
3. **Main IPC и логирование** — `pagGraphSlice`, append pair log и т.д.; не «лечится» перерисовкой View.

| Класс | Минимальная проверка (канон) |
|-------|------------------------------|
| Trace replay | Счётчик строк / длительность стадии (когда появится instrument) |
| `fg.refresh` | Частота относительно порогов в конфиге |
| IPC / slice | Время round-trip `pag-slice`, размер payload (без логирования полного JSON в канон-лог) |

---

## Anti-patterns (Do Not Implement This As)

1. View читает trace напрямую для подсветки (2D/3D) или merged, минуя store/controller (**D-MVC-1**, **D-HI-OWN-1**).
2. Remount `ForceGraph3D` на каждый monotonic **`graphRev`** или включение rev в React-key (**D-KEY-1**, **OR-011**).
3. Полный graph reload как единственный путь для мелких дельт при стабильном ключе монтирования.
4. **D-ORPHAN-C** как default при **OR-003** без named waiver.
5. Скрытый placeholder в node-list без контракта визуального канала при **D-ORPHAN-B**.
6. Неограниченный trace replay и неограниченная частота `fg.refresh` без throttle/budget.
