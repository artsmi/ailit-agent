# Стратегия: полноценные bash/shell-инструменты в ailit (`ailit-bash-strategy`)

Документ задаёт этапы внедрения произвольного (в рамках политики безопасности) выполнения shell-команд в runtime **`ailit`**, с UX в **Streamlit Chat** и **Textual TUI**: отдельный просмотр длинного вывода, история нескольких команд, в TUI по умолчанию последние 3–4 строки.

Канон workflow: [`.cursor/rules/project-workflow.mdc`](../.cursor/rules/project-workflow.mdc).

## 0. Референсы (локальные репозитории, без копипаста логики)

### 0.1 Claude Code — shell, таймауты, безопасность Bash

| Идея | Где смотреть |
|------|----------------|
| Выбор POSIX shell (`SHELL`, `CLAUDE_CODE_SHELL`, `which`), провайдер bash | ```73:137:/home/artem/reps/claude-code/utils/Shell.ts``` (`findSuitableShell`, `getShellConfig`) |
| Общий таймаут bash (env, default/max) | ```1:39:/home/artem/reps/claude-code/utils/timeouts.ts``` (`getDefaultBashTimeoutMs`, `getMaxBashTimeoutMs`) |
| Изолированный tmux-сокет для панели / наследование env | ```1:50:/home/artem/reps/claude-code/utils/tmuxSocket.ts``` (комментарии про Bash + TMUX) |
| Панель терминала (персистентность через tmux, fallback) | ```1:20:/home/artem/reps/claude-code/utils/terminalPanel.ts``` |
| Классификация команд для permissions | ```1:40:/home/artem/reps/claude-code/utils/permissions/bashClassifier.ts``` (по имени файла; уточнить при интеграции) |
| Глубокая валидация опасных паттернов (zsh/bash) | ```1:80:/home/artem/reps/claude-code/tools/BashTool/bashSecurity.ts``` (паттерны, `ZSH_DANGEROUS_COMMANDS`, далее по файлу) |
| Вспомогательные проверки команд | ```1:30:/home/artem/reps/claude-code/tools/BashTool/bashCommandHelpers.ts``` |
| Windows: git-bash / `SHELL` | ```83:121:/home/artem/reps/claude-code/utils/windowsPaths.ts``` (`findGitBashPath`, комментарии для BashTool) |

### 0.2 OpenCode — единый слой shell, bash tool, стриминг и truncation

| Идея | Где смотреть |
|------|----------------|
| Выбор shell, `killTree`, blacklist fish/nu, Windows pwsh/cmd | ```1:110:/home/artem/reps/opencode/packages/opencode/src/shell/shell.ts``` |
| Bash tool: spawn, streaming chunks, metadata `output` для UI, timeout/abort race, tail + spill to file | ```400:570:/home/artem/reps/opencode/packages/opencode/src/tool/bash.ts``` (`run`, `ctx.metadata`, `Truncate`, `Effect.raceAll`) |
| Тесты shell-поведения (ориентир на свой набор) | ```1:80:/home/artem/reps/opencode/packages/opencode/test/shell/shell.test.ts``` |

### 0.3 Текущий ailit (точки интеграции)

| Компонент | Файл |
|-----------|------|
| Встроенные tools (нет произвольного shell) | ```266:273:/home/artem/reps/ailit-agent/tools/agent_core/tool_runtime/builtins.py``` (`BUILTIN_HANDLERS`) |
| Спеки и `SideEffectClass` | ```10:31:/home/artem/reps/ailit-agent/tools/agent_core/tool_runtime/spec.py``` |
| Политика allow/ask/deny | ```18:46:/home/artem/reps/ailit-agent/tools/agent_core/tool_runtime/permission.py``` |
| Реестр tools для чата | ```104:120:/home/artem/reps/ailit-agent/tools/ailit/chat_app.py``` (`_chat_tool_registry`) |
| События tool в UI | ```525:533:/home/artem/reps/ailit-agent/tools/ailit/chat_app.py``` (`tool.call_started` / `tool.call_finished`) |
| TUI: базовый system и провайдер | ```121:125:/home/artem/reps/ailit-agent/tools/ailit/tui_chat_controller.py``` (поиск по `MessageRole.SYSTEM`) |
| Карта system-фрагментов (расширить после bash) | ```29:113:/home/artem/reps/ailit-agent/tools/ailit/prompt_map.py``` (`prompt_map_rows`) |
| Утилита «хвост» вывода для UX (этап 1, уже в репо) | `tools/agent_core/shell_output_preview.py` |

