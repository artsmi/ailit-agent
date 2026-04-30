"""Единые верхние границы PAG slice (CLI / SqlitePagStore).

Должны совпадать с ``MEM3D_PAG_MAX_*`` в
``desktop/src/renderer/runtime/pagGraphLimits.ts`` (D-SCL-1).
"""

from __future__ import annotations

PAG_SLICE_MAX_NODES: int = 20_000
PAG_SLICE_MAX_EDGES: int = 40_000
