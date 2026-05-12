# Целевой поток выполнения AgentMemory в рантайме (Runtime flow)

**Аннотация:** порядок от приёма `memory.query_context` до ответа и журнала: кто вызывает pipeline, сколько раз за RPC вызывается планер, где живёт continuation для `ailit memory init`, какие статусы и поле `runtime_trace` в `agent_memory_result.v1` даёт код сейчас. Детали протокола runtime→LLM — в [`llm-commands.md`](llm-commands.md); матрица ошибок и FR-no-progress — в [`failure-retry-observability.md`](failure-retry-observability.md).

Сокращения: **W14**, **PAG**, **KB** — см. [`glossary.md`](glossary.md).

## Связь с исходной постановкой

| ID | Формулировка требования (суть) |
|----|--------------------------------|
| OR-002 | AgentMemory обслуживает NL-запросы через брокер; статусы `complete` и `partial` или `blocked` только при недоступности API LLM или после ограниченных повторов, а не при каждой мелкой ошибке контента. **Норматив ниже; фактические условия `blocked` в коде шире — см. раздел «Текущая реализация».** |
| OR-005 | Целевая цепочка: приём запроса → проверка БД → шаги обработки → раунды LLM → выбор среза → обход → узлы и связи → сводка → завершение → при необходимости ограниченный partial. |
| OR-012 | Итоговый конверт результата `agent_memory_result.v1` согласован с этим потоком и с [`external-protocol.md`](external-protocol.md). Поле `runtime_trace` в v1 — **компактное поле конверта**, см. D-RUNTIME-TRACE-1 в «Текущая реализация». |

## Текущая реализация

Источник проверки при расхождении с нормативом: модули под `tools/agent_core/runtime/` — `subprocess_agents/memory_agent.py`, `agent_memory_query_pipeline.py`, `memory_init_orchestrator.py`, `agent_memory_result_v1.py`, `agent_memory_result_assembly.py`, `agent_memory_terminal_outcomes.py`.

### Entrypoints и один `run()` на RPC (F-P1, F-P2)

- **F-P1:** Продуктовый путь `memory.query_context`: `AgentMemoryWorker.handle` создаёт `AgentMemoryQueryPipeline` и вызывает `run` **ровно один раз** за обработку RPC; других production-вызовов `AgentMemoryQueryPipeline.run` вне worker и тестов нет.
- **F-P2:** CLI `ailit memory init` через `MemoryInitOrchestrator` отправляет тот же `service: memory.query_context` с `memory_init: True` в тот же `handle`. **Многораундовость init** — цикл continuation **вне** `AgentMemoryQueryPipeline.run` (оркестратор снова вызывает `worker.handle`), а не внутренний цикл второго `run()` в одном RPC.

### Один основной вызов планера и repair (F-P3)

- В одном `run()` — **один** основной вызов планера (`ChatProvider.complete` для команды планера).
- После `W14CommandParseError` — **до одного** repair-плана (`_repair_w14_command_output`), если разрешает gate `_should_repair_w14_error` (для части текстов ошибки repair **запрещён**).
- Отдельные repair-ветки для подкоманд **`summarize_c` / `summarize_b`** (`_repair_summarize_subcommand_w14_output` и связанные вызовы).
- **Второго** раунда `plan_traversal` «планер снова планер» внутри того же `run()` **нет**; исключение из `pl.run` после вызова провайдера **не перехватывается** внутри `run` и уходит наверх.

### `no_progress` / `cap_exceeded` как наблюдаемость partial (F-P4)

- `w14_intermediate_runtime_partial_reasons` добавляет в tuple причин **`no_progress`** или **`cap_exceeded`** на терминальном пути после промежуточного `plan_traversal`; это попадает в `runtime_partial_reasons` результата pipeline и далее в v1 через `extra_runtime_partial_reasons`.
- Это **наблюдаемость** partial, а не отдельный «abort второго планера внутри run»: второго планерского раунда в одном `run()` нет по определению (F-P3).

