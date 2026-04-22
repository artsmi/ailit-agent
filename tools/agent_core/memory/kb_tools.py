"""KB tool registry (search/fetch/write) backed by local SQLite."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec

from agent_core.memory.sqlite_kb import SqliteKb


@dataclass(frozen=True, slots=True)
class KbToolsConfig:
    """Configuration for KB tools."""

    enabled: bool
    db_path: Path
    namespace: str


def kb_tools_config_from_env() -> KbToolsConfig:
    """Parse env for local KB tools (H4.1 scaffold).

    - AILIT_KB=1 enables the tools.
    - AILIT_KB_DB_PATH points to sqlite file.
    - AILIT_KB_NAMESPACE chooses logical namespace.
    """
    import os

    raw = os.environ.get("AILIT_KB", "").strip().lower()
    enabled = raw in ("1", "true", "yes", "on")
    db_raw = os.environ.get("AILIT_KB_DB_PATH", "").strip()
    ns = os.environ.get("AILIT_KB_NAMESPACE", "default").strip() or "default"
    if db_raw:
        p = Path(db_raw).expanduser().resolve()
    else:
        p = Path.cwd().resolve() / ".ailit" / "kb.sqlite3"
    return KbToolsConfig(enabled=enabled, db_path=p, namespace=ns)


def build_kb_tool_registry(cfg: KbToolsConfig) -> ToolRegistry:
    """Build tool registry for kb.* tools."""
    if not cfg.enabled:
        return ToolRegistry(specs={}, handlers={})
    kb = SqliteKb(cfg.db_path)

    def _json_out(obj: object) -> str:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)

    def _s(args: Mapping[str, object], key: str) -> str:
        v = args.get(key)
        return str(v) if v is not None else ""

    def _i(args: Mapping[str, object], key: str, default: int) -> int:
        v = args.get(key)
        try:
            return int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return int(default)

    specs: dict[str, ToolSpec] = {}
    handlers: dict[str, Any] = {}

    specs["kb.search"] = ToolSpec(
        name="kb.search",
        description=(
            "Поиск по KB: вернуть top-k кандидатов (id, title, summary). "
            "Не возвращает полный текст."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "scope": {
                    "type": "string",
                    "description": "org|workspace|project|agent|run",
                },
                "namespace": {"type": "string"},
                "top_k": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
        side_effect=SideEffectClass.READ_ONLY,
    )

    def _kb_search(args: Mapping[str, object]) -> str:
        q = _s(args, "query").strip()
        scope = _s(args, "scope").strip() or None
        ns = _s(args, "namespace").strip() or cfg.namespace
        top_k = _i(args, "top_k", 8)
        rows = kb.search(query=q, scope=scope, namespace=ns, top_k=top_k)
        return _json_out(rows)

    handlers["kb.search"] = _kb_search

    specs["kb.fetch"] = ToolSpec(
        name="kb.fetch",
        description="Получить запись KB по id (ограниченный фрагмент body).",
        parameters_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "max_chars": {"type": "integer", "default": 2400},
            },
            "required": ["id"],
        },
        side_effect=SideEffectClass.READ_ONLY,
    )

    def _kb_fetch(args: Mapping[str, object]) -> str:
        rid = _s(args, "id").strip()
        max_chars = max(0, min(_i(args, "max_chars", 2400), 50_000))
        rec = kb.fetch(rid)
        if rec is None:
            return _json_out({"error": "not_found", "id": rid})
        body = rec.body
        if max_chars and len(body) > max_chars:
            body = body[:max_chars]
        return _json_out(
            {
                "id": rec.id,
                "kind": rec.kind,
                "scope": rec.scope,
                "namespace": rec.namespace,
                "title": rec.title,
                "summary": rec.summary,
                "body_snippet": body,
                "tags": list(rec.tags),
                "links": list(rec.links),
                "provenance": rec.provenance,
                "updated_at": rec.updated_at,
            },
        )

    handlers["kb.fetch"] = _kb_fetch

    specs["kb.write_fact"] = ToolSpec(
        name="kb.write_fact",
        description=(
            "Записать нормализованный факт в KB (без сырого чата). "
            "Возвращает id."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "scope": {"type": "string"},
                "namespace": {"type": "string"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "body": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "links": {"type": "array", "items": {"type": "string"}},
                "provenance": {"type": "object"},
                "author": {"type": "string"},
            },
            "required": ["id", "scope", "title", "summary"],
        },
        side_effect=SideEffectClass.WRITE,
    )

    def _kb_write_fact(args: Mapping[str, object]) -> str:
        rid = _s(args, "id").strip()
        scope = _s(args, "scope").strip() or "run"
        ns = _s(args, "namespace").strip() or cfg.namespace
        title = _s(args, "title").strip()
        summary = _s(args, "summary").strip()
        body = _s(args, "body")
        tags = args.get("tags")
        links = args.get("links")
        prov = args.get("provenance")
        author = _s(args, "author").strip() or "agent"
        tags_lst = list(tags) if isinstance(tags, list) else []
        links_lst = list(links) if isinstance(links, list) else []
        prov_map = dict(prov) if isinstance(prov, dict) else {}
        kb.write(
            record_id=rid,
            kind="fact",
            scope=scope,
            namespace=ns,
            title=title,
            summary=summary,
            body=body,
            tags=(str(x) for x in tags_lst),
            links=(str(x) for x in links_lst),
            provenance=prov_map,
            author=author,
        )
        return _json_out({"id": rid, "status": "ok"})

    handlers["kb.write_fact"] = _kb_write_fact

    return ToolRegistry(specs=specs, handlers=handlers)
