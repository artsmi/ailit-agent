# Каталог `~/.ailit` и переменные окружения

Этот документ описывает типичное **глобальное дерево данных пользователя** (по умолчанию `~/.ailit`) и **переменные окружения**, которые подменяют отдельные ветки. Значения по умолчанию для YAML-слияния см. в коде `ailit_cli.merged_config._default_ailit_config`.

## Корень: `AILIT_HOME` или `~/.ailit`

| Путь (относительно дома) | Назначение |
|--------------------------|------------|
| `config/` | Пользовательские YAML/JSON слои конфигурации. Основной активный файл — обычно `config/config.yaml` (см. `GlobalDirResolver` в `ailit_cli.user_paths`). |
| `state/` | Состояние: кэши, логи, артефакты сессий. |
| `state/logs/` | JSONL-логи процессов (`ailit-agent-*.log` и др.). |
| `runtime/` | Если не задан `AILIT_RUNTIME_DIR` и нет `XDG_RUNTIME_DIR`: сокеты supervisor/broker и рабочие файлы рантайма. |
| `pag/store.sqlite3` | По умолчанию SQLite **PAG** (граф архитектуры проекта), если не задан `AILIT_PAG_DB_PATH`. |
| `kb.sqlite3` | По умолчанию SQLite **KB** (факты), если не задан `AILIT_KB_DB_PATH`. |
| `projects/<id>/` | Глобальный реестр проектов (см. `global_ailit_layout.user_projects_root`). |
| `config.yaml` (в корне `.ailit`) | Альтернативный индекс активных id + schema (см. `global_ailit_layout.user_global_config_path`). |

## Переменные окружения (override)

| Переменная | За что отвечает |
|------------|-----------------|
| `AILIT_HOME` | Единый корень вместо `~/.ailit` для веток `config/` и `state/` (если не заданы отдельные `AILIT_CONFIG_DIR` / `AILIT_STATE_DIR`). |
| `AILIT_CONFIG_DIR` | Полный путь к каталогу конфигурации (в тестах — изолированный tmp). |
| `AILIT_STATE_DIR` | Полный путь к каталогу состояния и логов. |
| `AILIT_RUNTIME_DIR` | Каталог Unix-сокетов supervisor/broker и прочего runtime (приоритетнее `XDG_RUNTIME_DIR/ailit`). |
| `AILIT_PAG_DB_PATH` | Путь к файлу SQLite PAG (в тестах подменяется autouse-фикстурой). |
| `AILIT_KB_DB_PATH` | Путь к файлу SQLite KB. |
| `AILIT_MEMORY_JOURNAL_PATH` | JSONL-журнал шагов AgentMemory. |
| `AILIT_WORK_ROOT` | Корень work для инструментов агента в сценариях, где он используется. |
| `AILIT_WORK_ROOTS` | JSON-список корней (приоритет над `AILIT_WORK_ROOT` в части кода). |
| `AILIT_AGENT_MEMORY_CHAT_LOG_DIR` | Каталог human-readable chat/debug логов AgentMemory. |
| `AILIT_PAG` | Включение/флаги PAG в сессии (см. `PagRuntimeConfig.from_env`). |
| `AILIT_PAG_DB_PATH` | Явный путь к БД PAG. |
| `AILIT_PAG_TOP_K`, `AILIT_PAG_MAX_CHARS`, `AILIT_PAG_SYNC_ON_WRITE` | Лимиты и политика синхронизации PAG (см. `agent_memory.pag_runtime`). |
| `DEEPSEEK_API_KEY`, `KIMI_API_KEY`, `MOONSHOT_API_KEY` | Секреты провайдеров; могут накладываться на merge-конфиг (см. `merged_config.ProviderEnvOverlay`). |

## Файл `config.yaml` (слой пользователя)

См. **`config.yaml.example`** в этом каталоге: каждый ключ верхнего уровня и вложенные поля снабжены комментарием на русском. Порядок слияния слоёв описан в `ailit_cli.config_layer_order` и `merged_config`.

## Связь с репозиторием

- Исходники пакетов: каталог `ailit/` в корне репозитория (`ailit_base`, `agent_work`, `agent_memory`, `ailit_runtime`, `ailit_cli`, …).
- Тесты подставляют свой `HOME` и `AILIT_*`, чтобы не трогать пользовательский `~/.ailit` (корневой `conftest.py`).

Produced by: assistant (рефакторинг структуры пакетов).
