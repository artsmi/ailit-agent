# Запуск репозитория ailit-agent

## Python и пакеты

- **Версия:** `requires-python >= 3.10` (`pyproject.toml`).
- **Пакеты:** `setuptools` ищет пакеты в `tools/`: `agent_core`, `workflow_engine`, `ailit`, `project_layer`.
- **Точка CLI:** `[project.scripts]` → `ailit = "ailit.cli:main"`; реализация: `tools/ailit/cli.py`.

Рекомендуемый интерпретатор для разработки и тестов — venv в корне клона (например `.venv`), чтобы субпроцессы pytest видели те же зависимости, что и хост.

## Установка CLI и артефактов

Скрипт: **`scripts/install`** (корень репозитория).

| Режим | Команда |
|-------|---------|
| prod (по умолчанию) | `./scripts/install` |
| prod (явно) | `./scripts/install prod` |
| dev (editable + extras) | `./scripts/install dev` |

Переменные (фрагмент; полный список — в шапке скрипта):

| Переменная | Назначение |
|------------|------------|
| `AILIT_INSTALL_PREFIX` | Корень установки (дефолт `~/.local/share/ailit`), venv и desktop-артефакты. |
| `AILIT_INSTALL_NO_SHIM` | Не создавать симлинк `~/.local/bin/ailit`. |
| `AILIT_INSTALL_NO_SYSTEMD` | Не писать user unit systemd. |
| `AILIT_INSTALL_DRY_RUN` | Только логировать шаги. |

После установки: shim `~/.local/bin/ailit` (если не отключён) и при доступном user systemd — unit `~/.config/systemd/user/ailit.service` с `ExecStart` на `ailit runtime supervisor` и `Environment=AILIT_RUNTIME_DIR=%t/ailit` (см. скрипт).

## Runtime supervisor (долгоживущий процесс)

1. Убедиться, что `XDG_RUNTIME_DIR` и user bus доступны (иначе install может пропустить unit).
2. Запуск вручную: `ailit runtime supervisor` (блокирующий процесс).
3. Или: `systemctl --user start ailit.service` после install.

Каталог рантайма по умолчанию совпадает с логикой Python `default_runtime_dir` и Electron `defaultRuntimeDir`: `AILIT_RUNTIME_DIR`, иначе `XDG_RUNTIME_DIR/ailit`, иначе `~/.ailit/runtime`. В каталоге — `supervisor.sock` и прочие артефакты broker/trace.

## Desktop (Linux, Electron)

- **Prod:** `ailit desktop` — запуск собранного AppImage из префикса установки (`DesktopBinaryLocator` в `tools/ailit/desktop_cli.py`).
- **Dev из клона:** `ailit desktop --dev` — `npm run dev` в `desktop/` (Vite + Electron).

Переменная **`AILIT_CLI`**: в dev main-процесс Electron может вызывать CLI через `execFile` (например `ailit memory pag-slice`); при необходимости укажите полный путь к бинарю.

## Тесты

- **pytest:** из venv репозитория, например `./.venv/bin/python -m pytest`.
- **Конфиг:** `pyproject.toml` — `pythonpath`: `tools`, `tests/e2e`; по умолчанию `addopts` исключает маркеры `integration` и `manual_model_e2e`.
- **Изоляция:** autouse в `tests/conftest.py` — подмена `HOME`, `AILIT_RUNTIME_DIR`, `AILIT_PAG_DB_PATH`, `AILIT_KB_DB_PATH`, `AILIT_MEMORY_JOURNAL_PATH`, `AILIT_CONFIG_DIR`, `AILIT_STATE_DIR`, `AILIT_WORK_ROOT` (см. проектный workflow).

Подробнее по группам и файлам — [`../tests/INDEX.md`](../tests/INDEX.md). Для desktop Memory 3D / PAG финальный gate Vitest (**12 файлов, 80 тестов**, §5.0 ТЗ) и команда — в `context/tests/INDEX.md`; сводный отчёт финального `11` при наличии — `context/artifacts/reports/test_run_11_final.md`.

## Линтеры

- Python: `ruff` (`pyproject.toml`).
- Desktop: `eslint`, `typescript` (`desktop/package.json`).

## Bootstrap при отсутствии зависимостей

В `tools/ailit/cli.py` при старте может создаваться `.venv` и выполняться `pip install -e '.[dev]'` (переменные `AILIT_REPO_BOOTSTRAP_*` — см. код). Допущение: в CI/контейнерах без сети этот путь может быть нежелателен; предпочтительна явная установка через `scripts/install` или ручной venv.
