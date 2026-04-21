"""Карта системных фрагментов ailit (DP-4.1).

Это не «пользовательский чат», а инженерный инвентарь: что именно попадает в
system-сообщения, при каких условиях и с каким приоритетом.

Вдохновение:
- claude-code: слои `buildEffectiveSystemPrompt`
  (override/coordinator/agent/custom/default/append)
- opencode: модульность и разнесение промптов/политик по отдельным артефактам
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptFragmentRow:
    """Одна строка карты промптов."""

    fragment_id: str
    owner: str
    priority: str
    enabled_when: str
    where_defined: str
    token_notes: str


def prompt_map_rows() -> tuple[PromptFragmentRow, ...]:
    """Вернуть текущий инвентарь известных system-фрагментов."""
    return (
        PromptFragmentRow(
            fragment_id="default.base_system",
            owner="ailit",
            priority="default",
            enabled_when="всегда (если не задан override/custom/agent)",
            where_defined=(
                "tools/ailit/chat_app.py и tools/ailit/tui_chat_controller.py"
            ),
            token_notes="короткий базовый промпт; должен быть стабильным",
        ),
        PromptFragmentRow(
            fragment_id="global.assistant_style",
            owner="agent_core",
            priority="default/append",
            enabled_when=(
                "чат/TUI: merge с базовым system; workflow: augmentation"
            ),
            where_defined="tools/agent_core/system_style_defaults.py",
            token_notes=(
                "без эмодзи; отчёт по путям после изменения файлов"
            ),
        ),
        PromptFragmentRow(
            fragment_id="session.tool.write_file.telemetry",
            owner="agent_core",
            priority="diag",
            enabled_when="после успешного write_file в session loop",
            where_defined=(
                "tools/agent_core/tool_runtime/executor.py:"
                "_write_file_extras_before_run; "
                "tools/agent_core/session/loop.py:_tool_call_finished_payload"
            ),
            token_notes="relative_path, file_change_kind в tool.call_finished",
        ),
        PromptFragmentRow(
            fragment_id="project.rules",
            owner="project_layer",
            priority="append",
            enabled_when=(
                "если в project.yaml задан paths.rules и файл существует"
            ),
            where_defined="tools/project_layer/bootstrap.py:_rules_text",
            token_notes="может быть большим; нужен верхний лимит/квота",
        ),
        PromptFragmentRow(
            fragment_id="project.memory_hints",
            owner="project_layer",
            priority="append",
            enabled_when="если в project.yaml есть memory_hints",
            where_defined="tools/project_layer/bootstrap.py:compute_*",
            token_notes="дедуп; короткие буллеты",
        ),
        PromptFragmentRow(
            fragment_id="project.context_preview",
            owner="project_layer",
            priority="append",
            enabled_when="если refresh дал preview_text",
            where_defined=(
                "tools/project_layer/bootstrap.py:"
                "compute_workflow_augmentation"
            ),
            token_notes="обрезается до 8000 символов; нужна оценка токенов",
        ),
        PromptFragmentRow(
            fragment_id="teammate.mailbox_addendum",
            owner="project_layer",
            priority="append/agent",
            enabled_when="если agent.role == teammate",
            where_defined="tools/project_layer/teammate_prompt.py",
            token_notes="должен быть маленьким и неизменным",
        ),
        PromptFragmentRow(
            fragment_id="agent.system_append",
            owner="project_layer",
            priority="append/agent",
            enabled_when="если в project.yaml у агента задан system_append",
            where_defined="tools/project_layer/models.py + bootstrap.py",
            token_notes="пользовательский текст; нужен дедуп и лимит",
        ),
        PromptFragmentRow(
            fragment_id="plugins.skill_snippets",
            owner="project_layer",
            priority="append",
            enabled_when="если установлены plugin skills",
            where_defined="tools/project_layer/plugin_skills.py",
            token_notes="может быть большим; нужно кэширование и лимиты",
        ),
        PromptFragmentRow(
            fragment_id="chat.file_tools_hint",
            owner="ailit.chat",
            priority="append",
            enabled_when="если включены file_tools в чате",
            where_defined=(
                "tools/ailit/chat_app.py:_inject_file_tools_system_hint"
            ),
            token_notes="короткая подсказка; не дублировать в других режимах",
        ),
        PromptFragmentRow(
            fragment_id="bash.run_shell",
            owner="agent_core",
            priority="tool",
            enabled_when="если включён чекбокс Shell в ailit chat",
            where_defined=(
                "tools/agent_core/tool_runtime/"
                "bash_tools.py:run_shell_tool_spec"
            ),
            token_notes="SHELL side effect; shell_default в PermissionEngine",
        ),
        PromptFragmentRow(
            fragment_id="bash.chat.hint",
            owner="ailit.chat",
            priority="append",
            enabled_when="если включён чекбокс Shell в ailit chat",
            where_defined=(
                "tools/ailit/chat_app.py:ChatToolSystemHintComposer; "
                "_inject_tool_hints_before_first_user"
            ),
            token_notes=(
                "отдельно от file_tools; run_shell + PermissionEngine"
            ),
        ),
        PromptFragmentRow(
            fragment_id="bash.permission",
            owner="agent_core",
            priority="runtime",
            enabled_when="если в реестре есть run_shell",
            where_defined=(
                "tools/agent_core/tool_runtime/permission.py:"
                "PermissionEngine.evaluate (SHELL → shell_default)"
            ),
            token_notes=(
                "по умолчанию ASK; chat/TUI могут подставить ALLOW"
            ),
        ),
        PromptFragmentRow(
            fragment_id="project.bash",
            owner="project_layer",
            priority="config",
            enabled_when="если в project.yaml задана секция bash:",
            where_defined=(
                "tools/project_layer/models.py:BashSectionModel; "
                "tools/ailit/bash_project_env.py:BashProjectEnvSync"
            ),
            token_notes=(
                "default_timeout_ms, max_output_mb, "
                "allow_patterns (fnmatch)"
            ),
        ),
        PromptFragmentRow(
            fragment_id="bash.events.telemetry",
            owner="agent_core",
            priority="diag",
            enabled_when="после исполнения run_shell",
            where_defined=(
                "tools/agent_core/session/bash_tool_events.py:"
                "emit_bash_shell_telemetry"
            ),
            token_notes="bash.output_delta, bash.finished, bash.execution",
        ),
        PromptFragmentRow(
            fragment_id="bash.chat.store",
            owner="ailit.chat",
            priority="append",
            enabled_when="вкладка Меню → Shell",
            where_defined="tools/ailit/bash_chat_store.py",
            token_notes="ailit_bash_runs в session_state",
        ),
        PromptFragmentRow(
            fragment_id="workflow.extra_system_messages",
            owner="workflow_engine",
            priority="append",
            enabled_when="если run_config.extra_system_messages не пустой",
            where_defined="tools/workflow_engine/engine.py",
            token_notes="идёт в начало прогона каждой задачи",
        ),
    )
