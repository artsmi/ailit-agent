# Workflow: построение локальной AI-agent platform поверх `ai-multi-agents`

## Цель

Построить не просто замену внешнего runtime, а локальную или server-local AI-agent platform, которая:

- работает с проектным `context/*` как с каноническим знанием;
- хранит runtime state, events и episodic данные локально;
- визуализирует исполнение workflow и агентов;
- минимизирует token cost через shortlist, compaction и governance;
- поддерживает динамически расширяемые agents и workflows под конкретный проект;
- постепенно уходит от обязательной зависимости на Cursor/Claude Code.

## Режим исполнения на текущем этапе

На текущем этапе этот workflow должен исполняться так:

1. `ai-multi-agents` продолжает работать через текущий Cursor runtime.
2. `ai-multi-agents` используется как workflow shell для разработки нового runtime.
3. Реализация выполняется в репозитории `ailit-agent`.
4. Текущий рабочий путь `ai-multi-agents` нельзя деградировать или ломать.
5. Каждая задача ниже должна запускаться как отдельная маленькая feature-итерация.

Это означает:

- не делать big-bang migration;
- не заменять рабочий runtime сразу;
- не переписывать весь orchestration слой за один проход;
- развивать новый runtime отдельно, но совместимо с будущей интеграцией.

## Сквозной контракт live интеграционных тестов (DeepSeek)

Начиная с `Этапа 3` и далее, любые новые интеграционные тесты, которые требуют реального LLM вызова, выполняются через **DeepSeek** как единый live baseline provider.

Правила:

- секрет задается только через окружение (`DEEPSEEK_API_KEY`) или CI secrets;
- ключ **не** кладется в репозиторий и не фиксируется в markdown;
- без ключа live тесты должны **пропускаться**, а не ломать локальный прогон;
- для контроля квоты в CI рекомендуется дополнительный guard `AILIT_RUN_LIVE=1`.

Каноническое описание сценариев `small smoke` и `large scenario`:

- `context/proto/deepseek-integration-test-contract.md`

## Как использовать этот документ в `ai-multi-agents`

Этот workflow предназначен для практического режима:

1. выбрать одну задачу из этапа;
2. передать ее мультиагентной системе как отдельную feature-задачу;
3. ограничить scope только этой задачей;
4. после выполнения пройти критерии приемки;
5. затем пройти проверки из раздела `Тесты`;
6. только после этого переходить к следующей задаче.

Правильная единица работы:

- `одна задача workflow = одна итерация разработки`

## Главная продуктовая формула

Целевая система должна быть:

- `knowledge-aware`;
- `workflow-aware`;
- `low-infra`;
- `locally observable`;
- `project-configurable`;
- `provider-agnostic`.

Важно: задача проекта не в том, чтобы сделать еще один универсальный coding runtime "как у всех", а в том, чтобы сделать сильную платформу AI-агентов для реальных проектных workflow.

## Три слоя целевой архитектуры

### 1. `core runtime`

Отвечает за:

- provider abstraction;
- session loop;
- tools;
- permissions;
- approvals;
- streaming;
- retries;
- runtime state hooks;
- cost/token accounting.

### 2. `workflow layer`

Отвечает за:

- execution graph;
- роли агентов;
- machine-readable orchestration;
- stage transitions;
- blocked/resume semantics;
- artifacts lifecycle;
- visualization-friendly event flow.

### 3. `project layer`

Отвечает за:

- `rules/*` как policy layer;
- `context/*` как canonical knowledge;
- project-specific workflows;
- project-specific agents;
- project config;
- project memory boundaries.

## Что это значит для `orchestrator*.md`

Новый runtime не должен слепо поглотить `orchestrator*.md`.

Нужно разделить:

- **machine logic** уходит в код:
  - stage graph;
  - transitions;
  - retries;
  - blocked/resume;
  - routing между агентами;
  - lifecycle events;
  - проверяемые runtime rules;
