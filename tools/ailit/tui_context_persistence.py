"""Сохранение и загрузка состояния мульти-контекста TUI (Q.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ailit.tui_app_state import TuiAppState
from ailit.tui_chat_controller import TuiChatController
from ailit.tui_context_manager import (
    TuiContextManager,
    TuiContextProfile,
    TuiContextRuntime,
    UsageTotals,
)
from ailit.tui_message_codec import (
    messages_from_jsonable,
    messages_to_jsonable,
)
from ailit.user_paths import global_state_dir


def default_state_path() -> Path:
    """Путь к state.json в ``tui-sessions`` (под глобальным state)."""
    base = global_state_dir() / "tui-sessions"
    base.mkdir(parents=True, exist_ok=True)
    return base / "state.json"


def save_app_state(path: Path, app_state: TuiAppState) -> None:
    """Сериализовать контексты и активное имя."""
    blocks: list[dict[str, Any]] = []
    for name, rt in app_state.contexts.all_runtimes():
        prof = rt.profile
        blocks.append(
            {
                "name": name,
                "project_root": str(prof.project_root),
                "agent_id": prof.agent_id,
                "workflow_ref": prof.workflow_ref,
                "messages": messages_to_jsonable(rt.chat.snapshot_messages()),
                "usage": rt.usage.as_dict(),
            },
        )
    payload = {
        "version": 1,
        "active": app_state.contexts.active_name(),
        "provider": app_state.provider,
        "model": app_state.model,
        "max_turns": app_state.max_turns,
        "contexts": blocks,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_app_state(
    path: Path,
    *,
    default_root: Path,
) -> tuple[TuiContextManager, str, str, int] | None:
    """Загрузить менеджер и глобальные поля провайдера; None при ошибке."""
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if int(raw.get("version", 0)) != 1:
        return None
    active = str(raw.get("active") or "default")
    prov = str(raw.get("provider") or "mock")
    model = str(raw.get("model") or "mock")
    mt = int(raw.get("max_turns") or 10_000)
    ctxs_raw = raw.get("contexts")
    if not isinstance(ctxs_raw, list) or not ctxs_raw:
        return None
    runtimes: dict[str, TuiContextRuntime] = {}
    for item in ctxs_raw:
        if not isinstance(item, dict):
            continue
        n = str(item.get("name") or "").strip()
        if not n:
            continue
        root = Path(str(item.get("project_root") or default_root)).expanduser()
        prof = TuiContextProfile(
            name=n,
            project_root=root.resolve(),
            agent_id=str(item.get("agent_id") or "default"),
            workflow_ref=item.get("workflow_ref"),
        )
        msg_rows = item.get("messages")
        msgs = (
            messages_from_jsonable(msg_rows)
            if isinstance(msg_rows, list)
            else None
        )
        if msgs:
            chat = TuiChatController(seed_messages=msgs)
        else:
            chat = TuiChatController()
        usage = UsageTotals()
        u_raw = item.get("usage")
        if isinstance(u_raw, dict):
            usage.assign_from_totals(u_raw)
        runtimes[n] = TuiContextRuntime(profile=prof, chat=chat, usage=usage)
    if not runtimes:
        return None
    mgr = TuiContextManager(default_root=default_root, default_name="default")
    mgr.replace_from_serialized(active=active, runtimes=runtimes)
    return mgr, prov, model, mt
