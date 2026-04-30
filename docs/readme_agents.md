# Мультиагентные пайплайны

Обзор для **оператора**: зачем CLI, где лежат роли и контекст. Детальные процедуры — в правилах ядра (см. [`.cursor/README.md`](../.cursor/README.md) в установленном проекте).

## Иерархия правил

1. **Ядро** — `.cursor/rules/system/`: **не** править вручную в продуктовых репозиториях; обновлять из установленного пакета шаблонов.
2. **Проект** — `.cursor/rules/project/`: **обязательно** заполнить; точка входа **`project-config.mdc`**.

Опционально можно добавить `project-agent-models.mdc` в том же каталоге, чтобы закрепить модель для каждого агента. Если файл отсутствует или агент не указан, используется `auto`.

## Каталоги в продуктовом репозитории

| Путь | Назначение |
|------|------------|
| `context/arch/` | Границы процессов и их внутренняя декомпозиция |
| `context/proto/` | Контракты между процессами |
| `context/start/` | Способы запуска, env, порядок старта, зависимости |
| `context/tests/` | Тестовые группы, entrypoint'ы, покрытие, артефакты |
| `context/memories/` | Воспоминания о работе между задачами |
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

Точка входа: **`rules/start-learn-project.mdc`**. Только агенты **12** → **13**; создаётся/дополняется `context/`; в `rules/project/` разрешено обновлять только `project-config.mdc` и его поле `learn_last_run_at`.

## Pipeline (обзор)

### `feature`

Анализ → архитектура → план → разработка по задачам → review кода → **11_test_runner** → **12_change_inventory** → **13_tech_writer** → при наличии `project-milestones.mdc` обновление `context/workflow.md`.

### `fix` / `research`

См. `start-fix.mdc` и `start-research.mdc`.

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