- **policy logic** остается в `rules/*`:
  - роль агента;
  - инженерная дисциплина;
  - требования к review;
  - project-specific conventions;
  - narrative semantics.

Итоговая модель:

- `runtime` решает, **что и когда исполнять**;
- `rules/*` решают, **как агент должен себя вести внутри роли**.

## Что сохраняем из текущего `ai-multi-agents`

1. `rules/*` как главное отличие от обычных agent CLI.
2. `context/*` как source of truth.
3. `knowledge_refresh` и shortlist-подход.
4. `tools/runtime/*` как основу observability/state.
5. installer-first и low-infra раскладку.

## Что берем из референсов

### Из `claude-code`

- явный agent loop;
- зрелый tool runtime;
- permission/safety model;
- streaming reducer;
- context compaction;
- recovery semantics.

### Из `opencode`

- provider abstraction;
- session runtime;
- typed events/state;
- extensibility;
- clear runtime boundaries;
- transport normalization.

## Честная постановка задачи

Нельзя выиграть у `claude-code` или `opencode`, просто переписав transport.

Выигрыш может появиться только если собрать систему, которая сильнее в том, что у вас уже является преимуществом:

- knowledge discipline;
- project workflows;
- visual observability;
- cost control;
- local-first execution;
- project-configurable multi-agent behavior.

## Порядок этапов

1. Этап 1. Нормализация целевой платформы и границ трех слоев [выполнено]
2. Этап 2. Local state, event model и visual-first observability foundation [выполнено]
3. Этап 3. Provider abstraction и transport foundation [выполнено]
4. Этап 4. Tool runtime, permissions и safety [выполнено]
5. Этап 5. Session loop, streaming и token-cost management [выполнено]
6. Этап 6. Workflow engine и перенос machine logic из `orchestrator*.md` [выполнено]
7. Этап 7. Project layer, canonical context и dynamic agent/workflow config
8. Этап 8. Совместимый adapter для существующего `ai-multi-agents`
9. Этап 9. Hardening, packaging и controlled rollout

## Почему такой порядок

- без четких трех слоев проект легко расползется;
- без local state и events нельзя сделать честную визуализацию;
- без provider abstraction нельзя безопасно подключать Kimi/DeepSeek;
- без tool runtime и session loop не получится контролировать cost и поведение;
- без workflow engine вы останетесь просто надстройкой;
- без project layer вы потеряете главное преимущество `ai-multi-agents`;
- adapter и rollout нужно делать после появления полноценного substrate, а не до него.

---

## Этап 1. Нормализация целевой платформы и границ трех слоев [выполнено]

Цель этапа: перестать мыслить задачей как "заменой чужого рантайма" и зафиксировать ее как построение собственной платформы.

### Задача 1.1. Зафиксировать трехслойную архитектуру [выполнено]

**Что сделать**

- Описать `core runtime`, `workflow layer`, `project layer`.
- Зафиксировать границы между ними.
- Явно указать, какие подсистемы текущего `ai-multi-agents` остаются, а какие эволюционируют.

**Критерии приемки**

- любой ключевой модуль можно отнести к одному слою;
- нет смешения runtime, workflow и project semantics;
- placement будущих модулей понятен заранее.

**Тесты**

- сделать mapping всех текущих ключевых подсистем;
- проверить, что для каждой есть решение: сохранить, вынести, переписать или обернуть.

### Задача 1.2. Зафиксировать продуктовые приоритеты [выполнено]

**Что сделать**

- Явно определить, что для проекта важнее всего:
  - local storage;
  - visual monitoring;
  - token/cost minimization;
  - dynamic workflows;
  - project configuration;
  - controlled agent behavior.

**Критерии приемки**

- приоритеты зафиксированы документально;
- roadmap больше не выглядит как "делаем просто свой chat runtime";
- optimization решений можно проверять против продуктовых целей.

**Тесты**

- проверить, что каждый следующий этап напрямую поддерживает хотя бы один продуктовый приоритет;
- убедиться, что нет крупных этапов "ради красивой архитектуры без пользы продукту".

