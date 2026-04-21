# Ссылки для приёмки UX чата/агента (непрерывный tool cycle)

Документ дополняет реализацию по плану «непрерывный цикл инструментов»; сам план в Cursor не менялся.

## Изменения в ailit-agent

- Политика `suppress_tools_after_write_file`: по умолчанию выключена; legacy через `AILIT_SUPPRESS_TOOLS_AFTER_WRITE=1` — [`tools/agent_core/session/loop.py`](../tools/agent_core/session/loop.py) (`_default_suppress_tools_after_write_file`, `SessionSettings`).
- Проброс в workflow: [`tools/workflow_engine/engine.py`](../tools/workflow_engine/engine.py) — поле `WorkflowRunConfig.suppress_tools_after_write_file`, сборка `SessionSettings`.
- Телеметрия `write_file`: [`tools/agent_core/tool_runtime/executor.py`](../tools/agent_core/tool_runtime/executor.py) (`_write_file_extras_before_run`), событие `tool.call_finished` с `relative_path` / `file_change_kind` — [`tools/agent_core/session/loop.py`](../tools/agent_core/session/loop.py) (`_tool_call_finished_payload`).
- JSONL `task.finished`: поле `file_changes` — тот же `engine.py`.
- Глобальные промпты (эмодзи, отчёт по путям): [`tools/agent_core/system_style_defaults.py`](../tools/agent_core/system_style_defaults.py); workflow — [`tools/project_layer/bootstrap.py`](../tools/project_layer/bootstrap.py) (`compute_workflow_augmentation`); чат/TUI — [`tools/ailit/chat_app.py`](../tools/ailit/chat_app.py), [`tools/ailit/tui_chat_controller.py`](../tools/ailit/tui_chat_controller.py).
- Хвост «:» → «…»: [`tools/ailit/chat_transcript_view.py`](../tools/ailit/chat_transcript_view.py) (`TrailingColonEllipsisFormatter`).

## Внешние репозитории (ориентиры)

1. **claude-code** — опциональный `tool_choice` в side-запросах к API (принудительный инструмент только когда нужен), без обязательного «обрубания» основного цикла после записи файла:

   - файл: `/home/artem/reps/claude-code/utils/sideQuery.ts`, строки **44–45** (поле `tool_choice` в `SideQueryOptions`), **107–113** (проброс в `sideQuery`).

2. **opencode** — явное выставление `assistantMessage.finish = "tool-calls"` после выполнения инструмента, чтобы цепочка сообщений и UI оставались согласованными с tool-parts:

   - файл: `/home/artem/reps/opencode/packages/opencode/src/session/prompt.ts`, строки **662–664** (`assistantMessage.finish = "tool-calls"` после обновления сообщения).
