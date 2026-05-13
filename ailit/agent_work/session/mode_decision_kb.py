"""KB: история решений perm-5 (kind=mode_decision)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any

from agent_memory.sqlite_kb import SqliteKb


MODE_DECISION_KIND = "mode_decision"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_ts_iso() -> str:
    """Публичная метка времени для payload mode_decision (KB)."""
    return _utc_ts()


@dataclass(frozen=True, slots=True)
class ModeDecisionPayload:
    """Структурированное решение без сырого чата."""

    user_intent_short: str
    mode_chosen: str
    decided_by: str
    overridden: bool
    ts: str
    confidence: float | None = None
    reason: str | None = None


class ModeDecisionKbReader:
    """Чтение последних N решений для промпта классификатора."""

    def __init__(self, kb: SqliteKb, *, namespace: str) -> None:
        """Привязать KB и логический namespace."""
        self._kb = kb
        self._namespace = namespace.strip() or "default"

    def load_recent_payloads(self, *, limit: int) -> list[ModeDecisionPayload]:
        """Вернуть до ``limit`` последних решений (новые первыми)."""
        lim = max(1, min(int(limit), 50))
        rows = self._kb.list_recent_by_kind(
            kind=MODE_DECISION_KIND,
            namespace=self._namespace,
            limit=lim,
        )
        out: list[ModeDecisionPayload] = []
        for rec in rows:
            parsed = _parse_body(rec.body)
            if parsed is None:
                continue
            out.append(parsed)
        return list(reversed(out))


def _parse_body(body: str) -> ModeDecisionPayload | None:
    try:
        raw: dict[str, Any] = json.loads(body or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    intent = str(raw.get("user_intent_short") or "").strip()
    mode = str(raw.get("mode_chosen") or "").strip()
    by = str(raw.get("decided_by") or "").strip()
    ts = str(raw.get("ts") or "").strip()
    if not intent or not mode or not by or not ts:
        return None
    ov = bool(raw.get("overridden"))
    conf = raw.get("confidence")
    conf_f: float | None
    if isinstance(conf, (int, float)):
        conf_f = float(conf)
    else:
        conf_f = None
    reason = raw.get("reason")
    reason_s = str(reason).strip() if reason is not None else None
    return ModeDecisionPayload(
        user_intent_short=intent,
        mode_chosen=mode,
        decided_by=by,
        overridden=ov,
        ts=ts,
        confidence=conf_f,
        reason=reason_s,
    )


class ModeDecisionKbWriter:
    """Запись решения классификатора / пользователя в KB."""

    def __init__(self, kb: SqliteKb, *, namespace: str) -> None:
        """Привязать KB и namespace."""
        self._kb = kb
        self._namespace = namespace.strip() or "default"

    def write_decision(
        self,
        payload: ModeDecisionPayload,
        *,
        scope: str = "project",
        source: str | None = None,
        repo_provenance: Mapping[str, Any] | None = None,
    ) -> str:
        """Сохранить решение; вернуть id записи."""
        rid = str(uuid.uuid4())
        body_obj: dict[str, Any] = {
            "user_intent_short": payload.user_intent_short,
            "mode_chosen": payload.mode_chosen,
            "decided_by": payload.decided_by,
            "overridden": payload.overridden,
            "ts": payload.ts,
        }
        if payload.confidence is not None:
            body_obj["confidence"] = payload.confidence
        if payload.reason:
            body_obj["reason"] = payload.reason
        body = json.dumps(body_obj, ensure_ascii=False, sort_keys=True)
        title = f"mode:{payload.mode_chosen}"
        summary = payload.user_intent_short[:240]
        prov: dict[str, Any] = {"kind": MODE_DECISION_KIND}
        if source:
            prov["source"] = source
        if repo_provenance is not None:
            prov["repo"] = dict(repo_provenance)
        self._kb.write(
            record_id=rid,
            kind=MODE_DECISION_KIND,
            scope=scope,
            namespace=self._namespace,
            title=title,
            summary=summary,
            body=body,
            tags=("perm-5", "mode_decision"),
            links=(),
            provenance=prov,
            author="ailit",
            memory_layer="semantic",
            promotion_status="draft",
        )
        return rid


class ModeDecisionHistoryFormatter:
    """Текстовый блок истории для system-сообщения классификатора."""

    def format_block(self, items: list[ModeDecisionPayload]) -> str:
        """Сериализовать историю в компактный текст."""
        if not items:
            return "(нет предыдущих решений)"
        lines: list[str] = []
        for it in items:
            extra = ""
            if it.confidence is not None:
                extra += f" conf={it.confidence:.2f}"
            if it.reason:
                extra += f" reason={it.reason!r}"
            lines.append(
                f"- ts={it.ts} intent={it.user_intent_short!r} "
                f"mode={it.mode_chosen} by={it.decided_by} "
                f"overridden={it.overridden}{extra}",
            )
        return "\n".join(lines)
