from __future__ import annotations

from ailit_base.models import MessageRole
from ailit_base.system_prompt_builder import (
    SystemPromptLayers,
    build_effective_system_messages,
    dedupe_system_texts,
)


def _texts(msgs: list[object]) -> list[str]:
    out: list[str] = []
    for m in msgs:
        out.append(getattr(m, "content", ""))
    return out


def test_dedupe_system_texts_keeps_first_seen_order() -> None:
    assert dedupe_system_texts(["a", "b", "a", "c", "b"]) == ("a", "b", "c")


def test_build_effective_system_messages_override_replaces_all() -> None:
    layers = SystemPromptLayers(
        default=("d",),
        append=("x",),
        custom=("c",),
        agent=("a",),
        coordinator=("k",),
        override=("o",),
    )
    msgs = build_effective_system_messages(layers)
    assert [m.role for m in msgs] == [MessageRole.SYSTEM]
    assert _texts(msgs) == ["o"]


def test_build_effective_system_messages_priority_agent_then_append() -> None:
    layers = SystemPromptLayers(
        default=("d",),
        custom=("c",),
        agent=("a",),
        append=("x",),
    )
    assert _texts(build_effective_system_messages(layers)) == ["a", "x"]


def test_build_effective_system_messages_priority_custom_then_append() -> None:
    layers = SystemPromptLayers(
        default=("d",),
        custom=("c",),
        append=("x",),
    )
    assert _texts(build_effective_system_messages(layers)) == ["c", "x"]


def test_build_effective_system_messages_default_then_append() -> None:
    layers = SystemPromptLayers(default=("d",), append=("x",))
    assert _texts(build_effective_system_messages(layers)) == ["d", "x"]
