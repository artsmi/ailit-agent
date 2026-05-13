# Рабочий процесс 19: Desktop stack — чат, freeze, PAG rev и трассировка

**Идентификатор:** `desktop-stack-chat-freeze-pag-trace-19` (файл `plan/19-desktop-stack-chat-freeze-pag-trace.md`).

**Статус:** черновик под ревью `107_implementation_plan_reviewer` (после merge — вход для `start-feature` / `start-fix` по слайсам ниже).

**Канон SoT (поведение и контракты):** до публикации человеком отдельного пакета **desktop-stack** под `context/algorithms/` источник правды для трассировки слайсов — [`context/artifacts/target_doc/target_algorithm_draft.md`](../context/artifacts/target_doc/target_algorithm_draft.md). После user OK и publish от `100`/`13` ожидается пакет вида `context/algorithms/desktop-stack/**` (в репозитории путей пока нет; markdown-ссылку на несуществующий `INDEX.md` не использовать). Согласованные факты волны `cycle_d_current_repo_1`: [`synthesis.md`](../context/artifacts/target_doc/synthesis.md), gate `105`: [`verification.md`](../context/artifacts/target_doc/verification.md).

**Канон процесса планов:** [`.cursor/rules/project/project-workflow.mdc`](../.cursor/rules/project/project-workflow.mdc).

Produced by: 106_implementation_plan_author

---

## 1. Реализация и архитектурный сдвиг

Для оператора и разработчика продукт должен перестать «объясняться» выключением `memory.debug.chat_logs_enabled` как достаточной причиной полного зависания окна при отправке в чат. Параллельно фиксируется проверяемая семантика предупреждения PAG rev mismatch (монотонный graph rev по namespace, не номер строки чата) и граница ответственности: renderer (O(N) проекция, инкрементальный merge), main Electron (IPC, `pag-slice`, чтение JSONL), subprocess `ailit memory pag-slice`.

Архитектурно план **не** меняет протокол broker и **не** вводит sync IPC. Сдвиг — в **наблюдаемости и снижении ложных выводов**: измеримые корреляции OR-D6, точечные правки низкого blast radius (гард `broker_connect`), затем опционально алгоритмические смягчения нагрузки (chunk/yield для инкрементального PAG merge, снижение стоимости проекции чата / дедуп обновлений trace). Каждый слайс трассируется на markdown-канон (после publish — файлы под `context/algorithms/desktop-stack/**`).

---

## 2. Цель и границы

### 2.1 In scope

- Путь submit → `brokerRequest`, live trace → `rawTraceRows` → проекция чата и PAG merge (см. draft §Current Reality / Target Flow).
- Ветка `chat_logs_enabled: false`: что отключено на диске, что остаётся активным; SoT флага в main.
- Предупреждение rev mismatch и отдельный поток «тяжёлый merged»; запрет путаницы с порядковым номером сообщения.
- Диагностический контракт OR-D6: события, поля, forbidden для compact логов.
- Точечный fix D-D6 (`broker_connect` без гарда в renderer).
- Производительность renderer/main по гипотезам synthesis O1–O2 без смены транспорта.

### 2.2 Out of scope

- Donor research и любые выводы из внешних репозиториев (**OR-D7**).
- Полный rewrite broker IPC или замена Electron транспорта.
- Пакет `context/algorithms/desktop/` (Cycle C, graph-3dmvc) — только явный scope divider; смешивание без заголовка out-of-scope запрещено каноном (**DNI4**).

### 2.3 Явные запреты

| Запрет | Нормативный якорь |
|--------|-------------------|
| Утверждать единственный численный root cause freeze без метрик OR-D6 или без ≥ двух согласованных сигналов | **FR1**, **AC2** (канон) |
| Объяснять freeze только `chat_logs_enabled: false` | **FR2** |
| Описывать числа в PAG warning как «номер сообщения чата» | **FR3** |
| Вводить `sendSync` / `invokeSync` в Desktop | **DNI2** |
| Выкладывать raw stdout `pag-slice`, полный `rawTraceRows`, raw prompts в compact лог | OR-D6 **Forbidden** (канон) |

