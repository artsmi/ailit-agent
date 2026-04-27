"""Политика выбора tool_choice для session loop (одна точка смены правил)."""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.models import ToolChoice
from agent_core.tool_runtime.executor import ToolInvocation, ToolRunResult


@dataclass(frozen=True, slots=True)
class ToolChoicePolicyResult:
    """Решение политики для одного запроса к модели."""

    tool_choice: ToolChoice | None
    policy_reason: str
    tool_choice_mode_effective: str | None


class DefaultToolChoicePolicy:
    """Правила: по умолчанию auto; после write_file — один запрос с none."""

    def choose(
        self,
        *,
        tools_available: bool,
        suppress_next_request: bool,
        policy_enabled: bool,
    ) -> ToolChoicePolicyResult:
        """Выбрать tool_choice для ChatRequest.

        Без tools — ``tool_choice`` None.
        При ``suppress_next_request`` и включённой политике — ``mode=none``
        (OpenAI-совместимо при непустом списке tools). Иначе ``auto``.
        """
        if not tools_available:
            return ToolChoicePolicyResult(
                None,
                "no_tools_in_request",
                None,
            )
        if policy_enabled and suppress_next_request:
            return ToolChoicePolicyResult(
                ToolChoice(mode="none"),
                "after_successful_write_file_one_shot_none",
                "none",
            )
        return ToolChoicePolicyResult(
            ToolChoice(mode="auto"),
            "default_auto_with_tools",
            "auto",
        )


default_tool_choice_policy = DefaultToolChoicePolicy()


def last_batch_had_successful_write_file(
    invocations: tuple[ToolInvocation, ...] | list[ToolInvocation],
    results: tuple[ToolRunResult, ...] | list[ToolRunResult],
) -> bool:
    """Проверить успешный write_file или apply_patch в паре invocations/results."""
    _names = frozenset({"write_file", "apply_patch"})
    for inv, res in zip(invocations, results, strict=True):
        if inv.tool_name in _names and res.error is None:
            return True
    return False
