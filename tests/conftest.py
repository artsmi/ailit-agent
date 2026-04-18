"""Общие фикстуры pytest."""

from __future__ import annotations

import sys
from pathlib import Path

# Репозиторий в PYTHONPATH через pyproject; для IDE — подстраховка.
_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = _ROOT / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