---

## 3. Аудит / текущая картина

Сводка согласована с **`verification.md` (approved)** и детализирована в **`target_algorithm_draft.md`**. Доказательная база волны `102` (без повторного product research в рамках этого плана):

| Источник | Содержание для плана |
|----------|---------------------|
| `current_state/desktop_stack_chat_submission_agentwork.md` | F-D1–F-D7: submit, `brokerRequest` 30 s, O(N) `projectChatTraceRows`, синхронный `applyIncremental` без chunk budget |
| `current_state/desktop_stack_chat_logs_enabled_branch.md` | F-D8–F-D12: SoT yaml в main, зеркало renderer при старте, `broker_connect` без гарда (**D-D6**) |
| `current_state/desktop_stack_pag_rev_trace_delta_ui.md` | F-D13–F-D17: шаблон rev mismatch, семантика rev, UI warning vs error, `pagGraphSlice` серия IPC |
| `current_state/desktop_stack_electron_ipc_main_hotspots.md` | F-D18–F-D19: нет sync IPC; hotspots main: `runPagGraphSlice`, `memoryJournalRead`, `readDurableTraceRows`, live trace parse |

Пробел **G-NB1** (synthesis): доли времени broker vs renderer jank vs main не измерены в репо — закрывается слайсом **G19.1** (OR-D6).

---

## 4. Нормативные решения / контракты

| ID | Решение | Проверка |
|----|---------|----------|
| **OR-D1** | Не закрывать инцидент «freeze» одной гипотезой без измерений | Постмортем содержит ≥2 метрики из таблицы OR-D6 или пометка `verification_gap` |
| **OR-D2** | Rev mismatch — монотонный graph rev по namespace; шаблон строки фиксирован в каноне | Регресс на дословный префикс + поля; ручной smoke §Commands канона |
| **OR-D3** | Граница правок: renderer TS vs `desktop/src/main/*` vs CLI `ailit memory pag-slice` | CODEOWNERS / описание в PR ссылается на таблицу AC5 канона |
| **OR-D4** | План внедрения — этот файл; слайсы не дублируют канон целиком | Трассировка §6, DoD §16 |
| **OR-D5** | SoT `chat_logs_enabled`: main `readAgentMemoryChatLogsEnabled`; renderer — зеркало при старте | `desktop/src/main/agentMemoryYamlFlags.ts` + handler `ailit:agentMemoryChatLogsRoot` в `desktop/src/main/registerIpc.ts` |
| **OR-D6** | Диагностика: таблица метрик/событий из канона (минимум broker duration, trace rate/length, pag_slice duration/payload bounded, renderer longtask или rAF gap) | События в compact log с полями; нет forbidden payload |
| **OR-D7** | Donor research не выполнялся | Таблица Donor ref — одна строка `none` |
| **D-D1** | Текст rev mismatch — из `formatPagGraphRevMismatchWarning` | См. `pagGraphRevWarningFormat.ts` |
| **D-D2** | При `false` не отключаются trace, broker, PAG slice, incremental merge | Ручной smoke + отсутствие гарда «выключить trace» в PR |
| **D-D3** | Гипотеза renderer-jack: частый trace → O(N) projection + sync `applyIncremental` | Корреляция метрик G19.1 после внедрения |
| **D-D4** | Гипотеза main: `pag-slice`, durable trace read, journal read, live JSON.parse | Те же метрики |
| **D-D5** | Единственный обязательный await в submit-path — `brokerRequest` до 30 s | Инструментация G19.1 фиксирует duration |
| **D-D6** | `broker_connect` вызывает pair-log без проверки флага — tech debt; слайс G19.2 устраняет лишний IPC при `false` | Нет вызова `appendDesktopGraphPairLog` из renderer при `agentMemoryChatLogsFileTargetsEnabledRef !== true` для этого call site (или эквивалентный single enforcement) |
| **D-D7** | «Ожидается / в trace» ≠ порядковый номер строки чата | Док/PR не используют неверную формулировку |
| **FR1–FR5** | Правила постмортема и различения await vs jank | Review чеклист + канон |
| **AC1–AC5** | Критерии приёмки PR/доков из канона | CI + review |

