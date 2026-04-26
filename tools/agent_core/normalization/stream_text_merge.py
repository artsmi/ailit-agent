"""Слияние чанков стрима: зеркало `desktop/.../streamTextMerge.ts` (NFC)."""

from __future__ import annotations

import unicodedata


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def merge_stream_text(prev: str, chunk: str) -> str:
    """Слияние накопленного `prev` и `chunk` в одну полную строку (NFC)."""
    c = _nfc(chunk)
    if not c:
        return _nfc(prev)
    p = _nfc(prev)
    if not p:
        return c
    if c.startswith(p):
        return c
    if p.startswith(c):
        return p
    max_k = min(len(p), len(c)) - 1
    min_len = min(len(p), len(c))
    for k in range(max_k, 0, -1):
        if p[-k:] != c[:k]:
            continue
        if k == 1 and min_len > 3:
            continue
        if k == len(c):
            return p
        if k == len(p):
            return c
        return p + c[k:]
    return p + c
