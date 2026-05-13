# Desktop stack: чат, freeze, PAG rev и диагностика

> **Аннотация:** канон для сценария «отправка в чат → ощущаемый freeze UI при `memory.debug.chat_logs_enabled: false` → предупреждение о несоответствии rev PAG». Фиксируются проверяемая картина по коду, целевое поведение, границы Desktop vs runtime, диагностический контракт и запрет сводить причину только к отключению chat_logs.

## Статус

`approved` — явное подтверждение пользователя в чате Cursor (**2026-05-13**, форма «ок» по whitelist §Approval в `project-human-communication.mdc`).

## Навигация по пакету

| Файл | Для кого | Содержание |
|------|-----------|------------|
| Этот `INDEX.md` | Авторы фич по чату, trace, PAG rev, IPC | Цель, scope, current reality, target flow, примеры, observability OR-D6, acceptance, DNI. |
| [`glossary.md`](glossary.md) | Все читатели пакета | Расшифровки SoT, PAG, OR-D*, FR*. |
| [`donors/INDEX.md`](donors/INDEX.md) | Авторы target-doc и фич | Taken / Rejected / Not researched (для этого пакета — только Not researched). |

## Связанные каноны и планы

- Граф памяти и 3dmvc (отдельный scope): [`../desktop/INDEX.md`](../desktop/INDEX.md).
- План внедрения (не часть канона SoT поведения): [`../../../plan/19-desktop-stack-chat-freeze-pag-trace.md`](../../../plan/19-desktop-stack-chat-freeze-pag-trace.md).

## Исходная цель (в пересказе)

Пользователь наблюдает в ailit Desktop полное или сильное зависание UI при отправке сообщения в чат при выключенных файловых логах чата (`memory.debug.chat_logs_enabled: false`). Позже появляется предупреждение о несоответствии «номеров» между ожидаемым и фактическим rev графа PAG. После завершения AgentWork интерфейс снова отзывчив. Канон задаёт узкое множество причин с критериями отличия, границы ответственности Desktop vs runtime и основу для плана внедрения под `plan/`, без опоры на donor research.

## Why This Exists

Оператору и следующим агентам нужен **один** текст, который:

- разделяет симптомы «заблокирован ввод чата» и «долгий кадр / event loop»;
- связывает предупреждение PAG с **graph rev по namespace**, а не с порядковым номером строки чата;
- запрещает вывод «freeze только потому что логи выключены» без проверки trace/PAG/broker путей;
- задаёт **измеримый** диагностический контракт, если единственную причину нельзя доказать статическим чтением кода.

## Связь с исходной постановкой

| ID | Формулировка требования (суть, развёрнуто) |
|----|--------------------------------------------|
| **OR-D1** | Сузить причину зависания UI при submit: не утверждать единственный root cause без измерения или без явной ветки диагностики; не сводить к «только логи». |
| **OR-D2** | Связать симптом с PAG trace/rev: точные строки предупреждений, семантика `expectedNextRev` vs `traceRev`, действие Refresh. |
| **OR-D3** | Границы **Desktop (renderer / main Electron / IPC)** vs **subprocess CLI `ailit`** и broker runtime: кто владеет исправлением какого класса проблем. |
| **OR-D4** | Дать основу для плана внедрения: слайсы и приёмка трассируются на этот канон и на [`plan/19-desktop-stack-chat-freeze-pag-trace.md`](../../../plan/19-desktop-stack-chat-freeze-pag-trace.md) (owner плана — роль `106_implementation_plan_author`). |
| **OR-D5** | Зафиксировать SoT флага `chat_logs_enabled`, ветку `false`, и что она **не** отключает trace, broker, PAG slice, инкрементальный merge. |
| **OR-D6** | Диагностический контракт при многозначной причине: события, счётчики, корреляция main vs renderer. |
| **OR-D7** | Donor research **запрещён**; раздел donors — явно «Not researched». |

## Scope

### In scope

