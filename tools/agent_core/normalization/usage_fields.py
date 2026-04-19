"""Разбор сырого ``usage`` (OpenAI-совместимый API) в ``NormalizedUsage``."""

from __future__ import annotations

from typing import Any, Mapping

from agent_core.models import NormalizedUsage

_CONSUMED_TOP: frozenset[str] = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
    }
)


def _as_int(val: Any) -> int | None:
    """Привести значение к int или None."""
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _first_int(data: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    """Первое ненулевое/не-None значение по списку ключей."""
    for k in keys:
        v = _as_int(data.get(k))
        if v is not None:
            return v
    return None


def _details_int(
    data: Mapping[str, Any],
    key: str,
    inner_keys: tuple[str, ...],
) -> int | None:
    """Целое из вложенного dict по ключу ``key``."""
    inner = data.get(key)
    if not isinstance(inner, dict):
        return None
    return _first_int(inner, inner_keys)


def _collect_nested_unknown(
    prefix: str,
    nested: Mapping[str, Any],
    *,
    skip_keys: frozenset[str],
) -> list[tuple[str, Any]]:
    """Неизвестные поля внутри details-объекта."""
    found: list[tuple[str, Any]] = []
    for sub_k, sub_v in nested.items():
        if sub_k in skip_keys:
            continue
        iv = _as_int(sub_v)
        key = f"{prefix}.{sub_k}"
        if iv is not None:
            found.append((key, iv))
        elif sub_v not in (None, {}):
            found.append((key, sub_v))
    return found


class OpenAICompatUsageNormalizer:
    """Сырой ``usage`` → ``NormalizedUsage`` и хвост неизвестных полей."""

    def normalize(self, data: Mapping[str, Any] | None) -> NormalizedUsage:
        """Разобрать mapping в ``NormalizedUsage`` (None → missing)."""
        if not data:
            return NormalizedUsage(
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                usage_missing=True,
            )
        inp = _first_int(data, ("prompt_tokens", "input_tokens"))
        out = _first_int(data, ("completion_tokens", "output_tokens"))
        tot = _as_int(data.get("total_tokens"))
        reasoning = _first_int(data, ("reasoning_tokens",))
        if reasoning is None:
            reasoning = _details_int(
                data,
                "completion_tokens_details",
                ("reasoning_tokens",),
            )
        cr = _first_int(
            data,
            ("cache_read_input_tokens", "cache_read_tokens"),
        )
        cw = _first_int(
            data,
            ("cache_creation_input_tokens", "cache_write_tokens"),
        )
        unknown_list: list[tuple[str, Any]] = []

        ptd = data.get("prompt_tokens_details")
        if isinstance(ptd, dict):
            p_cached = _as_int(ptd.get("cached_tokens"))
            if cr is None and p_cached is not None:
                cr = p_cached
            unknown_list.extend(
                _collect_nested_unknown(
                    "prompt_tokens_details",
                    ptd,
                    skip_keys=frozenset({"cached_tokens"}),
                ),
            )

        ctd = data.get("completion_tokens_details")
        if isinstance(ctd, dict):
            unknown_list.extend(
                _collect_nested_unknown(
                    "completion_tokens_details",
                    ctd,
                    skip_keys=frozenset({"reasoning_tokens"}),
                ),
            )

        legacy_cached = _as_int(data.get("cached_tokens"))
        if legacy_cached is not None and cw is None and cr is None:
            cr = legacy_cached

        for k, v in data.items():
            if k in _CONSUMED_TOP:
                continue
            iv = _as_int(v)
            if iv is not None:
                unknown_list.append((k, iv))
            elif isinstance(v, (str, bool)):
                unknown_list.append((k, v))

        return NormalizedUsage(
            input_tokens=inp,
            output_tokens=out,
            total_tokens=tot,
            reasoning_tokens=reasoning,
            cached_tokens=legacy_cached,
            cache_read_tokens=cr,
            cache_write_tokens=cw,
            usage_unknown=tuple(unknown_list),
            usage_missing=False,
        )


_DEFAULT_NORMALIZER = OpenAICompatUsageNormalizer()


def normalize_usage_payload(data: Mapping[str, Any] | None) -> NormalizedUsage:
    """Публичная функция: нормализовать сырой блок ``usage``."""
    return _DEFAULT_NORMALIZER.normalize(data)


def usage_to_diag_dict(usage: NormalizedUsage) -> dict[str, Any]:
    """Плоский dict для JSONL / CLI (без None, с хвостом неизвестных)."""
    out: dict[str, Any] = {}
    if usage.usage_missing:
        out["usage_missing"] = True
        return out
    if usage.input_tokens is not None:
        out["input_tokens"] = usage.input_tokens
    if usage.output_tokens is not None:
        out["output_tokens"] = usage.output_tokens
    if usage.total_tokens is not None:
        out["total_tokens"] = usage.total_tokens
    if usage.reasoning_tokens is not None:
        out["reasoning_tokens"] = usage.reasoning_tokens
    if usage.cached_tokens is not None:
        out["cached_tokens"] = usage.cached_tokens
    if usage.cache_read_tokens is not None:
        out["cache_read_tokens"] = usage.cache_read_tokens
    if usage.cache_write_tokens is not None:
        out["cache_write_tokens"] = usage.cache_write_tokens
    if usage.usage_unknown:
        out["usage_unknown"] = {k: v for k, v in usage.usage_unknown}
    return out
