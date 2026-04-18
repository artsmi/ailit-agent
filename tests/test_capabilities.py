"""Матрица capability для провайдеров."""

from __future__ import annotations

import pytest

from agent_core.capabilities import Capability, capability_set_for, provider_supports


@pytest.mark.parametrize(
    ("provider_id", "expected_subset"),
    [
        (
            "deepseek",
            {
                Capability.CHAT,
                Capability.STREAMING,
                Capability.TOOLS,
                Capability.STRICT_SCHEMA,
                Capability.USAGE,
                Capability.PARSER_FALLBACK,
            },
        ),
        (
            "kimi",
            {
                Capability.CHAT,
                Capability.STREAMING,
                Capability.TOOLS,
                Capability.USAGE,
                Capability.PARSER_FALLBACK,
            },
        ),
        ("mock", set(Capability)),
    ],
)
def test_capability_matrix_covers_expected(provider_id: str, expected_subset: set) -> None:
    """Заявленные capability содержат ожидаемый набор."""
    caps = capability_set_for(provider_id)
    assert expected_subset <= caps


def test_kimi_strict_schema_flag_absent() -> None:
    """Kimi: strict schema не заявлена в матрице (ограниченная поддержка)."""
    assert not provider_supports("kimi", Capability.STRICT_SCHEMA)


def test_unknown_provider_defaults_to_chat_only() -> None:
    """Неизвестный id не падает и даёт минимум CHAT."""
    caps = capability_set_for("unknown_vendor")
    assert caps == frozenset({Capability.CHAT})