---

## 5. Трассировка нормативных ID → этап

| ID | Этап-исполнитель |
|----|------------------|
| **OR-D1** | **G19.1**, **G19.4** |
| **OR-D2** | **G19.3**, **G19.5** |
| **OR-D3** | **G19.5** |
| **OR-D4** | **G19.1**–**G19.5** (ссылка на этот план в PR) |
| **OR-D5** | **G19.2**, **G19.5** |
| **OR-D6** | **G19.1**, **G19.5** |
| **OR-D7** | **G19.2**, §15 Donor ref |
| **D-D1** | **G19.3** |
| **D-D2** | **G19.2**, **G19.5** |
| **D-D3** | **G19.1**, **G19.3**, **G19.4** |
| **D-D4** | **G19.1** |
| **D-D5** | **G19.1** |
| **D-D6** | **G19.2** |
| **D-D7** | **G19.3**, **G19.5** |
| **FR1–FR5** | **G19.1**, **G19.2**, **G19.3**, **G19.4**, **G19.5** |
| **AC1–AC5** | **G19.3**, **G19.5** |
| **DNI1** | **G19.2**, **G19.5** |
| **DNI2** | **G19.4**, **G19.5** |
| **DNI4** | **G19.5** |

*Примечание:* рекомендация **S-D3** (synthesis) закрывается **G19.3** (паритет `applyIncremental` vs chunked replay); **S-D4** — **G19.4** (проекция чата / дедуп trace). **G19.3** не меняет шаблон rev mismatch без ADR (**AC1** / **OR-D2**).

---

## 6. Запуск start-feature

Один **`Gx` за один run** `start-feature` (или `start-fix` для точечного бага): в постановке обязательны ссылка на этот план, идентификатор слайса (**G19.x**), frozen `original_user_request.md` для Cycle D, и ссылка на канон-candidate [`target_algorithm_draft.md`](../context/artifacts/target_doc/target_algorithm_draft.md). Правила постановки: [`.cursor/rules/start-feature.mdc`](../.cursor/rules/start-feature.mdc).

**n/a (doc-only):** не применяется — все слайсы якорятся в `desktop/` и main Electron.

---

## 7. Этапы / слайсы (Gx)

### G19.1 — Инструментация диагностики OR-D6 (корреляции freeze)

**Обязательные описания/выводы:** OR-D1, OR-D6, D-D3, D-D4, D-D5, FR1 (измеримый split вместо единственной гипотезы).

**Implementation anchors**

- `desktop/src/renderer/runtime/DesktopSessionContext.tsx` — обёртка вокруг `brokerRequest` / длительность; размер `rawTraceRows` (length), скользящее окно частоты trace (renderer).
- `desktop/src/main/registerIpc.ts` — handler `ailit:brokerRequest`, `ailit:pagGraphSlice` (уже есть события `desktop.pag_slice.*` — расширить полями `duration_ms`, bounded `payload_bytes` / `stdout_chars` per канон).
- `desktop/src/renderer/runtime/desktopSessionDiagnosticLog.ts` (или существующий compact logger) — единая точка записи compact событий без forbidden полей.

**Зависимости:** нет (первый слайс для разблокировки постмортемов).

**Anti-patterns**

- Не делать как логирование полного stdout `pag-slice` или полного массива trace в compact (**DNI** канона / OR-D6 Forbidden).
- Не делать как вывод «root cause = выключенные логи» в сообщениях диагностики (**FR2**).

**Критерии приёмки**

