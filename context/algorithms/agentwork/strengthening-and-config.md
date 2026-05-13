# Усиление AgentWork: конфигурация, данные и операционные рычаги

Раздел для человека и для `start-feature`: что реально меняет поведение, а что только диагностирует.

## Конфигурация `agent_work` (merge YAML)

Секция задаётся в `ailit/ailit_cli/merged_config.py` по умолчанию и перекрывается проектным `ailit` config.

| Поле | Эффект |
|------|--------|
| `enabled` | Включает микро-оркестратор (`WorkTaskOrchestrator`). `false` — прямой прогон без classify/plan/verify. |
| `active_profile` | Ключ в `profiles`. |
| `profiles.*.micro_plan` | Сейчас в коде по сути один режим строки; зарезервировано для профилей. |
| `verify_policy` | `python_default` — pytest + flake8 на small_code_change; иное значение отключает сбор verify-команд. |
| `max_repair_attempts` | Сколько раз разрешён repair после verify (целое ≥ 0). |
| `large_task_policy` | `decompose_only` — для крупных задач только текст декомпозиции без полного execute. |

Расширение: новые профили в `profiles` позволяют разным чатам (если провайдер конфига это поддержит) иметь разные лимиты repair и verify.

## Конфигурация `memory` (влияние на AgentWork)

| Поле | Эффект на AgentWork |
|------|---------------------|
| `enabled` | Включает KB tools в реестре и KB-first hint на первом сообщении. |
| `namespace` | Пишется в `AILIT_KB_NAMESPACE` при сборке реестра; участвует в fallback для `build_mode_kb_namespace`. |
| `runtime.max_memory_queries_per_user_turn` | Лимит RPC-итераций к AgentMemory за один user prompt. |

См. также пакет **`../agent-memory/`** для тонкой настройки таймаутов RPC и семантики W14.

## Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `AILIT_WORK_ROOT` / `AILIT_WORK_ROOTS` | Выставляются Assembler’ом: корни для file/bash tools. |
| `AILIT_KB`, `AILIT_KB_DB_PATH`, `AILIT_KB_NAMESPACE` | Локальная KB для `kb_*` и для perm KB reader/writer. |
| `AILIT_WORK_AGENT_PERM` | Включение perm-5 в AgentWork (`0` — выкл.). |
| `AILIT_PERM_TOOL_MODE` | Принудительный режим инструментов, если не ждём UI. |
| `AILIT_MULTI_AGENT` | Bypass perm-классификатора (режим ближе к edit для оркестраторских сценариев). |
| `AILIT_WORK_MICRO_ORCHESTRATOR` | Отключение микро-оркестратора целиком. |

## Усиление качества ответов (без правки кода)

1. **Заполнить PAG через AgentMemory** (`ailit memory init` и сопутствующие команды): тогда slice перед ходом несёт релевантные узлы, модель реже «стреляет вслепую».
2. **Заполнить SQLite KB фактами** (`kb_write_fact` или пайплайны авто-фактов): KB-first и ручные вызовы `kb_search` дают дешёвый контекст до тяжёлого grep/list_dir.
3. **Зафиксировать perm default в проекте** через UI «remember» после `not_sure` — меньше лишних вопросов и стабильнее режим записи.
4. **Формулировать задачи в зоне SMALL_CODE_CHANGE**: короткие глаголы и пути к файлам улучшают классификатор и извлечение `expected_files` в плане.
5. **Держать тесты рядом с кодом**: verify gate реально запускает pytest только для обнаруженных тестовых путей.

## Идеи для развития (implementation backlog)

Это **не** текущие обещания репозитория, а направления, которые логично вешать на задачи:

- **LLM micro-planner** вместо или в дополнение к `MicroPlanner` для нетривиальных ветвлений (с жёстким JSON schema и лимитом токенов).
- **Расширение verify_policy**: типовые команды для `npm test`, `cargo test`, контейнерный изолированный runner.
- **Согласование namespace**: один явный источник правды для AgentMemory namespace и `AILIT_KB_NAMESPACE`, чтобы slice и kb_* смотрели в согласованное адресное пространство проекта.
- **Метрики continuation**: телеметрия среднего числа RPC memory за ход для подстройки cap и `stop_condition` на стороне AgentMemory.
- **Классификатор задач на LLM** только как opt-in: детерминированный путь остаётся дефолтом для предсказуемости CI.

## Связь с системным промптом

Базовый system для сессии задаётся в `_WorkChatSession` через `merge_with_base_system("You are a helpful concise assistant.")` — усиление «личности» агента делается либо правкой этой базы (осторожно: затрагивает все чаты), либо проектными слоями конфигурации, если появятся хуки (сейчас основной рычаг — tool hints + memory slice + orchestrator hints).
