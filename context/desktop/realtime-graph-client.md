# Desktop: realtime-клиент графа (trace, slice, IPC, приёмка)

> **Аннотация:** нормативный поток от конфигурации сессии до стабильной 3D-сцены, фазы **state lifecycle**, компактная **observability**, примеры happy/partial/blocked, команды проверки и критерии приёмки **OR-001…OR-012**. Детальная матрица IPC и расширение шагов абстрактного алгоритма — по мере необходимости в плане внедрения и коде `desktop/src/`.

## Статус

`approved` — вместе с пакетом **2026-05-12**.

## Связь с исходной постановкой

Закрывает **OR-001**, **OR-007**, **OR-009**, **OR-010**, **OR-011**, **OR-008** (killer feature как паттерны), **OR-005**, **OR-006** (граница без Python-рефактора), плюс примеры и команды для **OR-004** / **OR-003** совместно с [`graph-3dmvc.md`](graph-3dmvc.md).

## Target flow (happy path, сжато)

1. **Сессия и конфиг:** main готовит пути; при необходимости создаётся `config.yaml` под каталогом Desktop пользователя.
2. **Запрос slice PAG:** renderer инициирует загрузку; main выполняет IPC slice.
3. **Ответ slice → Model:** renderer принимает JSON среза; merged **не** считается «готовым на main» одним blob.
4. **Full load / merge:** модули full load / merge обновляют `PagGraphSessionSnapshot.merged` и фазы в store.
5. **Trace replay (если журнал не пуст):** проход durable trace; целевое поведение — **bounded** по времени/строкам с observability, без dump сырого журнала в UI.
6. **Инкремент дельт:** типы вроде `pag.node.upsert` / `pag.edge.upsert`; monotonic `graphRev` обновляет состояние, но **не** обязан менять React-mount key графа (**OR-011**).
7. **Подсветка (3D):** через контроллер и snapshot `searchHighlightsByNamespace` с gating W14; выравнивание 2D — тот же контроллер (backlog).
8. **Scene graph DTO:** M/C формирует узлы/рёбра с лимитами **100 000 / 200 000** (**OR-010**); применяется predicate **OR-003** с default **D-ORPHAN-B** (см. [`graph-3dmvc.md`](graph-3dmvc.md)).
9. **Передача во View:** страница 3D получает DTO + side-channel; ключ данных совместим с `computeMemoryGraphDataKey`.
10. **Стабильное обновление WebGL:** ref + throttled `fg.refresh()`, не remount на каждый rev.
11. **Сцена готова:** store зафиксировал фазу; при ошибке slice — **blocked** с компактной причиной.

**Forbidden (сводка):** View как SoT подсветки из полного trace для 3D; rev в ключ remount; degree-0 в node-list при default **OR-003** без waiver **D-ORPHAN-C**.

## State lifecycle

| Фаза | Кто пишет store | Что читает View | Переходы | Compact event marker |
|------|-----------------|-----------------|----------|----------------------|
| `session_config` | main/renderer | loading / skeleton | → `pag_slice_inflight` / `blocked` | (см. код логирования) |
| `pag_slice_inflight` | Controller запрашивает; main slice | не интерпретирует сырой IPC как merged | → `merge_ready` / `partial` / `blocked` | `desktop.pag_slice.requested` → `completed` \| `error` |
| `merge_ready` | renderer merge | может ждать replay | → `trace_replay` или `scene_build` | `desktop.trace.replay.*` |
| `trace_replay` | Controller | не переключает SoT 3D на сырой trace | → `scene_build` / `partial` / `blocked` | start/end replay |
| `scene_build` | M/C: highlight, **D-ORPHAN-B**, caps | получает DTO после стадии | → `scene_ready` | `desktop.graph.scene_built` |
| `scene_ready` | store стабилен | `ForceGraph3D` + throttled refresh | дельты без remount ключа | `desktop.graph.refresh` |
| `partial` | Controller, компактная причина | частичный граф + причина | повтор только со сменой входа / backoff | `pag_slice.completed` + reason |
| `blocked` | ошибка slice/IPC | UI ошибки | после действия пользователя | `desktop.pag_slice.error` + `error_code` |

**Ownership:** merged и фазы — **renderer store**; View читает DTO после фазы не ниже `scene_build` для 3D; main — slice и trace, не единственный SoT merged одним blob.

## Examples

**Happy:** сессия открыта, slice успешен, merge и короткий replay, **D-ORPHAN-B** применён, ключ графа без rev, обновления подсветки через throttled refresh.

**Partial:** slice урезан или PAG занят; UI показывает доступный merged и статус `partial` с причиной; **запрещён** бесконечный повтор идентичного запроса.

