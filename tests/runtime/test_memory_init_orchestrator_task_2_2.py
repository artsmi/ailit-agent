"""TC-2_2: MemoryInitOrchestrator, D4 summary, journal VERIFY."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from agent_core.runtime.agent_memory_chat_log import COMPACT_LOG_FILE_NAME
from agent_core.runtime.memory_init_orchestrator import (
    MemoryInitOrchestrator,
    MemoryInitSigintGuard,
    count_compact_d4_summary_lines,
    normalize_memory_init_root,
)
from agent_core.runtime.memory_init_transaction import MemoryInitPaths as MIP
from agent_core.runtime.memory_journal import MemoryJournalRow
from agent_core.runtime.models import RuntimeRequestEnvelope
from agent_core.runtime.subprocess_agents.memory_agent import AgentMemoryWorker


def test_tc_2_2_summary_counts_d4(tmp_path: Path) -> None:
    p = tmp_path / "compact.log"
    ln1 = "timestamp=t init_session_id=u chat_id=c event=memory.why_llm x=1\n"
    ln2 = (
        "timestamp=t init_session_id=u chat_id=c "
        "event=memory.pag_graph op=node\n"
    )
    ln3 = (
        "timestamp=t init_session_id=u chat_id=c "
        "event=memory.w14_graph_highlight n=1\n"
    )
    ln4 = (
        "timestamp=t init_session_id=u chat_id=c "
        "event=memory.pag_graph op=edge\n"
    )
    lines = [ln1, ln2, ln3, ln4]
    p.write_text("".join(lines), encoding="utf-8")
    assert count_compact_d4_summary_lines(p) == (1, 1, 1)


def test_normalize_memory_init_root_ok(tmp_path: Path) -> None:
    d = tmp_path / "proj"
    d.mkdir()
    (d / "a.txt").write_text("x", encoding="utf-8")
    got = normalize_memory_init_root(d)
    assert got == d.resolve()


def test_normalize_memory_init_root_missing(tmp_path: Path) -> None:
    from agent_core.runtime.errors import RuntimeProtocolError

    with pytest.raises(RuntimeProtocolError):
        normalize_memory_init_root(tmp_path / "nope")


def _stub_handle_complete(
    self: AgentMemoryWorker,
    req: RuntimeRequestEnvelope,
) -> dict[str, object]:
    """Без live LLM продуктовый путь даёт ``partial``; stub фиксирует §4.1."""
    self._journal.append(
        MemoryJournalRow(
            chat_id=req.chat_id,
            request_id="stub-req",
            namespace=str(req.namespace or self._cfg.namespace),
            event_name="memory.result.returned",
            summary="stub",
            payload={
                "query_id": "mem-stub",
                "status": "complete",
                "result_kind_counts": {},
                "results_total": 0,
            },
        ),
    )
    sk = self._get_compact_sink()
    if sk is not None:
        sk.emit_memory_result_complete_marker(
            req=req,
            chat_id=req.chat_id,
            request_id="stub-req",
        )
    return {
        "ok": True,
        "payload": {
            "memory_slice": {"partial": False},
            "partial": False,
            "decision_summary": "stub",
            "recommended_next_step": "none",
        },
    }


def test_memory_init_orchestrator_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "x.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    logs = tmp_path / "chat_logs"
    logs.mkdir()
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(logs))
    am_cfg = tmp_path / "am.yaml"
    am_cfg.write_text(
        'schema_version: "1"\n'
        "memory:\n"
        "  llm:\n"
        "    enabled: false\n"
        "  debug:\n"
        "    verbose: 1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    jr = tmp_path / "memory-journal.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jr))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(tmp_path / "pag.sqlite3"))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(tmp_path / "kb.sqlite3"))
    rt = tmp_path / "runtime"
    rt.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))
    monkeypatch.setattr(
        AgentMemoryWorker,
        "handle",
        _stub_handle_complete,
    )
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=jr,
        runtime_dir=rt,
    )
    code = MemoryInitOrchestrator(paths=paths).run(proj, "ns1")
    assert code == 0
    assert jr.is_file()
    body = jr.read_text(encoding="utf-8")
    assert "memory.result.returned" in body


def test_memory_init_orchestrator_keyboard_interrupt_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_core.runtime.memory_init_orchestrator import _EXIT_INTERRUPT

    def _boom(
        self: AgentMemoryWorker,
        req: object,
    ) -> dict[str, object]:
        raise KeyboardInterrupt()

    monkeypatch.setattr(AgentMemoryWorker, "handle", _boom)
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x=1\n", encoding="utf-8")
    logs = tmp_path / "cl"
    logs.mkdir()
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(logs))
    am_cfg = tmp_path / "am.yaml"
    am_cfg.write_text(
        'schema_version: "1"\nmemory:\n  llm:\n    enabled: false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    jr = tmp_path / "j.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jr))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(tmp_path / "pag.sqlite3"))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(tmp_path / "kb.sqlite3"))
    rt = tmp_path / "rt"
    rt.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=jr,
        runtime_dir=rt,
    )
    code = MemoryInitOrchestrator(paths=paths).run(proj, "ns2")
    assert code == _EXIT_INTERRUPT


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX SIGINT delivery",
)
def test_memory_init_sigint_guard_os_kill_sets_cancelled() -> None:
    guard = MemoryInitSigintGuard()
    try:
        guard.install()

        def _send_sigint() -> None:
            time.sleep(0.08)
            os.kill(os.getpid(), signal.SIGINT)

        threading.Thread(target=_send_sigint, daemon=True).start()
        time.sleep(0.35)
        assert guard.cancelled is True
    finally:
        if guard.active:
            guard.restore()


def _handle_cooperative_sleep_then_ok_sigint_path(
    self: AgentMemoryWorker,
    req: RuntimeRequestEnvelope,
) -> dict[str, object]:
    """Handle sleep + фоновый SIGINT; run проверяет ``guard.cancelled``."""
    del req

    def _send_sigint() -> None:
        time.sleep(0.08)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=_send_sigint, daemon=True).start()
    time.sleep(0.35)
    return {
        "ok": True,
        "payload": {
            "memory_slice": {"partial": False},
            "partial": False,
            "decision_summary": "sigint-stub",
            "recommended_next_step": "none",
        },
    }


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX SIGINT delivery",
)
def test_memory_init_orchestrator_os_sigint_guard_cancelled_aborts_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_core.runtime.memory_init_orchestrator import _EXIT_INTERRUPT

    monkeypatch.setattr(
        AgentMemoryWorker,
        "handle",
        _handle_cooperative_sleep_then_ok_sigint_path,
    )
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x=1\n", encoding="utf-8")
    logs = tmp_path / "cl"
    logs.mkdir()
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(logs))
    am_cfg = tmp_path / "am.yaml"
    am_cfg.write_text(
        'schema_version: "1"\nmemory:\n  llm:\n    enabled: false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    jr = tmp_path / "j.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jr))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(tmp_path / "pag.sqlite3"))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(tmp_path / "kb.sqlite3"))
    rt = tmp_path / "rt"
    rt.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=jr,
        runtime_dir=rt,
    )
    code = MemoryInitOrchestrator(paths=paths).run(proj, "ns-sigint-guard")
    assert code == _EXIT_INTERRUPT
    compact_paths = list(logs.rglob(COMPACT_LOG_FILE_NAME))
    assert len(compact_paths) == 1
    compact_body = compact_paths[0].read_text(encoding="utf-8")
    assert "orch_memory_init_phase" in compact_body
    assert "phase=abort" in compact_body
    assert "phase=commit" not in compact_body
