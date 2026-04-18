# Мультиагентные пайплайны

Обзор для **оператора**: зачем CLI, где лежат роли и контекст. Детальные процедуры — в правилах ядра (см. [`.cursor/README.md`](../.cursor/README.md) в установленном проекте).

## Иерархия правил

1. **Ядро** — `.cursor/rules/system/`: **не** править вручную в продуктовых репозиториях; обновлять из установленного пакета шаблонов.
2. **Проект** — `.cursor/rules/project/`: **обязательно** заполнить; точка входа **`project-config.mdc`**.

Опционально можно добавить `project-agent-models.mdc` в том же каталоге, чтобы закрепить модель для каждого агента. Если файл отсутствует или агент не указан, используется `auto`. Для project-level learn scope можно добавить `project-learn-boundaries.mdc`: он задаёт source of truth для product vs tooling boundaries и позволяет исключить `context/tools/**` из product inventory без правки ядра.

## Каталоги в продуктовом репозитории

| Путь | Назначение |
|------|------------|
| `context/arch/` | Границы процессов и их внутренняя декомпозиция |
| `context/proto/` | Контракты между процессами |
| `context/start/` | Способы запуска, env, порядок старта, зависимости |
| `context/tests/` | Тестовые группы, entrypoint'ы, покрытие, артефакты |
| `context/memories/` | Воспоминания о работе между задачами |
| `context/tools/knowledge_refresh/` | Локальный helper layer для derived index, context pack и self-learning |
| `context/knowledge_index.sqlite3` | Производный локальный SQLite index, перестраиваемый из `context/*` |
| `context/workflow.md` | План по вехам **только если** подключён `project-milestones.mdc` |
| `context/artifacts/` | `status.md`, логи, черновики (**не коммитить**) |

## Контракты артефактов и JSON

См. `rules/system/artifacts/README.md` и файлы `artifact-*.mdc`.

## Почему «ничего не запускается»