---

## 1. Цели продукта

1. **Инструмент(ы)** для модели: выполнение shell-команды в **рабочем корне** проекта (как `AILIT_WORK_ROOT` для файловых tools), с явными лимитами (время, размер stdout/stderr, число параллельных процессов).
2. **Безопасность и governance**: класс побочного эффекта не ниже «опасной записи»; по умолчанию **ask** перед запуском (как write); опциональный denylist/allowlist и эвристики (в духе claude-code `bashSecurity`, opencode `collect`/`ask`).
3. **CHAT (Streamlit)**:
   - короткая команда / малый вывод — компактная метка в ленте (команда + exit + превью);
   - **длительная** или **большой вывод** — отдельный **view** (вкладка или `st.expander` + выделенная область): полный буфер или rolling tail **последних N строк** (настраиваемо, default N≈200 для просмотра; в сводке в ленте — меньше);
   - **несколько** параллельных/последовательных bash-вызовов — список сессий/вызовов с id; каждая доступна для просмотра (переключатель или аккордеон по `call_id`).
4. **TUI (Textual)**:
   - в основном чате по умолчанию **последние 3–4 строки** stdout/stderr (или общего merge) для каждого активного/завершённого вызова;
   - полный вывод — отдельный экран/panel по запросу (согласовать с паттернами `tui_app.py` / существующими экранами).

---

## 2. Этапы и задачи

### Этап A — Контракт данных и превью (фундамент UX)

**Критерии приёмки:** модуль без I/O, покрыт pytest; используется Chat/TUI в следующих этапах.

| Задача | Действия | Ссылки |
|--------|----------|--------|
| A.1 Хвост вывода и эвристика «длинная команда» | Зафиксировать API: `last_lines(text, n)`, правила склейки stderr+stdout, `suggest_detached_view(elapsed_ms, bytes, lines, user_thresholds)`. | `tools/agent_core/shell_output_preview.py`; тесты `tests/test_shell_output_preview.py` |
| A.2 Модель «запись о запуске» | Dataclass `ShellInvocationRecord`: `call_id`, `command`, `started_at`, `finished_at`, `exit_code`, `combined_output`, `truncated`, `detached_recommended`. Сериализация для session_state / TUI store. | Новый модуль `tools/agent_core/shell_invocation_record.py` (этап B) |

### Этап B — Runtime: subprocess + политика

**Критерии приёмки:** unit-тесты с фиктивной командой (`echo`, `exit 1`) без сети; интеграция в `default_builtin_registry` за флагом или отдельным `bash_tool_registry()`.

| Задача | Действия | Ссылки |
|--------|----------|--------|
| B.1 Исполнитель | `posix_spawn`/`subprocess.Popen`: cwd=`AILIT_WORK_ROOT`, env inherit + whitelist, **без** `shell=True` для произвольной строки; на Unix: `["/bin/bash", "-lc", command]` или эквивалент после аудита инъекций (claude-code: провайдер; opencode: `cmd()` в ```284:295:/home/artem/reps/opencode/packages/opencode/src/tool/bash.ts```). | Новый `tools/agent_core/tool_runtime/bash_runner.py` |
| B.2 Таймаут и убийство процесса | Аналог `Effect.raceAll` из opencode: таймаут + корректное завершение группы процессов; на Linux — `start_new_session=True` + killpg (как идея из ```15:44:/home/artem/reps/opencode/packages/opencode/src/shell/shell.ts``` `killTree`). | `bash_runner.py`; тест на зависший `sleep` с коротким timeout |
| B.3 Лимиты вывода | Стрим в память с cap; при превышении — spill в tempfile под `.ailit/` (аналог opencode `trunc.write`). | См. ```423:543:/home/artem/reps/opencode/packages/opencode/src/tool/bash.ts``` |
| B.4 ToolSpec | Новый `SideEffectClass` (например `SUBPROCESS` / `SHELL`) или переиспользовать `DESTRUCTIVE` + `requires_approval=True`; описание параметров: `command`, `timeout_ms`, `description`. | ```10:18:/home/artem/reps/ailit-agent/tools/agent_core/tool_runtime/spec.py``` |
| B.5 PermissionEngine | Маппинг нового класса на `ASK` по умолчанию. | ```33:46:/home/artem/reps/ailit-agent/tools/agent_core/tool_runtime/permission.py``` |

### Этап C — События и UI-agnostic телеметрия