### Задача 1.3. Зафиксировать судьбу `orchestrator*.md` [выполнено]

**Что сделать**

- Явно описать, какая логика уходит в код, а какая остается в policy docs.
- Разделить `machine logic` и `policy logic`.

**Критерии приемки**

- больше нет двусмысленности, что будет происходить с `orchestrator*.md`;
- понятно, что runtime переезжает только воспроизводимая исполняемая логика;
- `rules/*` сохраняют ценность как policy layer.

**Тесты**

- составить список минимум из 10 orchestration responsibilities и разнести их по двум категориям;
- проверить, что ни один критичный runtime transition не остается только в narrative markdown.

### Критерий этапа 1 [выполнено]

- целевая платформа описана точно;
- трехслойная модель зафиксирована;
- судьба `orchestrator*.md` понятна;
- roadmap синхронизирован с реальной целью проекта.

**Тест этапа**

- провести review документов и убедиться, что новый участник команды может объяснить архитектуру и продуктовую цель без устных уточнений.

### Артефакты этапа 1

- `context/INDEX.md`
- `context/arch/system-overview.md`
- `context/arch/repository-layout.md`
- `context/arch/state-and-persistence.md`
- `context/proto/external-workflow-and-cli.md`
- `context/proto/target-platform-interfaces-roadmap.md`

---

## Этап 2. Local state, event model и visual-first observability foundation [выполнено]

Цель этапа: сделать визуализацию и локальное хранение ядром системы, а не поздним дополнением.

### Задача 2.1. Зафиксировать локальную модель хранения [выполнено]

**Что сделать**

- Определить, что хранится локально:
  - runtime state;
  - event log;
  - snapshots;
  - episodic summaries;
  - usage/cost telemetry;
  - workflow definitions.

**Критерии приемки**

- storage model local-first;
- не требуется тяжелая внешняя БД;
- state пригоден для UI и resume.

**Тесты**

- пройтись по каждому типу данных и проверить формат хранения;
- проверить, что storage не подменяет `context/*`.

### Задача 2.2. Зафиксировать единый event contract [выполнено]

**Что сделать**

- Определить обязательные события для runtime, workflow и project layer.
- Сделать их пригодными для UI, state store и debugging.

**Критерии приемки**

- из событий можно восстановить выполнение;
- UI не зависит от ad-hoc логов;
- события не привязаны к одному провайдеру.

**Тесты**

- смоделировать типовой run и проверить полноту event mapping;
- проверить, что из event stream собирается snapshot.

### Задача 2.3. Зафиксировать visual-first модель мониторинга [выполнено]

**Что сделать**

- Описать, что UI должен уметь показывать:
  - активные workflows;
  - stages;
  - agents;
  - blocked states;
  - cost/tokens;
  - context usage;
  - последние key artifacts.

**Критерии приемки**

- visualization признана core feature;
- UI requirements формализованы до кодирования runtime;
- observability уже ориентирована на operator workflow.

**Тесты**

- составить экранную карту UI;
- проверить, что для каждого блока есть источник данных в event/state модели.

### Критерий этапа 2 [выполнено]

- локальное хранение описано;
- event model зафиксирована;
- визуализация встроена в архитектуру как core capability.

**Тест этапа**

- проверить, что по документам можно спроектировать минимальный local monitor без дополнительных архитектурных допущений.

### Артефакты этапа 2

- `context/arch/runtime-local-storage-model.md`
- `context/proto/runtime-event-contract.md`
- `context/arch/visual-monitoring-ui-map.md`
- `context/proto/deepseek-integration-test-contract.md` (сквозной контракт для этапов `3+`)

---

## Этап 3. Provider abstraction и transport foundation [выполнено]

Цель этапа: построить универсальный провайдерный слой для Kimi K2, DeepSeek и следующих моделей.

### Задача 3.1. Ввести capability-based provider interface [выполнено]

**Что сделать**

