# Workflow: переход `ai-multi-agents` на собственный Agent Core

## Цель

Подготовить исполнимый roadmap, по которому `ai-multi-agents` сможет отказаться от зависимости на внешний runtime Cursor/Claude Code как на вычислительное ядро и перейти на собственный `agent core`, сохранив:

- `rules/*` как policy layer;
- `context/*` как canonical knowledge layer;
- installer-first подход;
- low-infra профиль;
- совместимость с текущим `status.md`, runtime state и knowledge refresh;
- возможность сначала подключить `Kimi K2`, а затем `DeepSeek` и другие провайдеры.

## Основания для плана

### Текущее состояние `ai-multi-agents`

Сейчас система держится на трех слоях:

1. `templates/cursor/.cursor/rules/system/main/runtime-cli.mdc` задает transport к внешнему CLI.
2. `templates/cursor/.cursor/rules/system/main/orchestrator-duties.mdc` и соседние `orchestrator-stage-*.mdc` держат orchestration semantics в markdown.
3. `tools/runtime/*` и `tools/knowledge_refresh/*` дают локальный runtime/state/knowledge слой, но не заменяют внешнее агентное ядро.

Это дает переносимость, но создает ограничения:

- поведение зависит от внешнего CLI и его флагов;
- orchestration сильно завязан на natural-language policy;
- tool execution, retries, streaming и permissions не контролируются собственным кодом;
- подключение новой модели требует обходных путей вместо штатного provider layer.

### Что берем из референсов

#### Из `claude-code`

- явный `query loop` с кодовым `state`;
- строгий контракт инструмента: schema, destructive/read-only/concurrency-safe;
- централизованный streaming reducer;
- context compaction до вызова модели;
- permission/safety слой отдельно от логики провайдера;
- детерминированное resume/retry поведение.

#### Из `opencode`

- provider abstraction и message transforms;
- session processor как единый центр исполнения;
- typed event bus и run/session state;
- approval flow через асинхронное ожидание ответа оператора;
- явные runtime/addon boundaries;
- compaction и snapshot-first observability.

#### Из текущего `ai-multi-agents`

- `rules/*` нельзя терять: это конкурентное преимущество как policy layer;
- `context/*` должно остаться источником правды;
- installer и helper layer уже задают хороший low-infra deployment contract;
- `tools/runtime/*` нужно переиспользовать как observability и state foundation;
- knowledge refresh нельзя смешивать с runtime state.

#### Из внешних API-практик

- `Kimi K2`: tool calling в OpenAI-compatible потоке, поддержка streaming tool calls и parser fallback при необходимости ручного разбора;
- `DeepSeek`: OpenAI-compatible function calling, `strict` mode как важный режим для schema-driven tool execution.

## Глобальные инварианты

Каждая задача ниже обязана соблюдать следующее:

1. Новый `agent core` не подменяет `context/*`.
2. Новый `agent core` не ломает существующий installer-first rollout.
3. Migration path должен быть обратимым до финального cutover.
4. Любое новое ядро должно работать без тяжелой внешней инфраструктуры.
5. Provider layer должен быть capability-based, а не привязанным к бренду модели.
6. Orchestrator compatibility сначала обеспечивается адаптером, а не мгновенной полной переписью правил.

## Порядок этапов

1. Этап 1. Нормализация целевой модели Agent Core
2. Этап 2. Provider abstraction и transport foundation
3. Этап 3. Tool system, permissions и safety
4. Этап 4. Session loop, streaming и context management
5. Этап 5. Совместимый adapter для `ai-multi-agents`
6. Этап 6. Code-first orchestration runtime
7. Этап 7. Memory и context integration
8. Этап 8. Hardening, observability и governance
9. Этап 9. Rollout и отключение зависимости от Cursor/Claude Code

## Почему именно такой порядок

- без явных границ ядра легко смешать runtime, memory и policy;
- без provider abstraction любой Kimi/DeepSeek rollout станет vendor-locked;
- без tool/safety слоя свой агент быстро потеряет управляемость;
- без session loop невозможно стабильно поддержать streaming, retries и compaction;
- без compatibility adapter нельзя безопасно встроиться в `ai-multi-agents`;
- только после этого имеет смысл переносить orchestration semantics из markdown в код;
- hardening и cutover нужно делать только после появления совместимого ядра.

---

## Этап 1. Нормализация целевой модели Agent Core

