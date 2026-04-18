# Ручная проверка ailit-agent (DeepSeek и CLI)

Документ описывает, как самостоятельно проверить установку и базовые сценарии **ailit-agent** после этапов 4–6: tool runtime, session loop, workflow engine, команды `ailit`.

## Предусловия

- Python **3.10+**, репозиторий `ailit-agent` клонирован локально.
- Установка пакета в editable-режиме:

```bash
cd /path/to/ailit-agent
python3 -m pip install --upgrade pip setuptools
python3 -m pip install -e "."
python3 -m pip install -e ".[chat]"
```

Extra **`[chat]`** нужен для `ailit chat` (Streamlit). Для только `ailit agent` и тестов достаточно `pip install -e ".[dev]"` при необходимости pytest.

### Ключ DeepSeek

- Предпочтительно переменная окружения: `export DEEPSEEK_API_KEY=...`
- Либо файл **`config/test.local.yaml`** (в git не коммитится), скопированный из `config/test.local.yaml.example`, с заполненным `deepseek.api_key` и при необходимости `live.run: true`.

Политика секретов и live-тестов: [context/proto/deepseek-integration-test-contract.md](context/proto/deepseek-integration-test-contract.md).

### Проверка unit / integration тестов

```bash
cd /path/to/ailit-agent
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

Live-вызов DeepSeek (если есть ключ и `AILIT_RUN_LIVE=1` или `live.run` в yaml): помечен `@pytest.mark.integration`, один тест может быть пропущен без ключа.

---

## 1. Чат в браузере: `ailit chat` + DeepSeek

По умолчанию в чате **не** объявляются файловые tools — ответ идёт как у обычного диалога. Включите в боковой панели «Файловые инструменты», если нужны `read_file` / `write_file` (песочница = корень репозитория).

1. Задайте ключ (или заполните `config/test.local.yaml`).
2. Запустите:

```bash
ailit chat
```

3. Streamlit откроет локальный URL (по умолчанию порт **8501**). В боковой панели выберите **deepseek** (или **mock** без сети).
4. Введите сообщение в поле внизу. Ответ появится в чате; внизу отображается `state=...` сессии (`SessionRunner`).

**mock** — без API, детерминированный ответ (удобно проверить UI).

### Если в логе Streamlit: `inotify instance limit reached`

`ailit chat` уже запускает Streamlit с **`--server.fileWatcherType none`**, чтобы не создавать лишние inotify-наблюдатели (типичная причина `OSError: [Errno 24]`).

Если вы запускаете UI вручную без CLI, добавьте то же самое:

```bash
python3 -m streamlit run tools/ailit/chat_app.py --server.fileWatcherType none
```

Долгосрочно на Linux можно поднять лимиты (до перезагрузки — `sudo sysctl`, постоянно — в `/etc/sysctl.d/`):

```text
fs.inotify.max_user_instances=1024
fs.inotify.max_user_watches=524288
```

---

## 2. Workflow: `ailit agent run`

Контракт потока событий в stdout: **JSON Lines**, поле `contract`: `workflow_run_events_v1`, поле `v`: `1`.

### 2.1 Dry-run (без вызова модели)

```bash
ailit agent run examples/workflows/minimal.yaml --dry-run --provider mock
```

В stdout — строки JSON: `workflow.loaded`, `stage.entered`, `task.skipped_dry_run`, `workflow.finished`, и т.д.

### 2.2 Реальный прогон с DeepSeek

```bash
export DEEPSEEK_API_KEY=...
ailit agent run examples/workflows/minimal.yaml --provider deepseek --model deepseek-chat
```

При отсутствии ключа используйте **`--provider mock`** (ответ модели будет заглушечным через `MockProvider`, но цепочка session + workflow отработает).

Параметры:

- `--dry-run` — только события планирования.
- `--model` — имя модели (для DeepSeek по умолчанию из yaml или `deepseek-chat`).
- `--max-turns` — лимит ходов session loop на задачу.

---

## 3. Песочница файлов для встроенных tools

Инструменты **`read_file` / `write_file`** ограничены каталогом **`AILIT_WORK_ROOT`** (по умолчанию текущий cwd). Для проверки записи:

```bash
export AILIT_WORK_ROOT=/tmp/ailit-sandbox
```

---

## 4. Связь с ai-multi-agents

Команда **`ailit agent run`** выводит машинные события в формате, готовом для будущего adapter-а к [ai-multi-agents](file:///home/artem/reps/ai-multi-agents); полная совместимость с Cursor pipeline (`start-feature` и т.д.) — отдельный этап roadmap (adapter), не входит в минимальный MVP этапа 6.
