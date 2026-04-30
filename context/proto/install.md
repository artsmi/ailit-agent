# Установка (канон ссылок)

Первичный источник команд и переменных — скрипт **`scripts/install`** в корне репозитория.

## Ссылки

- Пошаговое описание сценариев (venv, shim, systemd, desktop): [`../start/repository-launch.md`](../start/repository-launch.md).
- Артефакты desktop после install: префикс `AILIT_INSTALL_PREFIX` (дефолт `~/.local/share/ailit`), AppImage в подкаталоге `desktop/` — см. `tools/ailit/desktop_cli.py` (`DesktopBinaryLocator`).

## Не путать

- Установка продуктового рантайма ≠ индексация markdown в `context/` (knowledge layer остаётся файловым каноном).
