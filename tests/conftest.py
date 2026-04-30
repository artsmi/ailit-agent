"""Общие фикстуры pytest.

Изоляция: см. :func:`isolate_ailit_test_artifacts` и ``project-workflow.mdc``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# Репозиторий в PYTHONPATH через pyproject; для IDE — подстраховка.
_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = _ROOT / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))


def _write_minimal_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema_version: \"1\"\n"
        "live:\n"
        "  run: false\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def isolate_ailit_test_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Изолировать тесты от глобального ``~/.ailit`` и дефолтных путей на ПК.

    Каталог: ``tmp_path / ailit_test_isolation / …``. Тесты могут
    переопределить переменные через ``monkeypatch`` сильнее, чем autouse.
    """
    base = tmp_path / "ailit_test_isolation"
    home = base / "home"
    home.mkdir(parents=True)
    runtime = base / "runtime"
    runtime.mkdir()
    pag_dir = base / "pag"
    pag_dir.mkdir()
    pag_db = pag_dir / "store.sqlite3"
    work = base / "work"
    work.mkdir()
    cfg_dir = base / "ailit_config"
    _write_minimal_config(cfg_dir / "config.yaml")
    state_dir = base / "ailit_state"
    state_dir.mkdir()
    kb_db = base / "kb.sqlite3"
    journal = base / "memory-journal.jsonl"

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(pag_db))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(kb_db))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(journal))
    monkeypatch.setenv("AILIT_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("AILIT_STATE_DIR", str(state_dir))
    # ``primary_work_root()`` prefers ``AILIT_WORK_ROOTS`` (JSON) over
    # ``AILIT_WORK_ROOT``. AgentWork registry setup sets WORK_ROOTS in-process;
    # clear stale values so the next test does not read another test's roots.
    monkeypatch.delenv("AILIT_WORK_ROOTS", raising=False)
    monkeypatch.delenv("AILIT_KB_NAMESPACE", raising=False)
    monkeypatch.setenv("AILIT_WORK_ROOT", str(work))
    # Чтобы `multiprocessing` (spawn) и `subprocess` видели пакеты из `tools/`.
    tools_s = str(_TOOLS)
    prev = os.environ.get("PYTHONPATH", "")
    sep = os.pathsep
    if tools_s and tools_s not in (prev.split(sep) if prev else []):
        merged = f"{tools_s}{sep}{prev}" if prev else tools_s
        monkeypatch.setenv("PYTHONPATH", merged)
    yield
