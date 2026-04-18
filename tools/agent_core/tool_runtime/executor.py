"""Исполнение инструментов с permissions, approvals и упорядочиванием."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import Sequence

from agent_core.tool_runtime.approval import ApprovalDecision, ApprovalSession
from agent_core.tool_runtime.permission import PermissionDecision, PermissionEngine
from agent_core.tool_runtime.registry import ToolRegistry
from agent_core.tool_runtime.schema_validate import parse_and_validate_arguments_json
from agent_core.tool_runtime.spec import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Один вызов инструмента от модели."""

    call_id: str
    tool_name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ToolRunResult:
    """Результат исполнения одного вызова."""

    call_id: str
    tool_name: str
    content: str
    error: str | None = None


class ApprovalPending(Exception):
    """Требуется решение оператора перед исполнением."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        super().__init__(f"approval pending for {tool_name} ({call_id})")
        self.call_id = call_id
        self.tool_name = tool_name


class ToolRejected(Exception):
    """Оператор отклонил вызов."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        super().__init__(f"tool rejected: {tool_name} ({call_id})")
        self.call_id = call_id
        self.tool_name = tool_name


class ToolExecutor:
    """Исполнитель: serial или safe-parallel только для read_only allow_parallel."""

    def __init__(
        self,
        registry: ToolRegistry,
        permission_engine: PermissionEngine | None = None,
    ) -> None:
        """Привязать реестр и движок разрешений."""
        self._registry = registry
        self._permission = permission_engine or PermissionEngine()

    def _guard_cancel(self, cancel: Event | None) -> None:
        if cancel is not None and cancel.is_set():
            raise RuntimeError("tool execution cancelled")

    def execute_one(
        self,
        inv: ToolInvocation,
        approvals: ApprovalSession,
        *,
        cancel: Event | None = None,
    ) -> ToolRunResult:
        """Исполнить один вызов с проверками."""
        self._guard_cancel(cancel)
        spec = self._registry.get_spec(inv.tool_name)
        perm = self._permission.evaluate(spec)
        if perm is PermissionDecision.DENY:
            return ToolRunResult(
                call_id=inv.call_id,
                tool_name=inv.tool_name,
                content="",
                error="permission_denied",
            )
        if perm is PermissionDecision.ASK:
            st = approvals.status(inv.call_id)
            if st is ApprovalDecision.PENDING:
                raise ApprovalPending(inv.call_id, inv.tool_name)
            if st is ApprovalDecision.REJECTED:
                raise ToolRejected(inv.call_id, inv.tool_name)
        args = parse_and_validate_arguments_json(spec, inv.arguments_json)
        self._guard_cancel(cancel)
        handler = self._registry.get_handler(inv.tool_name)
        try:
            out = handler(args)
        except Exception as exc:  # noqa: BLE001 — нормализация ошибок инструмента
            return ToolRunResult(
                call_id=inv.call_id,
                tool_name=inv.tool_name,
                content="",
                error=f"{type(exc).__name__}: {exc}",
            )
        return ToolRunResult(call_id=inv.call_id, tool_name=inv.tool_name, content=out, error=None)

    def execute_serial(
        self,
        invocations: Sequence[ToolInvocation],
        approvals: ApprovalSession,
        *,
        cancel: Event | None = None,
    ) -> list[ToolRunResult]:
        """Последовательное исполнение с сохранением порядка."""
        out: list[ToolRunResult] = []
        for inv in invocations:
            out.append(self.execute_one(inv, approvals, cancel=cancel))
        return out

    def execute_parallel_safe(
        self,
        invocations: Sequence[ToolInvocation],
        approvals: ApprovalSession,
        *,
        cancel: Event | None = None,
    ) -> list[ToolRunResult]:
        """Параллельно только если все вызовы read_only+allow_parallel и ALLOW."""
        if not invocations:
            return []
        specs: list[ToolSpec] = []
        for inv in invocations:
            spec = self._registry.get_spec(inv.tool_name)
            specs.append(spec)
            perm = self._permission.evaluate(spec)
            if perm is not PermissionDecision.ALLOW:
                msg = "parallel batch requires all ALLOW"
                raise ValueError(msg)
            if not spec.allow_parallel:
                msg = "parallel batch requires allow_parallel on all tools"
                raise ValueError(msg)
        self._guard_cancel(cancel)

        def run_one(inv: ToolInvocation) -> ToolRunResult:
            return self.execute_one(inv, approvals, cancel=cancel)

        with ThreadPoolExecutor(max_workers=min(8, len(invocations))) as pool:
            futures = [pool.submit(run_one, inv) for inv in invocations]
            results = [f.result() for f in futures]
        return results
