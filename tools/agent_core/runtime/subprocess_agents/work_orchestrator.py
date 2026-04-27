"""Micro-orchestration for ``AgentWork`` user tasks.

The orchestrator owns one user task and delegates model/tool execution to
``SessionRunner``.  It deliberately stays above the session loop so the same
executor can serve default AgentWork and future profile-based agents.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from agent_core.bash_runner import BashRunOutcome, run_bash_command
from agent_core.models import ChatMessage, MessageRole
from agent_core.session.event_contract import SessionEventSink
from agent_core.session.loop import (
    SessionOutcome,
    SessionRunner,
    SessionSettings,
)
from agent_core.session.state import SessionState
from agent_core.tool_runtime.approval import ApprovalSession

_ORCHESTRATOR_MARKER = "[ailit-work-orchestrator]"
_PLAN_EVENT = "work.micro_plan.compact"
_VERIFY_EVENT = "work.verify.finished"
_VERIFY_TIMEOUT_MS = 120_000
_VERIFY_MAX_CAPTURE_BYTES = 80_000
_SUMMARY_LIMIT = 4000


class WorkTaskKind(str, Enum):
    """High-level kind of one user task."""

    CHAT_ONLY = "chat_only"
    READ_ONLY = "read_only"
    SMALL_CODE_CHANGE = "small_code_change"
    LARGE_CODE_CHANGE = "large_code_change"


class WorkPhase(str, Enum):
    """Phases emitted by the AgentWork micro-orchestrator."""

    CLASSIFY = "classify"
    MICRO_PLAN = "micro_plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPAIR = "repair"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class AgentWorkProfile:
    """Runtime profile for AgentWork orchestration."""

    profile_id: str = "default"
    title: str = "AgentWork"
    micro_plan: str = "always_compact"
    verify_policy: str = "python_default"
    max_repair_attempts: int = 1
    large_task_policy: str = "decompose_only"
    enabled: bool = True

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> AgentWorkProfile:
        """Build the active profile from merged ailit config."""
        raw = cfg.get("agent_work")
        if not isinstance(raw, Mapping):
            return cls()
        active = (
            str(raw.get("active_profile") or "default").strip()
            or "default"
        )
        profiles = raw.get("profiles")
        body: Mapping[str, Any] = {}
        if isinstance(profiles, Mapping):
            hit = profiles.get(active)
            if isinstance(hit, Mapping):
                body = hit
        return cls(
            profile_id=active,
            title=str(body.get("title") or "AgentWork"),
            micro_plan=str(body.get("micro_plan") or "always_compact"),
            verify_policy=str(body.get("verify_policy") or "python_default"),
            max_repair_attempts=_positive_int(
                body.get("max_repair_attempts"),
                default=1,
            ),
            large_task_policy=str(
                body.get("large_task_policy") or "decompose_only",
            ),
            enabled=_truthy(raw.get("enabled"), default=True),
        )


@dataclass(frozen=True, slots=True)
class WorkTaskRequest:
    """Input for one AgentWork user task."""

    user_text: str
    workspace: Path
    chat_id: str
    assistant_message_id: str
    profile: AgentWorkProfile


@dataclass(frozen=True, slots=True)
class WorkStep:
    """One compact task step suitable for desktop trace/UI."""

    title: str
    expected_files: tuple[str, ...] = ()
    done_when: str = ""

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "title": self.title,
            "expected_files": list(self.expected_files),
            "done_when": self.done_when,
        }


@dataclass(frozen=True, slots=True)
class VerificationCommand:
    """A runtime verification command."""

    command: str
    cwd: Path
    reason: str

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "command": self.command,
            "cwd": str(self.cwd),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class WorkTaskPlan:
    """Compact plan for one user task."""

    kind: WorkTaskKind
    summary: str
    steps: tuple[WorkStep, ...]
    verification: tuple[VerificationCommand, ...] = ()
    expected_files: tuple[str, ...] = ()
    max_repair_attempts: int = 1
    large_task_policy: str = "decompose_only"

    def to_payload(self, profile: AgentWorkProfile) -> dict[str, Any]:
        """Return a JSON-friendly compact-plan payload."""
        return {
            "profile_id": profile.profile_id,
            "profile_title": profile.title,
            "task_kind": self.kind.value,
            "summary": self.summary,
            "steps": [s.to_payload() for s in self.steps],
            "expected_files": list(self.expected_files),
            "verification": [v.to_payload() for v in self.verification],
            "max_repair_attempts": self.max_repair_attempts,
            "large_task_policy": self.large_task_policy,
        }


@dataclass(frozen=True, slots=True)
class VerificationCommandResult:
    """Outcome of a single verification command."""

    command: str
    cwd: str
    reason: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    skipped: bool = False
    skip_reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "command": self.command,
            "cwd": self.cwd,
            "reason": self.reason,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Aggregate verification result."""

    ok: bool
    skipped: bool
    commands: tuple[VerificationCommandResult, ...] = ()
    reason: str = ""
    changed_files: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "ok": self.ok,
            "skipped": self.skipped,
            "reason": self.reason,
            "changed_files": list(self.changed_files),
            "commands": [c.to_payload() for c in self.commands],
        }


