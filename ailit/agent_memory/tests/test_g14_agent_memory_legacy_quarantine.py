"""
G14R.6: quarantine legacy C extraction; W14 runtime не тянет legacy модули.

План: `plan/14-agent-memory-runtime.md` §G14R.6.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_RUNTIME = _REPO / "ailit" / "agent_memory"
_LEGACY = _RUNTIME / "legacy"
_PIPELINE = _RUNTIME / "query" / "agent_memory_query_pipeline.py"
_LEGACY_SEM = _LEGACY / "semantic_c_extraction.py"
_LEGACY_PRM = _LEGACY / "memory_c_extractor_prompt.py"
_FORBIDDEN_SUBSTR = ("semantic_c_extraction", "memory_c_extractor_prompt")


def _is_importish_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    return s.startswith("import ") or " import " in s


def _runtime_mentions_forbidden_substrings() -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for path in sorted(_RUNTIME.rglob("*.py")):
        if path.is_dir():
            continue
        if "legacy" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            for sub in _FORBIDDEN_SUBSTR:
                if sub in line:
                    hits.append((path, i, line))
    return hits


def test_legacy_c_extraction_modules_are_deleted_or_quarantined() -> None:
    """
    A14R.15: legacy модули вне основного кода памяти, под `agent_memory.legacy` (D14R.4).
    """
    assert not (_RUNTIME / "semantic_c_extraction.py").exists()
    assert not (_RUNTIME / "memory_c_extractor_prompt.py").exists()
    assert _LEGACY_SEM.is_file()
    assert _LEGACY_PRM.is_file()


def test_w14_runtime_does_not_import_legacy_c_extraction() -> None:
    """
    W14: в `agent_memory` (кроме каталога `legacy/`) нет import legacy имён.

    Упоминания в docstring/комментариях (запрет) допустимы (archive/reference).
    """
    for path, line_no, line in _runtime_mentions_forbidden_substrings():
        if not _is_importish_line(line):
            continue
        if "tests" in str(path):
            continue
        for sub in _FORBIDDEN_SUBSTR:
            if sub in line and _is_importish_line(line):
                rel = path.relative_to(_REPO)
                msg = f"{rel}:{line_no}: {line!r}"
                pytest.fail(
                    f"W14 runtime не должен импортировать legacy C: {msg}",
                )


def test_w14_runtime_uses_summary_service_for_c_and_b() -> None:
    """
    G14R.6: pipeline якорь; SoT для C/B — `agent_memory_summary_service`.
    """
    import agent_memory.services.w14_clean_replacement as w14

    assert w14.W14_SOURCE_OF_TRUTH_EXCLUDES_LEGACY_C_EXTRACTOR_MODULES is True
    from agent_memory.services.agent_memory_summary_service import (
        AgentMemorySummaryService,
    )

    assert AgentMemorySummaryService is not None
    assert hasattr(AgentMemorySummaryService, "apply_summarize_c")
    assert hasattr(AgentMemorySummaryService, "apply_summarize_b")

    src = _PIPELINE.read_text(encoding="utf-8")
    assert "agent_memory_summary_service" in src
    # Якорь: pipeline ссылается на модуль (коммент G14R.6).
    assert "G14R.6" in src
