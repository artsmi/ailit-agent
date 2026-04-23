"""KB tool registry (search/fetch/write) backed by local SQLite."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.spec import SideEffectClass, ToolSpec

from agent_core.memory.layers import MemoryLayer, parse_memory_layer
from agent_core.memory.promotion_policy import evaluate_promotion
from agent_core.memory.sqlite_kb import SqliteKb


@dataclass(frozen=True, slots=True)
class KbToolsConfig:
    """Configuration for KB tools."""

    enabled: bool
    db_path: Path
    namespace: str


def kb_tools_config_from_env() -> KbToolsConfig:
    """Parse env for local KB tools (H4.1 scaffold).

    - По умолчанию KB включена; AILIT_KB=0 отключает.
    - AILIT_KB_DB_PATH points to sqlite file.
    - AILIT_KB_NAMESPACE chooses logical namespace.
    """
    import os

    raw = os.environ.get("AILIT_KB", "").strip().lower()
    enabled = raw not in ("0", "false", "no", "off")
    db_raw = os.environ.get("AILIT_KB_DB_PATH", "").strip()
    ns = os.environ.get("AILIT_KB_NAMESPACE", "default").strip() or "default"
    if db_raw:
        p = Path(db_raw).expanduser().resolve()
    else:
        p = Path("~/.ailit/kb.sqlite3").expanduser().resolve()
    return KbToolsConfig(enabled=enabled, db_path=p, namespace=ns)


def build_kb_tool_registry(cfg: KbToolsConfig) -> ToolRegistry:
    """Build tool registry for kb_* tools.

    Важно: некоторые OpenAI-совместимые провайдеры (DeepSeek) ограничивают
    имя function/tool паттерном ``^[a-zA-Z0-9_-]+$`` — точки запрещены.
    Поэтому используем имена вида ``kb_search`` вместо ``kb.search``.
    """
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

    def _b(args: Mapping[str, object], key: str, default: bool) -> bool:
        v = args.get(key)
        if isinstance(v, bool):
            return v
        if v in (None, ""):
            return default
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        return default

    def _memory_layer(args: Mapping[str, object]) -> str:
        raw = _s(args, "memory_layer").strip().lower()
        if not raw:
            return MemoryLayer.SEMANTIC.value
        p = parse_memory_layer(raw)
        return p.value if p is not None else MemoryLayer.SEMANTIC.value

    specs: dict[str, ToolSpec] = {}
    handlers: dict[str, Any] = {}

    specs["kb_search"] = ToolSpec(
        name="kb_search",
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
                "include_expired": {
                    "type": "boolean",
                    "default": False,
                    "description": "Включать записи вне valid_from/valid_to",
                },
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
        inc = _b(args, "include_expired", False)
        accel = os.environ.get("AILIT_KB_ACCEL", "").strip().lower()
        force_off = accel in ("0", "off", "false", "no")
        force_fts = accel in ("fts", "fts5", "bm25")
        auto_fts = not accel
        use_fts = (force_fts or auto_fts) and not force_off
        rows: list[dict[str, Any]] | None = None
        if use_fts and not inc:
            fts_rows = kb.search_fts(
                query=q,
                scope=scope,
                namespace=ns,
                top_k=top_k,
            )
            if fts_rows is None:
                rows = None
            elif fts_rows:
                rows = fts_rows
            else:
                # FTS пустой или не синхронизирован с kb_records — LIKE.
                rows = None
        if rows is None:
            rows = kb.search(
                query=q,
                scope=scope,
                namespace=ns,
                top_k=top_k,
                include_expired=inc,
            )
        return _json_out(rows)

    handlers["kb_search"] = _kb_search

    specs["kb_fetch"] = ToolSpec(
        name="kb_fetch",
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
                "memory_layer": rec.memory_layer,
                "valid_from": rec.valid_from,
                "valid_to": rec.valid_to,
                "supersedes_id": rec.supersedes_id,
                "source": rec.source,
                "episode_id": rec.episode_id,
                "promotion_status": rec.promotion_status,
                "updated_at": rec.updated_at,
            },
        )

    handlers["kb_fetch"] = _kb_fetch

    specs["kb_write_fact"] = ToolSpec(
        name="kb_write_fact",
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
                "memory_layer": {
                    "type": "string",
                    "description": "working|episodic|semantic|procedural",
                },
                "valid_from": {
                    "type": "string",
                    "description": "ISO-8601 UTC",
                },
                "valid_to": {
                    "type": "string",
                    "description": "ISO-8601 UTC",
                },
                "supersedes_id": {
                    "type": "string",
                    "description": "id записи, которую эта запись суперседит",
                },
                "source": {
                    "type": "string",
                    "description": "источник (путь, run, commit, …)",
                },
                "episode_id": {"type": "string"},
                "promotion_status": {
                    "type": "string",
                    "description": (
                        "только draft; остальное через kb_promote"
                    ),
                },
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
        ml = _memory_layer(args)
        vf = _s(args, "valid_from").strip() or None
        vt = _s(args, "valid_to").strip() or None
        sid = _s(args, "supersedes_id").strip() or None
        src = _s(args, "source").strip() or None
        epid = _s(args, "episode_id").strip() or None
        pstat = _s(args, "promotion_status").strip() or "draft"
        if pstat.lower() != "draft":
            msg = "в kb_write_fact только draft; смена — kb_promote"
            return _json_out(
                {
                    "status": "denied",
                    "rule": "promotion_via_kb_promote_only",
                    "message": msg,
                },
            )
        if rid:
            ex = kb.fetch(rid)
            if ex is not None and (
                (ex.promotion_status or "").strip().lower() == "superseded"
            ):
                return _json_out(
                    {
                        "status": "error",
                        "error": "immutable_superseded",
                        "id": rid,
                    },
                )
        tags_lst = list(tags) if isinstance(tags, list) else []
        links_lst = list(links) if isinstance(links, list) else []
        prov_map = dict(prov) if isinstance(prov, dict) else {}
        try:
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
                memory_layer=ml,
                valid_from=vf,
                valid_to=vt,
                supersedes_id=sid,
                source=src,
                episode_id=epid,
                promotion_status="draft",
            )
        except ValueError as e:
            if "superseded" in str(e).lower():
                return _json_out(
                    {
                        "status": "error",
                        "error": "immutable_superseded",
                        "id": rid,
                    },
                )
            raise
        return _json_out({"id": rid, "status": "ok"})

    handlers["kb_write_fact"] = _kb_write_fact

    specs["kb_promote"] = ToolSpec(
        name="kb_promote",
        description=(
            "Смена promotion_status: reviewed / promoted / deprecated. "
            "Допустимые шаги; не обходить через kb_write_fact."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id записи в KB"},
                "to_status": {
                    "type": "string",
                    "description": "reviewed|promoted|deprecated",
                },
                "namespace": {
                    "type": "string",
                    "description": "если задан, совпадает с namespace записи",
                },
                "reviewer": {
                    "type": "string",
                    "description": (
                        "кто подтвердил/промоутнул (для audit trail)"
                    ),
                },
                "note": {
                    "type": "string",
                    "description": "короткая причина/комментарий для audit",
                },
            },
            "required": ["id", "to_status"],
        },
        side_effect=SideEffectClass.WRITE,
    )

    def _kb_promote(args: Mapping[str, object]) -> str:
        rid = _s(args, "id").strip()
        to_s = _s(args, "to_status").strip().lower()
        ns_check = _s(args, "namespace").strip() or None
        reviewer = _s(args, "reviewer").strip() or None
        note = _s(args, "note").strip() or None
        if not rid or not to_s:
            return _json_out(
                {"status": "error", "error": "missing_id_or_to_status"},
            )
        rec = kb.fetch(rid)
        if rec is None:
            return _json_out(
                {
                    "status": "error",
                    "error": "not_found",
                    "id": rid,
                },
            )
        if ns_check is not None and rec.namespace != ns_check:
            return _json_out(
                {
                    "status": "denied",
                    "id": rid,
                    "rule": "namespace_mismatch",
                    "message": "namespace не совпадает с записью",
                },
            )
        cur = (rec.promotion_status or "").strip().lower() or "draft"
        from_status = rec.promotion_status
        if cur == to_s:
            return _json_out(
                {
                    "status": "ok",
                    "id": rid,
                    "from_status": from_status,
                    "to_status": to_s,
                    "no_op": True,
                },
            )
        dec = evaluate_promotion(rec, to_s)
        if not dec.ok:
            return _json_out(
                {
                    "status": "denied",
                    "id": rid,
                    "rule": dec.rule_id,
                    "message": dec.message,
                },
            )
        if not kb.update_record_promotion(rid, to_s):
            return _json_out(
                {
                    "status": "error",
                    "error": "update_failed",
                    "id": rid,
                },
            )
        kb.append_audit_event(
            record_id=rid,
            event={
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "kb_promote",
                "from_status": from_status,
                "to_status": to_s,
                "reviewer": reviewer,
                "note": note,
            },
        )
        return _json_out(
            {
                "status": "ok",
                "id": rid,
                "from_status": from_status,
                "to_status": to_s,
            },
        )

    handlers["kb_promote"] = _kb_promote

    return ToolRegistry(specs=specs, handlers=handlers)