### Семантика `blocked` в `am_v1_status` и пути без полного успешного envelope (F-P5, F-P6) — D-BLOCKED-1

- **F-P5 (шире OR-002):** Ветка `finish_decision` и сборка результатов дают **`blocked`**, если пусты `selected_results`, нет валидных `results` после сборки, либо при полном отказе assembly при отклонённых путях — не только «LLM недоступен».
- **F-P6:** Неперехваченное исключение из `pl.run` пробрасывается из pipeline. Для **memory init** `MemoryInitOrchestrator` может завершить фазу как пользовательский **`blocked`** с `reason_short=runtime_error` и **non-zero** exit — это путь **вне** успешного envelope с полным `agent_memory_result` в том же round.
- **Норматив OR-002** в разделе «Целевое поведение» сохраняется как **цель**; расхождение с кодом помечено здесь явно. Снятие расхождения — зона **`implementation_backlog`** до изменения кода или осознанного сужения продукта.

### Сборка `agent_memory_result.v1` (F-P7, F-P8) и `runtime_trace` — D-RUNTIME-TRACE-1

- **F-P7:** `build_agent_memory_result_v1` в worker получает `explicit_status` / `explicit_results` из результата pipeline; при отсутствии explicit finish используется проекция из `memory_slice` (ветка с `node_ids` / путями / `injected_text` по коду).
- **`runtime_trace` в v1:** в коде задаются **фиксированные** `steps_executed: 1` и `final_step: "finish"` плюс `partial_reasons` (в т.ч. из `runtime_partial_reasons`). Это **не** счётчик реальных шагов W14 и **не** полный граф исполнения. OR-012 следует читать как «согласованный компактный конверт», а не как пошаговую трассировку каждого внутреннего шага.
- **F-P8:** Состав `results[]` для finish задаёт `FinishDecisionResultAssembler`; маппинг части кодов отказа assembly в строки OR-013 — функция `or013_reasons_from_assembly_reject_codes` в `agent_memory_terminal_outcomes.py` (полная построчная матрица — см. оговорку `verification_gap` в пакете observability, когда тот файл синхронизирован).

### Продолжение init после partial (F-P9)

- **`memory_continuation_required`** вычисляет отдельная функция **`resolve_memory_continuation_required`**: `True` только при `final_partial`, флаге завершения W14 (`w14_finish`), `am_v1_status == partial`, **без** `w14_contract_failure`, **без** `recommended_next_step == fix_memory_llm_json`; для **`blocked`** функция возвращает **`None`** (не продолжать тем же правилом).
- Оркестратор init использует это **снаружи** `run()` для решения о следующем `worker.handle`, а не для второго `plan_traversal` внутри одного `run()`.

### Прочее (ранее зафиксированные факты)

- Два способа дойти до того же worker: **брокер** → subprocess `memory_agent` и **CLI** `ailit memory init` (тот же конвейер при корректном envelope).
- Основной планер **W14**: `AgentMemoryQueryPipeline.run` в `agent_memory_query_pipeline.py` — mechanical slice, один раунд планера, ветки `finish_decision`, **`propose_links`**, промежуточный `plan_traversal` с `_run_w14_action_runtime`, материализация B, indexer, **`summarize_c` / `summarize_b`**, сборка slice и explicit results где предусмотрено.
- Устаревший **G13** / `AgentMemoryLLMLoop` для `memory.query_context` **не** подключается.
- **Без LLM** (`memory.llm` выключен политикой): `_fallback_without_llm` → `_grow_pag_for_query`, затем slice или fallback-slice.
- Журнал шагов W14: `log_memory_w14_runtime_step` — **операционные** имена `state` / `next_state` из кода, не полный целевой граф ниже.
- Отмена: **`memory.cancel_query_context`** → `MemoryQueryCancelledError`, ответ с `memory_query_cancelled`.
- Дополнительные входы worker: **`memory.file_changed`**, **`memory.change_feedback`** — вне основного «один query → один W14-run».
- **KB** в этом pipeline не вызывается; init может трогать KB другими модулями — см. оркестратор init.