- Путь отправки сообщения: синхронный optimistic update, затем `await brokerRequest` (IPC, таймаут до 30 s на main).
- Live trace: построчные события → `mergeRows` → рост `rawTraceRows` → полная проекция чата O(N) на изменение и инкрементальный PAG merge без chunk budget (контраст с `afterFullLoad` replay).
- Ветка `chat_logs_enabled: false`: что отключается на диске, что остаётся активным; известный IPC roundtrip `broker_connect` без записи файла.
- PAG: rev mismatch warning (дословный шаблон), «тяжёлый merged» warning, `loadState` остаётся не `error` для rev mismatch.
- Main IPC hotspots: `pag-slice`, полное чтение durable trace, полное чтение memory journal, частый `JSON.parse` на live trace, `brokerJsonRequest`.
- Диагностический контракт OR-D6: таблица метрик в § Observability; **основные строки compact-логов реализованы в продукте** (слайс G19.1, см. «Где в коде» в том же разделе). Постмортем по-прежнему не закрывает единственный root cause без корреляции измерений.

### Out of scope

- Donor repositories и любые выводы из внешних кодовых баз (OR-D7).
- Полный rewrite протокола broker или смена транспорта IPC (только указание границы и риска).
- Утверждение **единственного** численного root cause без профилирования (запрещено acceptance ниже).
- Пакет [`../desktop/`](../desktop/INDEX.md) (Cycle C, graph-3dmvc): смешивать только через явный scope divider; там — алгоритмы 3D View; здесь — стек чата, trace, PAG slice и IPC.

## Current Reality Summary

Сводка по исследованию кода каталога `desktop/` (Cycle D): модули `DesktopSessionContext`, `registerIpc`, `traceSocketPool`, `pagGraphSessionStore`, форматы предупреждений PAG, `pagGraphBridge`.

**Submit и «ход агента».** Обработчик UI вызывает `sendUserPrompt` через `void`: сначала синхронно обновляются optimistic строки, затем async continuation ждёт `brokerRequest` (единственный обязательный await в этом пути; таймаут 30 s на стороне main). Флаг «идёт ход агента» для UI — логическое ИЛИ: проекция trace считает активный ход **или** есть optimistic строки. Снятие «хода» привязано к **нормализованным событиям trace** (`assistant_final`, `turn_completed`, `turn_failed`, `session.cancelled`, …), а не к завершению процесса AgentWork в ОС.

**Отличие «gated input» от «freeze окна».** Повторная отправка с клавиатуры блокируется при активном ходе; кнопка отправки меняется на Stop. Это **не** то же самое, что полная неотзывчивость окна: последняя требует либо долгого await IPC, либо долгой синхронной работы на main thread renderer или перегрузки main process Electron.

**Live trace и renderer.** Main рассылает **по одной** строке trace на окно. Renderer: `mergeRows` синхронно дедуплицирует и копирует массив; на каждое изменение `rawTraceRows` в render-фазе `useMemo` заново прогоняет `projectChatTraceRows` по **всему N** (O(N) на каждое добавление). При готовом PAG snapshot `useEffect` на `rawTraceRows` вызывает **`PagGraphSessionTraceMerge.applyIncremental`** синхронно, **без** chunk/microtask budget, в отличие от `afterFullLoad` replay (`applyAfterFullLoadReplayDeltasBounded` + `yieldReplayChunkBound`). Общий фактор нагрузки — **общий main thread renderer** и общий state trace/PAG для смонтированных виджетов; отдельного флага «freeze чата» из 3D `freezeGraphAtCenteredCoordinates` для submit нет.

**`chat_logs_enabled`.** SoT: файл конфигурации agent-memory на машине пользователя (`memory.debug.chat_logs_enabled`), чтение и coerce default **только в main** с кэшем по `mtimeMs`; fail-open при ошибке чтения — `true`. Renderer получает значение **один раз** при старте через IPC `ailit:agentMemoryChatLogsRoot`; UI просит перезапуск Desktop при смене yaml (live-refresh в renderer **не** задокументирован как контракт). При `false`: main handlers `ensureChatLogSessionDir` и `appendDesktopGraphPairLog` возвращают `{ ok: true, skipped: true }` **до** FS; trace subscribe, `appendTraceRow`, `brokerRequest`, `ailit:pagGraphSlice` и др. **не** читают флаг. Renderer гардит file-side пути pair-log и graph debug; **исключение:** при подключении к broker вызывается `logD("broker_connect", …)` без проверки флага — возможен IPC roundtrip, main по-прежнему не пишет файлы.

