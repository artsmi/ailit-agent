"""
Лимиты размера C-нод (G14R.6): единая точка для W14 runtime.

Значения совпадают с G13.4; legacy-референс в ``agent_core.legacy`` импортирует
отсюда же, без дублирования констант.
"""

from __future__ import annotations

from typing import Final

# G13.4: caps = MemoryLlmSubConfig / policy defaults.
C_NODE_FULL_B_MAX_CHARS: Final[int] = 32_768
C_NODE_EXCERPT_MAX_CHARS: Final[int] = 24_000
C_NODE_REMAP_MAX_EXCERPT_CHARS: Final[int] = 32_000
