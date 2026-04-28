# Установка ailit через `scripts/install`

## Назначение

Каноническое описание сценария установки из корня клона. Источник правды по шагам и путям — скрипт [`../../scripts/install`](../../scripts/install); при расхождении с этим документом приоритет у скрипта (документ нужно обновить).

## Предварительные требования

- **bash**, **Python 3** с `venv` и `pip`.
- Для артефактов **`desktop/`** (сборка AppImage и `npm ci`): **Node.js** и **npm**. Если `desktop/` отсутствует или npm недоступен, соответствующий блок установки пропускается или завершается с сообщением (см. скрипт).

## Режимы запуска

| Команда | Режим | Назначение |
|---------|--------|------------|
| `./scripts/install` | **prod** (по умолчанию) | Отдельный venv без editable-установки; пакет из корня репозитория ставится как обычный wheel-набор зависимостей (`pip install ".[chat,tui]"`). |
| `./scripts/install prod` | **prod** | То же, что без аргумента. |
| `./scripts/install dev` | **dev** | Editable: `pip install -e .`, extras `dev`, `chat`, `tui`; venv **внутри клона**: `<repo>/.venv`. |

Неизвестный первый аргумент → ошибка с подсказкой `dev | prod`.

## Переменные окружения

| Переменная | Эффект |
|------------|--------|
| `AILIT_INSTALL_PREFIX` | Корень для **prod**: venv и каталог `desktop/` (по умолчанию `~/.local/share/ailit`). В **dev** на размещение venv **не** влияет (venv всегда `<repo>/.venv`). |
| `AILIT_INSTALL_NO_SHIM=1` | Не создавать симлинк `~/.local/bin/ailit` на `ailit` из venv; пользователь активирует venv вручную (`source …/bin/activate`). |
| `AILIT_INSTALL_DRY_RUN` | Если непустая: только логировать шаги, не выполнять команды (где применимо в скрипте). |
| `AILIT_INSTALL_NO_SYSTEMD` | Не писать и не включать user-unit systemd для supervisor (см. ниже). |

## Куда что попадает

### Python и CLI

- **prod:** виртуальное окружение `{$AILIT_INSTALL_PREFIX:-~/.local/share/ailit}/venv`.
- **dev:** виртуальное окружение `<корень_репозитория>/.venv`.
- **Shim:** симлинк `~/.local/bin/ailit` → `$VENV/bin/ailit`, если не отключён `AILIT_INSTALL_NO_SHIM`. Убедитесь, что `~/.local/bin` в `PATH`.

### Desktop (Electron / Linux)

- При наличии каталога `desktop/` скрипт выполняет `npm ci` в `desktop/`.
- В **prod:** сборка `npm run package:linux`, ожидается AppImage в `desktop/dist-app/*.AppImage`; копия в  
  `{INSTALL_PREFIX}/desktop/ailit-desktop.AppImage`  
  где `INSTALL_PREFIX` — как выше.
- В **dev:** только зависимости; запуск разработки — из клона (`cd desktop && npm run dev`), без обязательной сборки AppImage.

### systemd (user)

- Юнит `~/.config/systemd/user/ailit.service`: запуск `ailit runtime supervisor` из `%h/.local/bin/ailit`, переменная `AILIT_RUNTIME_DIR=%t/ailit`.
- Устанавливается только если доступен рабочий `systemctl --user` (не в контейнере без user bus и т.п.) и не задан `AILIT_INSTALL_NO_SYSTEMD`.
- После установки: `systemctl --user enable --now ailit.service` и `restart` для идемпотентного обновления.

## Порядок операций в скрипте (логика)

1. Разбор режима и создание/использование venv, установка зависимостей пакета (см. таблицу режимов).
2. Опционально: установка артефактов **desktop** (`_install_desktop_artifacts`).
3. Опционально: симлинк **shim** в `~/.local/bin`.
4. Опционально: **systemd user** unit для runtime supervisor.

## Связанные документы

- Краткая выжимка и проверка: [`../../README.md`](../../README.md) (раздел установки и `ailit desktop`).
- Оглавление канона: [`../INDEX.md`](../INDEX.md).