**PAG rev warning (дословный шаблон для новых сообщений).** Текст формируется функцией `formatPagGraphRevMismatchWarning` (модуль предупреждений PAG):

```text
PAG: несоответствие graph rev (ожидается <expectedNextRev>, в trace <traceRev>) для «<namespace>». Выполните Refresh.
```

Символ закрывающей кавычки French в namespace в реализации экранируется (zero-width перед `»`), чтобы не ломать разбор; для **новых** строк namespace всегда присутствует; legacy regex без namespace — **только** для разбора старых строк.

**Предупреждение о «тяжёлом» merged (не rev).** При превышении лимита узлов в merged добавляется строка вида:

```text
PAG: в merged <N> нод (><лимит>). Срез тяжёлый; используйте Refresh при необходимости.
```

(конкретные числа и лимит — из констант `MEM3D_PAG_MAX_NODES` / кода). В 3D UI rev mismatch и прочие `warnings` показываются жёлтой полосой при `loadState === "ready"`; это **не** переводит `loadState` в `error`.

**Семантика чисел.** `expectedNextRev` в предупреждении = `last + 1`, где `last` — последний применённый rev по namespace в памяти store; `traceRev` = поле `rev` из trace-дельты. Несоответствие: `last > 0 && delta.rev !== last + 1`. Это **monotonic graph rev по namespace**, не порядковый номер строки чата. Есть catch-up после slice, чтобы не показывать ложный mismatch сразу после загрузки среза.

**Main и subprocess.** Нет `sendSync`/`invokeSync` в каталоге Desktop; коммуникация async `invoke`/`handle`. Тяжёлые места по коду (оценка без профиля): (1) `runPagGraphSlice` — `execFile` CLI `ailit memory pag-slice` и `JSON.parse` большого stdout (до 96 MiB buffer в bridge); (2) `memoryJournalRead` — полный `readFile` + `JSON.parse` каждой строки; (3) `readDurableTraceRows` — полный trace JSONL + parse; плюс live `traceSocketPool` с `JSON.parse` на main и `brokerJsonRequest` до 30 s ожидания первой строки.

## Target Behavior

1. **Человеку:** при отправке в чат UI остаётся в предсказуемом состоянии: либо виден прогресс/ответ, либо понятная блокировка ввода по правилам «ход агента», либо явная ошибка/таймаут broker — без бесконечного «молчания» без observability-причин.
2. **Диагностике:** при симптоме «всё окно зависло» команда разработки **обязана** отделить измеримые вклады: длительность `brokerRequest`, частота и размер live trace, длительность PAG slice IPC, длину `rawTraceRows`, long task / rAF gap на renderer — и **не** утверждать единственную причину без этих измерений.
3. **PAG:** при расхождении rev пользователь видит **ровно** канонический текст предупреждения выше; действие «Refresh» остаётся ожидаемым UX-ответом (как в текущем UI), пока канон по продукту не изменён отдельным решением.
4. **`chat_logs_enabled: false`:** файлы chat_logs и session dir **не** растут; trace, broker, PAG остаются активными; freeze в этом режиме **не** объясняется только отключением записи логов.

## Target Flow

