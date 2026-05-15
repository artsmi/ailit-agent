"""G20.7: prod memory orchestrators must not construct AgentMemoryWorker.

Whitelist (``AgentMemoryWorker(`` allowed outside these two files):
``tests/runtime/test_memory_init_orchestrator_task_2_2.py``,
``tests/runtime/test_memory_init_fix_uc01_uc02.py``,
``tests/runtime/test_memory_init_t4_uc05_real_handle.py``,
``ailit/ailit_runtime/subprocess_agents/memory_agent.py``,
other ``tests/**``, broker subprocess.

Orchestrator sources: ``ailit/agent_memory/init/memory_init_orchestrator.py``,
``ailit/agent_memory/query/memory_query_orchestrator.py``.

See ``plan/20-memory-cli-broker-viz.md`` §5 G20.7.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_MEMORY = _REPO_ROOT / "ailit" / "agent_memory"
_WORKER_CTOR = re.compile(r"AgentMemoryWorker\s*\(")


def test_g20_7_memory_init_orchestrator_no_inprocess_worker_ctor() -> None:
    path = _AGENT_MEMORY / "init" / "memory_init_orchestrator.py"
    text = path.read_text(encoding="utf-8")
    assert _WORKER_CTOR.search(text) is None, (
        "G20 D1: memory_init_orchestrator must not call AgentMemoryWorker( — "
        f"see plan/20-memory-cli-broker-viz.md G20.7; file={path}"
    )


def test_g20_7_memory_query_orchestrator_no_inprocess_worker_ctor() -> None:
    path = _AGENT_MEMORY / "query" / "memory_query_orchestrator.py"
    text = path.read_text(encoding="utf-8")
    assert _WORKER_CTOR.search(text) is None, (
        "G20 D1: memory_query_orchestrator must not call AgentMemoryWorker( — "
        f"see plan/20-memory-cli-broker-viz.md G20.7; file={path}"
    )
