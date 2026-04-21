## Постановка: Stop вместо Send + Inline Shell Activity в `ailit chat`

Цель: улучшить UX Streamlit-чата после включения tools по умолчанию:

1. Во время выполнения хода агента пользователь должен видеть **одну кнопку Stop**
   **вместо** отправки сообщения (ввод отключён/скрыт), чтобы не создавалось
   впечатление «можно отправить ещё один prompt».
2. В основном чате (ниже ленты сообщений) должен быть **постоянный** блок,
   показывающий работу shell:
   - какая команда уходит в (session) shell;
   - статус (running/ok/error/timeout);
   - превью **последних 5 строк** по умолчанию;
   - кнопка рядом с командой, открывающая **полный текущий лог** внизу
     (expanded view, актуальное состояние).

### Критерии приёмки

- `ailit chat`:
  - при активном прогоне (pending) `st.chat_input(...)` **не отображается**,
    вместо него есть кнопка **Stop** (одна, заметная);
  - внизу всегда виден блок **Shell activity** с минимумом:
    - tool name (`run_shell`, `run_shell_session`, `shell_reset`);
    - статус и `call_id` (сокращённый);
    - команда (если есть);
    - хвост последних 5 строк (настраиваемо);
    - кнопка **Лог** на строке команды, открывающая полный вывод.

### Реализация (ailit)

- события `tool.call_started` должны содержать `arguments_json`, чтобы UI мог
  показывать команду **сразу**, до `bash.execution`.
  См. `tools/agent_core/session/loop.py` — эмит событий.
- UI должен собирать:
  - `bash.output_delta` → инкрементальный вывод для превью;
  - `bash.finished` и `tool.call_finished` → статус;
  - `bash.execution` → финальные поля (exit_code, truncated, spill_path и т.п.).

### Референсы (идеи, без копипаста)

- `claude-code`: персистентный терминал на tmux + отдельный socket per session:
  `tools/ailit-agent` ориентируется на принцип «отдельная долгоживущая сессия».
  См. ```1:36:/home/artem/reps/claude-code/utils/terminalPanel.ts```.
- `opencode`: у bash tool есть инкрементальный output preview через metadata
  (last tail), а полный вывод может уходить в файл при truncation.
  См. ```420:559:/home/artem/reps/opencode/packages/opencode/src/tool/bash.ts```.