Цель этапа: зафиксировать границы нового ядра и исключить архитектурную двусмысленность до начала кодовой реализации.

### Задача 1.1. Зафиксировать boundaries нового ядра

**Что сделать**

- Описать, что именно входит в `agent core`, а что остается в `rules/*`, `tools/runtime/*` и `tools/knowledge_refresh/*`.
- Отдельно зафиксировать границы между:
  - provider layer;
  - tool executor;
  - session loop;
  - orchestration bridge;
  - memory/context integration;
  - observability/state.

**Критерии приемки**

- есть единый boundary document;
- нет пересечения ответственности между `agent core` и `knowledge_refresh`;
- зафиксировано, что `rules/*` остаются policy layer, а не переезжают полностью в runtime.

**Тесты**

- перечитать архитектурный документ и проверить, что каждый модуль отнесен только к одному слою;
- проверить, что для каждой текущей подсистемы `ai-multi-agents` есть решение: сохранить, адаптировать или заменить.

### Задача 1.2. Зафиксировать capability model для моделей и инструментов

**Что сделать**

- Описать capability matrix для провайдеров:
  - tool calling;
  - streaming;
  - structured output;
  - strict schema support;
  - reasoning mode;
  - retries/timeouts;
  - usage/cost telemetry.
- Отдельно описать capability matrix для инструментов:
  - read-only;
  - write;
  - destructive;
  - concurrency-safe;
  - approval-required.

**Критерии приемки**

- capability model описана без привязки к одному провайдеру;
- Kimi K2 и DeepSeek помещаются в одну общую модель;
- decisions по routing можно принимать на основе capabilities, а не hardcode-веток.

**Тесты**

- проверить, что один и тот же tool contract можно выполнить через Kimi и DeepSeek adapter;
- пройтись по capability matrix и убедиться, что для неизвестного провайдера можно добавить новый adapter без переписывания session loop.

### Задача 1.3. Зафиксировать migration path

**Что сделать**

- Описать поэтапную замену внешнего CLI на внутренний adapter.
- Разделить миграцию на:
  - adapter-compatible phase;
  - hybrid phase;
  - native-core phase;
  - full cutover phase.

**Критерии приемки**

- миграция не требует одномоментного отказа от текущих `runtime-cli.mdc`;
- rollback path понятен;
- installer impact описан заранее.

**Тесты**

- проверить, что для каждого этапа миграции есть вход, выход и обратимый rollback;
- убедиться, что ни один шаг не требует одновременной переписи `rules/*`, `runtime/*` и provider layer.

### Критерий этапа 1

- архитектура ядра нормализована;
- capability-based модель зафиксирована;
- migration path понятен и обратим;
- дальнейшие этапы можно выполнять без повторного спора о placement и boundaries.

**Тест этапа**

- провести архитектурный review документов и убедиться, что новый участник команды может объяснить placement всех ключевых подсистем без дополнительных устных договоренностей.

---

## Этап 2. Provider abstraction и transport foundation

Цель этапа: построить единый провайдерный слой, через который можно сначала подключить `Kimi K2`, затем `DeepSeek`, не ломая остальной runtime.

### Задача 2.1. Ввести provider interface

**Что сделать**

- Описать единый интерфейс провайдера:
  - `send_messages`;
  - `stream_messages`;
  - `normalize_tool_calls`;
  - `normalize_usage`;
  - `supports_capability`.
- Отделить transport, message normalization и provider-specific compatibility.

**Критерии приемки**

- кодовый контракт провайдера не зависит от конкретного SDK;
- transport и message transforms отделены;
- session loop не знает о бренд-специфичных деталях.

**Тесты**

- contract test на mock-provider;
- smoke test на сериализацию запроса и нормализацию ответа;
- проверка, что provider-specific поля не уходят выше adapter layer.

### Задача 2.2. Реализовать OpenAI-compatible transport foundation

**Что сделать**

- Зафиксировать transport, совместимый с OpenAI-style chat completions.
- Поддержать:
  - обычные ответы;
  - streaming;
  - tool calls;
  - tool call results;
  - базовые retry/timeout правила.

**Критерии приемки**

- transport подходит и для Kimi, и для DeepSeek;
- transport не тянет тяжелую vendor-specific инфраструктуру;
- tool calls и stream events приводятся к единому внутреннему виду.

**Тесты**