## Целевое поведение

### Нормативное решение по журналу и состояниям

**Источник истины для целевого продукта:** явная **целевая машина состояний** с именованными состояниями и допустимыми переходами. Событие журнала `memory.runtime.step` **обязано** содержать поля `state` и `next_state`, которые либо совпадают с узлами целевого графа состояний, либо помечены как устаревший свободный текст **только** в окне миграции (для нового кода после выравнивания такой режим по умолчанию **запрещён**).

Таблица внешних наблюдаемых событий в общем контракте рантайма (`D-OBS`, см. глоссарий) — это **подмножество** для брокера и клиентов, а не полный список всех имён внутреннего журнала памяти. Полный перечень внутренних имён — в [`failure-retry-observability.md`](failure-retry-observability.md).

### Целевые состояния (высокий уровень)

1. **`intake`** — принят конверт запроса; извлечены `query_id`, `user_turn_id`, `namespace`, `project_root`, лимиты; запрет на произвольные пути только из NL без нормализации.
2. **`db_preflight`** — открытие и проверка пути PAG и готовности SQLite; при фатальной ошибке БД → `blocked` только если нельзя продолжить после ограниченного восстановления; отсутствие файла проекта чаще → `partial` с причиной.
3. **`slice_select`** — выбор стартового среза (кэш/механика или пустой граф).
4. **`planner_round`** — раунд LLM для команды-конверта планера (`plan_traversal` или целевой `propose_links` на отдельном раунде, см. [`llm-commands.md`](llm-commands.md)).
5. **`planner_repair`** — **внутренняя фаза** ограниченного исправления формата ответа (не отдельное публичное имя `command` в конверте). Максимум **один** дополнительный вызов repair после ошибки разбора W14, если политика разрешает.
6. **`w14_action_materialize`** — материализация B/A, `contains`, индексация C, типизированные рёбра по правилам [`memory-graph-links.md`](memory-graph-links.md).
7. **`summarize_phase`** — внутренние вызовы LLM `summarize_c` / `summarize_b` как подкоманды (не отдельный раунд планера), с лимитами и явной политикой ошибок (ошибка сводки **не** переводит весь запрос в `blocked`, если остаётся полезный результат → `partial`). При сохраняемой ошибке разбора — не более одного repair с фазами `summarize_c_repair` / `summarize_b_repair`.
8. **`link_apply`** — применение **только** проверенных рантаймом кандидатов связей (LLM не пишет в БД напрямую).
9. **`finish_assembly`** — `finish_decision`, сборка `agent_memory_result.v1`, grants (см. [`external-protocol.md`](external-protocol.md)).
10. **`result_emit`** — журнал `memory.result.returned`, stdout/темы подсветки, ответ инициатору.

### Ограниченный partial и запрет бессмысленных циклов

- Повтор того же выбора файлов или узлов без новых пригодных кандидатов **запрещён** без смены входа, маркера прогресса, лимитов или исправления ответа модели (правило **FR-no-progress** в [`failure-retry-observability.md`](failure-retry-observability.md)). На уровне **одного** `run()` второго планерского раунда нет; запрет относится к **следующему** RPC или round оркестратора, если continuation разрешён (F-P9).
- Неограниченный обход дерева, неограниченное создание рёбер, «успех» без полезного результата — **запрещены** (анти-паттерн).

### Нормативная матрица статусов (цель OR-002)

| Статус | Когда (цель) |
|--------|----------------|
| `complete` | Достаточно доказательств для подцели; политика завершения выполнена. |
| `partial` | Полезный результат частично; лимиты; отсутствующий файл; отклонённые связи; ошибки сводки при остаточном контексте; падение разбора планера после политики partial. |
| `blocked` | **Цель:** только если недоступен API LLM **или** невозможно получить **валидный** ответ модели для обязательной фазы после **ограниченного** repair/retry согласно [`failure-retry-observability.md`](failure-retry-observability.md). **Факт в коде для `am_v1_status` шире** — см. F-P5, F-P6 в «Текущая реализация». |