- Зафиксировать провайдерный интерфейс и capability matrix.
- Убрать vendor-specific логику из будущего session loop.

**Критерии приемки**

- новый провайдер можно добавить через adapter;
- capabilities описаны явно;
- runtime не знает бренд-специфичных деталей.

**Тесты**

- contract test на mock-provider;
- capability mapping test для Kimi и DeepSeek.

### Задача 3.2. Реализовать shared transport foundation [выполнено]

**Что сделать**

- Подготовить общий transport для:
  - chat completions;
  - streaming;
  - tool calling;
  - usage normalization;
  - timeout/retry hooks.

**Критерии приемки**

- transport единый для Kimi и DeepSeek;
- shared request/response format зафиксирован;
- fallback paths определены.

**Тесты**

- golden tests на text/tool/usage normalization;
- timeout и malformed response tests.

### Задача 3.3. Подключить Kimi K2 и DeepSeek как первые штатные провайдеры [выполнено]

**Что сделать**

- Реализовать Kimi adapter и DeepSeek adapter.
- Поддержать parser fallback и strict schema там, где нужно.

**Критерии приемки**

- оба провайдера работают через единый runtime contract;
- provider switch делается конфигом;
- future providers можно добавлять без изменения session loop.

**Тесты**

- tool calling smoke tests;
- streaming tests;
- provider switch regression test.

### Критерий этапа 3 [выполнено]

- provider layer работает как отдельная зрелая подсистема;
- Kimi и DeepSeek подключаются без vendor lock-in;
- транспорт готов для product runtime.

**Тест этапа**

- прогнать одинаковый сценарий через mock, Kimi и DeepSeek и сравнить внутренний нормализованный результат.

### Артефакты этапа 3

- `tools/agent_core/` — пакет: `Capability`, модели запроса/ответа, `HttpxJsonTransport`, retry, нормализация OpenAI-формата, streaming assembler, parser fallback;
- `tools/agent_core/providers/` — `ChatProvider`, `MockProvider`, `OpenAICompatProvider`, `KimiAdapter`, `DeepSeekAdapter`, `ProviderFactory`;
- `tools/agent_core/config_loader.py` — чтение `config/test.local.yaml` и ключей;
- `tests/test_*.py` — contract, capability matrix, golden normalization, transport errors, streaming, factory, gate parity Kimi/DeepSeek, live DeepSeek smoke (`@pytest.mark.integration`);
- `pyproject.toml` — зависимости `httpx`, `pyyaml`, pytest.

---

## Этап 4. Tool runtime, permissions и safety [выполнено]

Цель этапа: сделать tools first-class частью платформы.

### Задача 4.1. Ввести единый tool contract [выполнено]

**Что сделать**

- Зафиксировать schema, side effects, approval, concurrency и result normalization.

**Критерии приемки**

- инструменты описываются одинаково;
- tool metadata достаточно для runtime, UI и governance;
- контракт не зависит от модели.

**Тесты**

- schema validation tests;
- contract serialization tests.

### Задача 4.2. Реализовать permission и approval subsystem [выполнено]

**Что сделать**

- Разделить allow, ask, deny и session-scoped approvals.
- Связать approvals с pause/resume и UI.

**Критерии приемки**

- destructive paths контролируемы;
- approval flow совместим с visual runtime;
- решения по permission не размазаны по промптам.

**Тесты**

- allow/ask/deny tests;
- pending approval resume tests.

### Задача 4.3. Реализовать tool executor [выполнено]

**Что сделать**

- Поддержать serial/safe-parallel execution, ordered results и cancellation behavior.

**Критерии приемки**

- tool execution предсказуемо;
- concurrency контролируется;
- failures обрабатываются воспроизводимо.

**Тесты**

- mixed batch tests;
- cancellation tests;
- deterministic ordering tests.

### Критерий этапа 4 [выполнено]

- tools стали отдельным runtime-слоем;
- permission и safety больше не зависят только от поведения модели;
- платформа готова к управляемому агентному исполнению.

**Тест этапа**

