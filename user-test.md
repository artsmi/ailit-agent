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

Файловые tools (`read_file` / `write_file`) в чате **включены по умолчанию**; песочница = **корень проекта** из поля в меню «☰» → Проект (или корень репозитория `ailit-agent`). Снимите чекбокс «Файловые tools», если нужен чистый диалог без tool calling. В меню «☰» → **Workflow** можно запустить тот же сценарий, что и `ailit agent run`, и увидеть JSONL в окне.

1. Задайте ключ (или заполните `config/test.local.yaml`).
2. Запустите:

```bash
ailit chat
```

3. Streamlit откроет локальный URL (по умолчанию порт **8501**). В шапке выберите **deepseek** (или **mock** без сети).
4. Введите сообщение в поле внизу. Ответ появится в чате; внизу отображается `state=...` сессии (`SessionRunner`).

**mock** — без API; при включённых файловых tools запросы на создание файла (например «сделай тестовый файл») приводят к вызову **`write_file`** без ручного approval. Для **DeepSeek** по-прежнему нужен реальный вызов инструмента моделью; в чате добавлена system-подсказка, чтобы не ограничиваться текстом «создам файл».

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

Команда **`ailit agent run`** выводит JSONL (`workflow_run_events_v1`); project layer (этап 7) — `--project-root` и `project.yaml`. Этап 8 — **`ailit compat run`** (JSONL + **`.ailit/status.md`**). Этап 9 — **`ailit debug bundle`**.

---

## 5. Этап 7: `project.yaml`, `--project-root`, чат

В корне репозитория есть пример **[project.yaml](project.yaml)** с реестром `workflows.minimal`, `agents`, canonical context (`context/**/*.md`).

### 5.1 CLI: workflow по id из проекта

```bash
cd /path/to/ailit-agent
ailit agent run minimal --project-root . --provider mock --dry-run
```

Параметры:

- `--project-root` — корень проекта (ожидается `project.yaml` внутри, если не задан `--project-file`);
- `--project-file` — явный путь к YAML проекта (родитель файла должен совпадать с ожидаемым корнем путей в реестре).

### 5.2 Чат: правое меню «☰»

Запустите **`ailit chat`**. В шапке: провайдер, `max_turns`, переключатель **Проект**, `agent_id`. В меню **☰** вкладки:

- **Проект** — корень, превью `project_id`, списки workflows/agents, `rollout.phase`;
- **Контекст** — кнопка «Обновить shortlist / context», превью canonical файлов и keywords;
- **Workflow** — запуск YAML (id или путь), dry-run / live, вывод JSONL в окне;
- **Adapter**, **Debug**, **Команда** — как ранее.

Сообщения в чате при включённом **Проект** используют tuning из `project.yaml` (rules, memory_hints, knowledge_refresh).

---

## 6. Этап 8: compat adapter

### 6.1 CLI

```bash
ailit compat run minimal --project-root /path/to/ailit-agent --provider mock --dry-run
```

В stdout — JSONL; в **`<project-root>/.ailit/status.md`** — markdown-статус. При **`runtime: legacy`** в `project.yaml` движок workflow не вызывается, в JSONL — `adapter.legacy_skip`.

### 6.2 Чат

В меню «☰» вкладка **Adapter**: смок mock + dry-run, просмотр JSONL и `status.md`.

---

## 7. Этап 9: debug bundle и rollout

### 7.1 CLI

```bash
ailit debug bundle --project-root /path/to/ailit-agent --out /tmp/ailit-debug.zip
```

В zip: `manifest.json`, `project.yaml` (если есть), дерево **`.ailit/`**.

### 7.2 Чат

Вкладка **Debug**: `rollout.phase`, сборка `.ailit/debug-bundle.zip`, скачивание; во вкладке **Команда** — пример CLI для bundle.