1. Пользователь отправляет сообщение в чат. Renderer выполняет валидацию, optimistic update, затем ожидает ACK от broker через IPC (`brokerRequest`).
2. Параллельно (независимо от ветки `chat_logs_enabled`) main и renderer обрабатывают live trace: строки попадают в `rawTraceRows`, пересчитывается проекция чата, при готовом PAG — инкрементальный merge.
3. Если граф PAG загружается или обновляется срезом, renderer инициирует серию `pagGraphSlice` IPC; main запускает subprocess `ailit memory pag-slice` и парсит JSON ответа.
4. При применении дельт PAG из trace store сравнивается ожидаемый следующий rev и `rev` дельты; при нарушении монотонности добавляется warning с каноническим текстом; UI показывает жёлтую полосу, `loadState` для rev mismatch **не** обязан становиться `error`.
5. Завершение «хода агента» в UI наступает по финальным событиям trace, после чего снимается блокировка повторной отправки (если не включена другая фаза).
6. При подозрении на freeze оператор собирает минимальный набор метрик из раздела Observability (счётчики, длительности, размеры) и сопоставляет с ветками «renderer O(N) + incremental merge», «main pag-slice / journal / durable trace», «broker await».

## Examples

### Example 1: Happy Path

Пользователь с включёнными или выключенными chat_logs (не важно для broker/trace) отправляет короткий запрос в чат. Broker отвечает в пределах сотен миллисекунд. Live trace приходит умеренным потоком. `rawTraceRows` растёт, проекция чата пересчитывается, PAG дельты монотонны: **нет** строки `PAG: несоответствие graph rev …`. Ввод после `assistant_final` / `turn_completed` снова разрешён. Окно остаётся отзывчивым (меню, смена фокуса работают).

**Проверка:** в компактном логе/консоли нет непрерывного роста предупреждений rev для того же namespace без смены сессии; нет превышения порога «тяжёлый merged» для текущего объёма данных.

### Example 2: Partial / «Freeze» Without Single Root Cause

Пользователь с `memory.debug.chat_logs_enabled: false` отправляет запрос в большой сессии. Окно **не отвечает** на ввод несколько секунд (пользователь описывает как «полный freeze»). Файлы `ailit-desktop-*.log` **не** растут (ветка `skipped` на main). При этом в trace идёт высокочастотный поток строк; в консоли или профиле по строкам OR-D6 видно либо длинные кадры renderer после каждого `mergeRows`, либо очередь тяжёлых IPC на main (`pag-slice`, чтение большого JSONL), либо `brokerRequest` близко к таймауту.

**Проверка:** диагностический отчёт содержит **корреляцию** хотя бы двух метрик (например, trace rows/s и p95 длительности кадра renderer, или длительность `pagGraphSlice` и overlap с временем freeze). Документ или постмортем **не** заключает «причина — выключенные логи» без показа активных путей trace/PAG/broker.

### Example 3: Failure / Blocked Path — Rev Mismatch, Broker Timeout, Oversized Graph

**3a. Rev mismatch.** В trace приходит дельта PAG с `rev`, не равным `last+1` для namespace при `last > 0`. Пользователь видит жёлтую полосу с текстом **ровно**:

`PAG: несоответствие graph rev (ожидается …, в trace …) для «…». Выполните Refresh.`

`loadState` остаётся в режиме готовности (не ошибка из-за rev). Пользователь выполняет Refresh графа по подсказке.

**3b. Broker timeout.** `brokerRequest` не получает первую строку ответа до 30 s. UI показывает ошибку транспорта / таймаута по правилам сессии; optimistic строка снимается или помечается ошибкой согласно коду.

**3c. Тяжёлый merged.** Количество узлов в merged превышает лимит; появляется предупреждение с префиксом `PAG:` про тяжёлый срез и Refresh. Это **отдельный** UX-поток от rev mismatch.

## Inputs

| Input | Owner | Required | Notes |
|-------|--------|----------|-------|
| Пользовательский текст сообщения | Human | required | |
| `brokerEndpoint`, workspace, session ids | Desktop session | required | |
| Live trace rows (JSON lines) | Broker → main → renderer | required для активной сессии | Построчная доставка. |
| PAG SQLite / slice params | PAG store + CLI | required когда граф активен | Через `pagGraphSlice`. |
| `memory.debug.chat_logs_enabled` | agent-memory yaml (main read) | required boolean | Default `true`; renderer mirror один раз при старте. |

## Outputs