- В compact / dev-консоли появляются измеримые поля минимум для: `brokerRequest` (`duration_ms`, `outcome`), `rawTraceRows_length` или эквивалент, расширенные `desktop.pag_slice.completed` (`duration_ms` + bounded size), и **либо** `longtask_duration_ms` **либо** `raf_gap_ms` p95 за окно при активном trace (как в таблице канона OR-D6).
- **`npm run test`** в `desktop/`: существующие тесты проходят; при добавлении чистых хелперов — новые unit-тесты с префиксом согласованным в PR (имя в описании PR обязательно).
- Ручной сценарий §12 совпадает с каноном: после шага 2 оператор может указать значения новых полей.

**Статические проверки**

- `rg "desktop\\.pag_slice\\.(requested|completed|error)" desktop/src` — якоря событий не удалены.
- `rg "brokerRequest" desktop/src/renderer/runtime/DesktopSessionContext.tsx` — точка обёртки согласована с PR.

**Donor:** см. строку таблицы **Donor ref** для G19.1.

---

### G19.2 — Гард pair-log на `broker_connect` (D-D6)

**Обязательные описания/выводы:** D-D6, OR-D5, D-D2, FR5.

**Implementation anchors**

- `desktop/src/renderer/runtime/DesktopSessionContext.tsx` — `connectToBroker`, вызов `pairLogWriterRef.current?.logD("broker_connect", …)` (см. отчёт `desktop_stack_chat_logs_enabled_branch.md` F7).
- `desktop/src/renderer/runtime/desktopGraphPairLogWriter.ts` — опционально centralize guard (single enforcement), если выбрано в PR.

**Зависимости:** нет жёсткой; логически после **G19.1** не требуется, но рекомендуется не смешивать с большим рефактором проекции в одном PR.

**Anti-patterns**

- Не менять семантику PAG rev и шаблон предупреждений в этом слайсе.
- Не отключать trace или broker «ради экономии» (**DNI1**).

**Критерии приёмки**

- При `agentMemoryChatLogsFileTargetsEnabledRef.current !== true` нет IPC `ailit:appendDesktopGraphPairLog` из пути `broker_connect` (или доказан эквивалентный no-op без roundtrip — предпочтительно отсутствие invoke).
- `cd desktop && npx vitest run src/renderer/runtime/desktopGraphPairLogWriter.test.ts` — зелёный; при изменении контракта writer — дополнить тесты в том же файле или новом `*.test.ts` (имя в PR).

**Статические проверки**

- `rg "broker_connect" desktop/src/renderer/runtime/DesktopSessionContext.tsx` — ровно один охваченный call site или список в PR.

**Donor:** см. строку таблицы **Donor ref** для G19.2.

---

### G19.3 — Паритет yield/chunk для инкрементального PAG merge + регресс rev-текста

**Обязательные описания/выводы:** OR-D2, D-D1, D-D3, D-D7, FR3, AC1, **S-D3** (паритет с `afterFullLoad` replay).

**Implementation anchors**

- `desktop/src/renderer/runtime/pagGraphSessionStore.ts` — `PagGraphSessionTraceMerge.applyIncremental`, `applyAfterFullLoadReplayDeltasBounded`, `yieldReplayChunkBound`.
- `desktop/src/renderer/runtime/DesktopSessionContext.tsx` — `useEffect` на `rawTraceRows` (инкрементальный merge).
- `desktop/src/renderer/runtime/pagGraphRevWarningFormat.ts` — шаблон строки (не менять без ADR).

**Зависимости:** **G19.1** желателен до merge, чтобы подтвердить эффект снижения long tasks метриками; не блокирует код-ревью логики merge при отсутствии инструментации в базовой ветке (тогда PR обязан ссылаться на `verification_gap`).

**Anti-patterns**

- Не удалять catch-up логику rev после slice (**F-D14** в отчёте PAG).
- Не ослаблять дедуп предупреждений (**F-D7** отчёта PAG).

**Критерии приёмки**

- `cd desktop && npx vitest run src/renderer/runtime/pagGraphSessionStore.test.ts src/renderer/runtime/pagGraphTraceDeltas.test.ts src/renderer/runtime/loadPagGraphMerged.test.ts` — зелёные.
- Нет изменения дословного пользовательского шаблона rev mismatch без отдельного ADR (**AC1**).

