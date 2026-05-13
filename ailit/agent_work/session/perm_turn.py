"""perm-5: координатор режима для хода (классификатор + KB); без ailit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from agent_memory.kb_tools import kb_tools_config_from_env
from agent_memory.sqlite_kb import SqliteKb
from ailit_base.providers.protocol import ChatProvider
from agent_work.session.repo_context import (
    detect_repo_context,
    namespace_for_repo,
)
from agent_work.session.mode_classifier import (
    ClassifierModelOutput,
    LlmPermModeClassifier,
)
from agent_work.session.mode_decision_kb import (
    MODE_DECISION_KIND,
    ModeDecisionHistoryFormatter,
    ModeDecisionKbReader,
    ModeDecisionKbWriter,
    ModeDecisionPayload,
    utc_ts_iso,
)
from agent_work.session.perm_tool_mode import normalize_perm_tool_mode


@dataclass(frozen=True, slots=True)
class PermTurnResolution:
    """Итог выбора режима перед основным прогоном."""

    final_mode: str
    not_sure: bool
    classification: ClassifierModelOutput | None


class PermModeTurnCoordinator:
    """Классификатор + KB-история; без tool-calling у основной модели."""

    def __init__(
        self,
        *,
        kb_namespace: str,
        history_max: int = 8,
        repo_payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Задать KB namespace: repo+branch или memory.namespace."""
        self._kb_namespace = kb_namespace.strip() or "default"
        self._history_max = max(1, min(int(history_max), 50))
        self._repo_payload: dict[str, Any] | None = (
            dict(repo_payload) if repo_payload is not None else None
        )

    def _open_kb(self) -> SqliteKb | None:
        cfg = kb_tools_config_from_env()
        if not cfg.enabled:
            return None
        return SqliteKb(cfg.db_path)

    def resolve_turn(
        self,
        *,
        provider: ChatProvider,
        model: str,
        temperature: float,
        user_intent: str,
        classifier_bypass: bool,
        forced_mode: str | None,
        diag_sink: Callable[[dict[str, Any]], None] | None,
    ) -> PermTurnResolution:
        """Определить режим для хода (или not_sure)."""
        if classifier_bypass:
            fm = normalize_perm_tool_mode(forced_mode or "edit")
            return PermTurnResolution(
                final_mode=fm,
                not_sure=False,
                classification=None,
            )
        kb = self._open_kb()
        if kb is not None:
            pdef = PermModeTurnCoordinator.project_default_mode_from_kb(
                kb,
                namespace=self._kb_namespace,
            )
            if pdef is not None:
                self._emit_classified(
                    diag_sink,
                    mode=pdef,
                    confidence=1.0,
                    reason="policy_project_default_kb",
                )
                return PermTurnResolution(
                    final_mode=pdef,
                    not_sure=False,
                    classification=None,
                )
        history_block = "(нет предыдущих решений)"
        if kb is not None:
            reader = ModeDecisionKbReader(kb, namespace=self._kb_namespace)
            items = reader.load_recent_payloads(limit=self._history_max)
            history_block = ModeDecisionHistoryFormatter().format_block(
                list(items),
            )
        clf = LlmPermModeClassifier(provider)
        parsed = clf.classify(
            model=model,
            temperature=min(0.3, float(temperature)),
            user_intent=user_intent,
            history_block=history_block,
        )
        if parsed is None:
            fm = normalize_perm_tool_mode("read")
            self._emit_classified(
                diag_sink,
                mode=fm,
                confidence=None,
                reason="classifier_parse_failed",
            )
            return PermTurnResolution(
                final_mode=fm,
                not_sure=False,
                classification=None,
            )
        self._emit_classified(
            diag_sink,
            mode=parsed.mode,
            confidence=parsed.confidence,
            reason=parsed.reason,
        )
        if parsed.mode == "not_sure":
            return PermTurnResolution(
                final_mode=normalize_perm_tool_mode("explore"),
                not_sure=True,
                classification=parsed,
            )
        fm = normalize_perm_tool_mode(parsed.mode)
        if kb is not None:
            writer = ModeDecisionKbWriter(kb, namespace=self._kb_namespace)
            pay = ModeDecisionPayload(
                user_intent_short=user_intent.strip()[:400],
                mode_chosen=fm,
                decided_by="llm",
                overridden=False,
                ts=utc_ts_iso(),
                confidence=parsed.confidence,
                reason=parsed.reason,
            )
            writer.write_decision(
                pay,
                scope="project",
                source="perm_mode_classifier",
                repo_provenance=self._repo_payload,
            )
        return PermTurnResolution(
            final_mode=fm,
            not_sure=False,
            classification=parsed,
        )

    def record_user_choice(
        self,
        *,
        user_intent: str,
        mode: str,
        remember_project: bool,
        diag_sink: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        """Записать выбор после not_sure; optional remember для проекта."""
        fm = normalize_perm_tool_mode(mode)
        self._emit_user_choice(diag_sink, mode=fm, remember=remember_project)
        kb = self._open_kb()
        if kb is None:
            return
        writer = ModeDecisionKbWriter(kb, namespace=self._kb_namespace)
        pay = ModeDecisionPayload(
            user_intent_short=user_intent.strip()[:400],
            mode_chosen=fm,
            decided_by="user",
            overridden=True,
            ts=utc_ts_iso(),
            confidence=None,
            reason="user_choice_after_not_sure",
        )
        scope = "project" if remember_project else "run"
        writer.write_decision(
            pay,
            scope=scope,
            source="perm_mode_user_ui",
            repo_provenance=self._repo_payload,
        )
        if remember_project:
            tag_pay = ModeDecisionPayload(
                user_intent_short="project_default",
                mode_chosen=fm,
                decided_by="policy",
                overridden=False,
                ts=utc_ts_iso(),
                confidence=None,
                reason="remember_always",
            )
            writer.write_decision(
                tag_pay,
                scope="project",
                source="perm_mode_remember_always",
                repo_provenance=self._repo_payload,
            )

    @staticmethod
    def project_default_mode_from_kb(
        kb: SqliteKb | None,
        *,
        namespace: str,
    ) -> str | None:
        """Последний policy-режим «remember always», если есть."""
        if kb is None:
            return None
        rows = kb.list_recent_by_kind(
            kind=MODE_DECISION_KIND,
            namespace=namespace.strip() or "default",
            limit=30,
        )
        for rec in rows:
            body = (rec.body or "").strip()
            if "remember_always" not in body:
                continue
            try:
                obj: dict[str, Any] = json.loads(body)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("user_intent_short") or "") != "project_default":
                continue
            mode = str(obj.get("mode_chosen") or "").strip()
            if mode:
                return normalize_perm_tool_mode(mode)
        return None

    @staticmethod
    def _emit_classified(
        sink: Callable[[dict[str, Any]], None] | None,
        *,
        mode: str,
        confidence: float | None,
        reason: str,
    ) -> None:
        if sink is None:
            return
        row: dict[str, Any] = {
            "contract": "ailit_session_diag_v1",
            "event_type": "mode.classified",
            "mode": mode,
            "reason": reason,
        }
        if confidence is not None:
            row["confidence"] = confidence
        sink(row)

    @staticmethod
    def _emit_user_choice(
        sink: Callable[[dict[str, Any]], None] | None,
        *,
        mode: str,
        remember: bool,
    ) -> None:
        if sink is None:
            return
        sink(
            {
                "contract": "ailit_session_diag_v1",
                "event_type": "mode.user_choice",
                "mode": mode,
                "remember_project": remember,
            },
        )


def build_mode_kb_namespace(
    *,
    memory_namespace: str,
    project_root: Path | None,
) -> str:
    """Namespace mode_decision: repo+branch или memory.namespace."""
    mem = (memory_namespace or "").strip() or "default"
    if project_root is None:
        return mem
    try:
        rc = detect_repo_context(project_root.resolve())
    except OSError:
        return mem
    return namespace_for_repo(
        repo_uri=rc.repo_uri,
        repo_path=rc.repo_path,
        branch=rc.branch,
    )


def memory_namespace_from_cfg(cfg: Mapping[str, Any]) -> str:
    """Достать namespace из merged memory."""
    mem = cfg.get("memory")
    if not isinstance(mem, dict):
        return "default"
    ns = str(mem.get("namespace") or "").strip()
    return ns or "default"


def perm_mode_enabled_from_env() -> bool:
    """Включён ли слой perm-5 (AILIT_PERM_MODE=0 выключает)."""
    import os

    raw = os.environ.get("AILIT_PERM_MODE", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")
