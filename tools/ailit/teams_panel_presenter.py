"""Human-readable сводка mailbox для панели «Команда» (L.3)."""

from __future__ import annotations

from pathlib import Path

from ailit.teams import TeamRootSelector, TeamSession


class TeamMailboxPanelPresenter:
    """Markdown для Streamlit: агенты и последние сообщения."""

    def __init__(self, *, project_root: Path, team_id: str) -> None:
        """Запомнить корень проекта и id команды."""
        self._project_root = project_root.resolve()
        self._team_id = team_id.strip() or "default"

    def markdown_digest(self, *, filter_to: str | None = None, max_messages: int = 40) -> str:
        """Собрать краткий отчёт по inbox."""
        session = TeamSession(TeamRootSelector.for_project(self._project_root), self._team_id)
        lines: list[str] = [f"**Команда** `{self._team_id}` (корень проекта `{self._project_root}`)", ""]
        agents = sorted(session.iter_recipient_names())
        if not agents:
            return lines[0] + "\n\n_Пока нет входящих (inbox пуст)._"
        ft = (filter_to or "").strip().lower()
        shown = [a for a in agents if not ft or a.lower() == ft]
        if not shown:
            lines.append(f"_Нет агентов по фильтру `{filter_to}`._")
            return "\n".join(lines)
        lines.append("**Агенты с inbox:** " + ", ".join(f"`{a}`" for a in shown))
        lines.append("")
        count = 0
        n_agents = len(shown)
        per = max(1, max_messages // n_agents) if n_agents else max_messages
        for agent in shown:
            msgs = list(session.inbox(agent))
            if not msgs:
                continue
            tail = msgs[-per:]
            lines.append(f"#### `{agent}` — последние {len(tail)}")
            for m in tail:
                fr = m.from_agent
                read = "✓" if m.read else "○"
                lines.append(f"- {read} **{fr}** → `{m.to_agent}` — _{m.ts}_ — {m.text[:200]}")
                count += 1
                if count >= max_messages:
                    lines.append("\n_…усечено по лимиту сообщений._")
                    return "\n".join(lines)
            lines.append("")
        return "\n".join(lines).strip()