**Статические проверки**

- `rg "formatPagGraphRevMismatchWarning|PAG: несоответствие graph rev" desktop/src/renderer/runtime` — ожидаемые совпадения; whitelist изменений в PR.

**Donor:** см. строку таблицы **Donor ref** для G19.3.

---

### G19.4 — Снижение нагрузки проекции чата / дедуп потока trace (**S-D4**)

**Обязательные описания/выводы:** OR-D1, D-D3, FR4, **S-D4** (O(N) на каждую строку).

**Implementation anchors**

- `desktop/src/renderer/runtime/chatTraceProjector.ts` — `projectChatTraceRows` и связанные структуры.
- `desktop/src/renderer/runtime/DesktopSessionContext.tsx` — `mergeRows`, подписка `ailit:traceRow`, батчинг (если вводится).

**Зависимости:** **G19.1** для валидации эффекта на метриках; иначе PR помечает `verification_gap` до появления метрик.

**Anti-patterns**

- Не ломать семантику «ход агента» и финальные события trace (**F-D2**, **F-D4** отчёта submit).
- Не вводить sync IPC.

**Критерии приёмки**

- `cd desktop && npx vitest run src/renderer/runtime/chatTraceProjector.test.ts` — зелёный; при добавлении батчинга — новые тесты с явными именами в PR.
- `cd desktop && npm run typecheck` — зелёный для затронутых проектов.

**Статические проверки**

- `rg "projectChatTraceRows|mergeRows" desktop/src/renderer/runtime/DesktopSessionContext.tsx desktop/src/renderer/runtime/chatTraceProjector.ts` — дифф ревьюится на асимптотику/частоту вызовов.

**Donor:** см. строку таблицы **Donor ref** для G19.4.

---

### G19.5 — Интеграция, регрессия, ручной smoke, статика репозитория

**Обязательные описания/выводы:** OR-D3, OR-D4, AC2, AC3, AC4, AC5, FR2, FR3.

**Implementation anchors**

- Весь затронутый diff `desktop/` + при cross-cutting — `desktop/src/main/registerIpc.ts`, `desktop/src/main/traceSocketPool.ts`, `desktop/src/main/pagGraphBridge.ts`.
- Канон-candidate: обновление ссылок в PR описании на `target_algorithm_draft.md` до publish.

**Зависимости:** после **G19.1**–**G19.4** по выбранному подмножеству слайсов в релизе.

**Anti-patterns**

- Не помечать e2e как passed без headless профиля (**канон**: `11_test_runner` → `blocked_by_environment`).

**Критерии приёмки**

- `cd desktop && npm run test` — полный прогон vitest после суммарных изменений релиза.
- `cd desktop && npm run lint` и `npm run typecheck` — зелёные (или явный waiver в PR с задачей follow-up — не предпочтительно).
- Ручной smoke из канона §Commands выполнен записью наблюдений (метрики OR-D6 после G19.1).
- Для Python-касаний (если слайс трогает CLI) из корня репо: `/path/to/venv/bin/python -m pytest` по затронутым модулям и `flake8` по затронутым файлам (**project-workflow**).

**Статические проверки**

- `rg "chat_logs_enabled" desktop/src/main desktop/src/renderer` — нет регрессии «отключили trace при false».

**Donor:** см. строку таблицы **Donor ref** для G19.5.

---

## 8. Зависимости между этапами (сводка)

```text
G19.1 (диагностика) ─────────┬──► G19.5
        │                  │
        ├──► G19.2 (независим по коду; рекомендовано релизить рано)
        │
        ├──► G19.3 (merge/yield + PAG регресс) ──► G19.5
        │
        └──► G19.4 (projection/batch) ─────────────► G19.5
```

---

## 9. Тесты и статика (сводный §)