Обычный чат — **один** сеанс. **Субагентов** нужно вызывать shell-командами **`agent …`** и **дождаться** результата каждого вызова (см. [референс](https://github.com/rdudov/agents/blob/master/README.md)).

Установка CLI Cursor: `curl https://cursor.com/install | bash`, затем `agent login`.

### Вызов `agent` из shell (роли с YAML `---`)

Текст запроса передаётся **позиционно** в конце команды (не через вымышленный «`-p` текст»: у Cursor `-p` — это `--print`). Чтобы начало файла роли с `---` не ломало разбор argv, после всех флагов ставь **`--`**, затем один закавыченный промпт. Пример и пояснения — в `rules/system/main/orchestrator-duties.mdc` (раздел «Запуск CLI») в установленном шаблоне.

## Запуск feature

Точка входа: **`rules/start-feature.mdc`** (в Cursor — `.cursor/rules/start-feature.mdc`). Постановка — **в конце** сообщения пользователя.

Шаблоны этапов: `rules/system/main/orchestrator-stage-*.mdc`.

## Запуск learn-проекта

Точка входа: **`rules/start-learn-project.mdc`**. Только агенты **12** → **13**; создаётся/дополняется `context/`; ведётся `context/artifacts/status.md`; после canonical-слоя допускается derived sync в `context/knowledge_index.sqlite3`; в `rules/project/` разрешено обновлять только `project-config.mdc` и его поле `learn_last_run_at`.

Если установлен runtime helper и доступен addon `monitor_ui`, `start-learn-project` сам вызовет `python3 -m context.tools.runtime.cli --repo-root . ensure-monitor`: monitor UI поднимется в фоне и откроется в браузере без блокировки orchestrator-сессии. Metadata процесса хранится в `context/runtime/monitor_server.json`, лог по умолчанию пишется в `context/runtime/monitor_server.log`.

Если в `rules/project/` есть `project-learn-boundaries.mdc`, оркестратор и агенты `12`/`13` обязаны следовать ему как project-level контракту для learn scope. Это особенно важно для репозиториев, где `context/tools/**` содержит helper-layer код, но не является продуктом.

## Knowledge Refresh

Knowledge refresh в Cursor-режиме работает как пополнение закоммиченного знания проекта без внешнего обязательного сервиса.

### Bootstrap через `start-learn-project`

Первый проход по новому проекту:

- запусти `rules/start-learn-project.mdc`;
- агент **12_change_inventory** соберёт факты о репозитории;
- агент **13_tech_writer** создаст или дополнит `context/arch/`, `context/proto/`, `context/start/`, `context/tests/`, `context/memories/`;
- оркестратор будет вести `context/artifacts/status.md`;
- если helper layer установлен, после writer pipeline выполнится derived sync в `context/knowledge_index.sqlite3`;
- в `rules/project/project-config.mdc` обновится только `learn_last_run_at`.

Итог bootstrap: в репозитории появляется canonical knowledge layer, пригодный для следующих feature/fix задач.

### Что является источником правды

- `context/arch/`
- `context/proto/`
- `context/start/`
- `context/tests/`
- `context/memories/`
- `INDEX.md` в knowledge-разделах и `context/memories/index.md`

Именно эти файлы считаются долговременным знанием проекта и должны проходить обычный review как часть репозитория.

### Что НЕ является источником правды

- `context/artifacts/` — только временные артефакты pipeline;
- локальный SQLite index и self-learning metadata — только производный ускоритель;
- optional semantic retrieval — только дополнительный слой поиска.

Если локальная DB или feedback metadata повреждены, рабочим источником всё равно остаётся `context/*`.

### Как knowledge refresh работает в `feature`

После успешного review кода и verify:

1. **11_test_runner** подтверждает проверку.
2. **12_change_inventory** конденсирует факты изменений в `context/artifacts/change_inventory.md`.
3. **13_tech_writer** обновляет только затронутые части `context/*`, `INDEX.md` и `context/memories/index.md`.
4. Если проект поддерживает локальный DB index, после writer pipeline выполняется только производный selective sync.

Это означает, что знания проекта пополняются после завершённой задачи, а не по сырым runtime-событиям.

### Как читать знания перед новой задачей

Перед новой задачей не нужно читать весь `context/`.

Рекомендуемый порядок:

1. Сначала прочитать только корневые индексные точки:
   - `context/arch/INDEX.md`
   - `context/proto/INDEX.md`
   - `context/start/INDEX.md`
   - `context/tests/INDEX.md`
   - `context/memories/index.md`
2. Для `arch` и при необходимости для `proto` сначала открыть только верхнеуровневые `overview`-документы.
3. Читать локальный `INDEX.md` внутри подпапки и `detail`-документы только если overview указывает на сложную зону.
4. Открыть полные knowledge files только для выбранных процессов, протоколов, запусков, тестов или memory entries.

Это и есть index-first и overview-first reading, на котором держится экономия токенов.

### Что означают root index, overview и detail

- `root INDEX.md` даёт карту раздела и помогает не читать лишнее.
- `overview`-документ объясняет модуль или подсистему на уровне, достаточном для большинства feature/fix задач.
- `detail`-документы нужны только для сложных или часто меняющихся внутренних зон и читаются выборочно.

Для `context/arch/` такая иерархия считается базовой. Для `context/proto/` второй уровень включается только там, где один overview уже не покрывает сложность.

### Anti-dup policy простыми словами

- canonical docs не должны начинаться с breadcrumb-шума вроде `Назад к индексу`;
- навигация должна жить в индексах и структуре каталогов;
- первая полезная строка документа должна объяснять содержание, а не повторять путь до файла.

### Роль локальной DB

Локальный DB index:

- ускоряет retrieval;
- хранит summaries, fingerprints, sync-state, relations и retrieval hints;
- может использоваться для self-learning feedback;
- полностью перестраивается из `context/*`.

Он не заменяет `context/*`, не должен быть единственным местом хранения знания и не обязателен для базового bootstrap-сценария.

### Как запускать helper layer в существующем проекте

После установки `full` или `system` helper layer находится в самом целевом репозитории по пути `context/tools/knowledge_refresh/`. Запускай его из корня проекта.

Runtime helper layer поддерживает два install-профиля:

- `--runtime-profile full` — runtime core и все optional addons;
- `--runtime-profile core` — только runtime core;
- `--runtime-addons monitor_ui,provider_analytics` — selective re-enable addons поверх `core`.

Пример для локального monitor без autopilot:

```bash
bash scripts/install-multiagent.sh --cursor --target "$(pwd)" --scope system --runtime-profile core --runtime-addons monitor_ui,provider_analytics
```

`monitor_ui` нужен не только для ручного `start-monitor`, но и для автозапуска UI из `start-feature`, `start-fix` и `start-learn-project`. При повторном запуске поддерживаемого pipeline existing monitor переиспользуется через metadata в `context/runtime/`. Если автозапуск нужно временно отключить, выставь `AI_MULTI_AGENTS_DISABLE_MONITOR_AUTOSTART=1` перед запуском IDE/CLI.

Минимально нужно:

- установленный `.cursor/` шаблон в целевом проекте;
- установленный helper layer в `context/tools/knowledge_refresh/`;
- `agent` CLI Cursor и `agent login`;
- `python3`.

Дополнительные Python-зависимости не нужны: helper layer использует только стандартную библиотеку.

Пример:

```bash
python3 -m context.tools.knowledge_refresh.cli sync-db
python3 -m context.tools.knowledge_refresh.cli \
  plan-context \
  --task "review feature module" \
  --scope arch \
  --scope proto \
  --task-type feature
```

По умолчанию persistent DB хранится в `context/knowledge_index.sqlite3`. `context/artifacts/` остаётся только временным каталогом pipeline.

Во `feature` этот helper можно использовать как optional shortlisting layer: сначала отобрать только релевантные root indexes, overview docs и 1-2 detail docs, а потом передавать их агенту вместо широкого чтения всего `context/*`.

### Mini web viewer

После установки helper layer в проект также попадает read-only entrypoint:

```bash
context/tools/knowledge_refresh/start-web --db-path context/knowledge_index.sqlite3
```

Опционально можно передать порт:

```bash
context/tools/knowledge_refresh/start-web --port 8877
```

Viewer поднимает локальный HTTP server для `context/knowledge_index.sqlite3`, печатает URL в stdout и даёт кнопки для типовых диагностических запросов: список таблиц, counts, documents, sections, relations, sync-state и retrieval hints.

Viewer нужен как локальный диагностический инструмент оператора. Он не меняет canonical docs, не запускает sync автоматически и не является обязательной частью pipeline.

### Rollout второго этапа

- обнови установленное ядро через installer;
- для нового проекта запусти `start-learn-project`, чтобы writer сразу строил knowledge layer по новой схеме;
- для существующего проекта второй уровень детализации будет появляться постепенно, только в high-signal зонах;
- если nested detail не нужен, knowledge layer остаётся компактным и продолжает работать через root indexes и overview docs.

## Pipeline (обзор)

### `feature`

Анализ → архитектура → план → разработка по задачам → review кода → **11_test_runner** → **12_change_inventory** → **13_tech_writer** → при наличии `project-milestones.mdc` обновление `context/workflow.md`.

### `fix`

См. `start-fix.mdc`.

### `research`

`start-research` пока остаётся заглушкой и не входит в набор поддерживаемых runtime/UI pipelines.

### Падение тестов

`rules/system/test/pipeline-test-failure.mdc`.

## Кто обновляет `context/`

| Этап | Агент | Когда запускается | Что обновляет |
|------|-------|-------------------|---------------|
| learn: инвентаризация | `12_change_inventory` | Первый шаг `start-learn-project` | Не пишет `context/`; готовит `{artifacts_dir}/change_inventory.md` как фактическую сводку по репозиторию |
| learn: запись контекста | `13_tech_writer` | После `12_change_inventory` в `start-learn-project` | `context/arch/`, `context/proto/`, `context/start/`, `context/tests/`, `context/memories/`; в `rules/project/` меняет только `project-config.mdc` |
| feature: архитектура | `04_architect` | После утверждения ТЗ | Актуализирует `context/arch/` и `context/proto/`, если архитектурные решения меняют границы процессов или контракты |
| feature: после review и тестов | `12_change_inventory` | После успешных `09_code_reviewer` и `11_test_runner` или допустимого локального успеха `08_developer` | Не пишет `context/`; собирает факты по реально сделанным изменениям текущей задачи |
| feature: после инвентаризации | `13_tech_writer` | После `12_change_inventory` для каждой задачи итерации | `context/arch/`, `context/proto/`, `context/start/`, `context/tests/`, `context/memories/` |
| feature: память итерации | `13_tech_writer` | На каждом завершённом проходе задачи после инвентаризации | Создаёт или обновляет файл `context/memories/feature_<task_description>_<time>.md` и `context/memories/index.md` |

## Роли

| № | Роль |
|---|------|
| 01 | Оркестратор |
| 02–11 | Как в `.cursor/README.md` |
| 12 | Инвентаризация изменений и репозитория (feature / learn) |
| 13 | Глубокое обновление `context/` (feature / learn) |