- golden tests на нормализацию text/tool/finish_reason;
- fault-injection tests на timeout, пустой ответ и malformed tool payload;
- smoke test на повторный запрос после retryable failure.

### Задача 2.3. Подключить `Kimi K2` как first provider

**Что сделать**

- Реализовать Kimi adapter через общий transport.
- Отдельно описать parser fallback на случай raw tool call parsing.
- Зафиксировать рекомендуемый режим использования для агентных задач.

**Критерии приемки**

- Kimi работает через общий provider contract;
- tool calling и streaming покрыты;
- parser fallback не ломает основной путь.

**Тесты**

- tool calling smoke test;
- streaming tool call assembly test;
- negative test с неполным tool chunk и проверкой корректной сборки/ошибки;
- manual parser fallback test на сыром tool response.

### Задача 2.4. Подключить `DeepSeek` как second provider

**Что сделать**

- Реализовать DeepSeek adapter через тот же transport.
- Поддержать `strict` mode для schema-driven tools там, где это уместно.
- Зафиксировать отличия от Kimi на уровне capabilities, а не логики ядра.

**Критерии приемки**

- DeepSeek adapter не требует отдельного session loop;
- strict schema path описан и протестирован;
- routing между Kimi и DeepSeek может быть выбран конфигом.

**Тесты**

- function calling smoke test;
- strict mode schema validation test;
- provider switch test без изменения tool executor и session loop.

### Критерий этапа 2

- есть единый provider abstraction layer;
- Kimi подключен как основной провайдер;
- DeepSeek подключен как альтернативный провайдер;
- provider switching возможен без переписывания остального ядра.

**Тест этапа**

- запустить одинаковый сценарий через mock, Kimi и DeepSeek adapters и проверить единый внутренний формат событий, tool calls и usage.

---

## Этап 3. Tool system, permissions и safety

Цель этапа: построить управляемую execution-модель инструментов до переноса orchestration в собственное ядро.

### Задача 3.1. Ввести единый tool contract

**Что сделать**

- Зафиксировать структуру инструмента:
  - имя;
  - schema;
  - описание;
  - side-effect class;
  - concurrency policy;
  - approval policy;
  - output normalization.

**Критерии приемки**

- все инструменты описываются единым контрактом;
- tool metadata достаточно для routing, permissions и UI;
- контракт не зависит от конкретной модели.

**Тесты**

- schema validation tests;
- contract serialization test;
- test на то, что один и тот же contract может быть отдан разным provider adapters.

### Задача 3.2. Реализовать permission и approval flow

**Что сделать**

- Разделить auto-allow, ask, deny и session-scoped approvals.
- Описать поведение для destructive tools и write tools.
- Сделать совместимость с human-in-the-loop паузами.

**Критерии приемки**

- permission decisions отделены от исполнения tool-а;
- destructive actions не проходят без политики;
- approval flow совместим с pause/resume semantics.

**Тесты**

- tests на allow/ask/deny режимы;
- test на pending approval и возобновление выполнения;
- negative test на попытку вызова запрещенного инструмента.

### Задача 3.3. Реализовать tool executor с контролем конкуренции

**Что сделать**

- Ввести исполнитель, который различает serial и concurrency-safe tools.
- Поддержать ordered result delivery.
- Отдельно описать отмену соседних вызовов при критической ошибке.

**Критерии приемки**

- executor воспроизводимо исполняет safe и unsafe инструменты;
- параллельность ограничена policy;
- порядок результатов стабилен.

**Тесты**

- test на пакет из concurrency-safe tools;
- test на смешанный пакет safe/unsafe;
- cancellation test при ошибке shell/write tool;
- deterministic ordering test.

### Критерий этапа 3

- появился единый tool system;
- permission layer отделен от provider layer;
- tool execution управляется политиками, а не ad-hoc промптом.

**Тест этапа**

- запустить сценарий с read-only, write и destructive tools и проверить правильность approval, ordering и error handling.

---

## Этап 4. Session loop, streaming и context management

Цель этапа: сделать собственное ядро предсказуемым на длинных агентных итерациях.

### Задача 4.1. Реализовать явный session loop

**Что сделать**

- Ввести главный цикл с явным состоянием:
  - messages;
  - pending tool calls;
  - retries;
  - pause state;
  - compaction state;
  - finish reason.

**Критерии приемки**

