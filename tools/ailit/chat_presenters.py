"""Human-readable представление событий workflow (JSONL) для ``ailit chat``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol


class EventPresenter(Protocol):
    """Стратегия: событие → короткая markdown-строка для пользователя."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Сформировать одну строку/абзац markdown."""
        ...


class WorkflowLoadedPresenter:
    """Событие ``workflow.loaded``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Описать загрузку workflow."""
        wid = event.get("workflow_id", "?")
        return f"Загружен workflow **`{wid}`**."


class WorkflowFinishedPresenter:
    """Событие ``workflow.finished``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Описать завершение прогона."""
        wid = event.get("workflow_id", "?")
        return f"Workflow **`{wid}`** завершён."


class StageEnteredPresenter:
    """Событие ``stage.entered``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Вход на стадию."""
        sid = event.get("stage_id", "?")
        wid = event.get("workflow_id", "?")
        return f"Стадия **`{sid}`** (workflow `{wid}`)."


class StageExitedPresenter:
    """Событие ``stage.exited``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Выход со стадии."""
        sid = event.get("stage_id", "?")
        wid = event.get("workflow_id", "?")
        return f"Стадия **`{sid}`** завершена (workflow `{wid}`)."


class TaskStartedPresenter:
    """Событие ``task.started``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Старт задачи."""
        tid = event.get("task_id", "?")
        sid = event.get("stage_id", "?")
        return f"Задача **`{tid}`** на стадии `{sid}` — выполнение…"


class TaskFinishedPresenter:
    """Событие ``task.finished``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Итог задачи."""
        tid = event.get("task_id", "?")
        state = event.get("session_state", "?")
        reason = event.get("reason")
        extra = f" Причина: `{reason}`." if reason else ""
        return f"Задача **`{tid}`** завершена: состояние **{state}**.{extra}"


class TaskSkippedDryRunPresenter:
    """Событие ``task.skipped_dry_run``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Пропуск в dry-run."""
        tid = event.get("task_id", "?")
        return f"Задача **`{tid}`** пропущена (dry-run, без вызова модели)."


class ProjectPolicyRefPresenter:
    """Событие ``project.policy.ref`` (гибридный маркер)."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Кратко о политике."""
        return "Политика проекта / hybrid: зафиксированы ссылки на артефакты."


class HumanGateRequestedPresenter:
    """Событие ``human.gate.requested``."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Запрос human gate."""
        gid = event.get("gate_id", "?")
        desc = str(event.get("description", "")).strip()
        tail = f" — {desc}" if desc else ""
        return f"Требуется **human gate** `{gid}`{tail}."


class FallbackEventPresenter:
    """Неизвестный ``event_type``: без полного JSON."""

    def present(self, event: Mapping[str, Any]) -> str:
        """Минимальная строка."""
        et = str(event.get("event_type", "?"))
        return f"Событие **`{et}`** (подробности — в блоке «диагностика»)."


class ChatEventPresenterRegistry:
    """Реестр стратегий по ``event_type``."""

    def __init__(
        self,
        presenters: Mapping[str, EventPresenter],
        *,
        fallback: EventPresenter | None = None,
    ) -> None:
        """Сохранить карту тип → презентер и fallback для неизвестных типов."""
        self._presenters: dict[str, EventPresenter] = dict(presenters)
        self._fallback: EventPresenter = (
            fallback if fallback is not None else FallbackEventPresenter()
        )

    @classmethod
    def default(cls) -> ChatEventPresenterRegistry:
        """Стандартный набор для ``workflow_run_events_v1``."""
        fb = FallbackEventPresenter()
        mapping: dict[str, EventPresenter] = {
            "workflow.loaded": WorkflowLoadedPresenter(),
            "workflow.finished": WorkflowFinishedPresenter(),
            "stage.entered": StageEnteredPresenter(),
            "stage.exited": StageExitedPresenter(),
            "task.started": TaskStartedPresenter(),
            "task.finished": TaskFinishedPresenter(),
            "task.skipped_dry_run": TaskSkippedDryRunPresenter(),
            "project.policy.ref": ProjectPolicyRefPresenter(),
            "human.gate.requested": HumanGateRequestedPresenter(),
        }
        return cls(mapping, fallback=fb)

    def format_event(self, event: Mapping[str, Any]) -> str:
        """Выбрать презентер по ``event_type``."""
        et = str(event.get("event_type", ""))
        presenter = self._presenters.get(et, self._fallback)
        return presenter.present(event)


_DEFAULT_REGISTRY = ChatEventPresenterRegistry.default()


def format_event_for_user(event: Mapping[str, Any]) -> str:
    """Одна строка markdown для пользователя по dict-событию (как в JSONL)."""
    return _DEFAULT_REGISTRY.format_event(event)


