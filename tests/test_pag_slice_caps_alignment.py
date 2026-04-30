"""D-SCL-1: caps slice = контракт desktop (pagGraphLimits)."""

from __future__ import annotations

from agent_core.memory.pag_slice_caps import (
    PAG_SLICE_MAX_EDGES,
    PAG_SLICE_MAX_NODES,
)


def test_pag_slice_caps_match_desktop_mem3d_contract() -> None:
    assert PAG_SLICE_MAX_NODES == 20_000
    assert PAG_SLICE_MAX_EDGES == 40_000