- выполнить сценарий с read-only, write и approval-required tools и проверить корректность исполнения.

### Артефакты этапа 4

- `tools/agent_core/tool_runtime/` — `ToolSpec`, `SideEffectClass`, JSON Schema валидация, `PermissionEngine`, `ApprovalSession`, `ToolExecutor`, `ToolRegistry`, встроенные `echo` / `read_file` / `write_file` (песочница `AILIT_WORK_ROOT`);
- `tests/test_tool_runtime_*.py` — схема, permissions, executor, gate-сценарий этапа 4;
- зависимость `jsonschema` в `pyproject.toml`.

---

## Этап 5. Session loop, streaming и token-cost management [выполнено]

Цель этапа: сделать runtime управляемым по состоянию и стоимости.

### Задача 5.1. Реализовать явный session loop [выполнено]

**Что сделать**

- Ввести loop с явным состоянием, finish reasons, retries и pause semantics.

**Критерии приемки**

- runtime loop отделен от provider logic;
- поведение воспроизводимо;
- loop тестируется независимо.

**Тесты**

- state transition tests;
- retry tests;
- pause/resume tests.

### Задача 5.2. Реализовать streaming reducer [выполнено]

**Что сделать**

- Централизовать сбор text deltas, tool deltas и finish events.

**Критерии приемки**

- stream собирается в стабильное внутреннее состояние;
- tool chunks не ломают run;
- код stream-обработки централизован.

**Тесты**

- text reconstruction tests;
- tool delta assembly tests;
- malformed chunk tests.

### Задача 5.3. Реализовать shortlist и context compaction [выполнено]

**Что сделать**

- Подключить shortlist-подход к session loop.
- Реализовать compaction для history, tool outputs и summaries.

**Критерии приемки**

- в loop попадает только релевантный context;
- cost/token profile контролируется;
- canonical docs не подменяются working memory.

**Тесты**

- shortlist selection tests;
- budget exceed tests;
- compaction regression tests.

### Задача 5.4. Ввести cost/token governance [выполнено]

**Что сделать**

- Нормализовать usage/cost.
- Добавить budget signals, лимиты и стратегию снижения token cost.

**Критерии приемки**

- cost становится first-class runtime concern;
- decisions можно принимать по budget данным;
- token minimization встроена в архитектуру, а не вынесена в конец.

**Тесты**

- usage normalization tests;
- budget threshold tests;
- provider comparison tests.

### Критерий этапа 5 [выполнено]

- runtime умеет стабильно исполнять длинные сессии;
- token cost контролируется архитектурно;
- shortlist и compaction реально уменьшают контекст.

**Тест этапа**

- прогнать длинный агентный сценарий с tools, shortlist и compaction и сравнить token profile до и после оптимизаций.

### Артефакты этапа 5

- `tools/agent_core/session/` — `SessionState`, `SessionRunner`, `SessionSettings`, `SessionOutcome`, `BudgetGovernance`, `compact_messages`, `apply_keyword_shortlist`, `StreamReducer`, мост `tool_definitions_from_registry`;
- расширение `ChatMessage.tool_calls` и сериализация в [openai_request.py](tools/agent_core/normalization/openai_request.py);
- `tests/test_session_*.py`, `tests/test_openai_request_tool_calls.py`.

---

## Этап 6. Workflow engine и перенос machine logic из `orchestrator*.md` [выполнено]

Цель этапа: превратить платформу из просто runtime в engine проектных workflow.

### Задача 6.1. Формализовать workflow graph [выполнено]

**Что сделать**

- Описать сущности:
  - workflow;
  - stage;
  - task;
  - transition;
  - barrier;
  - blocked reason;
  - human gate.

**Критерии приемки**

- workflow engine существует как first-class подсистема;
- orchestration больше не живет только в markdown;
- graph пригоден для UI и state store.

**Тесты**

- transition table tests;
- blocked/review path tests.

### Задача 6.2. Перенести machine logic из `orchestrator*.md` в runtime [выполнено]