@dataclass(frozen=True, slots=True)
class WorkTaskResult:
    """Final result returned to AgentWork."""

    ok: bool
    messages: tuple[ChatMessage, ...]
    final_text: str
    assistant_message_id: str
    error: str = ""
    plan: WorkTaskPlan | None = None
    verification: VerificationResult | None = None


@dataclass(frozen=True, slots=True)
class _ExecutionResult:
    outcome: SessionOutcome
    changed_files: tuple[str, ...]


class RuntimePublisher(Protocol):
    """Subset of ``_RuntimeEventEmitter`` used by the orchestrator."""

    def publish(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        """Publish an event to the runtime trace."""


def _truthy(value: Any, *, default: bool) -> bool:
    """Parse a bool-like config value."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _positive_int(value: Any, *, default: int) -> int:
    """Parse a positive integer with fallback."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _clip(text: str, limit: int = _SUMMARY_LIMIT) -> str:
    """Clip long stdout/stderr snippets for trace and repair prompts."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _waiting_approval_call_id(
    events: tuple[dict[str, Any], ...],
) -> str | None:
    """Return call id from the last waiting-approval event."""
    for ev in reversed(events):
        if ev.get("event_type") == "session.waiting_approval":
            cid = ev.get("call_id")
            if isinstance(cid, str) and cid:
                return cid
    return None


def _collect_changed_files(
    events: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    """Collect unique changed paths from successful write events."""
    seen: set[str] = set()
    out: list[str] = []
    for ev in events:
        if ev.get("event_type") != "tool.call_finished":
            continue
        if ev.get("ok") is False:
            continue
        rp = ev.get("relative_path")
        if not isinstance(rp, str):
            continue
        rel = rp.strip()
        if not rel or rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return tuple(out)


def _last_assistant_text(messages: tuple[ChatMessage, ...]) -> str:
    """Find the latest assistant message text."""
    for msg in reversed(messages):
        if msg.role is MessageRole.ASSISTANT:
            return msg.content or ""
    return ""


def _strip_orchestrator_messages(
    messages: tuple[ChatMessage, ...],
) -> tuple[ChatMessage, ...]:
    """Remove hidden orchestration hints before persisting chat state."""
    return tuple(
        msg
        for msg in messages
        if not (
            msg.role is MessageRole.SYSTEM
            and msg.content.startswith(_ORCHESTRATOR_MARKER)
        )
    )


def _extract_expected_files(text: str) -> tuple[str, ...]:
    """Extract likely path mentions from user text."""
    patterns = [
        r"`([^`]+\.[A-Za-z0-9_]+)`",
        r"([\w./-]+(?:test|tests)[\w./-]*\.py)",
        r"([\w./-]+\.(?:py|ts|tsx|js|jsx|md|yaml|yml|toml|json))",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for pat in patterns:
        for match in re.findall(pat, text, flags=re.IGNORECASE):
            rel = str(match).strip().strip(".,:;()[]{}")
            if not rel or rel in seen:
                continue
            seen.add(rel)
            out.append(rel)
    return tuple(out[:8])


class TaskClassifier:
    """Small deterministic classifier for AgentWork tasks."""

    _SMALL_MARKERS = (
        "add",
        "fix",
        "change",
        "update",
        "test",
        "pytest",
        "flake8",
        "код",
        "файл",
        "добав",
        "исправ",
        "измени",
        "обнов",
        "тест",
    )
    _LARGE_MARKERS = (
        "workflow",
        "architecture",
        "roadmap",
        "реализуй этап",
        "весь этап",
        "архитектур",
        "больш",
        "много файлов",
    )
    _READ_MARKERS = (
        "explain",
        "show",
        "read",
        "расскажи",
        "объясни",
        "покажи",
        "как устро",
        "где",
    )

    def classify(self, text: str) -> WorkTaskKind:
        """Classify user text into a task kind."""
        low = text.strip().lower()
        if not low:
            return WorkTaskKind.CHAT_ONLY
        if any(m in low for m in self._LARGE_MARKERS):
            return WorkTaskKind.LARGE_CODE_CHANGE
        if any(m in low for m in self._SMALL_MARKERS):
            return WorkTaskKind.SMALL_CODE_CHANGE
        if any(m in low for m in self._READ_MARKERS):
            return WorkTaskKind.READ_ONLY
        if "?" in low or low.endswith(("ли", "как", "что")):
            return WorkTaskKind.CHAT_ONLY
        return WorkTaskKind.CHAT_ONLY


class MicroPlanner:
    """Build compact deterministic plans for AgentWork tasks."""

    def build(
        self,
        request: WorkTaskRequest,
        kind: WorkTaskKind,
    ) -> WorkTaskPlan:
        """Return a compact plan for the classified task."""
        expected = _extract_expected_files(request.user_text)
        if kind is WorkTaskKind.SMALL_CODE_CHANGE:
            steps = (
                WorkStep(
                    title="Найти минимальную точку изменения.",
                    expected_files=expected,
                    done_when="Понятен существующий паттерн и область правки.",
                ),
                WorkStep(
                    title="Внести только нужную локальную правку.",
                    expected_files=expected,
                    done_when="Scope не расширен за пределы запроса.",
                ),
                WorkStep(
                    title="Запустить точечную проверку по изменённым файлам.",
                    expected_files=expected,
                    done_when="Verify gate завершён и отражён в trace.",
                ),
            )
            summary = _compact_summary(request.user_text)
            return WorkTaskPlan(
                kind=kind,
                summary=summary,
                steps=steps,
                expected_files=expected,
                max_repair_attempts=request.profile.max_repair_attempts,
                large_task_policy=request.profile.large_task_policy,
            )
        if kind is WorkTaskKind.LARGE_CODE_CHANGE:
            steps = (
                WorkStep(
                    title="Не выполнять большую задачу как micro-task.",
                    done_when="Пользователь получает краткую декомпозицию.",
                ),
                WorkStep(
                    title="Предложить следующий маленький проверяемый шаг.",
                    done_when="Есть безопасная единица работы для AgentWork.",
                ),
            )
            return WorkTaskPlan(
                kind=kind,
                summary=(
                    "Задача выглядит крупной: нужен отдельный workflow "
                    "или декомпозиция."
                ),
                steps=steps,
                expected_files=expected,
                max_repair_attempts=0,
                large_task_policy=request.profile.large_task_policy,
            )
        if kind is WorkTaskKind.READ_ONLY:
            steps = (
                WorkStep(
                    title="Собрать релевантный контекст без правок.",
                    expected_files=expected,
                    done_when="Ответ основан на найденном контексте.",
                ),
            )
            return WorkTaskPlan(
                kind=kind,
                summary=_compact_summary(request.user_text),
                steps=steps,
                expected_files=expected,
                max_repair_attempts=0,
                large_task_policy=request.profile.large_task_policy,
            )
        return WorkTaskPlan(
            kind=WorkTaskKind.CHAT_ONLY,
            summary=_compact_summary(request.user_text),
            steps=(
                WorkStep(
                    title="Ответить в чате без изменения файлов.",
                    done_when="Пользователь получил прямой ответ.",
                ),
            ),
            max_repair_attempts=0,
            large_task_policy=request.profile.large_task_policy,
        )


def _compact_summary(text: str) -> str:
    """Create a short one-line task summary."""
    clean = " ".join(text.split())
    if len(clean) <= 160:
        return clean or "Пустой запрос."
    return clean[:157].rstrip() + "..."


class RuntimeVerifier:
    """Runtime verification gate for AgentWork code tasks."""

    def build_commands(
        self,
        *,
        workspace: Path,
        changed_files: tuple[str, ...],
        plan: WorkTaskPlan,
        profile: AgentWorkProfile,
    ) -> tuple[VerificationCommand, ...]:
        """Build verification commands from actual changed files."""
        if profile.verify_policy != "python_default":
            return ()
        if plan.kind is not WorkTaskKind.SMALL_CODE_CHANGE:
            return ()
        py_files = tuple(p for p in changed_files if p.endswith(".py"))
        test_files = tuple(
            p
            for p in py_files
            if p.startswith("tests/") or "test" in Path(p).name
        )
        commands: list[VerificationCommand] = []
        for rel in test_files[:3]:
            commands.append(
                VerificationCommand(
                    command=f"python -m pytest {shlex.quote(rel)} -q",
                    cwd=workspace,
                    reason=f"Точечный pytest для изменённого теста {rel}.",
                ),
            )
        if py_files and _flake8_available():
            quoted = " ".join(shlex.quote(p) for p in py_files[:12])
            commands.append(
                VerificationCommand(
                    command=f"python -m flake8 {quoted}",
                    cwd=workspace,
                    reason="flake8 по изменённым Python-файлам.",
                ),
            )
        return tuple(commands)

    def run(
        self,
        *,
        workspace: Path,
        changed_files: tuple[str, ...],
        plan: WorkTaskPlan,
        profile: AgentWorkProfile,
    ) -> VerificationResult:
        """Run verification commands and return an aggregate result."""
        commands = self.build_commands(
            workspace=workspace,
            changed_files=changed_files,
            plan=plan,
            profile=profile,
        )
        if not commands:
            reason = (
                "Нет изменённых Python-файлов или доступной "
                "verify-команды."
            )
            if plan.kind is not WorkTaskKind.SMALL_CODE_CHANGE:
                reason = "Для этого типа задачи runtime verify не требуется."
            return VerificationResult(
                ok=plan.kind is not WorkTaskKind.SMALL_CODE_CHANGE,
                skipped=True,
                reason=reason,
                changed_files=changed_files,
            )
        results: list[VerificationCommandResult] = []
        for cmd in commands:
            outcome = run_bash_command(
                cmd.command,
                cwd=cmd.cwd,
                timeout_ms=_VERIFY_TIMEOUT_MS,
                max_capture_bytes=_VERIFY_MAX_CAPTURE_BYTES,
            )
            results.append(_command_result(cmd, outcome))
        ok = all(r.exit_code == 0 and not r.timed_out for r in results)
        return VerificationResult(
            ok=ok,
            skipped=False,
            commands=tuple(results),
            reason="ok" if ok else "verification_failed",
            changed_files=changed_files,
        )


def _flake8_available() -> bool:
    """Return True if flake8 can be invoked in this environment."""
    if shutil.which("flake8"):
        return True
    try:
        return importlib.util.find_spec("flake8") is not None
    except (ImportError, ValueError):
        return False


def _command_result(
    cmd: VerificationCommand,
    outcome: BashRunOutcome,
) -> VerificationCommandResult:
    """Convert bash outcome into a compact trace payload result."""
    return VerificationCommandResult(
        command=cmd.command,
        cwd=str(cmd.cwd),
        reason=cmd.reason,
        exit_code=outcome.exit_code,
        stdout=_clip(outcome.stdout),
        stderr=_clip(outcome.stderr),
        timed_out=outcome.timed_out or outcome.cancelled,
    )


class WorkTaskOrchestrator:
    """Strict micro-orchestrator for a single AgentWork prompt."""

    def __init__(
        self,
        *,
        runner: SessionRunner,
        approvals: ApprovalSession,
        settings: SessionSettings,
        base_messages: tuple[ChatMessage, ...],
        event_sink: SessionEventSink | None,
        publisher: RuntimePublisher,
        wait_for_approval: Callable[[str], None],
    ) -> None:
        """Bind dependencies for one task execution."""
        self._runner = runner
        self._approvals = approvals
        self._settings = settings
        self._base_messages = base_messages
        self._event_sink = event_sink
        self._publisher = publisher
        self._wait_for_approval = wait_for_approval
        self._classifier = TaskClassifier()
        self._planner = MicroPlanner()
        self._verifier = RuntimeVerifier()

    def run(self, request: WorkTaskRequest) -> WorkTaskResult:
        """Run classify → plan → execute → verify → repair → final."""
        if not request.profile.enabled or _orchestrator_disabled():
            execution = self._execute(self._base_messages)
            messages = _strip_orchestrator_messages(execution.outcome.messages)
            return self._legacy_result(request, messages, execution.outcome)

        self._phase(WorkPhase.CLASSIFY, "started")
        kind = self._classifier.classify(request.user_text)
        self._phase(WorkPhase.CLASSIFY, "finished", {"task_kind": kind.value})
        self._phase(WorkPhase.MICRO_PLAN, "started")
        plan = self._planner.build(request, kind)
        self._publish_plan(request, plan)
        self._phase(
            WorkPhase.MICRO_PLAN,
            "finished",
            {"task_kind": kind.value},
        )

        if kind is WorkTaskKind.LARGE_CODE_CHANGE:
            final = self._large_task_text(plan)
            messages = self._base_messages + (
                ChatMessage(role=MessageRole.ASSISTANT, content=final),
            )
            return WorkTaskResult(
                ok=True,
                messages=messages,
                final_text=final,
                assistant_message_id=request.assistant_message_id,
                plan=plan,
            )

        self._phase(WorkPhase.EXECUTE, "started")
        execute_messages = self._messages_for_execute(
            self._base_messages,
            plan,
        )
        execution = self._execute(execute_messages)
        messages = _strip_orchestrator_messages(execution.outcome.messages)
        self._phase(
            WorkPhase.EXECUTE,
            "finished",
            {
                "state": execution.outcome.state.value,
                "changed_files": list(execution.changed_files),
            },
        )
        if execution.outcome.state is not SessionState.FINISHED:
            return WorkTaskResult(
                ok=False,
                messages=messages,
                final_text=_session_end_user_message(
                    state=execution.outcome.state,
                    reason=execution.outcome.reason,
                ),
                assistant_message_id=request.assistant_message_id,
                error=(
                    execution.outcome.reason
                    or execution.outcome.state.value
                ),
                plan=plan,
            )

        verification = self._verify(request, plan, execution.changed_files)
        final_messages = messages
        if self._should_repair(plan, verification):
            self._phase(WorkPhase.REPAIR, "started")
            repair_messages = self._messages_for_repair(
                messages,
                plan,
                verification,
            )
            repair = self._execute(repair_messages)
            combined_changed = _merge_unique(
                execution.changed_files,
                repair.changed_files,
            )
            final_messages = _strip_orchestrator_messages(
                repair.outcome.messages,
            )
            self._phase(
                WorkPhase.REPAIR,
                "finished",
                {
                    "state": repair.outcome.state.value,
                    "changed_files": list(repair.changed_files),
                },
            )
            if repair.outcome.state is SessionState.FINISHED:
                verification = self._verify(request, plan, combined_changed)
            else:
                verification = VerificationResult(
                    ok=False,
                    skipped=False,
                    reason=repair.outcome.reason or repair.outcome.state.value,
                    changed_files=combined_changed,
                )
                self._publish_verify(verification)

        final_text = self._final_text(final_messages, plan, verification)
        return WorkTaskResult(
            ok=verification.ok or verification.skipped,
            messages=final_messages,
            final_text=final_text,
            assistant_message_id=request.assistant_message_id,
            error=(
                ""
                if verification.ok or verification.skipped
                else verification.reason
            ),
            plan=plan,
            verification=verification,
        )

    def _execute(self, messages: tuple[ChatMessage, ...]) -> _ExecutionResult:
        """Run ``SessionRunner`` with preserved approval loop semantics."""
        cur = tuple(messages)
        out: SessionOutcome | None = None
        changed: tuple[str, ...] = ()
        while True:
            out = self._runner.run(
                list(cur),
                self._approvals,
                self._settings,
                diag_sink=None,
                event_sink=self._event_sink,
            )
            changed = _merge_unique(
                changed,
                _collect_changed_files(out.events),
            )
            cur = tuple(out.messages)
            if out.state is SessionState.WAITING_APPROVAL:
                call_id = _waiting_approval_call_id(out.events)
                if not call_id:
                    break
                self._wait_for_approval(call_id)
                continue
            break
        assert out is not None
        return _ExecutionResult(outcome=out, changed_files=changed)

    def _verify(
        self,
        request: WorkTaskRequest,
        plan: WorkTaskPlan,
        changed_files: tuple[str, ...],
    ) -> VerificationResult:
        """Run and publish verification result."""
        self._phase(WorkPhase.VERIFY, "started")
        verification = self._verifier.run(
            workspace=request.workspace,
            changed_files=changed_files,
            plan=plan,
            profile=request.profile,
        )
        self._publish_verify(verification)
        self._phase(
            WorkPhase.VERIFY,
            "finished",
            {
                "ok": verification.ok,
                "skipped": verification.skipped,
                "reason": verification.reason,
            },
        )
        return verification

    def _publish_plan(
        self,
        request: WorkTaskRequest,
        plan: WorkTaskPlan,
    ) -> None:
        """Publish compact plan for desktop UI."""
        payload = plan.to_payload(request.profile)
        payload["chat_id"] = request.chat_id
        payload["message_id"] = request.assistant_message_id
        self._publisher.publish(event_type=_PLAN_EVENT, payload=payload)

    def _publish_verify(self, result: VerificationResult) -> None:
        """Publish verification result for trace/UI."""
        self._publisher.publish(
            event_type=_VERIFY_EVENT,
            payload=result.to_payload(),
        )

    def _phase(
        self,
        phase: WorkPhase,
        state: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish a compact phase lifecycle event."""
        payload: dict[str, Any] = {"phase": phase.value, "state": state}
        if extra:
            payload.update(dict(extra))
        self._publisher.publish(
            event_type=f"work.phase.{state}",
            payload=payload,
        )

    def _messages_for_execute(
        self,
        messages: tuple[ChatMessage, ...],
        plan: WorkTaskPlan,
    ) -> tuple[ChatMessage, ...]:
        """Append execution guidance outside SessionRunner internals."""
        if plan.kind in (WorkTaskKind.CHAT_ONLY, WorkTaskKind.READ_ONLY):
            return messages
        instruction = (
            f"{_ORCHESTRATOR_MARKER}\n"
            "Выполни только compact plan текущей задачи.\n"
            "Не расширяй scope. Для code-задачи не утверждай, что всё "
            "готово окончательно: runtime отдельно выполнит verify gate.\n"
            f"План: {plan.to_payload(AgentWorkProfile())}"
        )
        return messages + (
            ChatMessage(role=MessageRole.SYSTEM, content=instruction),
        )

    def _messages_for_repair(
        self,
        messages: tuple[ChatMessage, ...],
        plan: WorkTaskPlan,
        verification: VerificationResult,
    ) -> tuple[ChatMessage, ...]:
        """Append one repair instruction with verify failure summary."""
        failure = _verification_summary(verification)
        instruction = (
            f"{_ORCHESTRATOR_MARKER}\n"
            "Repair-фаза: исправь только причины падения verify ниже. "
            "Не расширяй scope и не добавляй новую функциональность.\n"
            f"Compact plan: {plan.summary}\n"
            f"Verify failure:\n{failure}"
        )
        return messages + (
            ChatMessage(role=MessageRole.SYSTEM, content=instruction),
        )

    def _should_repair(
        self,
        plan: WorkTaskPlan,
        verification: VerificationResult,
    ) -> bool:
        """Return True when a one-shot repair is allowed."""
        return (
            plan.kind is WorkTaskKind.SMALL_CODE_CHANGE
            and not verification.ok
            and not verification.skipped
            and plan.max_repair_attempts > 0
        )

    def _final_text(
        self,
        messages: tuple[ChatMessage, ...],
        plan: WorkTaskPlan,
        verification: VerificationResult,
    ) -> str:
        """Build final user-visible text after verify gate."""
        base = _last_assistant_text(messages).strip()
        if plan.kind is not WorkTaskKind.SMALL_CODE_CHANGE:
            return base
        if verification.ok:
            verify_line = self._verification_line(
                "Проверка пройдена",
                verification,
            )
            return "\n\n".join(p for p in (base, verify_line) if p)
        if verification.skipped:
            line = f"Проверка не выполнена: {verification.reason}"
            return "\n\n".join(p for p in (base, line) if p)
        line = self._verification_line("Проверка не прошла", verification)
        return "\n\n".join(p for p in (base, line) if p)

    def _verification_line(
        self,
        prefix: str,
        verification: VerificationResult,
    ) -> str:
        """Format a short verification line for final answer."""
        if not verification.commands:
            return f"{prefix}: {verification.reason}"
        cmds = ", ".join(c.command for c in verification.commands[:3])
        return f"{prefix}: `{cmds}`"

    def _legacy_result(
        self,
        request: WorkTaskRequest,
        messages: tuple[ChatMessage, ...],
        outcome: SessionOutcome,
    ) -> WorkTaskResult:
        """Return result for disabled orchestrator fallback."""
        if outcome.state is SessionState.FINISHED:
            text = _last_assistant_text(messages) or "(нет ответа ассистента)"
            return WorkTaskResult(
                ok=bool(_last_assistant_text(messages)),
                messages=messages,
                final_text=text,
                assistant_message_id=request.assistant_message_id,
                error="" if text else "no_assistant_message",
            )
        text = _session_end_user_message(
            state=outcome.state,
            reason=outcome.reason,
        )
        return WorkTaskResult(
            ok=False,
            messages=messages,
            final_text=text,
            assistant_message_id=request.assistant_message_id,
            error=outcome.reason or outcome.state.value,
        )

    def _large_task_text(self, plan: WorkTaskPlan) -> str:
        """Return concise decomposition for too-large tasks."""
        steps = "\n".join(f"- {s.title}" for s in plan.steps)
        return (
            "Эта задача крупнее micro-task для AgentWork. "
            "Я не запускаю её как локальную правку.\n\n"
            f"{steps}\n\n"
            "Следующий безопасный шаг: выберите одну маленькую проверяемую "
            "подзадачу, и AgentWork выполнит её через plan → execute → verify."
        )


def _orchestrator_disabled() -> bool:
    """Return True when env disables the micro-orchestrator for diagnostics."""
    raw = os.environ.get("AILIT_WORK_MICRO_ORCHESTRATOR", "").strip().lower()
    return raw in ("0", "false", "no", "off")


def _session_end_user_message(
    *,
    state: SessionState,
    reason: str | None,
) -> str:
    """Human-readable message for non-finished sessions."""
    r = (reason or "").strip()
    if state is SessionState.WAITING_APPROVAL and r == "approval_pending":
        return (
            "Выполнение остановилось: нужно подтверждение вызова инструмента."
        )
    if state is SessionState.ERROR and r:
        return f"Ошибка сессии: {r}"
    if r:
        return f"Сессия завершена ({state.value}): {r}"
    return f"Сессия завершена: {state.value}"


def _merge_unique(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[str, ...]:
    """Merge path tuples preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in left + right:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def _verification_summary(result: VerificationResult) -> str:
    """Format verification failure for repair prompt."""
    if not result.commands:
        return result.reason
    lines: list[str] = []
    for cmd in result.commands:
        if cmd.exit_code == 0 and not cmd.timed_out:
            continue
        lines.append(f"$ {cmd.command}")
        lines.append(f"exit_code: {cmd.exit_code}")
        if cmd.stdout:
            lines.append("--- stdout ---")
            lines.append(_clip(cmd.stdout, 2000))
        if cmd.stderr:
            lines.append("--- stderr ---")
            lines.append(_clip(cmd.stderr, 2000))
    return "\n".join(lines) if lines else result.reason
