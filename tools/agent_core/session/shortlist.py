"""Shortlist по ключевым словам (MVP без retrieval-слоя)."""

from __future__ import annotations

from collections.abc import Sequence

from agent_core.models import ChatMessage, MessageRole


class KeywordShortlistSelector:
    """Индексы: system, keyword в content, последний user."""

    def __init__(self, keywords: frozenset[str]) -> None:
        """Сохранить ключевые слова (без учёта регистра)."""
        self._kw_lower: tuple[str, ...] = tuple(
            kw.lower() for kw in keywords
        )

    def select_indices(self, messages: Sequence[ChatMessage]) -> set[int]:
        """Индексы сообщений, оставляемых shortlist по keyword."""
        keep: set[int] = set()
        for i, m in enumerate(messages):
            if m.role is MessageRole.SYSTEM:
                keep.add(i)
                continue
            lower = m.content.lower()
            if any(kw in lower for kw in self._kw_lower):
                keep.add(i)
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role is MessageRole.USER:
                keep.add(i)
                break
        return keep


class ToolChainIntegrityExpander:
    """Замыкание по парам assistant (tool_calls) и TOOL для валидного API."""

    @staticmethod
    def _parent_assistant_index(
        messages: Sequence[ChatMessage],
        tool_idx: int,
        tool_call_id: str,
    ) -> int | None:
        """Assistant, которому принадлежит tool_call_id."""
        for j in range(tool_idx - 1, -1, -1):
            m = messages[j]
            if m.role is not MessageRole.ASSISTANT or not m.tool_calls:
                continue
            if any(tc.call_id == tool_call_id for tc in m.tool_calls):
                return j
        return None

    @staticmethod
    def _tool_reply_indices(
        messages: Sequence[ChatMessage],
        ast_idx: int,
    ) -> list[int]:
        """Индексы TOOL сразу после assistant, по его call_id."""
        ast = messages[ast_idx]
        if ast.role is not MessageRole.ASSISTANT or not ast.tool_calls:
            return []
        needed = {tc.call_id for tc in ast.tool_calls}
        collected: set[str] = set()
        out: list[int] = []
        k = ast_idx + 1
        while k < len(messages) and messages[k].role is MessageRole.TOOL:
            tid = messages[k].tool_call_id
            if tid in needed:
                collected.add(tid)
                out.append(k)
            k += 1
            if collected == needed:
                break
        return out

    def expand(
        self,
        messages: Sequence[ChatMessage],
        keep: set[int],
    ) -> set[int]:
        """Расширить keep до замыкания по цепочкам assistant/tool."""
        out: set[int] = set(keep)
        changed = True
        while changed:
            changed = False
            for idx in sorted(out):
                m = messages[idx]
                if m.role is MessageRole.TOOL and m.tool_call_id:
                    parent = self._parent_assistant_index(
                        messages,
                        idx,
                        m.tool_call_id,
                    )
                    if parent is not None:
                        if parent not in out:
                            out.add(parent)
                            changed = True
                        for t_idx in self._tool_reply_indices(
                            messages,
                            parent,
                        ):
                            if t_idx not in out:
                                out.add(t_idx)
                                changed = True
                if m.role is MessageRole.ASSISTANT and m.tool_calls:
                    for t_idx in self._tool_reply_indices(
                        messages,
                        idx,
                    ):
                        if t_idx not in out:
                            out.add(t_idx)
                            changed = True
        return out


def apply_keyword_shortlist(
    messages: Sequence[ChatMessage],
    keywords: frozenset[str],
) -> list[ChatMessage]:
    """System, последний user, keyword и связанные tool-цепочки."""
    if not keywords:
        return list(messages)
    selector = KeywordShortlistSelector(keywords)
    expander = ToolChainIntegrityExpander()
    keep = selector.select_indices(messages)
    keep_final = expander.expand(messages, keep)
    return [messages[i] for i in sorted(keep_final)]
