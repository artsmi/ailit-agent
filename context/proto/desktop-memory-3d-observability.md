# Desktop Memory 3D — компактная наблюдаемость (trace / journal)

## Назначение

Канонические **имена событий** и **schema-like** правила для §3.2 ТЗ (`context/artifacts/technical_specification.md` §3.2), UC-03 (AC trace), UC-06 (фаза UI), UC-02 (highlight), согласованные с `context/artifacts/architecture.md` §4–5.7, §9 и с задачей **`task_1_1`** (ссылки на этот файл из `context/arch/desktop-pag-graph-snapshot.md` / merge волны 1).

**Граница:** описание контрактов для будущих точек emit в **renderer**; в рамках волны 1 **нет** обязательства на реализацию emit в коде.

---

## D-PROD-1: единственный продюсер `pag_graph_rev_reconciled`

- **Ровно один** продюсер события `pag_graph_rev_reconciled`: **desktop React renderer** (после атомарного применения slice + trace delta для namespace в смысле порядка X→Y, см. `architecture.md` §5.2).
- **Python / `AgentMemory` / broker / main IPC-адаптер** это событие **не** продюсируют (запрет dual-write и дубликатов в журнале).
- **Частота и идемпотентность:** по `architecture.md` §9 — повторный slice с тем же `graph_rev_after` не должен плодить reconcile-события: перед emit сравнение последнего зафиксированного rev и/или debounce на тик merge; событие допускается после согласованного merge-тика.

---

## Общие запреты (все compact-события ниже + контекст W14)

В payload **запрещено**: сырой пользовательский промпт, chain-of-thought, секреты API/токены, полный дамп графа (полная адъacency / сериализация всего merged для отладки).

---

## 1. `pag_graph_rev_reconciled`

| Поле | Правило |
|------|---------|
| `session_id` | **required** string |
| `namespace` | **required** string |
| `graph_rev_before` | **nullable** int — `null` при первичной инициализации, иначе предыдущий согласованный rev для namespace |
| `graph_rev_after` | **required** int |
| `reason_code` | **required** короткий enum/string; whitelist кодов (расширение только additive): `post_slice`, `post_trace`, `post_refresh`, `user_refresh`, `debounce_merge`, `poll_retry` (последние два — при выравнивании с Refresh/поллером по канону arch) |

**Forbidden:** как в «Общие запреты»; полные списки id всех нод графа (разрешены только компактные счётчики/длины, если появятся в отдельном решении — не в этом событии без смены ТЗ).

**Producer:** renderer (D-PROD-1).  
**Consumers:** desktop trace viewer, парсеры store (волна 2+).

---

## 2. `pag_snapshot_refreshed`

| Поле | Правило |
|------|---------|
| `session_id` | **required** string |
| `namespace` | **required** string, если refresh атомарен для одного namespace; **иначе** вместо `namespace` — **required** компактное поле **`namespaces`** (массив строк). В одной строке события: либо задан `namespace`, либо непустой `namespaces`, либо (при согласовании в коде) оба — по правилу emit-реализации, но **запрещено** отсутствие и того и другого. |
| `graph_rev_after` | **required** int (минимальный контракт ТЗ §3.2); multi-rev при multi-namespace — только **additive** расширением (например `graph_rev_by_namespace`), без ломки существующих обязательных полей |
| `reason_code` | **required** `user_refresh` \| `poll_retry` \| другие короткие коды по `architecture.md` §4 |

**Forbidden:** как в «Общие запреты».

**Producer:** renderer после **успешного** завершения Refresh (full load) в смысле канона `context/arch/desktop-pag-graph-snapshot.md`.

---

## 3. `memory_recall_ui_phase`

Имя **финализировано** (совпадает с черновиком ТЗ §3.2 и `architecture.md` §5.7; расхождение с веткой merge — править оба: этот файл и arch-ссылки в одной ветке).

| Поле | Правило |
|------|---------|
| `session_id` | **required** string |
| `phase_code` | **required** короткий string (например `recall_active`, `idle`) |
| `rotation_index` | **optional** int — индекс во whitelist; см. правило взаимоисключения ниже |
| `phrase_id` | **optional** string — только id фразы из фиксированного whitelist; см. правило взаимоисключения ниже |
| `namespace` | **optional** string — только если нужен disambiguation для multi-view; **default:** отсутствует |

**Правило `rotation_index` / `phrase_id`:** в каждой записи должно присутствовать **ровно одно** из двух полей (второе — отсутствует или **forbidden** передавать оба без явного приоритета в коде). Значения — не произвольный пользовательский текст.

**Forbidden:** текст пользовательского запроса, сырой промпт, CoT, секреты.

**Producer по умолчанию:** **renderer** (проекция broker/trace в UI-модель). Broker/Python **по умолчанию не** пишут это событие (см. одну строку в `broker-memory-work-inject.md`).

---

## D-OBS-HI-1: доказательство «применён highlight» без четвёртого compact-события

Отдельное **четвёртое** compact-событие вида «highlight_applied» **не вводится**, пока для AC достаточно существующего канала.

**Доказательство применения highlight** = запись события **`memory.w14.graph_highlight`** с payload схемы **`ailit_memory_w14_graph_highlight_v1`** (канон полей — текущий Python emit, без расширения v1 в этой итерации).

### Whitelist полей `ailit_memory_w14_graph_highlight_v1` (разрешённые ключи верхнего уровня payload)

| Поле | Правило |
|------|---------|
| `schema` | **required** literal `ailit_memory_w14_graph_highlight_v1` |
| `namespace` | **required** string (bounded) |
| `query_id` | **required** string (bounded) |
| `w14_command` | **required** string (bounded) |
| `w14_command_id` | **required** string (bounded) |
| `node_ids` | **required** array of strings (подмножество пути M1, не полный граф) |
| `edge_ids` | **required** array of strings |
| `reason` | **required** string (bounded) |
| `ttl_ms` | **required** int (в текущем emit задаётся явно; допускается фиксированный default 3000 в продюсере) |

### Forbidden для этого события (сверх общих запретов)

- Вложенный сырой пользовательский запрос, полный transcript чата, CoT.
- Секреты API.
- Полный дамп графа (export всех узлов/рёбер PAG); **`node_ids` / `edge_ids`** только как **компактный** путь подсветки по правилам M1 (`context/arch/w14-graph-highlight-m1.md`).

**Producer:** без изменений v1 — **`AgentMemoryWorker`** / `emit_w14_graph_highlight` после PAG-записей запроса (порядок относительно `pag.*` — канон w14 M1).

---

## Снятие highlight и D-HI-1 (без отдельного «clear»-события в этой итерации)

Политика «не обнулять highlight до явного снятия» и порядок по trace — **`context/arch/desktop-pag-graph-snapshot.md`** (раздел **D-HI-1**). Отдельного compact-события `graph_highlight_cleared` здесь **нет**; смена/сброс выводится из порядка trace и правил маппера `pagHighlightFromTrace` / последней применимой строки.

---

## Перекрёстные ссылки

- `context/artifacts/architecture.md` — §4 (модель событий), §5.2 (X→Y), §5.7 (§3.2 ТЗ), §9 (idempotency).
- `context/proto/pag-slice-desktop-renderer.md` — additive IPC для `graph_rev` на корне ответа slice (опционально).
- `context/proto/ailit-memory-w14-graph-highlight.md` — транспорт и владелец W14 v1.
- `context/arch/desktop-pag-graph-snapshot.md` — снимок, Refresh, D-HI-1.