| Команда | Назначение |
|---------|------------|
| `cd desktop && npm run test` | Полный `vitest run` |
| `cd desktop && npx vitest run src/renderer/runtime/chatTraceProjector.test.ts` | Проекция чата |
| `cd desktop && npx vitest run src/renderer/runtime/pagGraphSessionStore.test.ts src/renderer/runtime/pagGraphTraceDeltas.test.ts src/renderer/runtime/loadPagGraphMerged.test.ts` | PAG store / дельты / slice merge |
| `cd desktop && npx vitest run src/renderer/runtime/desktopGraphPairLogWriter.test.ts` | Pair-log writer / очередь |
| `cd desktop && npm run typecheck` | TS main/preload/renderer |
| `cd desktop && npm run lint` | ESLint |
| `rg "desktop\\.pag_slice"` / `rg "formatPagGraphRevMismatchWarning"` | Якоря контракта (см. этапы) |

Запрещённая формулировка «добавить тесты» без имени: каждый PR обязан перечислить **конкретные** файлы `*.test.ts` или новый файл с именем в описании.

---

## 10. Пользовательские сценарии

Сценарии **happy / partial-freeze / failure** заданы в канон-candidate §Examples (`target_algorithm_draft.md`). Для плана:

- **Happy:** короткий запрос, быстрый broker, нет rev mismatch; окно отзывчиво.
- **Partial / freeze:** `chat_logs_enabled: false`, длинный trace; файлы chat_logs не растут; оператор собирает ≥2 метрики OR-D6 (**после G19.1**); заключение без «только логи».
- **Failure:** rev mismatch — жёлтая полоса с каноническим текстом; broker timeout — ошибка по правилам сессии; тяжёлый merged — отдельное предупреждение.

---

## 11. Config source of truth

| Ключ / настройка | SoT | Примечание |
|------------------|-----|------------|
| `memory.debug.chat_logs_enabled` | `~/.ailit/agent-memory/config.yaml` (чтение в main `readAgentMemoryChatLogsEnabled`) | Renderer — зеркало при старте через `ailit:agentMemoryChatLogsRoot`; live-refresh не контракт |
| Env overrides тестов | `tests/conftest.py` autouse | Не использовать реальный `~/.ailit` в pytest |

---

## 12. Observability

Источник полей — канон §Observability OR-D6 (`target_algorithm_draft.md`). Минимум для закрытия **G19.1**: расширить существующие `desktop.pag_slice.*` и добавить измерения `brokerRequest`, длины trace, renderer frame gap/longtask, без forbidden payload.

**n/a:** нет — для этого workflow observability обязательна.

---

## 13. Gaps (таблица)

| ID | Тип (taxonomy human-comm) | Описание | Владелец слайса |
|----|---------------------------|----------|-----------------|
| G-NB1 | `verification_gap` | Доли broker vs renderer vs main не измерены в репо до G19.1 | G19.1 |
| G-NB2 | `implementation_backlog` | `buildAgentDialogueMessages` / `deriveAgentLinkKeysFromTrace` — асимптотика не разобрана построчно | вне минимального scope; backlog |
| G-NB3 | `verification_gap` | Версии Electron/React и batching burst trace не зафиксированы | документировать при инцидентах, не блокер плана |

---

## 14. Инструкции команде разработки: donor

Идеи из внешних репозиториев **не** использовались (**OR-D7**). После публикации канона команда читает **`context/algorithms/desktop-stack/donors/INDEX.md`** (когда файл появится у `100`/`13`); до publish — раздел draft «Будущий donors/INDEX.md». Не копировать код donor; только паттерны из таблицы Donor ref, если появятся строки с `Finding ID ≠ none`.

---

## 15. Donor ref (минимальная таблица)

| Этап / слайс | Donor report (path) | Finding ID | Donor path | Строки | Kind | Якорь в текущем repo (путь / символ) | Копировать |
|--------------|---------------------|------------|------------|--------|------|--------------------------------------|------------|
| G19.1–G19.5 | — | none | — | — | n/a | — | donor research explicitly excluded by user |