def format_jsonl_line_for_user(line: str) -> str:
    """Распарсить одну строку JSONL и отформатировать; при ошибке — безопасная строка."""
    raw = line.strip()
    if not raw:
        return ""
    if raw.startswith("#"):
        return f"> {raw}"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return f"> не JSON: `{raw[:120]}`"
    if not isinstance(obj, dict):
        return "> (не объект JSON)"
    return format_event_for_user(obj)


def summarize_workflow_jsonl_for_user(text: str, *, max_lines: int = 400) -> str:
    """Свести JSONL прогона в компактный markdown для основной панели."""
    all_lines = text.splitlines()
    out_lines: list[str] = []
    skipped = 0
    for i, ln in enumerate(all_lines):
        if i >= max_lines:
            skipped = len(all_lines) - max_lines
            break
        formatted = format_jsonl_line_for_user(ln)
        if formatted:
            out_lines.append(formatted)
    body = "\n\n".join(out_lines)
    if skipped > 0:
        body += f"\n\n_…пропущено строк: {skipped}_"
    return body if body else "_Нет событий для отображения._"


# --- Основной диалог: ответы инструментов (list_dir, glob_file, …) ---


class ListDirToolResultPresenter:
    """Форматирование JSON-ответа ``list_dir``."""

    def format(self, data: dict[str, Any]) -> str:
        """Markdown: путь и список имён."""
        path = str(data.get("path", "."))
        lines: list[str] = [f"**list_dir** `{path}`", ""]
        entries = data.get("entries")
        if isinstance(entries, list):
            for item in entries[:120]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "?"))
                kind = str(item.get("type", "?"))
                lines.append(f"- `{name}` _({kind})_")
        if data.get("truncated"):
            lines.extend(["", "_Список усечён лимитом инструмента._"])
        return "\n".join(lines).strip()


class GlobFileToolResultPresenter:
    """Форматирование JSON-ответа ``glob_file``."""

    def format(self, data: dict[str, Any]) -> str:
        """Markdown: шаблон и пути."""
        pattern = str(data.get("pattern", ""))
        base = str(data.get("base", "."))
        names = data.get("filenames")
        n_raw = data.get("num_files", 0)
        n = int(n_raw) if isinstance(n_raw, int) else 0
        lines: list[str] = [
            f"**glob_file** `{pattern}` в `{base}` — **{n}** файл(ов).",
            "",
        ]
        if isinstance(names, list):
            for rel in names[:60]:
                lines.append(f"- `{rel}`")
        if data.get("truncated"):
            lines.extend(["", "_Список усечён._"])
        return "\n".join(lines).strip()


def format_tool_message_content_markdown(content: str) -> str:
    """Сжать тело сообщения роли ``tool`` в markdown для основной колонки чата."""
    stripped = content.strip()
    if not stripped:
        return " "
    if stripped.startswith("wrote:"):
        return f"**Запись файла:** `{stripped}`"
    if not stripped.startswith("{"):
        limit = 6000
        body = stripped if len(stripped) <= limit else f"{stripped[:limit]}\n\n_…усечено_"
        return f"```text\n{body}\n```"
    try:
        obj: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return f"```\n{stripped[:4000]}\n```"
    if not isinstance(obj, dict):
        return "_Результат инструмента (JSON не объект)._"
    if "entries" in obj and "path" in obj:
        return ListDirToolResultPresenter().format(obj)
    if "filenames" in obj and "pattern" in obj:
        return GlobFileToolResultPresenter().format(obj)
    keys = ", ".join(sorted(str(k) for k in obj.keys())[:10])
    return f"**Результат инструмента** (поля: {keys}). Полный ответ — в «Сырой JSON»."


def tool_message_should_offer_raw_json(content: str) -> bool:
    """Показывать ли expander с сырым телом."""
    s = content.strip()
    return len(s) > 2 and (s.startswith("{") or s.startswith("["))


def format_assistant_chat_block_markdown(
    *,
    content: str,
    tool_calls: tuple[Any, ...] | None,
) -> str:
    """Текст ассистента + кратко о вызовах инструментов."""
    parts: list[str] = []
    if tool_calls:
        items: list[str] = []
        for tc in tool_calls:
            name = str(getattr(tc, "tool_name", "?"))
            arg = str(getattr(tc, "arguments_json", "")).strip()
            arg_show = arg if len(arg) <= 160 else f"{arg[:157]}…"
            items.append(f"- `{name}` — `{arg_show}`")
        parts.append("**Вызовы инструментов**\n" + "\n".join(items))
    body = content.strip()
    if body:
        parts.append(body)
    return "\n\n".join(parts) if parts else " "