| Output | Consumer | Notes |
|--------|----------|-------|
| Состояние чата (optimistic + projected lines) | Chat UI | |
| `rawTraceRows` | Проекция, PAG merge, диалог | Рост с длиной сессии. |
| PAG snapshot + `warnings` | 2D/3D graph UI | Rev mismatch; large merged. |
| IPC результаты `skipped: true` | Pair-log path | При `chat_logs_enabled: false` — без записи на диск. |

## State Lifecycle

- **Optimistic lines:** живут от `sendUserPrompt` до совпадения с trace или ошибки.
- **`rawTraceRows`:** монотонно растут в пределах сессии; сброс при смене сессии (см. код сессии в `desktop/`).
- **PAG `graphRevByNamespace`:** обновляется при slice и при применении дельт; предупреждения дедуплицируются и могут reconciliate при следующих проходах.
- **Флаг chat_logs в renderer:** фиксируется при старте; смена yaml без рестарта Desktop ведёт к потенциальному рассинхрону зеркала renderer и main cache — **main остаётся финальным gate** для записи файлов.

## Commands

### Manual smoke (человек)

1. Установить `memory.debug.chat_logs_enabled: false` в agent-memory config yaml (SoT на машине пользователя), **перезапустить** Desktop (контракт зеркала renderer).
2. Открыть чат в типичной сессии с длинным trace; отправить сообщение.
3. Наблюдать: рост файлов в chat_logs **отсутствует**; при этом trace/PAG/broker остаются активными (симптом freeze **не** доказывается отсутствием файлов).
4. При появлении жёлтой полосы PAG — убедиться, что текст соответствует канону rev mismatch; выполнить Refresh и зафиксировать, исчезло ли предупреждение согласно правилам reconcile.

**Expected:** воспроизводимость сценария с корреляцией по строкам OR-D6 из консоли (измерения G19.1 в `desktop/`) или зафиксированный blocker окружения (`blocked_by_environment`), если профилирование невозможно.

### Automated / dev (reference)

- Существующие unit-тесты в дереве `desktop/`: `chatTraceProjector.test.ts`, `pagGraphSessionStore.test.ts`, `pagGraphTraceDeltas.test.ts`, `loadPagGraphMerged.test.ts`.
- OR-D6 (G19.1): `desktopSessionDiagnosticLog.test.ts`, `desktopSessionTraceThroughputWindow.test.ts` (форматтеры broker/trace и окно throughput).
- **Отсутствует** по фактам исследования: интеграционный тест «sendUserPrompt + длинный trace + freeze метрика» — не требовать как уже существующий в каноне.

## Observability и диагностический контракт (OR-D6)

### Технический контракт

**Обязательные корреляции для локализации freeze (контракт OR-D6):** ниже — нормативные поля; **в коде Desktop** строки `event=…` для первых трёх строк и бюджета кадра эмитятся в G19.1 (см. «Где в коде»). Счётчик `pairlog_ipc_calls_total` из таблицы **ещё не** задан как отдельное compact-событие.

| Метрика / событие | Где измерять | Required fields / правило |
|-------------------|--------------|---------------------------|
| Длительность `brokerRequest` (IPC roundtrip) | Renderer → main | `duration_ms` (number), `chat_id` или session key (string), `outcome` enum: `ok\|timeout\|error` |
| Счётчик live trace rows | Renderer | `trace_rows_per_sec` скользящее окно; `rawTraceRows_length` (integer) на событие или раз в секунду |
| Длительность / размер `pagGraphSlice` | Main (и при необходимости renderer await) | Compact `desktop.pag_slice.requested\|completed\|error`: `duration_ms`, `payload_bytes` **bounded** (без полного JSON в лог); скаляр размера stdout — тип `stdoutByteLength` в `pagGraphBridge`, не тело stdout |
| Pair-log IPC | Renderer/main | При `chat_logs_enabled: false`: логировать факт `skipped: true` **не** обязательно для каждого вызова; для диагностики `broker_connect` — один счётчик `pairlog_ipc_calls_total` с breakdown `skipped_true` |
| Renderer frame budget | Renderer | `longtask_duration_ms` (если доступно через PerformanceObserver) **или** `raf_gap_ms` p95 за окно во время активного trace |

