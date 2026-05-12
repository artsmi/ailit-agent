# План внедрения 18: Desktop memory graph, 3dmvc, orphan D-ORPHAN-B

**Идентификатор:** `desktop-memory-graph-3dmvc`  
**Файл:** `plan/18-desktop-memory-graph-3dmvc.md`  
**Статус:** утверждён вместе с каноном `context/algorithms/desktop/` — user OK в чате (**2026-05-12**); ревью `107`: `plan_review_latest.json` (`approved`).

## Канон и источники правды

| Роль | Путь |
|------|------|
| **SoT поведения (до публикации пакета)** | [`context/artifacts/target_doc/target_algorithm_draft.md`](../context/artifacts/target_doc/target_algorithm_draft.md) — `Produced by: 104_target_doc_author`; верификация `105`: [`verification.md`](../context/artifacts/target_doc/verification.md) (`approved`, pass 2). |
| **Будущий хаб пакета** | `context/algorithms/desktop/INDEX.md` (появляется после user OK и split текста из draft; см. раздел «Миграция» в draft). |
| **Старый путь протокола (миграция)** | [`context/algorithms/agent-memory/desktop-realtime-graph-protocol.md`](../context/algorithms/agent-memory/desktop-realtime-graph-protocol.md) → stub/redirect на `context/algorithms/desktop/*` без устаревших чисел/remount (OR-007). |
| **Архитектура snapshot (согласование OR-012)** | [`context/arch/desktop-pag-graph-snapshot.md`](../context/arch/desktop-pag-graph-snapshot.md). |

Produced by: 106_implementation_plan_author

---

## 0. Запуск `start-feature` по этому плану

Точка входа продукта — правило **`.cursor/rules/start-feature.mdc`**: текущий чат играет роль **`01_orchestrator`**, код не пишет; роли **`02+`** запускаются только как **Cursor Subagents** по `.cursor/agents/01_orchestrator.md` и картам в **`.cursor/rules/project/project-agent-models.mdc`** (в репозитории по умолчанию везде `Auto`: параметр `model` в вызове Subagent не подставлять из IDE). Дополнительно: **`.cursor/rules/project/project-workflow.mdc`**, **`.cursor/rules/project/project-orchestrator-overrides.mdc`**, **`.cursor/rules/project/project-human-communication.mdc`**, для навигации по канону — **`context/INDEX.md`**.

### 0.1 Что необходимо знать **до** запуска `start-feature`

Ниже — минимум, без которого `02_analyst` и последующие роли не смогут трассировать ТЗ к канону и к слайсам **G1 / G3 / G4** этого плана.

| # | Требование | Зачем |
|---|------------|--------|
| **1** | **Полный pipeline**, а не «написать код в чате»:`02→03→04→05→06→07→task_waves(08→09→11)→финальный 11→12→13→auto commit` (см. `start-feature.mdc` §Route). | Иначе нарушается контракт репозитория: нет `task_waves`, нет финального `11`/`12`/`13`. |
| **2** | Перед `02` оркестратор сохраняет **замороженную** постановку в **`context/artifacts/original_user_request.md`** (цель, ожидаемый результат, **границы**, ссылка на слайс плана). | `02` не переинтерпретирует вход; постановка — единственный frozen scope. |
| **3** | В постановке явно указать **целевой документ (SoT)**: минимум хаб [`context/algorithms/desktop/INDEX.md`](../context/algorithms/desktop/INDEX.md) и файлы пакета по теме слайса (**`graph-3dmvc.md`** для OR-003 / highlight-семантики, **`realtime-graph-client.md`** для flow/observability/performance), плюс **этот файл** `plan/18-desktop-memory-graph-3dmvc.md` и **идентификатор этапа** (`G1`, `G3`, `G4`). | `start-feature.mdc` требует передавать утверждённый `context/algorithms/…` в `02` как обязательную опору; без ссылки на разделы канона completion по сценарию канона запрещён. |
| **4** | Знать **зависимости слайсов**: рекомендуемый порядок **G0 → G1 → G3 → G4**; **G0** (публикация пакета + stub) уже выполнен после user OK на target-doc — новые `start-feature` открывают **кодовые** слайсы **G1**, затем **G3**, затем **G4**, не перескакивая без закрытия предыдущего. | Иначе риск реализации без согласованного текста **D-ORPHAN-B** или дублирования конфликта OR-003. |
| **5** | **G2** — это **не** отдельный пятый полный `start-feature`: регрессия **pytest** / **vitest** из §5 плана (и новые тесты по мере появления) должна выполняться **на каждом PR** в CI / в финальном **`11_test_runner`** внутри каждого feature-run. | G2 — непрерывный контроль, а не отдельная «дорожка оркестратора» без кода. |
| **6** | Один запуск `start-feature` = **одна** сфокусированная USER-story (или несколько **task** в **одной** волне после `06`, если планировщик так нарежет), **не** смешивать G1+G3+G4 в одной размытой постановке без явного согласования scope. | Соответствует `project-workflow.mdc`: задачи с критериями приёмки; проще ревью и `09`. |
| **7** | **OR-006:** в постановке не расширять scope на **Python AgentMemory / broker DTO / SQLite** без отдельного согласования пользователя. | Иначе blocker на архитектуре или нарушение out-of-scope плана. |