## Target flow (сводка под код и цель)

1. Инициатор формирует envelope `memory.query_context` (broker или CLI init).
2. `AgentMemoryWorker.handle` создаёт `AgentMemoryQueryPipeline` и вызывает **`run` один раз**.
3. Внутри `run`: политика LLM → при необходимости mechanical slice → один вызов планера → при ошибке разбора — не более одного repair (если gate разрешает) → ветвление по команде W14 → при `plan_traversal` — материализация, indexer, summarize с собственными repair → терминальный результат pipeline.
4. После `run`: worker обогащает slice, вызывает **`build_agent_memory_result_v1`** (включая фиксированный `runtime_trace` по D-RUNTIME-TRACE-1), формирует ответ `ok: true` с полями результата либо ошибку отмены / проброс исключения.
5. Для **`ailit memory init`**: `MemoryInitOrchestrator` читает `resolve_memory_continuation_required`; при `True` готовит **новый** запрос и снова вызывает `handle` (**continuation снаружи** `run()`), а не расширяет один `run()` вторым планером.

## Технический контракт: фрагмент `agent_memory_result.v1`

### Поле `runtime_trace` (D-RUNTIME-TRACE-1)

| Правило | Значение |
|---------|----------|
| **Required** | Объект `runtime_trace` присутствует в собранном v1 (как в `build_agent_memory_result_v1`). |
| **Фиксированные поля шага** | `steps_executed` **всегда** целое `1`; `final_step` **всегда** строка `"finish"` в текущей реализации. |
| **Partial reasons** | `partial_reasons` объединяет причины из `partial` и `extra_runtime_partial_reasons` (в т.ч. `no_progress`, `cap_exceeded`, коды assembly — по фактам вызова). |
| **Forbidden для читателя канона** | Трактовать `steps_executed` как число реальных шагов W14 или как полный ориентир для отладки графа без чтения `log_memory_w14_runtime_step`. |

### `memory_continuation_required` после round (F-P9)

| Условие | Значение |
|---------|----------|
| **Когда `True`** | `final_partial` и завершение W14 (`w14_finish`), статус v1 **`partial`**, нет `w14_contract_failure`, шаг рекомендации **не** `fix_memory_llm_json`. |
| **Когда не продолжать (`None`)** | Статус **`blocked`** или нарушены условия строкой выше. |
| **Где применяется** | Логика init-оркестратора **после** успешного ответа worker с v1; не внутри `AgentMemoryQueryPipeline.run`. |

## Examples

### Example 1: Happy path — один broker RPC, один `run()`

Пользовательский сценарий через оболочку: один запрос `memory.query_context` до subprocess memory. Worker вызывает `pl.run` один раз, планер возвращает валидный `finish_decision`, assembly даёт результаты. В ответе `agent_memory_result.v1` статус `complete`, в журнале ожидаемые шаги W14 и маркер завершения согласно [`failure-retry-observability.md`](failure-retry-observability.md). Поле `runtime_trace` содержит `steps_executed: 1`, `final_step: "finish"` — это **не** противоречит успеху, но не описывает каждый внутренний шаг.

### Example 2: Partial path — `no_progress` в trace, без второго планера внутри `run()`

Планер выбрал промежуточный `plan_traversal`; после обхода кандидатов сработал путь с **нулём** новых кандидатов при ненулевом контексте узлов. В `runtime_partial_reasons` попадает **`no_progress`**, итоговый статус v1 **`partial`** при сохранении полезного среза. Следующий вызов планера возможен только **новым** RPC или новым round init-оркестратора, если `resolve_memory_continuation_required` вернул `True` — не вторым `plan_traversal` внутри того же `run()`.

### Example 3: Failure / blocked path — пустой finish и init `runtime_error`