**Что сделать**

- Вынести в код:
  - stage transitions;
  - retries;
  - resume;
  - escalation;
  - lifecycle events;
  - artifact checkpoints.

**Критерии приемки**

- критичная orchestration logic исполняется кодом;
- `rules/*` остаются policy layer;
- поведение можно тестировать без интерпретации большого markdown.

**Тесты**

- dry run tests на feature workflow;
- blocked/resume tests;
- artifact lifecycle tests.

### Задача 6.3. Сохранить policy-driven роли и hybrid режим [выполнено]

**Что сделать**

- Оставить role behavior и project-specific policy в markdown.
- Сохранить переходный hybrid режим.

**Критерии приемки**

- проект не теряет свою текущую силу в policy layer;
- migration можно делать поэтапно;
- rollback path остается понятным.

**Тесты**

- hybrid mode tests;
- rollback tests;
- compatibility tests со старыми правилами.

### Критерий этапа 6 [выполнено]

- у платформы есть workflow engine;
- machine logic больше не зависит от narrative orchestration;
- policy layer сохранен.

**Тест этапа**

- исполнить один и тот же workflow в hybrid и native режимах и сравнить transitions, artifacts и events.

### Артефакты этапа 6

- `tools/workflow_engine/` — `Workflow`, `Stage`, `Task`, `Transition`, `Barrier`, `HumanGate`, `BlockedReason`, загрузка YAML, `WorkflowEngine` с контрактом **`workflow_run_events_v1`** (JSONL в stdout);
- `tools/ailit/` — CLI `ailit` (`ailit chat` → Streamlit, `ailit agent run` → workflow);
- [user-test.md](user-test.md) — ручная проверка DeepSeek и CLI;
- [examples/workflows/minimal.yaml](examples/workflows/minimal.yaml);
- `pyproject.toml` — `project.scripts.ailit`, optional `[chat]`, пакеты `workflow_engine`, `ailit`;
- `tests/test_workflow_engine.py`.

---

## Этап 7. Project layer, canonical context и dynamic agent/workflow config

Цель этапа: сделать платформу по-настоящему настраиваемой под проект.

### Задача 7.1. Зафиксировать boundaries project layer

**Что сделать**

- Описать, где живут:
  - project rules;
  - canonical context;
  - project workflows;
  - project agents;
  - project-specific memory hints.

**Критерии приемки**

- project semantics отделены от core runtime;
- `context/*` остается source of truth;
- workflows можно адаптировать под проект без форка ядра.

**Тесты**

- boundary review test;
- test на отсутствие смешения project config и runtime internals.

### Задача 7.2. Ввести dynamic registration для agents и workflows

**Что сделать**

- Определить формат регистрации агентов и workflow под проект.
- Поддержать расширение без переписывания core runtime.

**Критерии приемки**

- новый агент можно добавить конфигурационно;
- новый workflow можно подключить без архитектурного взлома;
- проектная кастомизация становится штатной возможностью.

**Тесты**

- agent registration smoke test;
- workflow registration smoke test;
- override/fallback config tests.

### Задача 7.3. Встроить canonical context в execution path

**Что сделать**

- Использовать `knowledge_refresh` и shortlist как штатный контекстный слой.
- Сохранить разделение между canonical, working и episodic memory.

**Критерии приемки**

- platform использует `context/*` правильно;
- runtime не превращает knowledge layer в мусорный dump;
- project knowledge и workflow execution связаны осознанно.

**Тесты**

- shortlist tests;
- context selection regression tests;
- memory boundary tests.

### Критерий этапа 7

- project layer стал полноценным уровнем платформы;
- система поддерживает dynamic agents/workflows;
- canonical context встроен в execution path.

**Тест этапа**

- подключить test workflow и test agent в конфиге проекта и убедиться, что они исполняются через общий runtime без изменений в core.

---

## Этап 8. Совместимый adapter для существующего `ai-multi-agents`

Цель этапа: встроить новую платформу в текущий pipeline без резкого разрыва.