### 0.2 Как сопоставить постановку с этапами плана

| Слайс | Типичный запуск `start-feature` | Что приложить к `original_user_request.md` |
|-------|----------------------------------|---------------------------------------------|
| **G1** | Первый кодовый цикл после канона | Ссылка на §G1, якорные файлы `desktop/src/...` из таблицы G1, абзац из **`graph-3dmvc.md`** (OR-003, **D-ORPHAN-B**, Example 4). |
| **G3** | Отдельный цикл после закрытия G1 | §G3, **`graph-3dmvc.md`** (Highlight policy, OR-012), при необходимости правка **`context/arch/desktop-pag-graph-snapshot.md`**. |
| **G4** | Отдельный цикл после G3 | §G4, **`realtime-graph-client.md`** (Performance, Observability, State lifecycle). |
| **G0** | Обычно **не** требует нового `start-feature` (док уже в репо) | Только если нужна правка канона — тогда отдельная постановка «docs only» по согласованию. |

После **`06_planner`** обязательны **`task_waves`**; каждая дорожка: **`08_developer` → `09_code_reviewer` → `11_test_runner`**. Финальный **`11`**, затем **`12_change_inventory`**, **`13_tech_writer`**, **auto commit** (без push) — как в `start-feature.mdc`.

---

## 1. Цель и границы

### 1.1 Цель

Выровнять **renderer pipeline** Desktop (Electron): память/trace/PAG slice → **Model/Controller** → проекция **scene graph DTO** → **View** (3dmvc), устранить конфликт **OR-003** с текущим `ensureHighlightNodes` (**default target: D-ORPHAN-B**), зафиксировать **производительность** (anti-flicker, бюджеты refresh/replay, классы нагрузки main IPC), опубликовать нормативку в **`context/algorithms/desktop/*`** и выполнить **stub-миграцию** старого `desktop-realtime-graph-protocol.md`.

### 1.2 In scope

- TypeScript/React код под `desktop/src/` (renderer + main/preload по цепочке slice/log).
- Новые markdown-файлы пакета `context/algorithms/desktop/` и правка stub в `context/algorithms/agent-memory/desktop-realtime-graph-protocol.md` (после утверждения канона человеком).
- Регрессии: существующие pytest/vitest из draft; при необходимости — новые vitest на проекцию/orphan (только если пользователь/план этапа явно расширяют приёмку; базовый минимум — имена из draft).

### 1.3 Out of scope (жёстко)

- **Широкий рефакторинг Python AgentMemory / broker DTO / SQLite PAG** без отдельного согласования пользователя (**OR-006**). Любой slice с `tools/agent_core/**` или `pag_slice` semantics на стороне CLI — только с явным user gate в плане/approval.
- Полное описание Electron shell, брендбук, дублирование `docs/web-ui-book/`.
- Neo4j, Obsidian vault, Graphiti/Hindsight как обязательная инфраструктура.

### 1.4 Запрещённые shortcuts (сводка)

- Публикация SoT в старом `desktop-realtime-graph-protocol.md` без redirect.
- Закрытие OR-003 через **D-ORPHAN-C** без **named waiver** в human approval package.
- Подмена **D-ORPHAN-A** на default без явной записи в plan/approval (см. draft: только **D-ORPHAN-B** default).
- Включение `graphRevByNamespace` в ключ remount графа «для простоты» (**OR-011** / **D-KEY-1**).

---

## 2. Аудит / текущая картина

Кратко по [`target_algorithm_draft.md`](../context/artifacts/target_doc/target_algorithm_draft.md) §Current reality и отчётам `102`:

| Факт | Суть | Якорь реализации |
|------|------|------------------|
| **F1** | `merged` собирается в renderer из IPC slice, не одним blob с main. | `pagGraphSessionStore.ts`, `loadPagGraphMerged.ts` |
| **F2–F3** | Highlight добавляет узлы без рёбер; проектор режет только рёбра UC-04A, не degree-0 узлы — **mismatch OR-003** vs **D-ORPHAN-B**. | `memoryGraphState.ts` (`ensureHighlightNodes`), `memoryGraphForceGraphProjection.ts` |
| **F5–F10** | Линейный trace replay, частые `fg.refresh`, `appendFile` pair log, тяжёлый `pagGraphSlice` на main — классы «виснет». | `pagGraphSessionStore.ts`, `MemoryGraph3DPage.tsx`, `registerIpc.ts`, `pagGraphBridge.ts` |
| **F6 / OR-011** | Ключ графа **без** `graphRevByNamespace` — покрыто тестом. | `memoryGraphDataKey.ts`, `MemoryGraph3DPage.test.tsx` |
| **F12 / OR-010** | Caps **100k/200k** в коде и alignment pytest. | `pagGraphLimits.ts`, `pag_slice_caps.py` |
| **F11** | 2D и 3D расходятся по пути highlight — backlog **S3**. | `MemoryGraphPage.tsx` vs snapshot path в 3D |

Деталь: [`context/artifacts/target_doc/current_state/desktop_memory_agentmemory_integration.md`](../context/artifacts/target_doc/current_state/desktop_memory_agentmemory_integration.md), [`desktop_protocol_canon_vs_code.md`](../context/artifacts/target_doc/current_state/desktop_protocol_canon_vs_code.md).

---

## 3. Нормативные контракты (id → решение)

| ID | Решение | Проверка |
|----|---------|----------|
| **OR-001 … OR-012** | Как в draft §Связь с исходной постановкой / Acceptance criteria. | Таблица OR в draft + команды ниже. |
| **D-ORPHAN-B** | **Единственный default:** фильтр узлов степени 0 на **проекции** перед View; highlight — side-channel, не phantom node-list. | Сцена без изолированных узлов в node-data для `ForceGraph3D` при отсутствии waiver; тесты/снимки по слайсу G1. |
| **D-KEY-1** | Ключ монтирования графа не сериализует monotonic `graphRev`. | `TC-3D-UC04-03` зелёный. |
| **D-CAP-1** | Лимиты 100 000 / 200 000 из кода, не 20k/40k. | `tests/test_pag_slice_caps_alignment.py` зелёный. |
| **D-HI-OWN-1** | 3D highlight SoT — snapshot/controller; цель — единый контроллер для 2D/3D (**S3**). | Код после G3: отсутствие ad-hoc parse `rawTraceRows` в 2D для решения highlight (или явный tech debt с задачей). |
| **D-PERF-1** | Три класса: trace replay, `fg.refresh`, main IPC — observability + bounded policy по слайсу G4. | Compact events из draft §Observability; отсутствие неограниченного шторма. |

---

## 4. Этапы (слайсы) и зависимости

Зависимости: **G0** (публикация канона) блокируется **user OK** на target-doc пакет. **G1** может стартовать в коде параллельно подготовке G0 только если не меняется публичный контракт без канона — на практике связать: сначала зафиксировать текст D-ORPHAN-B в репо (`context/algorithms/desktop/graph-3dmvc.md` или draft до split), затем merge кода G1. Рекомендуемый порядок: **G0 → G1 → G3 → G4**, **G2** — непрерывный регресс в CI на каждом PR.

### G0 — Пакет `context/algorithms/desktop/` + stub OR-007

| Поле | Содержание |
|------|------------|
| **Цель** | Создать `context/algorithms/desktop/INDEX.md`, `graph-3dmvc.md`, `realtime-graph-client.md`, `glossary.md` (default; исключение `minimal_pack_no_glossary_file` только если явно записано в approval/этом плане — сейчас **не** записываем). Заменить тело `desktop-realtime-graph-protocol.md` на stub со ссылками. |
| **Implementation anchors** | Новые файлы под `context/algorithms/desktop/`; [`context/algorithms/agent-memory/desktop-realtime-graph-protocol.md`](../context/algorithms/agent-memory/desktop-realtime-graph-protocol.md). |
| **Трассировка draft** | draft §Миграция, §Планируемая структура пакета, §Scope (глоссарий). |
| **Anti-patterns** | Оставлять в stub числа 20k/40k или описание remount с `graphRev`; дублировать полный протокол в двух местах. |
| **Приёмка** | В дереве есть `context/algorithms/desktop/INDEX.md` со ссылками на файлы пакета и на `plan/18-desktop-memory-graph-3dmvc.md`; старый файл — только stub + ссылки; `13_tech_writer` / human scrub: **нет** ссылок читателя на `context/artifacts/…` внутри опубликованного пакета. |