**Blocked:** ошибка IPC/JSON; UI **blocked** с сообщением; remount не маскирует ошибку.

**Highlight без фантома:** при **D-ORPHAN-B** подсветка не добавляет изолированный узел в node-list для WebGL — side-channel или только узлы с рёбрами.

## Observability

События — **логические** id; реализация может добавлять префикс проекта.

| Событие | Когда | Required fields | Forbidden |
|---------|--------|-----------------|-----------|
| `desktop.pag_slice.requested` | перед IPC | session/workspace id | полный SQL, секреты |
| `desktop.pag_slice.completed` | успех | `duration_ms`, `node_count`, `edge_count` | полный JSON среза |
| `desktop.pag_slice.error` | ошибка | `error_code`, `duration_ms` | полный stderr без bound |
| `desktop.trace.replay.start/end` | replay | `row_count`, `duration_ms`, `rows_processed` | массив строк trace |
| `desktop.graph.scene_built` | DTO передан | `phase`, компактный fingerprint схемы ключа | полный DTO |
| `desktop.graph.refresh` | throttled refresh | `reason` enum | частота выше политики без агрегата |
| `desktop.pairlog.append` | append pair log | `bytes` или `batch_size` | повтор полного графа |

**Default:** недоступные числа — `null`, не выдуманные значения.

## Killer feature (OR-008, паттерны без копипаста доноров)

| Паттерн | Правило для Desktop |
|---------|---------------------|
| Типизированные рёбра | Явный тип связи в DTO; View не создаёт тип «на глаз». |
| Подграф с концами | Рёбра без обоих концов в capped множестве узлов — не в DTO для layout. |
| Инкремент | После первичного merge — дельты trace + slice, без O(весь мир) на каждый тик. |
| Focal + temporal budget | Лимит глубины/размера и при необходимости временной срез; caps — **D-CAP-1**. |
| Async stable read | После фазы `completed` в store для долгих операций. |

**Out of scope:** обязательный Markdown-vault, Neo4j, сторонние MCP как инфраструктура.

## Commands

Из **корня репозитория**:

| Проверка | Команда | Expected |
|----------|---------|----------|
| Caps Python / OR-010 | `.venv/bin/python -m pytest tests/test_pag_slice_caps_alignment.py` | exit 0 |
| Ключ 3D / OR-011 | `npm --prefix desktop test -- src/renderer/views/MemoryGraph3DPage.test.tsx -t "TC-3D-UC04-03"` | exit 0; тест **passed** |
| Smoke | Сборка/запуск Electron `desktop`, открыть 3D memory graph | граф виден; нет полного remount на каждый rev; ошибка slice — blocked UI |

**blocked_by_environment:** если нет зависимостей desktop, smoke помечается пропущенным с причиной.

## Acceptance criteria (OR-001 … OR-012)

| ID | Критерий |
|----|----------|
| OR-001 | В пакете зафиксированы границы Desktop↔память без описания всего Electron. |
| OR-002 | Документирован поток 3dmvc + этот target flow. |
| OR-003 | Default **D-ORPHAN-B**; **A** deferred; **C** только waiver — см. [`graph-3dmvc.md`](graph-3dmvc.md). |
| OR-004 | Политика ключа, throttled refresh, запрет remount как единственного ответа на rev. |
| OR-005 | Пакет `context/desktop/` с `INDEX.md` и `glossary.md` опубликован. |
| OR-006 | Нет скрытых задач на Python AgentMemory без user OK. |
| OR-007 | Stub в legacy-файле; SoT — этот пакет. |
| OR-008 | Раздел Killer feature выше. |
| OR-009 | Current reality отражена в текстах пакета и ссылках на код в плане. |
| OR-010 | Лимиты 100k/200k + pytest alignment зелёный. |
| OR-011 | Политика ключа + vitest **TC-3D-UC04-03** зелёный. |
| OR-012 | Highlight policy в [`graph-3dmvc.md`](graph-3dmvc.md). |

## How start-feature / start-fix must use this

- **`02` / `06`:** читать [`INDEX.md`](INDEX.md), [`graph-3dmvc.md`](graph-3dmvc.md), этот файл и [`../../plan/18-desktop-memory-graph-3dmvc.md`](../../plan/18-desktop-memory-graph-3dmvc.md) для задач по Desktop memory graph.
- **`08`:** не восстанавливать SoT в stub legacy-файле; не включать `graphRevByNamespace` в ключ «для простоты»; не использовать **D-ORPHAN-C** без waiver.
- **`11`:** минимум команды из таблицы выше.
- **`13`:** обновлять этот пакет только при сознательном изменении целевого поведения.

**Forbidden shortcuts:** публикация устаревших лимитов 20k/40k; логирование полного JSON slice или массива строк trace в канон-логах без bound.
