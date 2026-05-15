"""Явный session loop: провайдер → tool round → бюджет/compaction/shortlist."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from threading import Event
from typing import Any, Sequence

import httpx

from ailit_base.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    NormalizedChatResponse,
    StreamDone,
    StreamTextDelta,
    ToolChoice,
    ToolDefinition,
)
from ailit_base.normalization.stream_to_incremental import (
    stream_incremental_for_provider,
)
from ailit_base.providers.protocol import ChatProvider
from agent_work.session.budget import BudgetGovernance
from agent_work.session.compaction import compact_messages
from agent_work.session.context_pager import (
    READ_CONTEXT_PAGE_NAME,
    ContextPageStore,
    ContextPagerConfig,
    StoredPage,
    build_context_pager_read_registry,
    build_preview,
    build_tool_message_for_page,
    context_pager_config_from_env,
    locator_from_invocation,
    stable_page_id,
    tool_to_source_key,
)
from agent_work.session.context_ledger import (
    ContextSnapshotBuilder,
    provider_usage_confirmed_payload,
)
from agent_work.session.d_level_compact import DLevelCompactService
from agent_work.session.post_compact_restore import RecentFileReadStore
from agent_work.session.repo_context import (
    detect_repo_context,
    namespace_for_repo,
)
from agent_work.session.shortlist import apply_keyword_shortlist
from agent_work.session.tool_output_budget import (
    ToolOutputBudgetConfig,
    apply_tool_output_batch_budget,
    tool_output_budget_config_from_env,
)
from agent_work.session.tool_output_prune import (
    ToolOutputPruneConfig,
    apply_tool_output_prune,
    tool_output_prune_config_from_env,
)
from agent_work.session.state import SessionState
from agent_work.session.mode_permission_policy import (
    build_mode_permission_policy,
)
from agent_work.session.perm_tool_mode import (
    tool_definitions_for_perm_mode,
)
from agent_work.session.tool_exposure import tool_definitions_for_settings
from agent_work.session.tool_choice_policy import (
    default_tool_choice_policy,
    last_batch_had_successful_write_file,
)
from agent_work.session.bash_tool_events import emit_bash_shell_telemetry
from agent_work.session.event_contract import SessionEvent, SessionEventSink
from agent_work.tool_runtime.approval import ApprovalSession
from agent_work.tool_runtime.executor import (
    ApprovalPending,
    ToolExecutor,
    ToolInvocation,
    ToolRejected,
    ToolRunResult,
)
from agent_work.tool_runtime.permission import PermissionEngine
from ailit_base.normalization.usage_fields import usage_to_diag_dict
from agent_work.tool_runtime.read_file_envelope import (
    split_read_file_tool_output,
)
from agent_work.tool_runtime.registry import ToolRegistry
from agent_work.tool_runtime.workdir_paths import work_root
from ailit_base.transport.errors import TransportHttpError


def _is_read_timeout(exc: BaseException) -> bool:
    """Return True for provider read timeouts across httpx/httpcore layers."""
    if isinstance(exc, httpx.ReadTimeout):
        return True
    name = type(exc).__name__
    text = str(exc).lower()
    return name == "ReadTimeout" or "read operation timed out" in text


def _default_suppress_tools_after_write_file() -> bool:
    """Legacy: один запрос без tools после write_file (вкл. через env)."""
    raw = (
        os.environ.get("AILIT_SUPPRESS_TOOLS_AFTER_WRITE", "")
        .strip()
        .lower()
    )
    return raw in ("1", "true", "yes", "on")


def _tool_call_finished_payload(
    inv: ToolInvocation,
    res: ToolRunResult,
) -> dict[str, Any]:
    """Полезная нагрузка для UI/логов по завершении инструмента."""
    pl: dict[str, Any] = {
        "tool": inv.tool_name,
        "call_id": inv.call_id,
        "ok": res.error is None,
    }
    ext = res.extras
    if ext:
        for key in ("relative_path", "file_change_kind"):
            if key in ext:
                pl[key] = ext[key]
    return pl


def _incomplete_tool_followup(messages: Sequence[ChatMessage]) -> bool:
    """True если последний assistant с tool_calls ещё без всех TOOL ответов."""
    last_ast: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.role is MessageRole.ASSISTANT and m.tool_calls:
            last_ast = i
            break
    if last_ast is None:
        return False
    ast = messages[last_ast]
    assert ast.tool_calls is not None
    needed = {tc.call_id for tc in ast.tool_calls}
    got: set[str] = set()
    for j in range(last_ast + 1, len(messages)):
        tm = messages[j]
        if tm.role is MessageRole.TOOL and tm.tool_call_id:
            got.add(tm.tool_call_id)
    return not needed <= got


@dataclass(frozen=True, slots=True)
class SessionSettings:
    """Параметры одного прогона session loop."""

    model: str = "mock"
    temperature: float = 0.0
    max_tokens: int | None = None
    max_turns: int = 10_000
    agent_steps_cap: int | None = None
    max_context_units: int | None = None
    max_total_tokens: int | None = None
    compaction_tail_messages: int = 40
    compaction_max_tool_chars: int = 2000
    post_compact_restore_enabled: bool = True
    post_compact_restore_max_files: int = 5
    post_compact_restore_max_chars_per_file: int = 2500
    post_compact_restore_max_total_chars: int = 9000
    tool_exposure: str = "full"
    shortlist_keywords: frozenset[str] | None = None
    use_stream: bool = False
    suppress_tools_after_write_file: bool = field(
        default_factory=_default_suppress_tools_after_write_file,
    )
    context_pager: ContextPagerConfig = field(
        default_factory=context_pager_config_from_env,
    )
    tool_output_budget: ToolOutputBudgetConfig = field(
        default_factory=tool_output_budget_config_from_env,
    )
    tool_output_prune: ToolOutputPruneConfig = field(
        default_factory=tool_output_prune_config_from_env,
    )
    # perm-5: режим инструментов + (опционально) классификатор в UI.
    perm_mode_enabled: bool = False
    perm_tool_mode: str = "explore"
    perm_classifier_bypass: bool = False
    perm_history_max: int = 8
    pag_runtime_enabled: bool = True
    compact_to_memory_enabled: bool = False


def _perm_engine_for_session(
    init_perm: PermissionEngine,
    settings: SessionSettings,
) -> object:
    """Политика разрешений с учётом perm-режима или legacy init_perm."""
    if not settings.perm_mode_enabled:
        return init_perm
    return build_mode_permission_policy(
        settings.perm_tool_mode,
        legacy_engine=init_perm,
    )


def _effective_max_turns(settings: SessionSettings) -> int:
    """Минимум из настроек и опционального AILIT_AGENT_HARD_CAP."""
    raw = os.environ.get("AILIT_AGENT_HARD_CAP", "1000000")
    try:
        hard = int(raw)
    except ValueError:
        hard = 1_000_000
    hard = max(1, hard)
    configured = max(1, settings.max_turns)
    return min(configured, hard)


def _effective_agent_steps_cap(settings: SessionSettings) -> int | None:
    """Жёсткий cap agentic tool-итераций (OpenCode `steps`-аналог)."""
    raw = os.environ.get("AILIT_AGENT_STEPS_CAP", "").strip()
    if raw:
        try:
            v = int(raw)
        except ValueError:
            v = 0
        if v > 0:
            return v
    cap = settings.agent_steps_cap
    if cap is None:
        return None
    return cap if cap > 0 else None


_RUN_SHELL_LONG_PAT = re.compile(
    r"(^|[\s;|&])("
    r"make|cmake|ninja|docker|podman|apt|apt-get|yum|dnf|pip|pip3|poetry|npm"
    r"|pnpm|yarn"
    r"|\./|bash\s|sh\s|python\s|-m\s"
    r")",
    re.IGNORECASE,
)


def _maybe_guard_run_shell_invocation(
    inv: ToolInvocation,
    *,
    default_timeout_ms: int,
) -> tuple[ToolInvocation, dict[str, Any] | None]:
    """Guardrail: inject timeout_ms when command looks long."""
    if inv.tool_name not in ("run_shell", "run_shell_session"):
        return inv, None
    try:
        raw = json.loads(inv.arguments_json or "{}")
    except json.JSONDecodeError:
        return inv, None
    if not isinstance(raw, dict):
        return inv, None
    cmd = str(raw.get("command") or "").strip()
    if not cmd:
        return inv, None
    if raw.get("timeout_ms") not in (None, ""):
        return inv, None
    if not _RUN_SHELL_LONG_PAT.search(cmd):
        return inv, None
    raw2 = dict(raw)
    raw2["timeout_ms"] = int(default_timeout_ms)
    new_inv = ToolInvocation(
        inv.call_id,
        inv.tool_name,
        json.dumps(raw2, ensure_ascii=False),
    )
    meta = {
        "tool": inv.tool_name,
        "call_id": inv.call_id,
        "policy": "inject_timeout_ms",
        "timeout_ms": int(default_timeout_ms),
    }
    return new_inv, meta


def _prune_none_keys(d: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in d.items() if v is not None}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _normalize_user_intent(raw: str, max_chars: int = 280) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    s = " ".join(s.split())
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s


def _safe_id_part(raw: str, max_chars: int = 96) -> str:
    s = (raw or "").strip().replace("\\", "/")
    s = s.replace("://", "_").replace("/", "_")
    s = s.replace(":", "_").replace("@", "_").replace(" ", "_")
    if len(s) > max_chars:
        s = s[:max_chars]
    return s or "unknown"


def _append_kb_retrieval_digest_as_system(
    messages: list[ChatMessage],
    *,
    fr: dict[str, Any],
    level: str,
) -> None:
    """R4.4: memory block после kb_fetch (Letta-style; усечение body)."""
    title = str(fr.get("title") or "").strip()
    kind = str(fr.get("kind") or "").strip()
    summ = str(fr.get("summary") or "").strip()
    body = str(fr.get("body_snippet") or "")
    if len(body) > 1400:
        body = body[:1400].rstrip() + "…"
    head = f"{title} ({kind})" if kind else (title or kind or "kb_fetch")
    pieces = [f"KB fact (retrieval: {level}): {head}"]
    if summ:
        pieces.append(f"summary: {summ}")
    if body:
        pieces.append(f"excerpt: {body}")
    txt = "\n".join(pieces).strip()
    messages.append(ChatMessage(role=MessageRole.SYSTEM, content=txt))


def _append_kb_search_as_system(
    messages: list[ChatMessage],
    *,
    query: str,
    namespace: str | None,
    tool_output_json: str,
    max_chars: int = 2200,
) -> None:
    """Inject kb_search results without TOOL-role messages.

    OpenAI-compat APIs require TOOL messages to follow assistant tool_calls.
    Auto-retrieval is executed by runtime, so we expose it as a SYSTEM hint.
    """
    q = _normalize_user_intent(query, max_chars=120)
    ns = (namespace or "").strip()
    body = str(tool_output_json or "")
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "…"
    txt = (
        "KB retrieval (auto): "
        f"query={q!r} "
        f"namespace={ns!r}\n"
        f"{body}"
    ).strip()
    messages.append(ChatMessage(role=MessageRole.SYSTEM, content=txt))


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """Результат прогона или пауза на approval."""

    state: SessionState
    messages: tuple[ChatMessage, ...]
    events: tuple[dict[str, Any], ...]
    reason: str | None = None


class SessionRunner:
    """Готовит запросы к провайдеру, исполняет tools, ведёт бюджет."""

    def __init__(
        self,
        provider: ChatProvider,
        registry: ToolRegistry,
        *,
        permission_engine: PermissionEngine | None = None,
        file_changed_notifier: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Связать провайдер и реестр инструментов."""
        self._provider = provider
        self._base_registry = registry
        self._context_page_store = ContextPageStore()
        self._recent_reads = RecentFileReadStore()
        self._context_snapshot_builder = ContextSnapshotBuilder()
        self._d_level_compact = DLevelCompactService.default()
        self._pag_namespace: str = ""
        self._file_changed_notifier: (
            Callable[[dict[str, Any]], None] | None
        ) = file_changed_notifier
        perm = permission_engine or PermissionEngine()
        self._perm = perm

    def _tool_registry_for_run(
        self,
        settings: SessionSettings,
    ) -> ToolRegistry:
        """Реестр на прогон: базовый + read_context_page если pager вкл."""
        reg = self._base_registry
        if (
            settings.context_pager.enabled
            or settings.tool_output_budget.enabled
        ):
            return reg.merge(
                build_context_pager_read_registry(self._context_page_store),
            )
        return reg

    def _emit(
        self,
        events: list[dict[str, Any]],
        event_type: str,
        payload: dict[str, Any],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        row = {"event_type": event_type, **payload}
        events.append(row)
        if event_sink is not None:
            event_sink(SessionEvent(type=event_type, payload=dict(payload)))
        if diag_sink is not None:
            enriched: dict[str, Any] = {
                "contract": "ailit_session_diag_v1",
                "event_type": event_type,
                "ts": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                **payload,
            }
            diag_sink(enriched)

    def _safe_arguments_json(
        self,
        *,
        tool_name: str,
        arguments_json: str,
    ) -> str:
        """Redact potentially sensitive tool arguments for diagnostics."""
        name = str(tool_name or "")
        if name.startswith("kb_"):
            return "<redacted>"
        return arguments_json

    def _emit_memory_access(
        self,
        *,
        tool_name: str,
        call_id: str,
        arguments_json: str,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """Emit a safe, non-content memory access event (H4.2)."""
        name = str(tool_name or "")
        if not name.startswith("kb_"):
            return
        try:
            raw = json.loads(arguments_json) if arguments_json.strip() else {}
        except json.JSONDecodeError:
            raw = {}
        data: dict[str, Any] = {}
        if isinstance(raw, dict):
            for k in ("scope", "namespace", "top_k", "id", "to_status"):
                v = raw.get(k)
                if v is None:
                    continue
                if isinstance(v, (str, int)):
                    data[k] = v
            q = raw.get("query")
            if isinstance(q, str):
                data["query_len"] = len(q)
            body = raw.get("body")
            if isinstance(body, str):
                data["body_len"] = len(body)
        self._emit(
            events,
            "memory.access",
            {
                "tool": name,
                "call_id": str(call_id),
                **data,
            },
            diag_sink,
            event_sink,
        )

    def _maybe_inject_pag_slice(
        self,
        *,
        messages: list[ChatMessage],
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> tuple[str, tuple[str, ...], str | None]:
        """Inject a compact PAG slice as a system message (G7.4).

        Returns:
            (namespace, target_file_paths, fallback_reason)
        """
        from agent_memory.storage.pag_runtime import (  # noqa: WPS433
            PagRuntimeAgentMemory,
            PagRuntimeConfig,
            safe_event_payload_for_slice,
        )

        cfg = PagRuntimeConfig.from_env()
        if not cfg.enabled:
            return "", (), "disabled"
        goal = ""
        for m in reversed(messages[-12:]):
            if m.role is MessageRole.USER:
                goal = m.content or ""
                break
        mem = PagRuntimeAgentMemory(cfg)
        self._emit(
            events,
            "agent_memory.requested",
            {
                "contract_version": "ailit_pag_runtime_v1",
                "query_kind": "task",
                "level": "B",
                "db_path": str(mem.db_path),
            },
            diag_sink,
            event_sink,
        )
        slice_res = mem.build_slice_for_goal(
            project_root=Path(work_root()),
            goal=goal,
            query_kind="task",
        )
        self._pag_namespace = str(slice_res.namespace or "").strip()
        self._emit(
            events,
            "agent_memory.responded",
            {
                "contract_version": "ailit_pag_runtime_v1",
                **safe_event_payload_for_slice(slice_result=slice_res),
            },
            diag_sink,
            event_sink,
        )
        if slice_res.used and slice_res.injected_text:
            messages.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=slice_res.injected_text,
                ),
            )
            self._emit(
                events,
                "agent_work.pag_slice_used",
                {
                    "namespace": slice_res.namespace,
                    "files": list(slice_res.target_file_paths),
                },
                diag_sink,
                event_sink,
            )
            if slice_res.target_file_paths:
                self._emit(
                    events,
                    "agent_work.files_shortlisted",
                    {
                        "namespace": slice_res.namespace,
                        "files": list(slice_res.target_file_paths),
                    },
                    diag_sink,
                    event_sink,
                )
            return self._pag_namespace, slice_res.target_file_paths, None
        self._emit(
            events,
            "agent_work.pag_slice_rejected",
            {
                "namespace": slice_res.namespace,
                "staleness_state": slice_res.staleness_state,
                "fallback_reason": slice_res.fallback_reason,
            },
            diag_sink,
            event_sink,
        )
        return self._pag_namespace, (), slice_res.fallback_reason

    def _maybe_sync_pag_after_write_file(
        self,
        *,
        namespace: str,
        written_paths: Sequence[str],
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        from agent_memory.storage.pag_runtime import (  # noqa: WPS433
            PagRuntimeAgentMemory,
            PagRuntimeConfig,
            changed_ranges_from_write,
            safe_event_payload_for_sync,
        )

        cfg = PagRuntimeConfig.from_env()
        if not cfg.enabled or not cfg.sync_on_write_file:
            return
        ns = str(namespace).strip()
        if not written_paths:
            return
        if not ns:
            try:
                rc = detect_repo_context(Path(work_root()))
            except Exception:  # noqa: BLE001
                rc = None
            if rc is not None:
                ns = namespace_for_repo(
                    repo_uri=rc.repo_uri,
                    repo_path=rc.repo_path,
                    branch=rc.branch,
                )
        if not ns:
            return
        mem = PagRuntimeAgentMemory(cfg)
        ranges = changed_ranges_from_write(relative_paths=written_paths)
        mem.sync_after_write(
            project_root=Path(work_root()),
            namespace=ns,
            changed_paths=written_paths,
            changed_ranges=ranges,
        )
        self._emit(
            events,
            "agent_memory.synced_changes",
            safe_event_payload_for_sync(
                namespace=ns,
                changed_paths=written_paths,
                changed_ranges=ranges,
            ),
            diag_sink,
            event_sink,
        )

    def _emit_memory_promotion(
        self,
        *,
        inv: ToolInvocation,
        res: ToolRunResult,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """JSONL: memory.promotion.* по kb_promote / kb_write_fact."""
        name = str(inv.tool_name or "")
        if name not in ("kb_promote", "kb_write_fact"):
            return
        if res.error is not None:
            return
        try:
            payload = json.loads(res.content or "{}")
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        st = str(payload.get("status") or "")
        if name == "kb_promote":
            if st == "ok":
                self._emit(
                    events,
                    "memory.promotion.applied",
                    {
                        "call_id": str(inv.call_id),
                        "id": payload.get("id"),
                        "from_status": payload.get("from_status"),
                        "to_status": payload.get("to_status"),
                        "no_op": bool(payload.get("no_op", False)),
                    },
                    diag_sink,
                    event_sink,
                )
            elif st == "denied":
                self._emit(
                    events,
                    "memory.promotion.denied",
                    {
                        "call_id": str(inv.call_id),
                        "id": payload.get("id"),
                        "rule": payload.get("rule"),
                        "message": payload.get("message"),
                    },
                    diag_sink,
                    event_sink,
                )
        elif name == "kb_write_fact" and st == "denied":
            rule = str(payload.get("rule") or "")
            if rule == "promotion_via_kb_promote_only":
                self._emit(
                    events,
                    "memory.promotion.denied",
                    {
                        "call_id": str(inv.call_id),
                        "id": None,
                        "rule": rule,
                        "message": payload.get("message"),
                        "via": "kb_write_fact",
                    },
                    diag_sink,
                    event_sink,
                )

    def _namespace_for_d_level_compact(self) -> str:
        ns = str(self._pag_namespace or "").strip()
        if ns:
            return ns
        try:
            rc = detect_repo_context(Path(work_root()))
        except Exception:  # noqa: BLE001
            return "default"
        return namespace_for_repo(
            repo_uri=rc.repo_uri,
            repo_path=rc.repo_path,
            branch=rc.branch,
        )

    def _prepare_context(
        self,
        messages: list[ChatMessage],
        settings: SessionSettings,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> list[ChatMessage]:
        compacted = compact_messages(
            messages,
            tail_max=settings.compaction_tail_messages,
            max_tool_chars=settings.compaction_max_tool_chars,
        )
        if (
            settings.compact_to_memory_enabled
            and len(messages) > settings.compaction_tail_messages
        ):
            removed = messages[: -settings.compaction_tail_messages]
            ns = self._namespace_for_d_level_compact()
            try:
                res = self._d_level_compact.compact(
                    namespace=ns,
                    removed_messages=removed,
                    kept_messages=compacted,
                    linked_node_ids=(f"A:{ns}",),
                    trigger="auto",
                )
                compacted = [res.message, *compacted]
                self._emit(
                    events,
                    "context.compacted",
                    res.to_event_payload(trigger="auto"),
                    diag_sink,
                    event_sink,
                )
            except Exception as exc:  # noqa: BLE001
                self._emit(
                    events,
                    "context.compact_failed",
                    {
                        "schema": "context.compact_failed.v1",
                        "reason": f"{type(exc).__name__}:{exc}",
                    },
                    diag_sink,
                    event_sink,
                )
        if (
            settings.post_compact_restore_enabled
            and len(messages) > settings.compaction_tail_messages
        ):
            already = "\n".join(m.content for m in compacted[-8:]).strip()
            restore_msg, plan = self._recent_reads.build_restore_message(
                already_in_context=already,
                max_files=settings.post_compact_restore_max_files,
                max_chars_per_file=(
                    settings.post_compact_restore_max_chars_per_file
                ),
                max_total_chars=settings.post_compact_restore_max_total_chars,
            )
            if restore_msg is not None and plan.restored:
                compacted.append(restore_msg)
                self._emit(
                    events,
                    "compaction.restore_files",
                    {
                        "restored_files": len(plan.restored),
                        "injected_chars": plan.injected_chars,
                    },
                    diag_sink,
                    event_sink,
                )
        if settings.shortlist_keywords:
            return apply_keyword_shortlist(
                compacted,
                settings.shortlist_keywords,
            )
        return compacted

    def _invoke_model_request(
        self,
        *,
        context: list[ChatMessage],
        settings: SessionSettings,
        tool_choice: ToolChoice | None,
        tools_defs: tuple[ToolDefinition, ...],
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
        request_meta: dict[str, Any],
        cancel: Event | None,
    ) -> NormalizedChatResponse:
        """Вызов провайдера: stream или complete; эмит событий диагностики."""
        turn_id = str(request_meta.get("turn_id") or "turn-unknown")
        snapshot = self._context_snapshot_builder.build(
            context=context,
            model=settings.model,
            turn_id=turn_id,
            tools_defs=tools_defs,
        )
        self._emit(
            events,
            "context.snapshot",
            snapshot.to_payload(),
            diag_sink,
            event_sink,
        )
        self._emit(
            events,
            "model.request",
            {
                "context_messages": len(context),
                "tools_count": len(tools_defs),
                **request_meta,
            },
            diag_sink,
            event_sink,
        )
        req = ChatRequest(
            messages=context,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            tools=tools_defs,
            tool_choice=tool_choice,
            stream=settings.use_stream,
        )
        if settings.use_stream:
            attempts = 0
            while True:
                emitted_delta = False
                inc = stream_incremental_for_provider(self._provider)
                inc.reset()
                try:
                    stream_events = self._provider.stream(req)
                    for ev in stream_events:
                        if cancel is not None and cancel.is_set():
                            self._emit(
                                events,
                                "session.cancelled",
                                {"phase": "model_stream"},
                                diag_sink,
                                event_sink,
                            )
                            raise RuntimeError("cancelled")
                        if isinstance(ev, StreamTextDelta):
                            if ev.channel == "reasoning":
                                ev_name = "assistant.thinking"
                            else:
                                ev_name = "assistant.delta"
                            em = inc.consume(ev.channel, ev.text)
                            if em is not None:
                                pl: dict[str, Any] = {
                                    "text": em.text,
                                    "text_mode": em.text_mode,
                                }
                                self._emit(
                                    events,
                                    ev_name,
                                    pl,
                                    diag_sink,
                                    event_sink,
                                )
                                emitted_delta = True
                        if isinstance(ev, StreamDone):
                            return ev.response
                    msg = "stream ended without StreamDone"
                    raise ValueError(msg)
                except Exception as exc:  # noqa: BLE001
                    if (
                        _is_read_timeout(exc)
                        and not emitted_delta
                        and attempts < 1
                    ):
                        attempts += 1
                        self._emit(
                            events,
                            "model.retry",
                            {
                                "error_class": "timeout",
                                "reason": f"{type(exc).__name__}:{exc}",
                                "attempt": attempts,
                                "max_attempts": 1,
                                **request_meta,
                            },
                            diag_sink,
                            event_sink,
                        )
                        continue
                    raise
        if cancel is not None and cancel.is_set():
            self._emit(
                events,
                "session.cancelled",
                {"phase": "model_complete"},
                diag_sink,
                event_sink,
            )
            raise RuntimeError("cancelled")
        attempts = 0
        while True:
            try:
                return self._provider.complete(req)
            except Exception as exc:  # noqa: BLE001
                if _is_read_timeout(exc) and attempts < 1:
                    attempts += 1
                    self._emit(
                        events,
                        "model.retry",
                        {
                            "error_class": "timeout",
                            "reason": f"{type(exc).__name__}:{exc}",
                            "attempt": attempts,
                            "max_attempts": 1,
                            **request_meta,
                        },
                        diag_sink,
                        event_sink,
                    )
                    continue
                raise

    def _finalize_after_turn_cap(
        self,
        messages: list[ChatMessage],
        settings: SessionSettings,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
        bud: BudgetGovernance,
    ) -> SessionOutcome:
        """После исчерпания лимита ходов — один text-only запрос без tools."""
        self._emit(
            events,
            "session.cap_hit",
            {"policy": "finalize_text_only"},
            diag_sink,
            event_sink,
        )
        ctx_base = self._prepare_context(
            messages,
            settings,
            events,
            diag_sink,
            event_sink,
        )
        cap_msg = (
            "The maximum number of agent steps for this session was reached. "
            "Reply in natural language only: brief summary of progress, "
            "what is still pending if anything, and how the user may "
            "continue. Do not use tools."
        )
        finalize_prompt = ChatMessage(
            role=MessageRole.SYSTEM,
            content=cap_msg,
        )
        ctx_final = list(ctx_base) + [finalize_prompt]
        tools_empty: tuple[ToolDefinition, ...] = ()
        try:
            resp = self._invoke_model_request(
                context=ctx_final,
                settings=settings,
                tool_choice=None,
                tools_defs=tools_empty,
                events=events,
                diag_sink=diag_sink,
                event_sink=event_sink,
                request_meta={
                    "turn_id": "cap_finalize",
                    "tool_choice_mode": "none_finalize",
                    "policy_reason": "session_turn_cap",
                },
                cancel=None,
            )
        except Exception as exc:  # noqa: BLE001
            err_reason = f"{type(exc).__name__}:{exc}"
            extra: dict[str, object] = {}
            if _is_read_timeout(exc):
                extra["error_class"] = "timeout"
            self._emit(
                events,
                "model.error",
                {"reason": err_reason, "phase": "cap_finalize", **extra},
                diag_sink,
                event_sink,
            )
            messages.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=(
                        "Достигнут лимит шагов агента в этой сессии; "
                        "не удалось получить итоговое резюме от модели. "
                        "Продолжите новым сообщением или проверьте "
                        "настройки провайдера."
                    ),
                )
            )
            return SessionOutcome(
                state=SessionState.FINISHED,
                messages=tuple(messages),
                events=tuple(events),
                reason="cap_finalize_failed",
            )

        bud.record_usage(resp.usage)
        self._emit(
            events,
            "context.provider_usage_confirmed",
            provider_usage_confirmed_payload(
                usage=resp.usage,
                turn_id="cap_finalize",
            ),
            diag_sink,
            event_sink,
        )
        fin = resp.finish_reason.value
        resp_tool_names = [tc.tool_name for tc in resp.tool_calls]
        self._emit(
            events,
            "model.response",
            {
                "finish": fin,
                "tool_calls_count": len(resp.tool_calls),
                "tool_names": resp_tool_names,
                "usage": usage_to_diag_dict(resp.usage),
                "usage_session_totals": bud.diag_totals_dict(),
                "phase": "cap_finalize",
            },
            diag_sink,
            event_sink,
        )
        over = bud.check_exceeded(messages)
        if over is not None:
            self._emit(
                events,
                "session.budget",
                {"reason": over},
                diag_sink,
                event_sink,
            )
            return SessionOutcome(
                state=SessionState.BUDGET_EXCEEDED,
                messages=tuple(messages),
                events=tuple(events),
                reason=over,
            )

        text = "".join(resp.text_parts)
        if resp.tool_calls:
            fallback = (
                "Итог: после лимита шагов модель снова запросила инструменты; "
                "их выполнение отключено. Кратко опишите пользователю "
                "состояние задачи текстом."
            )
            text = text or fallback
        messages.append(ChatMessage(role=MessageRole.ASSISTANT, content=text))
        return SessionOutcome(
            state=SessionState.FINISHED,
            messages=tuple(messages),
            events=tuple(events),
            reason=None,
        )

    def _emit_context_pager_page_used(
        self,
        inv: ToolInvocation,
        res: ToolRunResult,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """Событие context.pager.page_used после read_context_page."""
        if res.error is not None:
            return
        if inv.tool_name != READ_CONTEXT_PAGE_NAME:
            return
        try:
            args = (
                json.loads(inv.arguments_json)
                if (inv.arguments_json and inv.arguments_json.strip())
                else {}
            )
        except json.JSONDecodeError:
            return
        if not isinstance(args, dict):
            return
        page_id = str(args.get("page_id", "") or "").strip()
        if not page_id:
            return
        try:
            off = int(args.get("offset_lines", 0) or 0)
        except (TypeError, ValueError):
            off = 0
        try:
            mlines = int(args.get("max_lines", 200) or 200)
        except (TypeError, ValueError):
            mlines = 200
        content = res.content or ""
        returned_lines = len(content.splitlines()) if content else 0
        self._emit(
            events,
            "context.pager.page_used",
            {
                "page_id": page_id,
                "reason": "read_context_page",
                "offset_lines": off,
                "max_lines": mlines,
                "returned_lines": returned_lines,
            },
            diag_sink,
            event_sink,
        )

    def _emit_fs_read_file_completed(
        self,
        inv: ToolInvocation,
        res: ToolRunResult,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """Наблюдаемость range-read (E2E-M3-01); path — только basename."""
        if res.error is not None:
            return
        try:
            raw = (
                json.loads(inv.arguments_json)
                if (inv.arguments_json and inv.arguments_json.strip())
                else {}
            )
        except json.JSONDecodeError:
            return
        if not isinstance(raw, dict):
            return
        p = raw.get("path")
        rel = str(p) if isinstance(p, str) else ""
        tail = os.path.basename(rel.replace("\\", "/")) if rel else "?"
        try:
            off = int(raw.get("offset", 1) or 1)
        except (TypeError, ValueError):
            off = 1
        lim_raw = raw.get("limit")
        limit: int | None
        if lim_raw is None or lim_raw == "":
            limit = None
        else:
            try:
                limit = int(lim_raw)
            except (TypeError, ValueError):
                limit = None
        body = res.content or ""
        stub = body.startswith(
            "File unchanged since last read in this process:",
        )
        if not stub:
            pay = split_read_file_tool_output(body)
            ret_lines = int(pay.body_line_count)
        else:
            ret_lines = len((body or "").splitlines()) if body else 0
        ex = res.extras or {}
        ar = ex.get("ailit_read") if isinstance(ex, dict) else None
        if not stub and isinstance(ar, dict) and ar:
            total_ln = int(ar.get("total_lines", 0) or 0)
            c_from = int(ar.get("from_line", 0) or 0)
            c_to = int(ar.get("to_line", 0) or 0)
            r_src = str(ar.get("source", "") or "")
        else:
            total_ln = 0
            c_from = off
            c_to = 0
            r_src = ""
        range_read = (off > 1) or (limit is not None)
        payload: dict[str, Any] = {
            "call_id": str(inv.call_id),
            "path_tail": tail,
            "offset_line": off,
            "limit_line": limit,
            "returned_lines": ret_lines,
            "range_read": range_read,
            "unchanged_stub": stub,
        }
        if not stub and isinstance(ar, dict) and ar:
            payload["content_from_line"] = c_from
            payload["content_to_line"] = c_to
            payload["total_lines"] = total_ln
            payload["read_source"] = r_src
        self._emit(
            events,
            "fs.read_file.completed",
            payload,
            diag_sink,
            event_sink,
        )

    def _append_tool_results(
        self,
        messages: list[ChatMessage],
        invs: list[ToolInvocation],
        results: list[ToolRunResult],
        settings: SessionSettings,
        events: list[dict[str, Any]],
        diag_sink: Callable[[dict[str, Any]], None] | None,
        event_sink: SessionEventSink | None,
    ) -> None:
        """Добавить TOOL: pager → char budget (батч) → сообщения."""
        written: list[str] = []
        written_items: list[dict[str, Any]] = []
        for inv, tr in zip(invs, results, strict=True):
            if (
                tr.tool_name in ("write_file", "apply_patch")
                and tr.error is None
            ):
                ext = tr.extras or {}
                rp = ext.get("relative_path")
                if isinstance(rp, str) and rp.strip():
                    p0 = rp.strip()
                    written.append(p0)
                    written_items.append(
                        {
                            "path": p0,
                            "tool": str(tr.tool_name or ""),
                            "call_id": str(inv.call_id),
                        },
                    )
        if written:
            wr = tuple(sorted(set(written)))
            self._maybe_sync_pag_after_write_file(
                namespace=self._pag_namespace,
                written_paths=wr,
                events=events,
                diag_sink=diag_sink,
                event_sink=event_sink,
            )
            if self._file_changed_notifier is not None:
                self._file_changed_notifier(
                    {
                        "namespace": str(self._pag_namespace or "").strip(),
                        "written_paths": wr,
                        "written_items": written_items,
                    },
                )
        pcfg = settings.context_pager
        rows: list[tuple[ToolInvocation, ToolRunResult, str]] = []
        for inv, tr in zip(invs, results, strict=True):
            body = tr.content if tr.error is None else f"error:{tr.error}"
            if tr.error is None and inv.tool_name == "read_file":
                self._recent_reads.observe_read_file(
                    arguments_json=inv.arguments_json,
                    tool_output=tr.content or "",
                )
                self._emit_fs_read_file_completed(
                    inv, tr, events, diag_sink, event_sink,
                )
            # Не пагинировать вывод read_context_page: иначе каждый чанк
            # становится новой «страницей» → модель снова вызывает
            # read_context_page(offset=0) → бесконечная цепочка page_id.
            if (
                pcfg.enabled
                and tr.error is None
                and inv.tool_name != READ_CONTEXT_PAGE_NAME
                and len(body) >= pcfg.min_body_chars
            ):
                page_id = stable_page_id(
                    content=body,
                    call_id=inv.call_id,
                    tool_name=inv.tool_name,
                )
                source = tool_to_source_key(inv.tool_name)
                loc = locator_from_invocation(
                    inv.tool_name,
                    inv.arguments_json,
                )
                preview = build_preview(
                    body,
                    max_lines=pcfg.preview_max_lines,
                    max_chars=pcfg.preview_max_chars,
                )
                self._context_page_store.put(
                    page_id,
                    StoredPage(
                        full_text=body,
                        source=source,
                        tool_name=inv.tool_name,
                        locator=loc,
                    ),
                )
                b_total = len(body.encode("utf-8"))
                b_prev = len(preview.encode("utf-8"))
                preview_line_count = len(preview.splitlines())
                self._emit(
                    events,
                    "context.pager.page_created",
                    {
                        "page_id": page_id,
                        "source": source,
                        "tool_name": inv.tool_name,
                        "locator": loc,
                        "bytes_total": b_total,
                        "bytes_preview": b_prev,
                        "preview_lines": preview_line_count,
                    },
                    diag_sink,
                    event_sink,
                )
                body = build_tool_message_for_page(
                    page_id=page_id,
                    source=source,
                    locator=loc,
                    full_text=tr.content,
                    preview=preview,
                    config=pcfg,
                )
            rows.append((inv, tr, body))

        bcfg = settings.tool_output_budget
        bodies, t0, t1, nrep, extra_pager = apply_tool_output_batch_budget(
            rows,
            budget=bcfg,
            page_store=self._context_page_store,
        )
        for pev in extra_pager:
            self._emit(
                events,
                "context.pager.page_created",
                pev,
                diag_sink,
                event_sink,
            )
        if bcfg.enabled and nrep > 0:
            page_ids = [
                e.get("page_id")
                for e in extra_pager
                if e.get("page_id")
            ]
            self._emit(
                events,
                "tool.output_budget.enforced",
                {
                    "limit": bcfg.max_total_chars,
                    "total_before": t0,
                    "total_after": t1,
                    "replaced_count": nrep,
                    "page_id": [x for x in page_ids if isinstance(x, str)],
                },
                diag_sink,
                event_sink,
            )
        for inv, body in zip(
            (r[0] for r in rows), bodies, strict=True,
        ):
            messages.append(
                ChatMessage(
                    role=MessageRole.TOOL,
                    content=body,
                    tool_call_id=inv.call_id,
                ),
            )

    def _maybe_set_suppress_after_write_file(
        self,
        invs: list[ToolInvocation],
        results: list[ToolRunResult],
        settings: SessionSettings,
        suppress_next: list[bool],
    ) -> None:
        """Выставить флаг подавления tools после успешного write_file."""
        if not settings.suppress_tools_after_write_file:
            return
        if last_batch_had_successful_write_file(invs, results):
            suppress_next[0] = True

    def run(
        self,
        messages: list[ChatMessage],
        approvals: ApprovalSession,
        settings: SessionSettings,
        *,
        budget: BudgetGovernance | None = None,
        diag_sink: Callable[[dict[str, Any]], None] | None = None,
        event_sink: SessionEventSink | None = None,
        cancel: Event | None = None,
    ) -> SessionOutcome:
        """Цикл до FINISHED, бюджета, ошибки или паузы на approval."""
        events: list[dict[str, Any]] = []
        try:
            rc = detect_repo_context(Path(work_root()))
            self._emit(
                events,
                "memory.policy",
                {
                    "enabled": True,
                    "repo": rc.to_event_payload(),
                },
                diag_sink,
                event_sink,
            )
        except Exception:  # noqa: BLE001
            # Диагностика не должна ломать сессию.
            pass
        if settings.perm_mode_enabled:
            self._emit(
                events,
                "mode.enforced",
                {
                    "perm_tool_mode": settings.perm_tool_mode,
                    "perm_classifier_bypass": settings.perm_classifier_bypass,
                },
                diag_sink,
                event_sink,
            )
        if (
            settings.context_pager.enabled
            or settings.tool_output_budget.enabled
        ):
            self._context_page_store.clear()
        active_reg = self._tool_registry_for_run(settings)
        perm_engine = _perm_engine_for_session(self._perm, settings)
        executor = ToolExecutor(active_reg, perm_engine)
        bud = budget or BudgetGovernance(
            max_total_tokens=settings.max_total_tokens,
            max_context_units=settings.max_context_units,
        )
        suppress_next: list[bool] = [False]
        last_auto_kb_query: str | None = None
        wrote_repo_fact = False
        wrote_repo_tree_fact = False
        wrote_repo_signals_fact = False
        wrote_session_intent_fact = False
        wrote_repo_entrypoints_fact = False
        wrote_repo_safe_commands_fact = False
        auto_kb_search_n = 0
        auto_kb_fetch_n = 0
        auto_kb_write_n = 0
        cap_search = max(1, _env_int("AILIT_AUTO_KB_SEARCH_CAP", 30))
        cap_fetch = max(1, _env_int("AILIT_AUTO_KB_FETCH_CAP", 30))
        cap_write = max(1, _env_int("AILIT_AUTO_KB_WRITE_CAP", 10))
        steps_cap = _effective_agent_steps_cap(settings)
        agent_steps = 0
        last_model_tool_sig: str | None = None
        same_tool_sig_n = 0
        pag_namespace: str = ""

        for turn in range(_effective_max_turns(settings)):
            if cancel is not None and cancel.is_set():
                self._emit(
                    events,
                    "session.cancelled",
                    {"phase": "turn_loop"},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.ERROR,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason="cancelled",
                )
            self._emit(
                events,
                "session.turn",
                {"index": turn},
                diag_sink,
                event_sink,
            )
            if steps_cap is not None and agent_steps >= steps_cap:
                return self._finalize_after_turn_cap(
                    messages,
                    settings,
                    events,
                    diag_sink,
                    event_sink,
                    bud,
                )
            if settings.tool_output_prune.enabled:
                pr = apply_tool_output_prune(
                    messages,
                    settings.tool_output_prune,
                )
                pcount = int(pr.get("pruned_tools_count", 0) or 0)
                if pcount > 0:
                    self._emit(
                        events,
                        "tool.output_prune.applied",
                        {
                            "pruned_tools_count": pcount,
                            "pruned_bytes_estimate": int(
                                pr.get("pruned_bytes_estimate", 0) or 0,
                            ),
                            "protected_tools": pr.get("protected_skipped", []),
                        },
                        diag_sink,
                        event_sink,
                    )
            exc = bud.check_exceeded(messages)
            if exc is not None:
                self._emit(
                    events,
                    "session.budget",
                    {"reason": exc},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.BUDGET_EXCEEDED,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason=exc,
                )

            if _incomplete_tool_followup(messages):
                ast_idx = next(
                    i
                    for i in range(len(messages) - 1, -1, -1)
                    if messages[i].role is MessageRole.ASSISTANT
                    and messages[i].tool_calls
                )
                ast = messages[ast_idx]
                assert ast.tool_calls is not None
                invs = [
                    ToolInvocation(tc.call_id, tc.tool_name, tc.arguments_json)
                    for tc in ast.tool_calls
                ]
                guarded: list[ToolInvocation] = []
                for inv in invs:
                    ginv, meta = _maybe_guard_run_shell_invocation(
                        inv,
                        default_timeout_ms=30_000,
                    )
                    if meta is not None:
                        self._emit(
                            events,
                            "run_shell.guardrail",
                            meta,
                            diag_sink,
                            event_sink,
                        )
                    guarded.append(ginv)
                invs = guarded
                tool_names = [inv.tool_name for inv in invs]
                self._emit(
                    events,
                    "tool.batch",
                    {"count": len(invs), "tool_names": tool_names},
                    diag_sink,
                    event_sink,
                )
                try:
                    for inv in invs:
                        self._emit(
                            events,
                            "tool.call_started",
                            {
                                "tool": inv.tool_name,
                                "call_id": inv.call_id,
                                "arguments_json": self._safe_arguments_json(
                                    tool_name=inv.tool_name,
                                    arguments_json=inv.arguments_json,
                                ),
                            },
                            diag_sink,
                            event_sink,
                        )
                        self._emit_memory_access(
                            tool_name=inv.tool_name,
                            call_id=inv.call_id,
                            arguments_json=inv.arguments_json,
                            events=events,
                            diag_sink=diag_sink,
                            event_sink=event_sink,
                        )
                    results = executor.execute_serial(
                        invs,
                        approvals,
                        cancel=cancel,
                    )
                except ApprovalPending as exc:
                    self._emit(
                        events,
                        "session.waiting_approval",
                        {"call_id": exc.call_id, "tool": exc.tool_name},
                        diag_sink,
                        event_sink,
                    )
                    return SessionOutcome(
                        state=SessionState.WAITING_APPROVAL,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason="approval_pending",
                    )
                except ToolRejected as exc:
                    return SessionOutcome(
                        state=SessionState.ERROR,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason=f"rejected:{exc.tool_name}",
                    )
                for inv, res in zip(invs, results, strict=True):

                    def _emit_bash_et(et: str, pl: dict[str, Any]) -> None:
                        self._emit(events, et, pl, diag_sink, event_sink)

                    emit_bash_shell_telemetry(_emit_bash_et, inv, res)
                    self._emit(
                        events,
                        "tool.call_finished",
                        _tool_call_finished_payload(inv, res),
                        diag_sink,
                        event_sink,
                    )
                    self._emit_memory_promotion(
                        inv=inv,
                        res=res,
                        events=events,
                        diag_sink=diag_sink,
                        event_sink=event_sink,
                    )
                    self._emit_context_pager_page_used(
                        inv, res, events, diag_sink, event_sink
                    )
                self._maybe_set_suppress_after_write_file(
                    invs,
                    results,
                    settings,
                    suppress_next,
                )
                self._append_tool_results(
                    messages,
                    invs,
                    results,
                    settings,
                    events,
                    diag_sink,
                    event_sink,
                )
                continue

            if (
                not wrote_repo_fact
                and "kb_write_fact" in active_reg.specs
            ):
                try:
                    rc2 = detect_repo_context(Path(work_root()))
                except Exception:  # noqa: BLE001
                    rc2 = None
                if rc2 is not None:
                    if auto_kb_write_n >= cap_write:
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_write_fact",
                                "cap": cap_write,
                                "count": auto_kb_write_n,
                                "reason": "auto_write_repo_identity",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_fact = True
                        continue
                    stable = rc2.repo_uri or rc2.repo_path
                    rid = (
                        "repo:"
                        + stable.replace("/", "_").replace(":", "_")
                    )
                    if rc2.branch:
                        rid = rid + ":" + rc2.branch.replace("/", "_")
                    nsw = namespace_for_repo(
                        repo_uri=rc2.repo_uri,
                        repo_path=rc2.repo_path,
                        branch=rc2.branch,
                    )
                    title = f"Repo: {rc2.repo_uri or rc2.repo_path}"
                    parts = []
                    if rc2.branch:
                        parts.append(f"branch={rc2.branch}")
                    if rc2.commit:
                        parts.append(f"commit={rc2.commit[:10]}")
                    summary = "; ".join(parts) if parts else "repo identity"
                    body = "\n".join(
                        [
                            f"repo_uri={rc2.repo_uri}",
                            f"repo_path={rc2.repo_path}",
                            f"branch={rc2.branch or ''}",
                            f"commit={rc2.commit or ''}",
                            f"default_branch={rc2.default_branch or ''}",
                        ],
                    ).strip()
                    invw = ToolInvocation(
                        call_id=f"auto_kb_write_repo_{turn}",
                        tool_name="kb_write_fact",
                        arguments_json=json.dumps(
                            {
                                "id": rid,
                                "scope": "project",
                                "namespace": nsw,
                                "title": title,
                                "summary": summary,
                                "body": body,
                                "author": "auto_memory",
                                "provenance": rc2.to_event_payload(),
                            },
                            ensure_ascii=False,
                        ),
                    )
                    self._emit(
                        events,
                        "tool.batch",
                        {
                            "count": 1,
                            "tool_names": ["kb_write_fact"],
                            "reason": "auto_kb",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit(
                        events,
                        "tool.call_started",
                        {
                            "tool": invw.tool_name,
                            "call_id": invw.call_id,
                            "arguments_json": self._safe_arguments_json(
                                tool_name=invw.tool_name,
                                arguments_json=invw.arguments_json,
                            ),
                            "reason": "auto_kb",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit_memory_access(
                        tool_name=invw.tool_name,
                        call_id=invw.call_id,
                        arguments_json=invw.arguments_json,
                        events=events,
                        diag_sink=diag_sink,
                        event_sink=event_sink,
                    )
                    try:
                        resw = executor.execute_one(
                            invw,
                            approvals,
                            cancel=cancel,
                        )
                    except ApprovalPending:
                        self._emit(
                            events,
                            "memory.auto_write.skipped",
                            {
                                "tool": "kb_write_fact",
                                "reason": "approval_pending",
                                "kind": "repo_identity",
                            },
                            diag_sink,
                            event_sink,
                        )
                    else:
                        auto_kb_write_n += 1
                        self._emit(
                            events,
                            "tool.call_finished",
                            _tool_call_finished_payload(invw, resw),
                            diag_sink,
                            event_sink,
                        )
                        self._emit(
                            events,
                            "memory.auto_write.done",
                            {
                                "tool": "kb_write_fact",
                                "kind": "repo_identity",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_fact = True

            if (
                not wrote_session_intent_fact
                and "kb_write_fact" in active_reg.specs
            ):
                last_user_intent = next(
                    (
                        m
                        for m in reversed(messages)
                        if (
                            m.role is MessageRole.USER
                            and (m.content or "").strip()
                        )
                    ),
                    None,
                )
                intent = (
                    _normalize_user_intent(last_user_intent.content)
                    if last_user_intent is not None
                    else ""
                )
                if intent:
                    if auto_kb_write_n >= cap_write:
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_write_fact",
                                "cap": cap_write,
                                "count": auto_kb_write_n,
                                "reason": "auto_write_session_intent",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_session_intent_fact = True
                    else:
                        try:
                            rc_int = detect_repo_context(Path(work_root()))
                        except Exception:  # noqa: BLE001
                            rc_int = None
                        ns_int: str | None = None
                        stable = None
                        if rc_int is not None:
                            ns_int = namespace_for_repo(
                                repo_uri=rc_int.repo_uri,
                                repo_path=rc_int.repo_path,
                                branch=rc_int.branch,
                            )
                            stable = rc_int.repo_uri or rc_int.repo_path
                        else:
                            stable = str(work_root())
                        rid_int = (
                            "session_intent:"
                            + str(stable).replace("/", "_").replace(":", "_")
                        )
                        if rc_int is not None and rc_int.branch:
                            rid_int = (
                                rid_int
                                + ":"
                                + rc_int.branch.replace("/", "_")
                            )
                        body_int = "\n".join(
                            [
                                f"user_intent={intent}",
                                (
                                    f"repo_uri="
                                    f"{rc_int.repo_uri if rc_int else ''}"
                                ),
                                (
                                    f"repo_path="
                                    f"{rc_int.repo_path if rc_int else ''}"
                                ),
                                f"branch={rc_int.branch if rc_int else ''}",
                                f"commit={rc_int.commit if rc_int else ''}",
                            ],
                        ).strip()
                        inv_int = ToolInvocation(
                            call_id=f"auto_kb_write_intent_{turn}",
                            tool_name="kb_write_fact",
                            arguments_json=json.dumps(
                                {
                                    "id": rid_int,
                                    "scope": "run",
                                    "namespace": ns_int,
                                    "title": "Session intent",
                                    "summary": intent,
                                    "body": body_int[:2000],
                                    "author": "auto_memory",
                                    "provenance": (
                                        rc_int.to_event_payload()
                                        if rc_int is not None
                                        else {}
                                    ),
                                    "source": "auto_session_intent",
                                },
                                ensure_ascii=False,
                            ),
                        )
                        self._emit(
                            events,
                            "tool.batch",
                            {
                                "count": 1,
                                "tool_names": ["kb_write_fact"],
                                "reason": "auto_kb_intent",
                            },
                            diag_sink,
                            event_sink,
                        )
                        self._emit(
                            events,
                            "tool.call_started",
                            {
                                "tool": inv_int.tool_name,
                                "call_id": inv_int.call_id,
                                "arguments_json": self._safe_arguments_json(
                                    tool_name=inv_int.tool_name,
                                    arguments_json=inv_int.arguments_json,
                                ),
                                "reason": "auto_kb_intent",
                            },
                            diag_sink,
                            event_sink,
                        )
                        self._emit_memory_access(
                            tool_name=inv_int.tool_name,
                            call_id=inv_int.call_id,
                            arguments_json=inv_int.arguments_json,
                            events=events,
                            diag_sink=diag_sink,
                            event_sink=event_sink,
                        )
                        try:
                            res_int = executor.execute_one(
                                inv_int,
                                approvals,
                                cancel=cancel,
                            )
                        except ApprovalPending:
                            self._emit(
                                events,
                                "memory.auto_write.skipped",
                                {
                                    "tool": "kb_write_fact",
                                    "reason": "approval_pending",
                                    "kind": "session_intent",
                                },
                                diag_sink,
                                event_sink,
                            )
                        else:
                            auto_kb_write_n += 1
                            self._emit(
                                events,
                                "tool.call_finished",
                                _tool_call_finished_payload(
                                    inv_int,
                                    res_int,
                                ),
                                diag_sink,
                                event_sink,
                            )
                            self._emit(
                                events,
                                "memory.auto_write.done",
                                {
                                    "tool": "kb_write_fact",
                                    "kind": "session_intent",
                                },
                                diag_sink,
                                event_sink,
                            )
                        wrote_session_intent_fact = True

            if (
                not wrote_repo_tree_fact
                and "list_dir" in active_reg.specs
                and "kb_write_fact" in active_reg.specs
            ):
                try:
                    rc4 = detect_repo_context(Path(work_root()))
                except Exception:  # noqa: BLE001
                    rc4 = None
                if rc4 is not None:
                    if auto_kb_write_n >= cap_write:
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_write_fact",
                                "cap": cap_write,
                                "count": auto_kb_write_n,
                                "reason": "auto_write_repo_tree_root",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_tree_fact = True
                        continue
                    ns_tree = namespace_for_repo(
                        repo_uri=rc4.repo_uri,
                        repo_path=rc4.repo_path,
                        branch=rc4.branch,
                    )
                    inv_ls = ToolInvocation(
                        call_id=f"auto_list_dir_root_{turn}",
                        tool_name="list_dir",
                        arguments_json=json.dumps(
                            {"path": "."},
                            ensure_ascii=False,
                        ),
                    )
                    try:
                        res_ls = executor.execute_one(
                            inv_ls,
                            approvals,
                            cancel=cancel,
                        )
                    except ApprovalPending:
                        res_ls = ToolRunResult(
                            call_id=inv_ls.call_id,
                            tool_name=inv_ls.tool_name,
                            content="",
                            error="approval_pending",
                            extras=None,
                        )
                    tree_body = ""
                    if res_ls.error is None and res_ls.content:
                        tree_body = str(res_ls.content)
                    inv_tree = ToolInvocation(
                        call_id=f"auto_kb_write_tree_{turn}",
                        tool_name="kb_write_fact",
                        arguments_json=json.dumps(
                            {
                                "id": f"repo_tree:{ns_tree}",
                                "scope": "project",
                                "namespace": ns_tree,
                                "title": "Repo tree (root)",
                                "summary": (
                                    "Root directory entries (list_dir)."
                                ),
                                "body": tree_body[:8000],
                                "author": "auto_memory",
                                "provenance": (
                                    rc4.to_event_payload()
                                    if rc4 is not None
                                    else {}
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    )
                    self._emit(
                        events,
                        "tool.batch",
                        {
                            "count": 1,
                            "tool_names": ["kb_write_fact"],
                            "reason": "auto_kb_tree",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit(
                        events,
                        "tool.call_started",
                        {
                            "tool": inv_tree.tool_name,
                            "call_id": inv_tree.call_id,
                            "arguments_json": self._safe_arguments_json(
                                tool_name=inv_tree.tool_name,
                                arguments_json=inv_tree.arguments_json,
                            ),
                            "reason": "auto_kb_tree",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit_memory_access(
                        tool_name=inv_tree.tool_name,
                        call_id=inv_tree.call_id,
                        arguments_json=inv_tree.arguments_json,
                        events=events,
                        diag_sink=diag_sink,
                        event_sink=event_sink,
                    )
                    try:
                        res_tree = executor.execute_one(
                            inv_tree,
                            approvals,
                            cancel=cancel,
                        )
                    except ApprovalPending:
                        self._emit(
                            events,
                            "memory.auto_write.skipped",
                            {
                                "tool": "kb_write_fact",
                                "reason": "approval_pending",
                                "kind": "repo_tree_root",
                            },
                            diag_sink,
                            event_sink,
                        )
                    else:
                        auto_kb_write_n += 1
                        self._emit(
                            events,
                            "tool.call_finished",
                            _tool_call_finished_payload(inv_tree, res_tree),
                            diag_sink,
                            event_sink,
                        )
                        self._emit(
                            events,
                            "memory.auto_write.done",
                            {
                                "tool": "kb_write_fact",
                                "kind": "repo_tree_root",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_tree_fact = True

            if (
                not wrote_repo_signals_fact
                and "glob_file" in active_reg.specs
                and "kb_write_fact" in active_reg.specs
            ):
                try:
                    rc5 = detect_repo_context(Path(work_root()))
                except Exception:  # noqa: BLE001
                    rc5 = None
                if rc5 is not None:
                    if auto_kb_write_n >= cap_write:
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_write_fact",
                                "cap": cap_write,
                                "count": auto_kb_write_n,
                                "reason": "auto_write_repo_signals",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_signals_fact = True
                        continue
                    ns_sig = namespace_for_repo(
                        repo_uri=rc5.repo_uri,
                        repo_path=rc5.repo_path,
                        branch=rc5.branch,
                    )
                    patterns = (
                        "pyproject.toml",
                        "package.json",
                        "Cargo.toml",
                        "go.mod",
                        "requirements.txt",
                        "setup.py",
                        "**/package.xml",
                        "**/CMakeLists.txt",
                    )
                    hits: dict[str, list[str]] = {}
                    for i, pat in enumerate(patterns):
                        inv_g = ToolInvocation(
                            call_id=f"auto_glob_sig_{turn}_{i}",
                            tool_name="glob_file",
                            arguments_json=json.dumps(
                                {
                                    "pattern": pat,
                                    "path": ".",
                                    "max_files": 10,
                                },
                                ensure_ascii=False,
                            ),
                        )
                        try:
                            res_g = executor.execute_one(
                                inv_g,
                                approvals,
                                cancel=cancel,
                            )
                        except ApprovalPending:
                            continue
                        if res_g.error is not None:
                            continue
                        try:
                            payload = json.loads(res_g.content or "{}")
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(payload, dict):
                            continue
                        files = payload.get("filenames")
                        if isinstance(files, list) and files:
                            hits[str(pat)] = [str(x) for x in files[:10]]
                    inv_sig = ToolInvocation(
                        call_id=f"auto_kb_write_signals_{turn}",
                        tool_name="kb_write_fact",
                        arguments_json=json.dumps(
                            {
                                "id": f"repo_signals:{ns_sig}",
                                "scope": "project",
                                "namespace": ns_sig,
                                "title": "Repo signals (detected files)",
                                "summary": (
                                    f"Detected {len(hits)} signature patterns."
                                ),
                                "body": json.dumps(
                                    hits,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                )[:8000],
                                "author": "auto_memory",
                                "provenance": rc5.to_event_payload(),
                            },
                            ensure_ascii=False,
                        ),
                    )
                    self._emit(
                        events,
                        "tool.batch",
                        {
                            "count": 1,
                            "tool_names": ["kb_write_fact"],
                            "reason": "auto_kb_signals",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit(
                        events,
                        "tool.call_started",
                        {
                            "tool": inv_sig.tool_name,
                            "call_id": inv_sig.call_id,
                            "arguments_json": self._safe_arguments_json(
                                tool_name=inv_sig.tool_name,
                                arguments_json=inv_sig.arguments_json,
                            ),
                            "reason": "auto_kb_signals",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit_memory_access(
                        tool_name=inv_sig.tool_name,
                        call_id=inv_sig.call_id,
                        arguments_json=inv_sig.arguments_json,
                        events=events,
                        diag_sink=diag_sink,
                        event_sink=event_sink,
                    )
                    try:
                        res_sig = executor.execute_one(
                            inv_sig,
                            approvals,
                            cancel=cancel,
                        )
                    except ApprovalPending:
                        self._emit(
                            events,
                            "memory.auto_write.skipped",
                            {
                                "tool": "kb_write_fact",
                                "reason": "approval_pending",
                                "kind": "repo_signals",
                            },
                            diag_sink,
                            event_sink,
                        )
                    else:
                        auto_kb_write_n += 1
                        self._emit(
                            events,
                            "tool.call_finished",
                            _tool_call_finished_payload(inv_sig, res_sig),
                            diag_sink,
                            event_sink,
                        )
                        self._emit(
                            events,
                            "memory.auto_write.done",
                            {
                                "tool": "kb_write_fact",
                                "kind": "repo_signals",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_signals_fact = True

            if (
                not wrote_repo_entrypoints_fact
                and "glob_file" in active_reg.specs
                and "kb_write_fact" in active_reg.specs
            ):
                try:
                    rc_ep = detect_repo_context(Path(work_root()))
                except Exception:  # noqa: BLE001
                    rc_ep = None
                if rc_ep is not None:
                    if auto_kb_write_n >= cap_write:
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_write_fact",
                                "cap": cap_write,
                                "count": auto_kb_write_n,
                                "reason": "auto_write_repo_entrypoints",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_entrypoints_fact = True
                    else:
                        ns_ep = namespace_for_repo(
                            repo_uri=rc_ep.repo_uri,
                            repo_path=rc_ep.repo_path,
                            branch=rc_ep.branch,
                        )
                        pats = (
                            "README*",
                            "pyproject.toml",
                            "requirements.txt",
                            "setup.py",
                            "package.json",
                            "Cargo.toml",
                            "go.mod",
                            "Makefile",
                            "docker-compose*.yml",
                            "docker-compose*.yaml",
                            "**/package.xml",
                        )
                        hits: dict[str, list[str]] = {}
                        for i, pat in enumerate(pats):
                            inv_g = ToolInvocation(
                                call_id=f"auto_glob_entry_{turn}_{i}",
                                tool_name="glob_file",
                                arguments_json=json.dumps(
                                    {
                                        "pattern": pat,
                                        "path": ".",
                                        "max_files": 20,
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            try:
                                res_g = executor.execute_one(
                                    inv_g,
                                    approvals,
                                    cancel=cancel,
                                )
                            except ApprovalPending:
                                continue
                            if res_g.error is not None:
                                continue
                            try:
                                payload = json.loads(res_g.content or "{}")
                            except json.JSONDecodeError:
                                continue
                            if not isinstance(payload, dict):
                                continue
                            files = payload.get("filenames")
                            if isinstance(files, list) and files:
                                hits[str(pat)] = [str(x) for x in files[:20]]
                        inv_ep = ToolInvocation(
                            call_id=f"auto_kb_write_entrypoints_{turn}",
                            tool_name="kb_write_fact",
                            arguments_json=json.dumps(
                                {
                                    "id": f"repo_entrypoints:{ns_ep}",
                                    "scope": "project",
                                    "namespace": ns_ep,
                                    "title": "Repo entrypoints",
                                    "summary": (
                                        f"Detected {len(hits)} entrypoint "
                                        "patterns."
                                    ),
                                    "body": json.dumps(
                                        hits,
                                        ensure_ascii=False,
                                        sort_keys=True,
                                    )[:8000],
                                    "author": "auto_memory",
                                    "provenance": rc_ep.to_event_payload(),
                                    "source": "auto_repo_entrypoints",
                                },
                                ensure_ascii=False,
                            ),
                        )
                        try:
                            _ = executor.execute_one(
                                inv_ep,
                                approvals,
                                cancel=cancel,
                            )
                        except ApprovalPending:
                            self._emit(
                                events,
                                "memory.auto_write.skipped",
                                {
                                    "tool": "kb_write_fact",
                                    "reason": "approval_pending",
                                    "kind": "repo_entrypoints",
                                },
                                diag_sink,
                                event_sink,
                            )
                        else:
                            auto_kb_write_n += 1
                            self._emit(
                                events,
                                "memory.auto_write.done",
                                {
                                    "tool": "kb_write_fact",
                                    "kind": "repo_entrypoints",
                                },
                                diag_sink,
                                event_sink,
                            )
                        wrote_repo_entrypoints_fact = True

            if (
                not wrote_repo_safe_commands_fact
                and "kb_write_fact" in active_reg.specs
            ):
                try:
                    rc_cmd = detect_repo_context(Path(work_root()))
                except Exception:  # noqa: BLE001
                    rc_cmd = None
                if rc_cmd is not None:
                    if auto_kb_write_n >= cap_write:
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_write_fact",
                                "cap": cap_write,
                                "count": auto_kb_write_n,
                                "reason": "auto_write_repo_safe_commands",
                            },
                            diag_sink,
                            event_sink,
                        )
                        wrote_repo_safe_commands_fact = True
                    else:
                        ns_cmd = namespace_for_repo(
                            repo_uri=rc_cmd.repo_uri,
                            repo_path=rc_cmd.repo_path,
                            branch=rc_cmd.branch,
                        )
                        cmds: list[str] = []
                        cmds.extend(
                            [
                                "python3 -m pytest -q",
                                "python3 -m flake8 .",
                            ],
                        )
                        inv_cmd = ToolInvocation(
                            call_id=f"auto_kb_write_safe_cmds_{turn}",
                            tool_name="kb_write_fact",
                            arguments_json=json.dumps(
                                {
                                    "id": f"repo_safe_commands:{ns_cmd}",
                                    "scope": "project",
                                    "namespace": ns_cmd,
                                    "title": "Repo safe commands (hints)",
                                    "summary": (
                                        "Suggested non-destructive commands "
                                        "(do not auto-run)."
                                    ),
                                    "body": json.dumps(
                                        {"commands": cmds},
                                        ensure_ascii=False,
                                        sort_keys=True,
                                    ),
                                    "author": "auto_memory",
                                    "provenance": rc_cmd.to_event_payload(),
                                    "source": "auto_repo_safe_commands",
                                },
                                ensure_ascii=False,
                            ),
                        )
                        try:
                            _ = executor.execute_one(
                                inv_cmd,
                                approvals,
                                cancel=cancel,
                            )
                        except ApprovalPending:
                            self._emit(
                                events,
                                "memory.auto_write.skipped",
                                {
                                    "tool": "kb_write_fact",
                                    "reason": "approval_pending",
                                    "kind": "repo_safe_commands",
                                },
                                diag_sink,
                                event_sink,
                            )
                        else:
                            auto_kb_write_n += 1
                            self._emit(
                                events,
                                "memory.auto_write.done",
                                {
                                    "tool": "kb_write_fact",
                                    "kind": "repo_safe_commands",
                                },
                                diag_sink,
                                event_sink,
                            )
                        wrote_repo_safe_commands_fact = True

            if "kb_search" in active_reg.specs:
                last_user = next(
                    (
                        m
                        for m in reversed(messages)
                        if (
                            m.role is MessageRole.USER
                            and (m.content or "").strip()
                        )
                    ),
                    None,
                )
                q = (last_user.content or "").strip() if last_user else ""
                q = q[:200]
                if q and q != last_auto_kb_query:
                    last_auto_kb_query = q
                    if auto_kb_search_n >= cap_search:
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_search",
                                "cap": cap_search,
                                "count": auto_kb_search_n,
                                "reason": "auto_kb_search_branch",
                            },
                            diag_sink,
                            event_sink,
                        )
                        continue
                    try:
                        rc3 = detect_repo_context(Path(work_root()))
                    except Exception:  # noqa: BLE001
                        rc3 = None
                    ns_branch: str | None = None
                    ns_def: str | None = None
                    if rc3 is not None:
                        ns_branch = namespace_for_repo(
                            repo_uri=rc3.repo_uri,
                            repo_path=rc3.repo_path,
                            branch=rc3.branch,
                        )
                        if (
                            rc3.default_branch
                            and rc3.default_branch != rc3.branch
                        ):
                            ns_def = namespace_for_repo(
                                repo_uri=rc3.repo_uri,
                                repo_path=rc3.repo_path,
                                branch=rc3.default_branch,
                            )
                    inv = ToolInvocation(
                        call_id=f"auto_kb_search_{turn}",
                        tool_name="kb_search",
                        arguments_json=json.dumps(
                            _prune_none_keys(
                                {
                                    "query": q,
                                    "scope": "project",
                                    "namespace": ns_branch,
                                    "top_k": 5,
                                },
                            ),
                            ensure_ascii=False,
                        ),
                    )
                    self._emit(
                        events,
                        "tool.batch",
                        {
                            "count": 1,
                            "tool_names": ["kb_search"],
                            "reason": "auto_kb",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit(
                        events,
                        "tool.call_started",
                        {
                            "tool": inv.tool_name,
                            "call_id": inv.call_id,
                            "arguments_json": self._safe_arguments_json(
                                tool_name=inv.tool_name,
                                arguments_json=inv.arguments_json,
                            ),
                            "reason": "auto_kb",
                        },
                        diag_sink,
                        event_sink,
                    )
                    self._emit_memory_access(
                        tool_name=inv.tool_name,
                        call_id=inv.call_id,
                        arguments_json=inv.arguments_json,
                        events=events,
                        diag_sink=diag_sink,
                        event_sink=event_sink,
                    )
                    res = executor.execute_one(inv, approvals, cancel=cancel)
                    auto_kb_search_n += 1
                    self._emit(
                        events,
                        "tool.call_finished",
                        _tool_call_finished_payload(inv, res),
                        diag_sink,
                        event_sink,
                    )
                    _append_kb_search_as_system(
                        messages,
                        query=q,
                        namespace=ns_branch,
                        tool_output_json=res.content or "[]",
                    )
                    if (
                        "kb_fetch" in active_reg.specs
                        and rc3 is not None
                        and auto_kb_fetch_n < cap_fetch
                    ):
                        try:
                            payload = json.loads(res.content or "[]")
                        except json.JSONDecodeError:
                            payload = []
                        if isinstance(payload, list) and payload:
                            top = payload[0]
                            rid = (
                                str(top.get("id") or "")
                                if isinstance(top, dict)
                                else ""
                            )
                            if rid:
                                invf = ToolInvocation(
                                    call_id=f"auto_kb_fetch_{turn}",
                                    tool_name="kb_fetch",
                                    arguments_json=json.dumps(
                                        {"id": rid, "max_chars": 0},
                                        ensure_ascii=False,
                                    ),
                                )
                                resf = executor.execute_one(
                                    invf,
                                    approvals,
                                    cancel=cancel,
                                )
                                if resf.error is None:
                                    auto_kb_fetch_n += 1
                                    try:
                                        fr = json.loads(resf.content or "{}")
                                    except json.JSONDecodeError:
                                        fr = {}
                                    prov = (
                                        fr.get("provenance")
                                        if isinstance(fr, dict)
                                        else None
                                    )
                                    fcommit = (
                                        str(prov.get("commit") or "")
                                        if isinstance(prov, dict)
                                        else ""
                                    )
                                    level = (
                                        "commit_exact"
                                        if rc3.commit and fcommit == rc3.commit
                                        else "branch_namespace"
                                    )
                                    self._emit(
                                        events,
                                        "memory.retrieval.match",
                                        {
                                            "level": level,
                                            "id": rid,
                                            "namespace": ns_branch,
                                            "fact_commit": fcommit or None,
                                            "repo_commit": rc3.commit or None,
                                        },
                                        diag_sink,
                                        event_sink,
                                    )
                                    if isinstance(fr, dict) and fr:
                                        _append_kb_retrieval_digest_as_system(
                                            messages,
                                            fr=fr,
                                            level=level,
                                        )
                    elif (
                        "kb_fetch" in active_reg.specs
                        and rc3 is not None
                        and auto_kb_fetch_n >= cap_fetch
                    ):
                        self._emit(
                            events,
                            "memory.auto_kb.rate_limited",
                            {
                                "tool": "kb_fetch",
                                "cap": cap_fetch,
                                "count": auto_kb_fetch_n,
                                "reason": "auto_kb_fetch_match",
                            },
                            diag_sink,
                            event_sink,
                        )
                    if ns_def:
                        try:
                            payload = json.loads(res.content or "[]")
                        except json.JSONDecodeError:
                            payload = []
                        no_hits = (
                            not isinstance(payload, list)
                            or len(payload) == 0
                        )
                        if no_hits:
                            if auto_kb_search_n >= cap_search:
                                self._emit(
                                    events,
                                    "memory.auto_kb.rate_limited",
                                    {
                                        "tool": "kb_search",
                                        "cap": cap_search,
                                        "count": auto_kb_search_n,
                                        "reason": (
                                            "auto_kb_search_default_fallback"
                                        ),
                                    },
                                    diag_sink,
                                    event_sink,
                                )
                                continue
                            self._emit(
                                events,
                                "memory.retrieval.fallback",
                                {
                                    "policy": "branch_first_default_fallback",
                                    "from_namespace": ns_branch,
                                    "to_namespace": ns_def,
                                },
                                diag_sink,
                                event_sink,
                            )
                            inv2 = ToolInvocation(
                                call_id=f"auto_kb_search_def_{turn}",
                                tool_name="kb_search",
                                arguments_json=json.dumps(
                                    {
                                        "query": q,
                                        "scope": "project",
                                        "namespace": ns_def,
                                        "top_k": 5,
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            self._emit(
                                events,
                                "tool.batch",
                                {
                                    "count": 1,
                                    "tool_names": ["kb_search"],
                                    "reason": "auto_kb_fallback",
                                },
                                diag_sink,
                                event_sink,
                            )
                            self._emit(
                                events,
                                "tool.call_started",
                                {
                                    "tool": inv2.tool_name,
                                    "call_id": inv2.call_id,
                                    "arguments_json": (
                                        self._safe_arguments_json(
                                            tool_name=inv2.tool_name,
                                            arguments_json=inv2.arguments_json,
                                        )
                                    ),
                                    "reason": "auto_kb_fallback",
                                },
                                diag_sink,
                                event_sink,
                            )
                            self._emit_memory_access(
                                tool_name=inv2.tool_name,
                                call_id=inv2.call_id,
                                arguments_json=inv2.arguments_json,
                                events=events,
                                diag_sink=diag_sink,
                                event_sink=event_sink,
                            )
                            res2 = executor.execute_one(
                                inv2,
                                approvals,
                                cancel=cancel,
                            )
                            auto_kb_search_n += 1
                            self._emit(
                                events,
                                "tool.call_finished",
                                _tool_call_finished_payload(inv2, res2),
                                diag_sink,
                                event_sink,
                            )
                            _append_kb_search_as_system(
                                messages,
                                query=q,
                                namespace=ns_def,
                                tool_output_json=res2.content or "[]",
                            )
                            if (
                                "kb_fetch" in active_reg.specs
                                and rc3 is not None
                                and auto_kb_fetch_n < cap_fetch
                            ):
                                try:
                                    payload2 = json.loads(res2.content or "[]")
                                except json.JSONDecodeError:
                                    payload2 = []
                                if isinstance(payload2, list) and payload2:
                                    top2 = payload2[0]
                                    rid2 = (
                                        str(top2.get("id") or "")
                                        if isinstance(top2, dict)
                                        else ""
                                    )
                                    if rid2:
                                        invf2 = ToolInvocation(
                                            call_id=(
                                                f"auto_kb_fetch_def_{turn}"
                                            ),
                                            tool_name="kb_fetch",
                                            arguments_json=json.dumps(
                                                {"id": rid2, "max_chars": 0},
                                                ensure_ascii=False,
                                            ),
                                        )
                                        resf2 = executor.execute_one(
                                            invf2,
                                            approvals,
                                            cancel=cancel,
                                        )
                                        if resf2.error is None:
                                            auto_kb_fetch_n += 1
                                            try:
                                                fr2 = json.loads(
                                                    resf2.content or "{}",
                                                )
                                            except json.JSONDecodeError:
                                                fr2 = {}
                                            prov2 = (
                                                fr2.get("provenance")
                                                if isinstance(fr2, dict)
                                                else None
                                            )
                                            fcommit2 = (
                                                str(prov2.get("commit") or "")
                                                if isinstance(prov2, dict)
                                                else ""
                                            )
                                            level2 = (
                                                "commit_exact"
                                                if (
                                                    rc3.commit
                                                    and fcommit2 == rc3.commit
                                                )
                                                else "default_fallback"
                                            )
                                            self._emit(
                                                events,
                                                "memory.retrieval.match",
                                                {
                                                    "level": level2,
                                                    "id": rid2,
                                                    "namespace": ns_def,
                                                    "fact_commit": (
                                                        fcommit2 or None
                                                    ),
                                                    "repo_commit": (
                                                        rc3.commit or None
                                                    ),
                                                },
                                                diag_sink,
                                                event_sink,
                                            )
                                            if isinstance(fr2, dict) and fr2:
                                                _append_kb_retrieval_digest_as_system(  # noqa: E501
                                                    messages,
                                                    fr=fr2,
                                                    level=level2,
                                                )
                            elif (
                                "kb_fetch" in active_reg.specs
                                and rc3 is not None
                                and auto_kb_fetch_n >= cap_fetch
                            ):
                                self._emit(
                                    events,
                                    "memory.auto_kb.rate_limited",
                                    {
                                        "tool": "kb_fetch",
                                        "cap": cap_fetch,
                                        "count": auto_kb_fetch_n,
                                        "reason": (
                                            "auto_kb_fetch_match_fallback"
                                        ),
                                    },
                                    diag_sink,
                                    event_sink,
                                )

            # G7.4: PAG-first context slice before the model request.
            # Desktop Workflow 10 uses AgentMemory as the mandatory actor and
            # disables this in-process fallback through SessionSettings.
            if (
                settings.pag_runtime_enabled
                and messages
                and messages[-1].role in (
                    MessageRole.USER,
                    MessageRole.SYSTEM,
                )
            ):
                pag_namespace, _, _ = self._maybe_inject_pag_slice(
                    messages=messages,
                    events=events,
                    diag_sink=diag_sink,
                    event_sink=event_sink,
                )

            ctx = self._prepare_context(
                messages,
                settings,
                events,
                diag_sink,
                event_sink,
            )
            if settings.perm_mode_enabled:
                tools_defs, pmeta = tool_definitions_for_perm_mode(
                    active_reg,
                    settings.perm_tool_mode,
                )
                self._emit(
                    events,
                    "tool.perm_mode.applied",
                    {
                        "perm_mode": pmeta.perm_mode,
                        "tools_total": pmeta.tools_total,
                        "tools_exposed": pmeta.tools_exposed,
                        "schema_chars": pmeta.schema_chars,
                        "schema_chars_full": pmeta.schema_chars_full,
                        "schema_savings": pmeta.schema_savings,
                    },
                    diag_sink,
                    event_sink,
                )
            else:
                tools_defs, tex = tool_definitions_for_settings(
                    active_reg,
                    settings.tool_exposure,
                )
                self._emit(
                    events,
                    "tool.exposure.applied",
                    {
                        "mode": tex.mode,
                        "tools_total": tex.tools_total,
                        "tools_exposed": tex.tools_exposed,
                        "schema_chars": tex.schema_chars,
                        "schema_chars_full": tex.schema_chars_full,
                        "schema_savings": tex.schema_savings,
                    },
                    diag_sink,
                    event_sink,
                )
            st_sup = settings.suppress_tools_after_write_file
            should_use_suppress = suppress_next[0] and st_sup
            if suppress_next[0]:
                suppress_next[0] = False
            decision = default_tool_choice_policy.choose(
                tools_available=bool(tools_defs),
                suppress_next_request=should_use_suppress,
                policy_enabled=settings.suppress_tools_after_write_file,
            )
            try:
                meta = {
                    "turn_id": f"turn-{turn}",
                    "tool_choice_mode": decision.tool_choice_mode_effective,
                    "policy_reason": decision.policy_reason,
                }
                resp = self._invoke_model_request(
                    context=ctx,
                    settings=settings,
                    tool_choice=decision.tool_choice,
                    tools_defs=tools_defs,
                    events=events,
                    diag_sink=diag_sink,
                    event_sink=event_sink,
                    request_meta=meta,
                    cancel=cancel,
                )
            except Exception as exc:  # noqa: BLE001
                err_reason = f"{type(exc).__name__}:{exc}"
                extra: dict[str, object] = {}
                if _is_read_timeout(exc):
                    extra["error_class"] = "timeout"
                if isinstance(exc, TransportHttpError):
                    if exc.status_code is not None:
                        extra["status_code"] = exc.status_code
                    if exc.body_snippet:
                        extra["body_snippet"] = exc.body_snippet
                self._emit(
                    events,
                    "model.error",
                    {"reason": err_reason, **extra},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.ERROR,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason=err_reason,
                )

            bud.record_usage(resp.usage)
            self._emit(
                events,
                "context.provider_usage_confirmed",
                provider_usage_confirmed_payload(
                    usage=resp.usage,
                    turn_id=f"turn-{turn}",
                ),
                diag_sink,
                event_sink,
            )
            resp_tool_names = [tc.tool_name for tc in resp.tool_calls]
            fin = resp.finish_reason.value
            self._emit(
                events,
                "model.response",
                {
                    "finish": fin,
                    "tool_calls_count": len(resp.tool_calls),
                    "tool_names": resp_tool_names,
                    "usage": usage_to_diag_dict(resp.usage),
                    "usage_session_totals": bud.diag_totals_dict(),
                },
                diag_sink,
                event_sink,
            )
            over = bud.check_exceeded(messages)
            if over is not None:
                self._emit(
                    events,
                    "session.budget",
                    {"reason": over},
                    diag_sink,
                    event_sink,
                )
                return SessionOutcome(
                    state=SessionState.BUDGET_EXCEEDED,
                    messages=tuple(messages),
                    events=tuple(events),
                    reason=over,
                )

            text = "".join(resp.text_parts)
            if resp.tool_calls:
                agent_steps += 1
                messages.append(
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=text,
                        tool_calls=tuple(resp.tool_calls),
                    )
                )
                sig = "|".join(
                    f"{tc.tool_name}:{tc.arguments_json}"
                    for tc in resp.tool_calls
                )
                if sig and sig == last_model_tool_sig:
                    same_tool_sig_n += 1
                else:
                    last_model_tool_sig = sig
                    same_tool_sig_n = 0
                if same_tool_sig_n >= 2:
                    self._emit(
                        events,
                        "session.doom_loop",
                        {
                            "policy": "finalize_text_only",
                            "same_signature_n": same_tool_sig_n,
                        },
                        diag_sink,
                        event_sink,
                    )
                    return self._finalize_after_turn_cap(
                        messages,
                        settings,
                        events,
                        diag_sink,
                        event_sink,
                        bud,
                    )
                invs = [
                    ToolInvocation(tc.call_id, tc.tool_name, tc.arguments_json)
                    for tc in resp.tool_calls
                ]
                guarded2: list[ToolInvocation] = []
                for inv in invs:
                    ginv, meta = _maybe_guard_run_shell_invocation(
                        inv,
                        default_timeout_ms=30_000,
                    )
                    if meta is not None:
                        self._emit(
                            events,
                            "run_shell.guardrail",
                            meta,
                            diag_sink,
                            event_sink,
                        )
                    guarded2.append(ginv)
                invs = guarded2
                tool_names = [inv.tool_name for inv in invs]
                self._emit(
                    events,
                    "tool.batch",
                    {"count": len(invs), "tool_names": tool_names},
                    diag_sink,
                    event_sink,
                )
                try:
                    for inv in invs:
                        self._emit(
                            events,
                            "tool.call_started",
                            {
                                "tool": inv.tool_name,
                                "call_id": inv.call_id,
                                "arguments_json": self._safe_arguments_json(
                                    tool_name=inv.tool_name,
                                    arguments_json=inv.arguments_json,
                                ),
                            },
                            diag_sink,
                            event_sink,
                        )
                        self._emit_memory_access(
                            tool_name=inv.tool_name,
                            call_id=inv.call_id,
                            arguments_json=inv.arguments_json,
                            events=events,
                            diag_sink=diag_sink,
                            event_sink=event_sink,
                        )
                    results = executor.execute_serial(
                        invs,
                        approvals,
                        cancel=cancel,
                    )
                except ApprovalPending as exc:
                    self._emit(
                        events,
                        "session.waiting_approval",
                        {"call_id": exc.call_id, "tool": exc.tool_name},
                        diag_sink,
                        event_sink,
                    )
                    return SessionOutcome(
                        state=SessionState.WAITING_APPROVAL,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason="approval_pending",
                    )
                except ToolRejected as exc:
                    return SessionOutcome(
                        state=SessionState.ERROR,
                        messages=tuple(messages),
                        events=tuple(events),
                        reason=f"rejected:{exc.tool_name}",
                    )
                for inv, res in zip(invs, results, strict=True):

                    def _emit_bash_et2(et: str, pl: dict[str, Any]) -> None:
                        self._emit(events, et, pl, diag_sink, event_sink)

                    emit_bash_shell_telemetry(_emit_bash_et2, inv, res)
                    self._emit(
                        events,
                        "tool.call_finished",
                        _tool_call_finished_payload(inv, res),
                        diag_sink,
                        event_sink,
                    )
                    self._emit_memory_promotion(
                        inv=inv,
                        res=res,
                        events=events,
                        diag_sink=diag_sink,
                        event_sink=event_sink,
                    )
                    self._emit_context_pager_page_used(
                        inv, res, events, diag_sink, event_sink
                    )
                self._maybe_set_suppress_after_write_file(
                    invs,
                    results,
                    settings,
                    suppress_next,
                )
                self._append_tool_results(
                    messages,
                    invs,
                    results,
                    settings,
                    events,
                    diag_sink,
                    event_sink,
                )
                if resp.finish_reason is not FinishReason.TOOL_CALLS:
                    pass
                continue
            agent_steps = 0
            last_model_tool_sig = None
            same_tool_sig_n = 0

            messages.append(
                ChatMessage(role=MessageRole.ASSISTANT, content=text),
            )
            if (
                "kb_write_fact" in active_reg.specs
                and auto_kb_write_n < cap_write
            ):
                try:
                    rc_out = detect_repo_context(Path(work_root()))
                except Exception:  # noqa: BLE001
                    rc_out = None
                stable = (
                    (rc_out.repo_uri or rc_out.repo_path)
                    if rc_out is not None
                    else str(work_root())
                )
                ns_out: str | None = None
                if rc_out is not None:
                    ns_out = namespace_for_repo(
                        repo_uri=rc_out.repo_uri,
                        repo_path=rc_out.repo_path,
                        branch=rc_out.branch,
                    )
                ts = datetime.now(timezone.utc).isoformat()
                rid_out = (
                    "session_outcome:"
                    + _safe_id_part(str(stable))
                    + ":"
                    + _safe_id_part(ts, max_chars=48)
                )
                if rc_out is not None and rc_out.branch:
                    rid_out = rid_out + ":" + _safe_id_part(rc_out.branch)
                tool_calls = sum(
                    1
                    for e in events
                    if e.get("event_type") == "tool.call_started"
                )
                mem_access = sum(
                    1
                    for e in events
                    if e.get("event_type") == "memory.access"
                )
                body_out = json.dumps(
                    {
                        "ts": ts,
                        "state": "finished",
                        "tool_calls": tool_calls,
                        "memory_access": mem_access,
                        "rate_limited": int(
                            sum(
                                1
                                for e in events
                                if e.get("event_type")
                                == "memory.auto_kb.rate_limited"
                            ),
                        ),
                        "repo": (
                            rc_out.to_event_payload()
                            if rc_out is not None
                            else None
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )[:3000]
                inv_out = ToolInvocation(
                    call_id=f"auto_kb_write_outcome_{turn}",
                    tool_name="kb_write_fact",
                    arguments_json=json.dumps(
                        {
                            "id": rid_out,
                            "scope": "run",
                            "namespace": ns_out,
                            "title": "Session outcome",
                            "summary": (
                                f"finished; tools={tool_calls}; "
                                f"kb_access={mem_access}"
                            ),
                            "body": body_out,
                            "author": "auto_memory",
                            "provenance": (
                                rc_out.to_event_payload()
                                if rc_out is not None
                                else {}
                            ),
                            "source": "auto_session_outcome",
                        },
                        ensure_ascii=False,
                    ),
                )
                self._emit(
                    events,
                    "tool.call_started",
                    {
                        "tool": inv_out.tool_name,
                        "call_id": inv_out.call_id,
                        "arguments_json": self._safe_arguments_json(
                            tool_name=inv_out.tool_name,
                            arguments_json=inv_out.arguments_json,
                        ),
                        "reason": "auto_kb_outcome",
                    },
                    diag_sink,
                    event_sink,
                )
                self._emit_memory_access(
                    tool_name=inv_out.tool_name,
                    call_id=inv_out.call_id,
                    arguments_json=inv_out.arguments_json,
                    events=events,
                    diag_sink=diag_sink,
                    event_sink=event_sink,
                )
                try:
                    res_out = executor.execute_one(
                        inv_out,
                        approvals,
                        cancel=cancel,
                    )
                except ApprovalPending:
                    self._emit(
                        events,
                        "memory.auto_write.skipped",
                        {
                            "tool": "kb_write_fact",
                            "reason": "approval_pending",
                            "kind": "session_outcome",
                        },
                        diag_sink,
                        event_sink,
                    )
                else:
                    auto_kb_write_n += 1
                    self._emit(
                        events,
                        "tool.call_finished",
                        _tool_call_finished_payload(inv_out, res_out),
                        diag_sink,
                        event_sink,
                    )
                    self._emit(
                        events,
                        "memory.auto_write.done",
                        {"tool": "kb_write_fact", "kind": "session_outcome"},
                        diag_sink,
                        event_sink,
                    )
            return SessionOutcome(
                state=SessionState.FINISHED,
                messages=tuple(messages),
                events=tuple(events),
                reason=None,
            )

        return self._finalize_after_turn_cap(
            messages,
            settings,
            events,
            diag_sink,
            event_sink,
            bud,
        )