### G1 (S1) — OR-003 / D-ORPHAN-B + highlight semantics

| Поле | Содержание |
|------|------------|
| **Цель** | Реализовать шаг проекции **degree-0** на индуцированном подграфе перед передачей во View; убрать противоречие с `ensureHighlightNodes` (side-channel / не добавлять phantom в node-list для WebGL). |
| **Implementation anchors** | `desktop/src/renderer/runtime/memoryGraphForceGraphProjection.ts` (`MemoryGraphForceGraphProjector`, `filterEdgesUc04BranchA`); `desktop/src/renderer/runtime/memoryGraphState.ts` (`ensureHighlightNodes`); `desktop/src/renderer/runtime/pagGraphSessionStore.ts` (`PagGraphSessionTraceMerge`, `applyHighlightFromTraceRows`); `desktop/src/renderer/views/MemoryGraph3DPage.tsx` (потребление DTO). |
| **Трассировка draft** | draft §Инварианты View (OR-003, D-ORPHAN-B), §Highlight policy, §Example 4. |
| **Зависимости** | Текст G0 или эквивалентный раздел draft согласован с ревьюером; иначе риск расхождения канона и кода. |
| **Anti-patterns** | D-ORPHAN-C как тихий default; фильтрация только в WebGL шейдере без M/C; View, читающий полный trace для highlight (**D-HI-OWN-1**). |
| **Приёмка** | Поведение из draft §Example 1 и §Example 4: в node-list для WebGL нет узлов степени 0 при default **D-ORPHAN-B**; highlight доступен через согласованный side-channel. Регрессия: команды из §5 остаются зелёными; ручной smoke §6. Дополнительные vitest на проекцию — только если отдельная постановка задачи явно требует новых тестов. |

### G2 (S2) — Выравнивание caps / key / stale-комментарии

| Поле | Содержание |
|------|------------|
| **Цель** | Гарантировать совпадение канона и кода OR-010/OR-011; убрать устаревшие комментарии в TS, если противоречат `computeMemoryGraphDataKey`. |
| **Implementation anchors** | `desktop/src/renderer/runtime/pagGraphLimits.ts` (или актуальный путь лимитов); `desktop/src/renderer/runtime/memoryGraphDataKey.ts`; `tools/agent_core/.../pag_slice_caps.py` — **только чтение/синхронизация констант**, без смены семантики slice без gate. |
| **Трассировка draft** | draft §Current reality (F6, F12), §Commands. |
| **Приёмка** | `tests/test_pag_slice_caps_alignment.py` — exit 0; vitest `TC-3D-UC04-03` — exit 0 (команда ниже). |

### G3 (S3) — Единый highlight controller (D-HI-OWN-1)

| Поле | Содержание |
|------|------------|
| **Цель** | Свести 2D и 3D к одному выходу контроллера highlight из snapshot/M/C (**F11**), не дублируя parse `rawTraceRows` в `MemoryGraphPage` для решений, которые уже есть в store. |
| **Implementation anchors** | `desktop/src/renderer/views/MemoryGraphPage.tsx`; `desktop/src/renderer/runtime/pagGraphSessionStore.ts`; `desktop/src/renderer/runtime/pagHighlightFromTrace.ts`; при необходимости `DesktopSessionContext.tsx`. |
| **Трассировка draft** | draft §Highlight policy, OR-012, synthesis **S3**. |
| **Зависимости** | После G1 (иначе дважды менять контракт highlight). |
| **Anti-patterns** | Полный rewrite 2D UI в одном PR без постановки. |
| **Приёмка** | Один источник SoT для highlight DTO, согласованный с `context/arch/desktop-pag-graph-snapshot.md` или зафиксированное отклонение в `context/algorithms/desktop/*.md`. |

### G4 (S4) — Performance: replay, refresh, IPC logging