**Forbidden в compact логах:** полный stdout `pag-slice`; полное содержимое `rawTraceRows`; raw prompts; секреты.

**Default для постмортема:** даже при наличии строк OR-D6 в консоли документ **обязан** фиксировать корреляцию хотя бы двух сигналов (см. примеры §Examples) и помечать `verification_gap`, если нет живого smoke (ручной сценарий Commands) или полного repo-gate без отдельного прогона.

**Граница с D-OBS-1:** whitelist в [`../../proto/runtime-event-contract.md`](../../proto/runtime-event-contract.md) описывает compact-топики журнала **AgentWork ↔ AgentMemory**; строки `desktop.session.*` / `desktop.pag_slice.*` идут в **console** main/renderer (FC-3 в `desktopSessionDiagnosticLog.ts`), это отдельный канал.

### Где в коде (слайс G19.1)

- Renderer: `desktop/src/renderer/runtime/desktopSessionDiagnosticLog.ts` — `formatDesktopSessionBrokerRequestLine`, `formatDesktopSessionTraceMergeLine`, `emitDesktopSessionCompactInfo`; константы `DESKTOP_SESSION_BROKER_REQUEST_EVENT`, `DESKTOP_SESSION_TRACE_MERGE_EVENT`; скользящее окно `desktopSessionTraceThroughputWindow.ts`; бюджет кадра `desktopSessionRendererBudgetTelemetry.ts`; обёртка и throttle в `DesktopSessionContext.tsx` (`invokeBrokerRequestObserved`, merge trace).
- Main: `desktop/src/main/registerIpc.ts` — `logDesktopPagSliceRequested`, `logDesktopPagSliceCompleted`, `logDesktopPagSliceError` (`event=desktop.pag_slice.*`).
- CLI bridge: `desktop/src/main/pagGraphBridge.ts` — `runPagGraphSliceWithStdoutMetrics`, поле `stdoutByteLength`.

### Уже существующие якоря (по коду `desktop/`, обновлено)

- Main: `desktop.pag_slice.requested`, `completed`, `error` (поля см. `registerIpc.ts`).
- Renderer: `desktop.session.broker_request`, `desktop.session.trace_merge` (поля см. `desktopSessionDiagnosticLog.ts`).
- Pair-log: `desktop.pairlog.append`, `desktop.pairlog.append_failed` (при успешной записи; при `skipped` — тихий путь).
- PAG merge debug (renderer): события вида `merge_after_incremental`, `merge_pag_delta`, replay start/end — **активны только когда включён путь graph debug / pair writes**; при `chat_logs_enabled: false` часть каналов отключена, trace через `appendTraceRow` остаётся.

## Failure And Retry Rules

### FR1: Единственный root cause без измерения

**Forbidden:** утверждать в документации релиза или постмортеме одну причину freeze (например, «только PAG» или «только broker») без таблицы метрик OR-D6 или без воспроизведения с хотя бы двумя согласованными сигналами (например, `brokerRequest_duration` max + `rawTraceRows_length` плюс скрин long task).

### FR2: Приписывание freeze ветке `chat_logs_enabled: false`

**Forbidden:** использовать отключение файловых логов как **достаточное** объяснение зависания UI. **Required:** явно перечислить остающиеся активные пути (trace, broker, PAG slice, incremental merge, durable trace read на connect).

### FR3: Путаница rev с номером сообщения в чате

**Forbidden:** описывать числа в предупреждении PAG как «номер сообщения чата». **Required:** формулировка «monotonic graph rev по namespace».

### FR4: Broker await vs renderer jank

**Required:** в любом incident write-up разделять «await `brokerRequest` до 30 s» и «длинный синхронный кадр renderer из-за O(N) projection / `applyIncremental`».

### FR5: `broker_connect` pair-log при `false`