---

## 16. Definition of Done / трассировка «слайс → канон»

**Два слоя трассировки (CHK-3 / W14 п.3):** (1) уже опубликованные файлы под [`context/algorithms/desktop/`](../context/algorithms/desktop/INDEX.md) и смежный материал — только разрешимые markdown-ссылки; (2) контракт Cycle D (чат, freeze, PAG rev, OR-D6) до появления пакета `desktop-stack` — handoff на [`target_algorithm_draft.md`](../context/artifacts/target_doc/target_algorithm_draft.md). Пакет `context/algorithms/desktop-stack/**` создаётся при publish черновика канона после user OK; до этого момента колонка «desktop-stack» = *n/a (путь отсутствует)*, без ссылок на несуществующие `.md`.

| Слайс | Опубликованный канон (`context/algorithms/**`, существующие пути) | Draft / будущий desktop-stack |
|-------|-------------------------------------------------------------------|-------------------------------|
| G19.1 | Навигация и границы desktop: [`context/algorithms/desktop/INDEX.md`](../context/algorithms/desktop/INDEX.md); observability/trace: [`context/algorithms/desktop/realtime-graph-client.md`](../context/algorithms/desktop/realtime-graph-client.md) | [`target_algorithm_draft.md`](../context/artifacts/target_doc/target_algorithm_draft.md) — §Observability OR-D6, §Failure FR1 |
| G19.2 | Те же [`INDEX.md`](../context/algorithms/desktop/INDEX.md), [`realtime-graph-client.md`](../context/algorithms/desktop/realtime-graph-client.md) (границы UI / IPC) | Draft — §Current Reality (`chat_logs_enabled`), §Failure FR5 |
| G19.3 | PAG / 3dmvc: [`context/algorithms/desktop/graph-3dmvc.md`](../context/algorithms/desktop/graph-3dmvc.md); клиент: [`realtime-graph-client.md`](../context/algorithms/desktop/realtime-graph-client.md) | Draft — §Target Flow п.2–4, §Examples 3a/3c, §Do Not Implement DNI1 |
| G19.4 | Производительность проекции / граф: [`graph-3dmvc.md`](../context/algorithms/desktop/graph-3dmvc.md), [`realtime-graph-client.md`](../context/algorithms/desktop/realtime-graph-client.md) | Draft — §Current Reality (O(N) projection), §Failure FR4 |
| G19.5 | Сводная приёмка desktop-пакета: [`INDEX.md`](../context/algorithms/desktop/INDEX.md); при касании протокола памяти на границе — [`context/algorithms/agent-memory/failure-retry-observability.md`](../context/algorithms/agent-memory/failure-retry-observability.md) (общий контракт логов, без дублирования Cycle D) | Draft — §Acceptance Criteria, §How start-feature / start-fix Must Use This; после publish — *обновить строки на реальные `desktop-stack/*.md`* |

---

## 17. Self-review плана (workflow quality bar)

| Критерий из `project-workflow.mdc` | Статус | Примечание |
|-------------------------------------|--------|------------|
| Каждый нормативный id из §4 и **DNI1/DNI2/DNI4** из §2.3 имеет этап в §5 | ok | |
| У каждого Gx есть «Обязательные описания/выводы» | ok | |
| Implementation anchors указаны | ok | `desktop/` + main |
| Anti-patterns per stage | ok | |
| Exact tests/commands (не «добавить тесты») | ok | §9, этапы |
| Dependencies между этапами | ok | §8 |
| Donor paths только в таблице §15 | ok | одна строка `none` |
| Config SoT / observability | ok | §11–12 |
| Нет противоречия `verification.md` | ok | согласовано с approved **105** |
| Gaps с типами taxonomy | ok | §13 |

---

## 18. Message для `107` / `100`

План готов к машинному ревью **`107_implementation_plan_reviewer`** (`context/artifacts/target_doc/plan_review_latest.json`). Блокирующих противоречий с **`verification.md`** не заявлено.
