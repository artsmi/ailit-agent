"""TC-2_2: MemoryInitOrchestrator, D4 summary, journal VERIFY."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_memory.observability.agent_memory_chat_log import (
    COMPACT_LOG_FILE_NAME,
    create_unique_cli_session_dir,
)
from agent_memory.init.memory_init_orchestrator import (
    MemoryInitOrchestrator,
    MemoryInitSigintGuard,
    count_compact_d4_summary_lines,
    normalize_memory_init_root,
)
from agent_memory.init.memory_init_transaction import MemoryInitPaths as MIP
from agent_memory.storage.memory_journal import MemoryJournalRow, MemoryJournalStore
from ailit_runtime.models import RuntimeRequestEnvelope
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def test_tc_2_2_summary_counts_d4(tmp_path: Path) -> None:
    p = tmp_path / "compact.log"
    ln1 = "timestamp=t init_session_id=u chat_id=c event=memory.why_llm x=1\n"
    ln2 = (
        "timestamp=t event=memory.pag_graph op=node rev=1 "
        "subject=p#L:n\n"
    )
    ln3 = (
        "timestamp=t event=memory.w14_graph_highlight query_id=q "
        "w14_command=c n_node=1 n_edge=0\n"
    )
    ln4 = "timestamp=t event=memory.pag_graph op=edge rev=2 subject=x\n"
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
    from ailit_runtime.errors import RuntimeProtocolError

    with pytest.raises(RuntimeProtocolError):
        normalize_memory_init_root(tmp_path / "nope")


def _broker_invoke_for_stub_worker(
    *,
    namespace: str,
    broker_chat_id: str,
    monkeypatch: pytest.MonkeyPatch,
    handle_impl: Any,
) -> tuple[Callable[[Mapping[str, Any]], dict[str, Any]], Path]:
    """In-process ``AgentMemoryWorker`` как stand-in для broker RPC (G20.5)."""
    cli_dir = create_unique_cli_session_dir()
    cfg = MemoryAgentConfig(
        chat_id=broker_chat_id,
        broker_id=f"broker-{broker_chat_id}",
        namespace=namespace,
        session_log_mode="cli_init",
        cli_session_dir=cli_dir,
        broker_trace_stdout=False,
    )
    worker = AgentMemoryWorker(cfg)
    monkeypatch.setattr(AgentMemoryWorker, "handle", handle_impl)

    def invoke(env: Mapping[str, Any]) -> dict[str, Any]:
        req = RuntimeRequestEnvelope.from_dict(dict(env))
        out = worker.handle(req)
        return dict(out)

    return invoke, cli_dir


def _stub_handle_complete(
    self: AgentMemoryWorker,
    req: RuntimeRequestEnvelope,
) -> dict[str, object]:
    """Без live LLM продуктовый путь даёт ``partial``; stub фиксирует §4.1.

    Доп. поля ``agent_memory_result`` (continuation и т.д.) игнорируются —
    см. UC-01 в ``test_memory_init_fix_uc01_uc02.py``.
    """
    pl = req.payload if isinstance(req.payload, dict) else {}
    sp = str(pl.get("memory_init_shadow_journal_path") or "").strip()
    jstore = MemoryJournalStore(Path(sp)) if sp else self._journal
    jstore.append(
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
            "agent_memory_result": {
                "schema_version": "agent_memory_result.v1",
                "memory_continuation_required": False,
            },
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
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=jr,
        runtime_dir=rt,
    )
    bcid = "tc22-e2e-ns1"
    invoke, cli_dir = _broker_invoke_for_stub_worker(
        namespace="ns1",
        broker_chat_id=bcid,
        monkeypatch=monkeypatch,
        handle_impl=_stub_handle_complete,
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns1",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    assert jr.is_file()
    body = jr.read_text(encoding="utf-8")
    assert "memory.result.returned" in body


def test_memory_init_orchestrator_keyboard_interrupt_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_memory.init.memory_init_orchestrator import _EXIT_INTERRUPT

    def _boom(
        self: AgentMemoryWorker,
        req: object,
    ) -> dict[str, object]:
        raise KeyboardInterrupt()

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
    bcid = "tc22-kb-ns2"
    invoke, cli_dir = _broker_invoke_for_stub_worker(
        namespace="ns2",
        broker_chat_id=bcid,
        monkeypatch=monkeypatch,
        handle_impl=_boom,
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns2",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
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
            "agent_memory_result": {
                "schema_version": "agent_memory_result.v1",
                "memory_continuation_required": False,
            },
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
    from agent_memory.init.memory_init_orchestrator import _EXIT_INTERRUPT

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
    bcid = "tc22-sigint-guard"
    invoke, cli_dir = _broker_invoke_for_stub_worker(
        namespace="ns-sigint-guard",
        broker_chat_id=bcid,
        monkeypatch=monkeypatch,
        handle_impl=_handle_cooperative_sleep_then_ok_sigint_path,
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-sigint-guard",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == _EXIT_INTERRUPT
    compact_paths = list(logs.rglob(COMPACT_LOG_FILE_NAME))
    assert len(compact_paths) == 1
    compact_body = compact_paths[0].read_text(encoding="utf-8")
    assert "orch_memory_init_phase" in compact_body
    assert "phase=abort" in compact_body
    assert "phase=commit" not in compact_body


def test_memory_init_init_soak_partial_without_continuation_then_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Init soak: несколько RPC с partial без continuation, затем complete."""
    proj = tmp_path / "proj-soak"
    proj.mkdir()
    (proj / "m.py").write_text("x = 1\n", encoding="utf-8")
    logs = tmp_path / "chat_logs_soak"
    logs.mkdir()
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(logs))
    am_cfg = tmp_path / "am-soak.yaml"
    am_cfg.write_text(
        'schema_version: "1"\n'
        "memory:\n"
        "  llm:\n"
        "    enabled: false\n"
        "  init:\n"
        "    max_continuation_rounds: 8\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    jr = tmp_path / "memory-journal-soak.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jr))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(tmp_path / "pag-soak.sqlite3"))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(tmp_path / "kb-soak.sqlite3"))
    rt = tmp_path / "runtime-soak"
    rt.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))
    paths = MIP(
        pag_db=tmp_path / "pag-soak.sqlite3",
        kb_db=tmp_path / "kb-soak.sqlite3",
        journal_canonical=jr,
        runtime_dir=rt,
    )
    bcid = "soak-chat-1"
    soak_calls: dict[str, int] = {"n": 0}

    def _handle_soak(
        self: AgentMemoryWorker,
        req: RuntimeRequestEnvelope,
    ) -> dict[str, object]:
        pl = req.payload if isinstance(req.payload, dict) else {}
        sp = str(pl.get("memory_init_shadow_journal_path") or "").strip()
        jstore = MemoryJournalStore(Path(sp)) if sp else self._journal
        soak_calls["n"] += 1
        rid = f"soak-req-{soak_calls['n']}"
        if soak_calls["n"] < 3:
            jstore.append(
                MemoryJournalRow(
                    chat_id=req.chat_id,
                    request_id=rid,
                    namespace=str(req.namespace or self._cfg.namespace),
                    event_name="memory.result.returned",
                    summary="stub-partial",
                    payload={
                        "query_id": "mem-partial",
                        "status": "partial",
                        "result_kind_counts": {},
                        "results_total": 0,
                    },
                ),
            )
            return {
                "ok": True,
                "payload": {
                    "memory_slice": {"partial": True},
                    "partial": True,
                    "decision_summary": "partial",
                    "recommended_next_step": "continue",
                    "agent_memory_result": {
                        "schema_version": "agent_memory_result.v1",
                        "status": "partial",
                        "memory_continuation_required": False,
                    },
                },
            }
        jstore.append(
            MemoryJournalRow(
                chat_id=req.chat_id,
                request_id=rid,
                namespace=str(req.namespace or self._cfg.namespace),
                event_name="memory.result.returned",
                summary="stub-complete",
                payload={
                    "query_id": "mem-done",
                    "status": "complete",
                    "result_kind_counts": {},
                    "results_total": 0,
                },
            ),
        )
        return {
            "ok": True,
            "payload": {
                "memory_slice": {"partial": False},
                "partial": False,
                "decision_summary": "done",
                "recommended_next_step": "none",
                "agent_memory_result": {
                    "schema_version": "agent_memory_result.v1",
                    "status": "complete",
                    "memory_continuation_required": False,
                },
            },
        }

    invoke, cli_dir = _broker_invoke_for_stub_worker(
        namespace="ns-soak",
        broker_chat_id=bcid,
        monkeypatch=monkeypatch,
        handle_impl=_handle_soak,
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-soak",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    assert soak_calls["n"] == 3


def test_memory_init_soak_continues_when_recommended_step_is_fix_llm_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Init soak: ``recommended_next_step=fix_memory_llm_json`` не обрывает цикл
    до исчерпания бюджета; второй RPC может завершить журнал ``complete``.
    """
    proj = tmp_path / "proj-fixjson"
    proj.mkdir()
    (proj / "f.py").write_text("y = 2\n", encoding="utf-8")
    logs = tmp_path / "chat_logs_fixjson"
    logs.mkdir()
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(logs))
    am_cfg = tmp_path / "am-fixjson.yaml"
    am_cfg.write_text(
        'schema_version: "1"\n'
        "memory:\n"
        "  llm:\n"
        "    enabled: false\n"
        "  init:\n"
        "    max_continuation_rounds: 8\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    jr = tmp_path / "memory-journal-fixjson.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jr))
    monkeypatch.setenv(
        "AILIT_PAG_DB_PATH",
        str(tmp_path / "pag-fixjson.sqlite3"),
    )
    monkeypatch.setenv(
        "AILIT_KB_DB_PATH",
        str(tmp_path / "kb-fixjson.sqlite3"),
    )
    rt = tmp_path / "runtime-fixjson"
    rt.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))
    paths = MIP(
        pag_db=tmp_path / "pag-fixjson.sqlite3",
        kb_db=tmp_path / "kb-fixjson.sqlite3",
        journal_canonical=jr,
        runtime_dir=rt,
    )
    bcid = "fixjson-chat-1"
    fix_calls: dict[str, int] = {"n": 0}

    def _handle_fixjson(
        self: AgentMemoryWorker,
        req: RuntimeRequestEnvelope,
    ) -> dict[str, object]:
        pl = req.payload if isinstance(req.payload, dict) else {}
        sp = str(pl.get("memory_init_shadow_journal_path") or "").strip()
        jstore = MemoryJournalStore(Path(sp)) if sp else self._journal
        fix_calls["n"] += 1
        rid = f"fixjson-req-{fix_calls['n']}"
        if fix_calls["n"] == 1:
            return {
                "ok": True,
                "payload": {
                    "memory_slice": {"partial": True},
                    "partial": True,
                    "decision_summary": "json",
                    "recommended_next_step": "fix_memory_llm_json",
                    "agent_memory_result": {
                        "schema_version": "agent_memory_result.v1",
                        "status": "partial",
                        "memory_continuation_required": False,
                    },
                },
            }
        jstore.append(
            MemoryJournalRow(
                chat_id=req.chat_id,
                request_id=rid,
                namespace=str(req.namespace or self._cfg.namespace),
                event_name="memory.result.returned",
                summary="stub-complete",
                payload={
                    "query_id": "mem-done",
                    "status": "complete",
                    "result_kind_counts": {},
                    "results_total": 0,
                },
            ),
        )
        return {
            "ok": True,
            "payload": {
                "memory_slice": {"partial": False},
                "partial": False,
                "decision_summary": "done",
                "recommended_next_step": "none",
                "agent_memory_result": {
                    "schema_version": "agent_memory_result.v1",
                    "status": "complete",
                    "memory_continuation_required": False,
                },
            },
        }

    invoke, cli_dir = _broker_invoke_for_stub_worker(
        namespace="ns-fixjson",
        broker_chat_id=bcid,
        monkeypatch=monkeypatch,
        handle_impl=_handle_fixjson,
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-fixjson",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    assert fix_calls["n"] == 2


def test_memory_init_soak_continues_when_envelope_complete_but_journal_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Envelope может отдать ``agent_memory_result.status=complete`` до маркера
    complete в shadow-журнале; оркестратор продолжает RPC до VERIFY ok.
    """
    proj = tmp_path / "proj-env-complete"
    proj.mkdir()
    (proj / "g.py").write_text("z = 3\n", encoding="utf-8")
    logs = tmp_path / "chat_logs_env_complete"
    logs.mkdir()
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(logs))
    am_cfg = tmp_path / "am-env-complete.yaml"
    am_cfg.write_text(
        'schema_version: "1"\n'
        "memory:\n"
        "  llm:\n"
        "    enabled: false\n"
        "  init:\n"
        "    max_continuation_rounds: 8\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    jr = tmp_path / "memory-journal-env-complete.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jr))
    monkeypatch.setenv(
        "AILIT_PAG_DB_PATH",
        str(tmp_path / "pag-env-complete.sqlite3"),
    )
    monkeypatch.setenv(
        "AILIT_KB_DB_PATH",
        str(tmp_path / "kb-env-complete.sqlite3"),
    )
    rt = tmp_path / "runtime-env-complete"
    rt.mkdir()
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))
    paths = MIP(
        pag_db=tmp_path / "pag-env-complete.sqlite3",
        kb_db=tmp_path / "kb-env-complete.sqlite3",
        journal_canonical=jr,
        runtime_dir=rt,
    )
    bcid = "env-complete-chat"
    calls: dict[str, int] = {"n": 0}

    def _handle_env_complete(
        self: AgentMemoryWorker,
        req: RuntimeRequestEnvelope,
    ) -> dict[str, object]:
        pl = req.payload if isinstance(req.payload, dict) else {}
        sp = str(pl.get("memory_init_shadow_journal_path") or "").strip()
        jstore = MemoryJournalStore(Path(sp)) if sp else self._journal
        calls["n"] += 1
        rid = f"env-req-{calls['n']}"
        if calls["n"] == 1:
            jstore.append(
                MemoryJournalRow(
                    chat_id=req.chat_id,
                    request_id=rid,
                    namespace=str(req.namespace or self._cfg.namespace),
                    event_name="memory.result.returned",
                    summary="stub-partial",
                    payload={
                        "query_id": "mem-partial",
                        "status": "partial",
                        "result_kind_counts": {},
                        "results_total": 0,
                    },
                ),
            )
            return {
                "ok": True,
                "payload": {
                    "memory_slice": {"partial": False},
                    "partial": False,
                    "decision_summary": "premature",
                    "recommended_next_step": "none",
                    "agent_memory_result": {
                        "schema_version": "agent_memory_result.v1",
                        "status": "complete",
                        "memory_continuation_required": False,
                    },
                },
            }
        jstore.append(
            MemoryJournalRow(
                chat_id=req.chat_id,
                request_id=rid,
                namespace=str(req.namespace or self._cfg.namespace),
                event_name="memory.result.returned",
                summary="stub-complete",
                payload={
                    "query_id": "mem-done",
                    "status": "complete",
                    "result_kind_counts": {},
                    "results_total": 0,
                },
            ),
        )
        return {
            "ok": True,
            "payload": {
                "memory_slice": {"partial": False},
                "partial": False,
                "decision_summary": "done",
                "recommended_next_step": "none",
                "agent_memory_result": {
                    "schema_version": "agent_memory_result.v1",
                    "status": "complete",
                    "memory_continuation_required": False,
                },
            },
        }

    invoke, cli_dir = _broker_invoke_for_stub_worker(
        namespace="ns-env-complete",
        broker_chat_id=bcid,
        monkeypatch=monkeypatch,
        handle_impl=_handle_env_complete,
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-env-complete",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    assert calls["n"] == 2
