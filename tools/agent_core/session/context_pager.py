"""Context Pager: большие tool outputs в страницы + read_context_page."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Mapping

from agent_core.session.token_economy_env import (
    env_flag,
    token_economy_globally_disabled,
)
from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec

READ_CONTEXT_PAGE_NAME: Final[str] = "read_context_page"


@dataclass(frozen=True, slots=True)
class ContextPagerConfig:
    """Параметры pager: включается env и пороги превью."""

    enabled: bool
    min_body_chars: int
    preview_max_lines: int
    preview_max_chars: int


def context_pager_config_from_env() -> ContextPagerConfig:
    """Разобрать AILIT_CONTEXT_PAGER* (plan workflow-token-economy W-TE-1).

    По умолчанию **вкл.**, `AILIT_TOKEN_ECONOMY=0` отключает все слои.
    """
    import os

    if token_economy_globally_disabled():
        return ContextPagerConfig(
            enabled=False,
            min_body_chars=4000,
            preview_max_lines=24,
            preview_max_chars=3500,
        )
    enabled = env_flag("AILIT_CONTEXT_PAGER", default=True)
    min_body = int(os.environ.get("AILIT_CONTEXT_PAGER_MIN_CHARS", "4000"))
    max_lines = int(os.environ.get("AILIT_CONTEXT_PAGER_PREVIEW_LINES", "24"))
    max_chars = int(
        os.environ.get("AILIT_CONTEXT_PAGER_PREVIEW_CHARS", "3500"),
    )
    return ContextPagerConfig(
        enabled=enabled,
        min_body_chars=max(256, min_body),
        preview_max_lines=max(4, min(200, max_lines)),
        preview_max_chars=max(512, min(50_000, max_chars)),
    )


@dataclass(frozen=True, slots=True)
class StoredPage:
    """Полный текст страницы и метаданные для диагностики."""

    full_text: str
    source: str
    tool_name: str
    locator: str


class ContextPageStore:
    """In-memory хранилище на один прогон `SessionRunner.run()`."""

    def __init__(self) -> None:
        """Пустое хранилище."""
        self._pages: dict[str, StoredPage] = {}

    def clear(self) -> None:
        """Сбросить перед новым прогоном сессии."""
        self._pages.clear()

    def put(self, page_id: str, page: StoredPage) -> None:
        """Сохранить страницу."""
        self._pages[page_id] = page

    def get(self, page_id: str) -> StoredPage | None:
        """Получить страницу или None."""
        return self._pages.get(page_id)

    def __len__(self) -> int:
        return len(self._pages)


def stable_page_id(*, content: str, call_id: str, tool_name: str) -> str:
    """Детерминированный id: sha256 от содента и идентификаторов вызова."""
    h = hashlib.sha256(
        f"{tool_name}\n{call_id}\n{content}".encode("utf-8"),
    ).hexdigest()[:16]
    return f"p_{h}"


def tool_to_source_key(tool_name: str) -> str:
    """Канонический source для события context.pager (см. план §2.1)."""
    if tool_name in ("read_file",):
        return "file_read"
    if tool_name in ("grep", "grep_file"):
        return "grep"
    if tool_name in ("glob_file", "glob_file_search"):
        return "glob"
    if tool_name in ("list_dir",):
        return "list_dir"
    if tool_name in ("run_shell_command", "run_shell", "bash_exec"):
        return "shell"
    if tool_name in ("echo",):
        return "echo"
    if tool_name in ("write_file", "apply_patch"):
        return "file_write"
    return tool_name


def locator_from_invocation(
    tool_name: str,
    arguments_json: str,
) -> str:
    """Короткий локатор для логов (путь, команда, …)."""
    try:
        args = json.loads(arguments_json) if arguments_json.strip() else {}
    except json.JSONDecodeError:
        return tool_name
    if not isinstance(args, dict):
        return tool_name
    path = args.get("path")
    if isinstance(path, str) and path.strip():
        return f"{tool_name}:{path.strip()}"
    fp = args.get("filePath")
    if isinstance(fp, str) and fp.strip():
        return f"{tool_name}:{fp.strip()}"
    cmd = args.get("command")
    if isinstance(cmd, str) and cmd.strip():
        c = cmd.strip().replace("\n", " ")
        if len(c) > 120:
            c = c[:117] + "..."
        return f"{tool_name}:{c}"
    pat = args.get("pattern")
    if isinstance(pat, str) and pat.strip():
        return f"{tool_name}:pattern={pat[:80]}"
    return tool_name


def build_preview(
    text: str,
    *,
    max_lines: int,
    max_chars: int,
) -> str:
    """Первые `max_lines` строк, обрезка по символам — детерминированно."""
    lines = text.splitlines()
    head = lines[:max_lines]
    out = "\n".join(head)
    if len(out) > max_chars:
        return out[: max_chars - 3] + "..."
    return out


def build_tool_message_for_page(
    *,
    page_id: str,
    source: str,
    locator: str,
    full_text: str,
    preview: str,
    config: ContextPagerConfig,
) -> str:
    """Текст TOOL-сообщения вместо полного вывода."""
    b_total = len(full_text.encode("utf-8"))
    b_prev = len(preview.encode("utf-8"))
    return (
        f"[Context page {page_id}]\n"
        f"source={source}\n"
        f"locator={locator}\n"
        f"bytes_total={b_total}\n"
        f"bytes_preview={b_prev}\n"
        f"preview (first {config.preview_max_lines} lines, "
        f"truncated by {config.preview_max_chars} chars max):\n"
        f"---\n{preview}\n---\n"
        f"To read more, call {READ_CONTEXT_PAGE_NAME} with "
        f'{{"page_id": "{page_id}", "offset_lines": 0, "max_lines": 200}}.'
    )


def read_context_page_handler(
    store: ContextPageStore,
    arguments: Mapping[str, Any],
) -> str:
    """Вернуть срез текста страницы по offset_lines / max_lines."""
    page_id = str(arguments.get("page_id", "") or "").strip()
    if not page_id:
        return "error: page_id is required"
    off_raw = arguments.get("offset_lines", 0)
    try:
        offset = int(off_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "error: offset_lines must be an integer"
    if offset < 0:
        return "error: offset_lines must be >= 0"
    max_raw = arguments.get("max_lines", 200)
    try:
        max_lines = int(max_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "error: max_lines must be an integer"
    max_lines = max(1, min(2000, max_lines))

    page = store.get(page_id)
    if page is None:
        return f"error: unknown page_id {page_id!r}"
    lines = page.full_text.splitlines()
    end = offset + max_lines
    chunk = lines[offset:end]
    body = "\n".join(chunk)
    if not body and offset > 0:
        return f"error: offset_lines {offset} past end of page"
    return body


def build_context_pager_read_registry(store: ContextPageStore) -> ToolRegistry:
    """Реестр с инструментом догрузки страницы (merge с базовым)."""
    name = READ_CONTEXT_PAGE_NAME
    spec = ToolSpec(
        name=name,
        description=(
            "Догрузить фрагмент из context page; "
            "page_id из маркера [Context page p_...]."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "page_id, например p_abc12...",
                },
                "offset_lines": {
                    "type": "integer",
                    "description": "Смещение по строкам (0 — с начала).",
                },
                "max_lines": {
                    "type": "integer",
                    "description": (
                        "Сколько строк вернуть (1–2000, default 200)."
                    ),
                },
            },
            "required": ["page_id"],
        },
        side_effect=SideEffectClass.READ_ONLY,
    )

    def _handler(args: Mapping[str, object]) -> str:
        return read_context_page_handler(store, args)

    return ToolRegistry(specs={name: spec}, handlers={name: _handler})


__all__ = [
    "ContextPageStore",
    "ContextPagerConfig",
    "StoredPage",
    "build_context_pager_read_registry",
    "build_preview",
    "build_tool_message_for_page",
    "context_pager_config_from_env",
    "locator_from_invocation",
    "read_context_page_handler",
    "stable_page_id",
    "tool_to_source_key",
    "READ_CONTEXT_PAGE_NAME",
]