Ветка `finish_decision` даёт пустые `selected_results` и пустой набор валидных `results` — в v1 уходит **`blocked`** по F-P5, хотя LLM мог быть доступен: это **расхождение с нормативом OR-002**, зафиксированное выше. Отдельно: при исключении из `pl.run` init-оркестратор может завершить фазу как **`blocked`** с `reason_short=runtime_error` и **non-zero** exit **без** полного тела `agent_memory_result` в этом round (F-P6).

## Commands

### Проверка соответствия канона коду (разработчик)

```bash
cd /home/artem/reps/ailit-agent
.venv/bin/python -m pytest tests/test_g14r7_agent_memory_result_assembly.py -q
```

**Expected:** тесты проходят; в них покрыты `resolve_memory_continuation_required` и сборка v1.

```bash
.venv/bin/python -m pytest tests/runtime/test_memory_init_fix_uc01_uc02.py -q
```

**Expected:** сценарии continuation / partial для init; согласовать с F-P2 и F-P9.

### Manual smoke (продукт)

```bash
ailit memory init ./
```

**Expected:** при полном успехе exit `0`; при частичном прогрессе init — поведение exit см. оркестратор и `failure-retry-observability.md` после синхронизации unit `u_failure_obs`. При «падении» фазы — возможен `blocked` с `runtime_error` без полного v1 в том же round (F-P6).

## Observability

- **Обязательные compact-сигналы по планеру:** шаги `log_memory_w14_runtime_step` (`state`, `next_state`), фазы repair планера и summarize в LLM-журнале — см. код pipeline.
- **Завершение запроса:** маркер `memory.result.returned` и поля v1 — см. [`failure-retry-observability.md`](failure-retry-observability.md).
- **Нельзя** выводить из `runtime_trace.steps_executed` число реальных шагов W14 (D-RUNTIME-TRACE-1); для графа шагов смотреть W14 runtime logs.

## Failure and retry rules (runtime-flow slice)

- **FR-RT-1:** Не более **одного** repair ответа планера на ошибку разбора W14 за один `run()`, если `_should_repair_w14_error` разрешает repair.
- **FR-RT-2:** Второй раунд **`plan_traversal` внутри того же `run()`** отсутствует в коде; «ещё один планер» означает **новый** `handle` / RPC или следующий round оркестратора init.
- **FR-RT-3:** Трактовка **`blocked`** в v1 — по фактам F-P5; норматив OR-002 — в таблице «Нормативная матрица»; снятие расхождения — `implementation_backlog` или смена кода.

## Acceptance criteria

1. Читатель различает **один** `pl.run` на RPC и **continuation init снаружи** `run()`.
2. Описаны **все** идентификаторы фактов F-P1–F-P9 в человекочитаемом виде со ссылкой на каталог модулей, а не на pipeline-артефакты.
3. D-BLOCKED-1 и D-RUNTIME-TRACE-1 отражены: шире `blocked` в коде; фиксированный `runtime_trace`.
4. Примеры покрывают happy, partial (`no_progress`/continuation), blocked/runtime_error.
5. Команды pytest указывают на существующие тесты в репозитории.

## Do not implement this as

- **DNI-RT-1:** Описывать многораундовый планер **внутри** одного `AgentMemoryQueryPipeline.run` для текущего кода.
- **DNI-RT-2:** Читать `runtime_trace.steps_executed` как счётчик шагов W14.
- **DNI-RT-3:** Сужать фактические условия `blocked` до одной фразы «только LLM недоступен», игнорируя F-P5 и F-P6.

## How start-feature / start-fix must use this

- **`02_analyst`** читает этот файл до `technical_specification.md`, если задача касается потока AgentMemory и статусов v1.
- **`06_planner`** трассирует задачи к шагам **Target flow** и **Acceptance criteria**; отдельный файл плана под `plan/17-*.md` не используется — нарезка из разделов этого файла и постановки задачи, не дублировать канон внутри плана.
- **`11_test_runner`** проверяет команды из раздела **Commands** или помечает проверку как blocked по окружению с причиной.
- **`13_tech_writer`** обновляет этот файл только если меняется продуктовое поведение pipeline или сборки v1.