**Критерии приёмки:** в JSONL / `session.turn` (или существующий diag) видны `bash.output_delta`, `bash.finished` с размерами; SessionRunner не ломает существующие тесты.

| Задача | Действия | Ссылки |
|--------|----------|--------|
| C.1 События стрима | Эмитить чанки для UI (throttle, например 100–200 ms). | `tools/agent_core/session/loop.py` (рядом с tool execution) |
| C.2 Идентификатор вызова | Прокинуть `call_id` из tool runtime в события. | `tools/agent_core/tool_runtime/executor.py` |

### Этап D — CHAT (Streamlit)

**Критерии приёмки:** ручной сценарий: две длинные команды подряд — обе видны в списке; открытие view показывает последние N строк; короткая команда остаётся inline.

| Задача | Действия | Ссылки |
|--------|----------|--------|
| D.1 Чекбокс «Bash / shell» | Аналог «Файловые tools»; при включении — реестр с bash tool + system hint. | ```182:186:/home/artem/reps/ailit-agent/tools/ailit/chat_app.py``` |
| D.2 Хранилище вызовов | `st.session_state["bash_runs"]`: список `ShellInvocationRecord`. | Новый небольшой модуль `tools/ailit/bash_chat_store.py` |
| D.3 View | Вкладка «Shell» или боковая колонка: выбор `call_id`, `st.code(tail_full, language="bash")`, настройка N. | `tools/ailit/chat_app.py` |
| D.4 Подсказка модели | Не дублировать file_tools hint; отдельный блок про bash и политику подтверждения. | `_inject_file_tools_system_hint` рядом в `chat_app.py` |

### Этап E — TUI (Textual)

**Критерии приёмки:** в списке сообщений под tool-блоком 3–4 строки превью; по клавише/фокусу — полный вывод.

| Задача | Действия | Ссылки |
|--------|----------|--------|
| E.1 Виджет превью | Rich markup: метка «running…» / duration; `LineTailSelector` из A.1. | `tools/ailit/tui_chat_controller.py`, при необходимости новый виджет-файл |
| E.2 Реестр tools TUI | Синхронизация с chat: те же builtins + bash при флаге. | См. сборку провайдера в `tui_chat_controller.py` / `tui_app.py` |

### Этап F — Документация, промпт-карта, конфиг проекта

| Задача | Действия | Ссылки |
|--------|----------|--------|
| F.1 `prompt_map_rows` | Строки: `bash.tool`, `bash.chat.hint`, `bash.permission`. | `tools/ailit/prompt_map.py` |
| F.2 `project.yaml` | Опционально: `bash: { default_timeout_ms, max_output_mb, allow_patterns }` — парсинг в `project_layer`. | `tools/project_layer/models.py`, корневой `project.yaml` |

### Этап G — Безопасность (углубление)

| Задача | Действия | Ссылки |
|--------|----------|--------|
| G.1 Статический скан | Портировать **идеи** (не код дословно) из claude-code: heredoc, process substitution, опасные zsh builtins. | ```1:74:/home/artem/reps/claude-code/tools/BashTool/bashSecurity.ts``` |
| G.2 Песочница (опционально) | Оценить `SandboxManager` из claude-code | ```35:40:/home/artem/reps/claude-code/utils/Shell.ts``` (import) + пакет `sandbox/` |

---

## 3. Нефункциональные требования

- **Нет сети по умолчанию** в классификаторе: если команда требует сети — отдельный флаг или запрет до явной политики проекта.
- **Логи**: не писать секреты из env в открытый лог; маскировать типичные ключи.
- **Совместимость**: mock-провайдер в тестах не обязан реально вызывать bash; e2e с bash — только при пометке и в CI с осторожностью.

---

## 4. Связь с существующими стратегиями

- Пересечение с [`plan/deploy-project-strategy.md`](deploy-project-strategy.md) (DP: инструменты, rollout): после закрытия этапов A–D обновить статус в корневом `README.md`.
- Глобальные команды и оркестрация (если понадобится общий pool процессов): см. [`plan/project-orchestrator-strategy.md`](project-orchestrator-strategy.md) на уровне постановки, не блокирует MVP bash в одном work root.

---

## 5. Выполнено в рамках постановки этого документа (инкремент 2026-04)

- Добавлены утилиты превью вывода (`shell_output_preview.py`) и тесты — задел под этапы D/E.
- Настоящий bash-tool, UI и политика — по этапам B–E выше.