- runtime loop существует как first-class кодовая сущность;
- continue/retry/pause причины определяются явно;
- loop можно тестировать без реального провайдера.

**Тесты**

- state transition tests;
- retry limit tests;
- pause/resume tests;
- terminal reason tests.

### Задача 4.2. Реализовать streaming reducer

**Что сделать**

- Централизовать обработку text deltas, tool deltas, reasoning deltas и finish events.
- Поддержать сборку tool calls из streaming chunks.

**Критерии приемки**

- stream processing не размазан по коду;
- reducer умеет собирать финальное message state;
- частичные tool chunks не ломают loop.

**Тесты**

- text streaming reconstruction test;
- tool delta assembly test;
- malformed chunk recovery test.

### Задача 4.3. Реализовать context compaction и budget control

**Что сделать**

- Описать budget policy для:
  - message history;
  - tool outputs;
  - summaries;
  - canonical context excerpts.
- Сначала ввести предсказуемый базовый compaction path, затем расширения.

**Критерии приемки**

- есть единый budget-aware compaction policy;
- compact не подменяет canonical docs;
- long-running session не деградирует в хаотичный history dump.

**Тесты**

- tests на превышение message budget;
- tests на усечение больших tool outputs;
- regression test, что после compaction критичные facts остаются доступны loop-у.

### Критерий этапа 4

- session loop работает детерминированно;
- streaming и tool deltas централизованы;
- context budget контролируется кодом, а не только качеством промпта.

**Тест этапа**

- прогнать длинную симулированную агентную сессию с несколькими tool calls, pause/resume и compaction, затем проверить конечное состояние loop и сохранность ключевых данных.

---

## Этап 5. Совместимый adapter для `ai-multi-agents`

Цель этапа: встроить собственный `agent core` в текущий pipeline без немедленной поломки `rules/*`.

### Задача 5.1. Ввести runtime adapter вместо прямого CLI transport

**Что сделать**

- Спроектировать adapter, который принимает:
  - роль агента;
  - входные данные шага;
  - model selection;
  - repo root;
  - policy hints.
- Adapter должен отдавать stdout-compatible результат для существующего pipeline либо совместимый артефактный ответ.

**Критерии приемки**

- текущий orchestrator может вызвать новый runtime через совместимую точку входа;
- роли и stage prompts продолжают работать;
- внешний формат результата остается пригодным для текущего artifact parsing.

**Тесты**

- compatibility test на одной роли;
- end-to-end smoke test `роль -> adapter -> provider -> tool -> ответ`;
- regression test на существующий artifact parser.

### Задача 5.2. Интегрировать adapter в `runtime-cli.mdc` migration path

**Что сделать**

- Описать новый transport path рядом с существующими Cursor/Claude блоками.
- Ввести controlled switch между внешним CLI и внутренним agent core.

**Критерии приемки**

- migration path не ломает текущие установки;
- проект может выбрать старый или новый runtime конфигом;
- fallback на старый transport остается доступным.

**Тесты**

- config switch test;
- fallback test при недоступности нового runtime;
- installer smoke test на оба режима.

### Задача 5.3. Подключить runtime events и state к новому adapter

**Что сделать**

- Сделать так, чтобы вызов нового ядра публиковал те же ключевые lifecycle signals, что нужны `tools/runtime/*`.
- Сохранить совместимость с `status.md` как projection.

**Критерии приемки**

- новый adapter не выпадает из существующего observability/state слоя;
- snapshot и `status.md` продолжают быть согласованными;
- monitor/UI future path не ломается.

**Тесты**

- runtime event mapping test;
- snapshot consistency test;
- test на согласованность `run_state` и `status.md`.

### Критерий этапа 5

- собственный `agent core` можно вызвать из `ai-multi-agents` без отказа от существующего pipeline;
- transport к модели больше не зависит только от Cursor/Claude CLI;
- observability и artifact contracts не сломаны.

**Тест этапа**

- выполнить маленький сценарий feature-stage через новый adapter и убедиться, что артефакты, runtime events и status projection корректны.

---

## Этап 6. Code-first orchestration runtime

Цель этапа: постепенно перенести основные orchestration semantics из markdown-only режима в кодовый runtime, не теряя policy layer.

### Задача 6.1. Выделить machine-readable stage graph

**Что сделать**

- Формализовать stages, transitions, retry rules, blocked reasons и escalation points.
- Отделить machine contract от narrative-инструкций в markdown.

