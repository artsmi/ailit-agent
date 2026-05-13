"""Статические эвристики безопасности для shell-команд (этап G.1).

Цель: дать минимальный "failsafe" при всегда включённом `run_shell`.
Мы не пытаемся полностью распарсить bash: это набор простых проверок по идеям
claude-code (heredoc, process substitution, опасные zsh builtins и т.п.).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Final


class BashSecuritySeverity(str, Enum):
    """Важность найденного паттерна."""

    DENY = "deny"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class BashSecurityFinding:
    """Один результат статического скана команды."""

    severity: BashSecuritySeverity
    rule_id: str
    message: str


class BashSecurityScanner:
    """Простой сканер опасных конструкций в shell-командах."""

    _CONTROL_CHARS_RE: Final[re.Pattern[str]] = re.compile(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
    )
    _POWERSHELL_COMMENT_RE: Final[re.Pattern[str]] = re.compile(r"<#")
    _PROC_SUBST_RE: Final[re.Pattern[str]] = re.compile(r"(<\(|>\()")
    _ZSH_EQUALS_EXPANSION_RE: Final[re.Pattern[str]] = re.compile(
        r"(?:^|[\s;&|])=[a-zA-Z_]",
    )
    _CMD_SUBST_DOLLAR_RE: Final[re.Pattern[str]] = re.compile(r"\$\(")
    _PARAM_EXPANSION_RE: Final[re.Pattern[str]] = re.compile(r"\$\{")
    _HEREDOC_RE: Final[re.Pattern[str]] = re.compile(r"<<")

    _ZSH_DANGEROUS_BASE: Final[frozenset[str]] = frozenset(
        {
            "zmodload",
            "emulate",
            "sysopen",
            "sysread",
            "syswrite",
            "sysseek",
            "zpty",
            "ztcp",
            "zsocket",
        },
    )

    def scan(self, command: str) -> tuple[BashSecurityFinding, ...]:
        """Проверить строку команды и вернуть findings (deny + warn)."""
        cmd = command
        out: list[BashSecurityFinding] = []

        if "\n" in cmd or "\r" in cmd:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.DENY,
                    rule_id="newline",
                    message=(
                        "Команда содержит перенос строки "
                        "(multiline запрещён)."
                    ),
                ),
            )
        if self._CONTROL_CHARS_RE.search(cmd) is not None:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.DENY,
                    rule_id="control_chars",
                    message="Команда содержит управляющие символы.",
                ),
            )
        if self._POWERSHELL_COMMENT_RE.search(cmd) is not None:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.DENY,
                    rule_id="powershell_comment",
                    message=(
                        "Обнаружен синтаксис комментариев PowerShell (`<#`)."
                    ),
                ),
            )

        stripped = cmd.strip()
        base = stripped.split(maxsplit=1)[0].lower() if stripped else ""
        if base in self._ZSH_DANGEROUS_BASE:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.DENY,
                    rule_id="zsh_dangerous_builtin",
                    message=f"Запрещён базовый builtin ({base}).",
                ),
            )

        if self._ZSH_EQUALS_EXPANSION_RE.search(cmd) is not None:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.WARN,
                    rule_id="zsh_equals_expansion",
                    message=(
                        "Похоже на zsh equals expansion (`=cmd`) — "
                        "проверьте команду."
                    ),
                ),
            )
        if self._PROC_SUBST_RE.search(cmd) is not None:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.WARN,
                    rule_id="process_substitution",
                    message=(
                        "Обнаружена process substitution "
                        "(`<(...)` или `>(...)`)."
                    ),
                ),
            )
        if self._CMD_SUBST_DOLLAR_RE.search(cmd) is not None:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.WARN,
                    rule_id="command_substitution",
                    message="Обнаружена command substitution (`$(...)`).",
                ),
            )
        if "`" in cmd:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.WARN,
                    rule_id="backticks",
                    message=(
                        "Обнаружены backticks для substitution "
                        "(`` `...` ``)."
                    ),
                ),
            )
        if self._PARAM_EXPANSION_RE.search(cmd) is not None:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.WARN,
                    rule_id="parameter_expansion",
                    message=(
                        "Обнаружена параметрическая подстановка (`${...}`)."
                    ),
                ),
            )
        if self._HEREDOC_RE.search(cmd) is not None:
            out.append(
                BashSecurityFinding(
                    severity=BashSecuritySeverity.WARN,
                    rule_id="heredoc",
                    message="Обнаружен heredoc (`<<`).",
                ),
            )
        return tuple(out)


class BashSecurityFormatter:
    """Форматирование findings для вывода в tool-result."""

    @staticmethod
    def warnings_block(findings: tuple[BashSecurityFinding, ...]) -> str:
        """Сформировать блок предупреждений (пусто, если их нет)."""
        warns = [
            f for f in findings if f.severity is BashSecuritySeverity.WARN
        ]
        if not warns:
            return ""
        lines: list[str] = []
        lines.append("--- security_warnings ---")
        for f in warns:
            lines.append(f"- {f.rule_id}: {f.message}")
        lines.append("")
        return "\n".join(lines)