**Current fact:** один call site вызывает pair-log writer без проверки флага; main возвращает `skipped: true`, диск не растёт. **Канон:** это **не** доказательство записи логов и **не** опровержение FR2; сокращение лишнего IPC — допустимый slice плана (низкий blast radius), не обязательная часть минимального диагностического набора.

## Acceptance Criteria

1. Любой PR, который меняет submit/trace/PAG rev UX, содержит ссылку на этот канон и не нарушает дословный шаблон rev mismatch для новых строк (или явный ADR на изменение копирайта).
2. Документация и постмортемы **не** утверждают «freeze из-за `chat_logs_enabled: false` alone» (формулировка нарушения — fail review).
3. Диагностический чеклист OR-D6 отражён в плане внедрения хотя бы как задачи с измеримым done (метрика или событие с полями из таблицы выше).
4. Ручной smoke из раздела Commands воспроизводим человеком с доступом к Desktop и тестовой сессией.
5. Разделение ownership Desktop vs CLI: изменения в `ailit memory pag-slice` трактуются как **runtime/CLI**, изменения в chunking replay / incremental merge — как **renderer Desktop**, изменения в `brokerJsonRequest` timeout/ошибках — как **main Desktop + broker contract**.

## Do Not Implement This As

- **DNI1:** «Выключим trace при `chat_logs_enabled: false`, чтобы не было нагрузки» без отдельного продукта decision — ломает наблюдаемость AgentWork.
- **DNI2:** Синхронный `invokeSync` для «ускорения» — запрещено архитектурой Desktop (нет в текущем коде; не вводить).
- **DNI3:** Публикация канона с обязательными для читателя ссылками на временные артефакты pipeline (каталог артефактов target-doc и аналоги) — запрещено (**CR4** в `.cursor/rules/start-research.mdc`).
- **DNI4:** Смешивание этого канона с пакетом [`../desktop/`](../desktop/INDEX.md) (graph-3dmvc, orphan policy) без явного заголовка «out of scope / ссылка только по необходимости».

## How start-feature / start-fix Must Use This

- **`02_analyst`** читает этот документ перед `technical_specification.md`, если задача касается Desktop чата, trace, PAG rev или ветки `chat_logs_enabled`.
- **`06_planner`** трассирует задачи на Target Flow и Acceptance Criteria; **последовательность слайсов и файл плана** ведутся в [`plan/19-desktop-stack-chat-freeze-pag-trace.md`](../../../plan/19-desktop-stack-chat-freeze-pag-trace.md), не дублируются полным планом внутри канона.
- **`08_developer`** реализует слайсы без изменения шаблона предупреждения без явного согласования.
- **`11_test_runner`** помечает команды как `blocked_by_environment`, если нет headless Electron профиля; не подменяет отсутствие e2e выдуманным «pass».
- **`13_tech_writer`** при расхождении кода и канона — либо код-фикс, либо осознанное изменение канона по отдельному согласованию.

## Self-check (CR7)

| Было | Стало |
|------|--------|
| «Ключевой алгоритм обеспечивает прозрачную синхронизацию и устойчивую деградацию.» | «При расхождении rev UI показывает строку `PAG: несоответствие graph rev …`; `loadState` не переходит в `error` только из-за rev mismatch (код PAG UI).» |
| «Система корректно обрабатывает ошибки и избегает зависаний.» | «Единственный обязательный await в submit-path — `brokerRequest` до 30 s; длинный кадр renderer идёт от O(N) `projectChatTraceRows` и синхронного `applyIncremental`; причина freeze не доказывается без метрик OR-D6.» |

## Что проверить человеку

1. Совпадает ли пересказ цели с тем, что нужно закрепить для сценария freeze + PAG.
2. Достаточно ли жёстко запрещено объяснение «всё из-за выключенных логов».
3. Понятны ли три примера (happy / partial-freeze / failure) и отдельно rev vs «тяжёлый merged».
4. Готовы ли вы утвердить диагностический контракт OR-D6 как обязательный follow-up в плане 19 без требования немедленной реализации всех метрик в коде до approval канона.