**Критерии приемки**

- stage graph можно обработать кодом;
- blocking, retry и review paths заданы явно;
- markdown остается policy layer, а не единственным runtime semantics source.

**Тесты**

- transition table tests;
- blocked path tests;
- retry budget tests.

### Задача 6.2. Перенести stage execution в orchestrator runtime

**Что сделать**

- Реализовать кодовый runtime, который исполняет:
  - analysis;
  - architecture;
  - planning;
  - development;
  - review;
  - verification;
  - writer/update steps.

**Критерии приемки**

- последовательность этапов определяется кодом и конфигом;
- роли и prompts продолжают браться из policy layer;
- поведение воспроизводимо и логируется через runtime state.

**Тесты**

- stage order tests;
- blocked/escalation tests;
- end-to-end dry run на типовой feature flow.

### Задача 6.3. Сохранить hybrid режим

**Что сделать**

- Оставить возможность, при необходимости, использовать часть старого orchestration flow.
- Зафиксировать условия, когда используется hybrid, а когда native runtime.

**Критерии приемки**

- переход на code-first runtime не является all-or-nothing;
- rollout можно делать поэтапно;
- есть понятные rollback conditions.

**Тесты**

- hybrid mode test;
- rollback test;
- compatibility test на старые правила и новые runtime hooks.

### Критерий этапа 6

- orchestration semantics частично или полностью формализованы в коде;
- `rules/*` остаются policy layer;
- hybrid и native режимы описаны и воспроизводимы.

**Тест этапа**

- выполнить один и тот же stage flow в hybrid и native режиме и сравнить: stage transitions, artifact outputs и runtime events.

---

## Этап 7. Memory и context integration

Цель этапа: связать новый `agent core` с knowledge/memory системой `ai-multi-agents`, не разрушая границы между canonical knowledge и runtime memory.

### Задача 7.1. Зафиксировать memory boundaries для нового ядра

**Что сделать**

- Разделить:
  - canonical project memory;
  - retrieval memory;
  - episodic runtime memory;
  - procedural memory;
  - session working memory.

**Критерии приемки**

- нет смешения `context/*` и runtime state;
- session memory не объявляется источником правды;
- retrieval и episodic слои используются осознанно.

**Тесты**

- boundary review test;
- test на то, что один и тот же факт не пишется бесконтрольно в несколько слоев;
- regression test на корректность knowledge_refresh сценариев.

### Задача 7.2. Встроить knowledge shortlist в session loop

**Что сделать**

- Использовать существующий knowledge refresh shortlisting path как источник компактного контекста.
- Передавать в session loop только релевантный subset canonical knowledge.

**Критерии приемки**

- session loop не тянет весь `context/*`;
- сохраняется index-first reading;
- knowledge shortlist совместим с task/stage context.

**Тесты**

- shortlist selection tests;
- token budget comparison before/after shortlist;
- test на fallback path при пустом shortlist.

### Задача 7.3. Добавить episodic summaries для будущего retrieval

**Что сделать**

- Сохранять summary-first эпизоды выполнения:
  - retries;
  - blocked states;
  - successful resolutions;
  - integration outcomes.

**Критерии приемки**

- episodic layer пригоден для future retrieval;
- архив не раздувается сырыми логами;
- summaries привязаны к run/stage/task identifiers.

**Тесты**

- episode creation tests;
- retrieval readiness test;
- test на ограничение размера episode payload.

### Критерий этапа 7

- новый `agent core` корректно интегрирован с knowledge/memory boundaries;
- `context/*` осталось canonical project memory;
- session context стал компактнее и управляемее.

**Тест этапа**

- выполнить сценарий с реальным shortlist, blocked episode и successful completion, затем проверить корректность canonical docs, episodic summaries и runtime state.

---

## Этап 8. Hardening, observability и governance

Цель этапа: довести ядро до эксплуатационной зрелости.

### Задача 8.1. Ввести retry, timeout и provider failure policy

**Что сделать**

- Описать retryable и non-retryable ошибки.
- Зафиксировать правила для:
  - provider timeout;
  - malformed model output;
  - tool execution failure;
  - approval timeout;
  - network instability.

**Критерии приемки**

- recovery policy детерминирована;
- silent failure paths отсутствуют;
- эскалация пользователю формализована.

**Тесты**

