"""Состояние TUI: провайдер и менеджер контекстов (этап Q)."""

from __future__ import annotations

from dataclasses import dataclass

from ailit.tui_context_manager import TuiContextManager
from ailit.tui_session_types import TuiSessionState


@dataclass
class TuiAppState:
    """Полное состояние приложения для slash и ``SessionRunner``."""

    provider: str
    model: str
    max_turns: int
    contexts: TuiContextManager

    def session_view(self) -> TuiSessionState:
        """Собрать ``TuiSessionState`` для активного контекста."""
        prof = self.contexts.active_profile()
        return TuiSessionState(
            project_root=prof.project_root,
            provider=self.provider,
            model=self.model,
            max_turns=self.max_turns,
            agent_id=prof.agent_id,
            workflow_ref=prof.workflow_ref,
        )