| Поле | Содержание |
|------|------------|
| **Цель** | Адресовать **D-PERF-1**: bounded/trace replay observability, throttle/budget `fg.refresh`, снижение шторма `appendDesktopGraphPairLog` (batch/queue), документированные mitigations без Python core. |
| **Implementation anchors** | `pagGraphSessionStore.ts` (`afterFullLoad`); `MemoryGraph3DPage.tsx` (highlight loop, resize); `desktop/src/main/registerIpc.ts`; `pagGraphBridge.ts`. |
| **Трассировка draft** | draft §Performance, §Observability, §State lifecycle. |
| **Зависимости** | Частично параллельно G1 после инвентаризации; тесное пересечение с G3 по `MemoryGraph3DPage.tsx` — порядок merge согласовать с `06`. |
| **Anti-patterns** | Логировать полный JSON slice или массив trace в compact log (**forbidden** в draft). |
| **Приёмка** | События уровня `desktop.trace.replay.*` / `desktop.graph.refresh` / `desktop.pairlog.append` с полями из draft §Observability (когда инструментирование добавлено); отсутствие регрессии ключевых vitest. **G-N1** (benchmark replay) остаётся gap до отдельной задачи. |

---

## 5. Тесты и статика

Выполнять из корня репозитория; Python — venv проекта.

| Проверка | Команда | Ожидаемый результат |
|----------|---------|---------------------|
| **OR-010 alignment** | `.venv/bin/python -m pytest tests/test_pag_slice_caps_alignment.py` | Exit code **0**. |
| **OR-011 / UC-04 key stability** | `npm --prefix desktop test -- src/renderer/views/MemoryGraph3DPage.test.tsx -t "TC-3D-UC04-03"` | Exit code **0**; в выводе vitest тест **`TC-3D-UC04-03`** **passed** (`desktop/package.json`: `"test": "vitest run"`). |
| **flake8** | По затронутым `.py` **только если** этап меняет Python (по умолчанию G1–G4 — нет). | 0 ошибок. |
| **Регресс renderer store** | `npm --prefix desktop test -- src/renderer/runtime/pagGraphSessionStore.test.ts` (и соседние `*.test.ts` по диффу этапа) | Зелёный, если файлы затронуты. |

Статика по TS: следовать существующему ESLint/tsc pipeline пакета `desktop` (команды из `desktop/package.json`).

---

## 6. Пользовательские сценарии (smoke)

| Сценарий | Шаги | Ожидание |
|----------|------|----------|
| **Happy** | Запустить Desktop; открыть 3D memory graph для workspace с PAG и небольшим trace. | Граф отображается; нет полного remount canvas на каждую дельту rev; нет изолированных узлов в сцене при default (**D-ORPHAN-B**). |
| **Partial** | Симулировать усечённый slice / busy PAG (как в draft §Example 2). | UI **partial** с компактной причиной; нет бесконечного цикла идентичных запросов. |
| **Failure** | Ошибка slice (невалидный JSON / отказ CLI). | **blocked** с сообщением; не «тихий» пустой граф; см. draft §Example 3. |

`blocked_by_environment`: отсутствие Electron deps — зафиксировать в отчёте `11`, не заменять автотестами.

---

## 7. Наблюдаемость / доказательства закрытия

Минимальный набор **логических** id событий и полей — в draft §Observability (`desktop.pag_slice.*`, `desktop.trace.replay.*`, `desktop.graph.scene_built`, `desktop.graph.refresh`, `desktop.pairlog.append`). Закрытие G4 без появления этих точек в коде — **неполная** реализация этапа (если этап декларирует инструментирование).

---

## 8. Gaps (таблица)

| ID | Тип (taxonomy human comm) | Важность | Кто закрывает | Заметка |
|----|---------------------------|----------|---------------|---------|
| **G-N1** | `verification_gap` | medium | Отдельный research/perf slice | Benchmark `afterFullLoad` vs `rawTraceRows.length`. |
| **G-N2** | `verification_gap` | medium | Backlog e2e | Автоматический e2e на hang. |
| **G-N3** | `doc_incomplete` / `implementation_backlog` | low | `realtime-graph-client.md` при публикации | Полная IPC-матрица preload/main. |
| **G-N4** | `verification_gap` | low | Узкий job | Broker primary vs highlight policy. |

---

## 9. Donor ref (минимальная таблица)

Единственное место с путями donor repo и строками. В тексте этапов: «см. строку таблицы для Gx».