### Задача 8.1. Ввести compatibility adapter

**Что сделать**

- Подготовить adapter между текущими entrypoints и новым runtime/workflow engine.

**Критерии приемки**

- существующий pipeline может вызывать новый runtime;
- artifact contracts сохраняются;
- migration path остается обратимым.

**Тесты**

- compatibility tests на ролях;
- artifact parser regression tests.

### Задача 8.2. Связать adapter с state, events и UI

**Что сделать**

- Подключить compatibility path к runtime state, events и visual monitoring.

**Критерии приемки**

- старый pipeline становится наблюдаемым через новый runtime;
- `status.md`, snapshots и UI остаются согласованными;
- local monitor может показывать реальные project runs.

**Тесты**

- snapshot consistency tests;
- UI integration smoke tests.

### Задача 8.3. Ввести controlled runtime switch

**Что сделать**

- Позволить проекту выбрать старый или новый runtime конфигом.

**Критерии приемки**

- rollback path жив;
- installer и docs поддерживают оба режима;
- cutover можно делать постепенно.

**Тесты**

- config switch tests;
- fallback tests;
- install smoke tests.

### Критерий этапа 8

- новая платформа встроена в текущий `ai-multi-agents`;
- migration path безопасен;
- старый и новый режимы могут сосуществовать.

**Тест этапа**

- выполнить малый реальный workflow через compatibility adapter и проверить artifacts, events, UI и status projection.

---

## Этап 9. Hardening, packaging и controlled rollout

Цель этапа: довести платформу до состояния реального продукта.

### Задача 9.1. Подготовить packaging и installer

**Что сделать**

- Зафиксировать, как раскладываются `core runtime`, `workflow layer` и project-facing части.

**Критерии приемки**

- installer умеет ставить новые слои;
- low-infra модель не ломается;
- selective rollout возможен.

**Тесты**

- clean install tests;
- update install tests.

### Задача 9.2. Довести observability и debug bundle

**Что сделать**

- Подготовить operator-friendly debug path:
  - snapshots;
  - raw events;
  - workflow trace;
  - token/cost trace;
  - blocked reasons.

**Критерии приемки**

- по debug bundle можно диагностировать runtime issue;
- данные пригодны для локальной эксплуатации;
- визуализация и диагностика опираются на одни и те же данные.

**Тесты**

- debug completeness tests;
- blocked/retry/success scenario tests.

### Задача 9.3. Провести staged rollout

**Что сделать**

- Разделить rollout на:
  - internal alpha;
  - hybrid beta;
  - default-on;
  - optional legacy fallback.

**Критерии приемки**

- у каждой фазы есть exit criteria;
- cutover идет по фактам;
- внешние CLI становятся fallback, а не ядром.

**Тесты**

- rollout checklist tests;
- rollback drills;
- side-by-side comparisons.

### Критерий этапа 9

- платформа готова к реальному использованию;
- новый runtime и workflow engine стали основным substrate;
- внешние CLI больше не являются обязательным вычислительным ядром.

**Тест этапа**

- выполнить сценарий "чистая установка -> проектный workflow -> tools -> UI -> completion" без обязательной зависимости от Cursor/Claude CLI.

---

## Боевой порядок выполнения

Строго сверху вниз:

1. Этап 1
2. Этап 2
3. Этап 3
4. Этап 4
5. Этап 5
6. Этап 6
7. Этап 7
8. Этап 8
9. Этап 9

## Ожидаемый итог

После прохождения workflow проект должен получить:

1. собственный `core runtime`;
2. собственный `workflow engine`;
3. полноценный `project layer` поверх них;
4. local state и local monitor UI;
5. Kimi K2 и DeepSeek через общий provider layer;
6. token/cost governance как core capability;
7. dynamic agents и workflows под проект;
8. использование `context/*` как canonical context layer;
9. controlled migration off Cursor/Claude Code;
10. платформу AI-агентов, а не просто надстройку над чужим runtime.
