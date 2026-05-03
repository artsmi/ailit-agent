# Мультиагентные пайплайны

Обзор для **оператора**: где лежат роли, точки входа и canonical context. Детальные процедуры теперь описаны в самодостаточных файлах `.cursor/agents/*.md` и entrypoint-правилах `.cursor/rules/start-*.mdc`.

## Иерархия правил

1. **Агенты** — `.cursor/agents/`: самодостаточные prompt-файлы ролей `00`-`17`.
2. **Проект** — `.cursor/rules/project/`: проектные overrides; точка входа **`project-config.mdc`**.
3. **Точки входа** — `.cursor/rules/start-*.mdc`: `feature`, `fix`, `learn`, `research`.

В **ailit-agent** в репозитории закреплён `project-agent-models.mdc`: все роли Subagent идут по карте (по умолчанию `Auto` — без явного `model` в tool call). Явные slug вроде `gpt-5.5-medium` не подставлять без строки в карте. В других репозиториях на базе этого шаблона файл может быть опционален; тогда fallback задаётся правилами оркестратора.

## Каталоги в продуктовом репозитории

| Путь | Назначение |
|------|------------|
| `context/arch/` | Границы процессов и их внутренняя декомпозиция |
| `context/install/` | Установка, packaging, update/uninstall |
| `context/modules/` | Карта модулей и ownership |
| `context/files/` | Meaningful file catalog; generated/vendor группируются отдельно |
| `context/models/` | DTO, config models, trace events |
| `context/proto/` | Контракты между процессами |
| `context/start/` | Способы запуска, env, порядок старта, зависимости |
| `context/tests/` | Тестовые группы, entrypoint'ы, покрытие, артефакты |
| `context/memories/` | Воспоминания о работе между задачами |
| `context/workflow.md` | План по вехам **только если** подключён `project-milestones.mdc` |
| `context/artifacts/` | `status.md`, логи, черновики (**не коммитить**) |

## Контракты артефактов и JSON

Контракты JSON и markdown-артефактов встроены в соответствующие agent-файлы: `.cursor/agents/02_*.md` ... `.cursor/agents/17_*.md`. Оркестратор сверяет ответы по схемам, описанным в этих файлах.

## Почему «ничего не запускается»

Обычный чат — **один** сеанс. Для pipeline `01_orchestrator` запускает роли `02+` отдельными Cursor Subagents согласно `.cursor/agents/01_orchestrator.md`. Если Subagents недоступны, pipeline останавливается с blocker.

## Запуск feature

Точка входа: **`rules/start-feature.mdc`** (в Cursor — `.cursor/rules/start-feature.mdc`). Постановка — **в конце** сообщения пользователя.

Режим `feature`: `02 → 03 → 04 → 05 → 06 → 07 → task_waves(08→09→11) → final 11 → 12 → 13 → auto commit`.

## Запуск learn-проекта

Точка входа: **`rules/start-learn-project.mdc`**. Только агенты **12** → **13**; создаётся/дополняется `context/`; в `rules/project/` разрешено обновлять только `project-config.mdc` и его поле `learn_last_run_at`.

## Pipeline (обзор)

### `feature`

Анализ → архитектура → план → разработка по задачам → review кода → **11_test_runner** → **12_change_inventory** → **13_tech_writer** → при наличии `project-milestones.mdc` обновление `context/workflow.md`.

### `fix` / `research`

См. `start-fix.mdc` и `start-research.mdc`.

### Падение тестов

См. `.cursor/agents/11_test_runner.md`: `failed` ведёт к `fix_by_tests`, `blocked_by_environment` требует разблокировки или эскалации, `passed` не заменяет code review approval.

## Кто обновляет `context/`

| Этап | Агент | Когда запускается | Что обновляет |
|------|-------|-------------------|---------------|
| learn: инвентаризация | `12_change_inventory` | Первый шаг `start-learn-project` | Не пишет `context/`; готовит `{artifacts_dir}/change_inventory.md` как фактическую сводку по репозиторию |
| learn: запись контекста | `13_tech_writer` | После `12_change_inventory` в `start-learn-project` | `context/arch/`, `context/install/`, `context/start/`, `context/modules/`, `context/files/`, `context/models/`, `context/proto/`, `context/tests/`, `context/memories/` |
| feature/fix: после финального verify | `12_change_inventory` | После успешного final `11_test_runner` | Не пишет `context/`; собирает факты по суммарному diff до commit |
| feature/fix: запись контекста | `13_tech_writer` | После `12_change_inventory` | Обновляет только затронутые canonical sections |
| feature: память итерации | `13_tech_writer` | На каждом завершённом проходе задачи после инвентаризации | Создаёт или обновляет файл `context/memories/feature_<task_description>_<time>.md` и `context/memories/index.md` |

## Роли

| № | Роль |
|---|------|
| 01 | Оркестратор |
| 02–09 | Feature/fix: анализ, review, архитектура, план, разработка, code review |
| 10 | Общий researcher для отдельных вопросов |
| 11 | Независимый verify |
| 12 | Инвентаризация изменений и репозитория (feature / learn) |
| 13 | Глубокое обновление `context/` (feature / learn) |
| 14 | Donor researcher для research pipeline |
| 15 | Research synthesizer |
| 16 | Plan author |
| 17 | Research plan reviewer |
