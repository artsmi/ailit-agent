"""Жёсткие правила смены ``promotion_status`` в KB (M3-3/4)."""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.memory.layers import MemoryLayer
from agent_core.memory.sqlite_kb import KbRecord

PROMOTE_TARGET_STATUSES: frozenset[str] = frozenset(
    {"reviewed", "promoted", "deprecated"},
)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Результат проверки перехода ``promotion_status``."""

    ok: bool
    rule_id: str
    message: str

    @staticmethod
    def allow() -> PromotionDecision:
        """Переход разрешён."""
        return PromotionDecision(True, "", "")

    @staticmethod
    def deny(rule_id: str, message: str) -> PromotionDecision:
        """Переход запрещён."""
        return PromotionDecision(False, str(rule_id), str(message))


def _norm_status(value: str | None) -> str:
    s = str(value or "").strip().lower()
    return s if s else "draft"


def evaluate_promotion(rec: KbRecord, to_status: str) -> PromotionDecision:
    """Проверить, допустим ли переход *текущий* → *to_status*.

    ``superseded`` считается терминалом. Повторная установка того же
    статуса обрабатывается в ``kb_promote`` до вызова этой функции.
    """
    target = str(to_status or "").strip().lower()
    if target not in PROMOTE_TARGET_STATUSES:
        return PromotionDecision.deny(
            "invalid_target",
            f"to_status: одно из {', '.join(sorted(PROMOTE_TARGET_STATUSES))}",
        )
    cur = _norm_status(rec.promotion_status)
    if cur == "superseded":
        return PromotionDecision.deny(
            "terminal_superseded",
            "запись superseded не меняется через kb_promote",
        )
    if target == "reviewed":
        if cur != "draft":
            return PromotionDecision.deny(
                "invalid_transition",
                f"в reviewed только из draft, сейчас: {cur}",
            )
        if not (rec.source or "").strip():
            return PromotionDecision.deny(
                "review_requires_source",
                "нужен непустой source",
            )
        if len((rec.summary or "").strip()) < 5:
            return PromotionDecision.deny(
                "review_requires_summary",
                "нужен summary длиной ≥5 символов",
            )
        if not (rec.body or "").strip():
            return PromotionDecision.deny(
                "review_requires_body",
                "нужен непустой body",
            )
        return PromotionDecision.allow()
    if target == "promoted":
        if cur != "reviewed":
            return PromotionDecision.deny(
                "promoted_requires_reviewed",
                "к promoted только из reviewed",
            )
        layer = (rec.memory_layer or "").strip().lower()
        if layer not in (
            MemoryLayer.SEMANTIC.value,
            MemoryLayer.PROCEDURAL.value,
        ):
            return PromotionDecision.deny(
                "promoted_requires_layer",
                "memory_layer должен быть semantic или procedural",
            )
        if not (rec.source or "").strip():
            return PromotionDecision.deny(
                "promoted_requires_source",
                "нужен непустой source",
            )
        return PromotionDecision.allow()
    if target == "deprecated":
        return PromotionDecision.allow()
    return PromotionDecision.deny("unknown", "недопустимый переход")