- failure injection tests;
- retry budget tests;
- escalation path tests.

### Задача 8.2. Нормализовать usage/cost telemetry

**Что сделать**

- Собрать usage/cost в единую модель на run/stage/task/agent уровне.
- Подготовить данные для routing и budget governance.

**Критерии приемки**

- usage нормализуется независимо от провайдера;
- cost telemetry не протекает vendor-specific полями наружу;
- budget signals можно использовать в runtime decisions.

**Тесты**

- provider usage normalization tests;
- budget threshold tests;
- test на неполные usage данные.

### Задача 8.3. Расширить observability и debug bundle

**Что сделать**

- Сделать snapshots, raw events и debug summary достаточными для диагностики сбоя.
- Поддержать human-readable и machine-readable views.

**Критерии приемки**

- по debug bundle можно понять, что произошло, без чтения разрозненных логов;
- snapshots и события согласованы;
- UI/monitor future path поддержан.

**Тесты**

- snapshot regression tests;
- debug bundle completeness test;
- test на blocked, retry и success сценарии.

### Критерий этапа 8

- ядро устойчиво к типовым отказам;
- usage/cost и observability доведены до рабочего уровня;
- debug path воспроизводим.

**Тест этапа**

- провести fault-injection run с таймаутом, retry и финальной эскалацией, затем проверить события, snapshots, cost/usage и debug bundle.

---

## Этап 9. Rollout и отключение зависимости от Cursor/Claude Code

Цель этапа: перевести `ai-multi-agents` на собственное ядро как основной runtime, сохранив контролируемый rollback.

### Задача 9.1. Подготовить installer и packaging для нового ядра

**Что сделать**

- Определить, как новый `agent core` раскладывается через installer.
- Согласовать это с существующими `runtime` и `knowledge_refresh` helper layers.

**Критерии приемки**

- installer умеет ставить новый runtime;
- старые пути не ломаются;
- selective rollout поддержан.

**Тесты**

- clean install test;
- update install test;
- selective runtime profile test.

### Задача 9.2. Провести staged rollout

**Что сделать**

- Зафиксировать rollout по фазам:
  - internal alpha;
  - hybrid beta;
  - default-on for new installs;
  - full cutover.

**Критерии приемки**

- у каждой rollout-фазы есть exit criteria;
- rollback и fallback paths описаны;
- cutover делается по фактам, а не по желанию.

**Тесты**

- phase gate checklist;
- rollback drill;
- side-by-side comparison test старого и нового runtime.

### Задача 9.3. Убрать критическую зависимость от внешнего CLI

**Что сделать**

- Перевести внешний CLI transport в optional fallback.
- Зафиксировать, какие сценарии еще допустимо держать на старом runtime временно.

**Критерии приемки**

- собственный `agent core` является основным runtime;
- Cursor/Claude CLI больше не нужны как обязательное ядро;
- fallback остается только как временная или аварийная опция.

**Тесты**

- default runtime test без Cursor/Claude CLI;
- fallback-only test;
- documentation validation test по сценарию "чистая установка и первый запуск".

### Критерий этапа 9

- `ai-multi-agents` может работать на собственном `agent core` как на основном ядре;
- внешний CLI перестал быть обязательной вычислительной зависимостью;
- rollout и rollback задокументированы и проверяемы.

**Тест этапа**

- выполнить сценарий "чистая установка -> запуск feature flow -> tool execution -> runtime events -> completion" без обязательного использования Cursor/Claude CLI.

---

## Рекомендуемый боевой порядок

Строгий порядок исполнения:

1. Этап 1
2. Этап 2
3. Этап 3
4. Этап 4
5. Этап 5
6. Этап 6
7. Этап 7
8. Этап 8
9. Этап 9

## Ожидаемый результат после прохождения workflow

После прохождения всех этапов `ai-multi-agents` должен получить:

1. собственный `agent core` с явным runtime loop;
2. capability-based provider abstraction;
3. Kimi K2 как первый штатный провайдер;
4. DeepSeek как второй штатный провайдер;
5. управляемый tool system с permission и safety layer;
6. совместимый adapter для текущего pipeline;
7. постепенный перенос orchestration semantics из markdown-only в code-first runtime;
8. интеграцию с canonical knowledge без подмены `context/*`;
9. устойчивый observability, retry и governance слой;
10. возможность работать без обязательной зависимости от Cursor/Claude Code.