| Этап / слайс | Donor report (path) | Finding ID | Donor path | Строки | Kind | Якорь в текущем repo | Копировать |
|--------------|---------------------|------------|------------|--------|------|------------------------|------------|
| G1 | `context/artifacts/target_doc/donor/obsidian_memory_mcp_graph_semantics.md` | F6 | `/home/artem/reps/obsidian-memory-mcp/storage/MarkdownStorageManager.ts` | `350-375` | code | `memoryGraphForceGraphProjection.ts` / фильтр подграфа | только референс / идея |
| G4 | `context/artifacts/target_doc/donor/graphiti_memory_graph_ui_patterns.md` | F1 | `/home/artem/reps/graphiti/graphiti_core/graphiti.py` | `933-1107` | code | `pagGraphSessionStore.ts` / инкремент после merge | только референс / идея |
| G4 | `context/artifacts/target_doc/donor/graphiti_memory_graph_ui_patterns.md` | F5 | `/home/artem/reps/graphiti/graphiti_core/search/search_config.py` | `29-118` | code | `pagGraphLimits.ts` / budget caps | только референс / идея |
| G4 | `context/artifacts/target_doc/donor/graphiti_memory_graph_ui_patterns.md` | F6 | `/home/artem/reps/graphiti/graphiti_core/search/search.py` | `104-106` | code | `MemoryGraph3DPage.tsx` / focal subgraph | только референс / идея |
| G4 | `context/artifacts/target_doc/donor/hindsight_memory_increment_patterns.md` | F4 | `/home/artem/reps/hindsight/skills/hindsight-docs/references/developer/api/operations.md` | `30-80` | docs | `pagGraphSessionStore.ts` / фазы stable read | только референс / идея |

---

## 10. Definition of Done и трассировка «слайс → канон»

| Этап | Файл(ы) канона после split | Раздел / якорь в draft (до split) | Что проверяем |
|------|----------------------------|-----------------------------------|---------------|
| G0 | [`context/algorithms/desktop/INDEX.md`](../context/algorithms/desktop/INDEX.md) (будущий), [`context/algorithms/desktop/glossary.md`](../context/algorithms/desktop/glossary.md), stub [`desktop-realtime-graph-protocol.md`](../context/algorithms/agent-memory/desktop-realtime-graph-protocol.md) | draft §Миграция, §Планируемая структура пакета, §Scope | Навигация; нет артефактных ссылок в пакете; stub без stale чисел. |
| G1 | [`context/algorithms/desktop/graph-3dmvc.md`](../context/algorithms/desktop/graph-3dmvc.md) | draft §Инварианты View, §OR-003 predicate, §Anti-patterns | OR-003 + **D-ORPHAN-B** в поведении и тексте. |
| G2 | [`context/algorithms/desktop/realtime-graph-client.md`](../context/algorithms/desktop/realtime-graph-client.md) | draft §Current reality F6/F12, §Commands | pytest caps + vitest `TC-3D-UC04-03`. |
| G3 | `context/algorithms/desktop/graph-3dmvc.md` + при необходимости правка `context/arch/desktop-pag-graph-snapshot.md` | draft §Highlight policy, OR-012 | Нет F11 drift по согласованному критерию этапа. |
| G4 | `context/algorithms/desktop/realtime-graph-client.md` | draft §Performance, §Observability, §State lifecycle | Компактные события; mitigations IPC/refresh/replay задокументированы и частично в коде. |

**Сквозной DoD workflow 18:** канон опубликован в `context/algorithms/desktop/*` (после user OK), stub на месте, G1–G4 закрыты или явно отложены с gap-id, pytest + vitest из §5 зелёные на `main`, ручной smoke из §6 пройден либо помечен `blocked_by_environment`.

---

## 11. Как использовать план в `start-feature` / `start-fix`

- **`02_analyst`:** трассировать ТЗ к OR-id и к файлам `context/algorithms/desktop/*` после публикации.  
- **`06_planner`:** нарезать PR по этапам G0–G4; не смешивать G1 с Python runtime без OR-006.  
- **`08` / реализация:** якоря из §4; donor — только идеи (таблица §9).  
- **`11_test_runner`:** команды §5 + smoke §6.  
- **`13_tech_writer`:** обновлять `context/algorithms/desktop/*` при смене поведения; синхронизировать arch при OR-012.

---

## 12. Связь со synthesis slices S1–S4

| Slice synthesis | Этап плана |
|-----------------|------------|
| S1 | G1 |
| S2 | G2 |
| S3 | G3 |
| S4 | G4 |

Каркас пакета и миграция из synthesis п.1 / draft unit 0 — **G0**.
