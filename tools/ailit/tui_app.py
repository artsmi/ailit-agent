"""Терминальный чат ailit на Textual (этап P)."""

from __future__ import annotations

import argparse
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog


def resolve_model(provider: str, model: str | None) -> str:
    """Модель по умолчанию в зависимости от провайдера."""
    if model:
        return model
    return "mock" if provider == "mock" else "deepseek-chat"


class AilitTuiApp(App[None]):
    """Каркас TUI: журнал и строка ввода."""

    BINDINGS = [("ctrl+q", "quit", "Выход")]

    def __init__(self, *, args: argparse.Namespace, repo_root: Path) -> None:
        """Сохранить аргументы CLI и корень репозитория ailit-agent."""
        super().__init__()
        self._args = args
        self._repo_root = repo_root
        pr = getattr(args, "project_root", None)
        self._project_root = (
            Path(str(pr)).resolve() if pr else Path.cwd().resolve()
        )
        self.title = "ailit tui"
        self.sub_title = str(self._project_root)

    def compose(self) -> ComposeResult:
        """Шапка, журнал, ввод, подвал."""
        yield Header()
        yield RichLog(id="chat_log", wrap=True, highlight=True)
        yield Input(
            id="chat_input",
            placeholder="Сообщение… (slash-команды: /help)",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Фокус и подзаголовок с провайдером и моделью."""
        prov = str(getattr(self._args, "provider", "mock"))
        model = resolve_model(prov, getattr(self._args, "model", None))
        self.sub_title = f"{self._project_root} | {prov} | {model}"
        self.query_one("#chat_input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Эхо ввода (обработка slash и LLM — в P.2/P.3)."""
        line = event.value.strip()
        self.query_one("#chat_input", Input).value = ""
        if not line:
            return
        log = self.query_one("#chat_log", RichLog)
        log.write(f"[dim]user>[/dim] {line}")
        log.write("[yellow]Каркас P.1 — подключение цикла в P.3[/yellow]")


def run_ailit_tui(args: argparse.Namespace, *, repo_root: Path) -> None:
    """Точка входа Textual."""
    AilitTuiApp(args=args, repo_root=repo_root).run()
