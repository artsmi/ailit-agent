"""UC-01 / UC-02 / UC-03 регрессия для memory init (task_3_1)."""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_memory.observability.agent_memory_chat_log import (
    COMPACT_LOG_FILE_NAME,
    AgentMemoryChatDebugLog,
    create_unique_cli_session_dir,
)
from agent_memory.config.agent_memory_config import (
    AgentMemoryFileConfig,
    MemoryDebugSubConfig,
)
from agent_memory.query.agent_memory_query_pipeline import (
    AgentMemoryQueryPipeline,
    W14RuntimeLimits,
)
from agent_memory.init.memory_init_orchestrator import (
    MEMORY_INIT_CANONICAL_GOAL,
    MemoryInitOrchestrator,
)
from agent_memory.init.memory_init_summary import (
    emit_memory_init_user_summary,
)
from agent_memory.init.memory_init_transaction import MemoryInitPaths as MIP
from agent_memory.storage.memory_journal import MemoryJournalRow, MemoryJournalStore
from ailit_runtime.models import RuntimeRequestEnvelope
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def _verbose_cfg() -> AgentMemoryFileConfig:
    base: AgentMemoryFileConfig = AgentMemoryFileConfig()
    return replace(
        base,
        memory=replace(
            base.memory,
            debug=MemoryDebugSubConfig(verbose=1),
        ),
    )


def _apply_memory_init_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tmp + env: без ~/.ailit (как test_memory_init_orchestrator_task_2_2)."""
    logs = tmp_path / "chat_logs"
    logs.mkdir(parents=True, exist_ok=True)
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
    rt.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))


def _uc_stub_journal_store(
    worker: AgentMemoryWorker,
    req: RuntimeRequestEnvelope,
) -> MemoryJournalStore:
    """G20.5: append в shadow из payload orchestrator."""
    pl = req.payload if isinstance(req.payload, dict) else {}
    sp = str(pl.get("memory_init_shadow_journal_path") or "").strip()
    if sp:
        return MemoryJournalStore(Path(sp))
    return worker._journal


def _broker_invoke_worker(
    worker: AgentMemoryWorker,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def invoke(env: Mapping[str, Any]) -> dict[str, Any]:
        req = RuntimeRequestEnvelope.from_dict(dict(env))
        return dict(worker.handle(req))

    return invoke


def _memory_init_stub_worker(
    *,
    namespace: str,
    broker_chat_id: str,
    cli_dir: Path,
) -> AgentMemoryWorker:
    cfg = MemoryAgentConfig(
        chat_id=broker_chat_id,
        broker_id=f"broker-{broker_chat_id}",
        namespace=namespace,
        session_log_mode="cli_init",
        cli_session_dir=cli_dir,
        broker_trace_stdout=False,
    )
    return AgentMemoryWorker(cfg)


def _stub_handle_w14_verify_fail_partial(
    self: AgentMemoryWorker,
    req: RuntimeRequestEnvelope,
) -> dict[str, object]:
    """
    TC-UC06 B: W14 invalid slice; нет ``memory.result.returned`` complete.

    Без stub complete; VERIFY журнала → partial (exit 1).
    """
    _uc_stub_journal_store(self, req).append(
        MemoryJournalRow(
            chat_id=req.chat_id,
            request_id="stub-w14-req",
            namespace=str(req.namespace or self._cfg.namespace),
            event_name="memory.slice.returned",
            summary="w14 stub",
            payload={"partial": True},
        ),
    )
    return {
        "ok": True,
        "payload": {
            "memory_slice": {
                "kind": "memory_slice",
                "schema": "memory.slice.v1",
                "level": "B",
                "reason": "w14_command_output_invalid",
                "w14_contract_failure": True,
                "partial": True,
            },
            "partial": True,
            "decision_summary": "w14 command output invalid: envelope",
            "recommended_next_step": "fix_memory_llm_json",
            "agent_memory_result": {
                "schema_version": "agent_memory_result.v1",
                "memory_continuation_required": False,
                "status": "partial",
            },
        },
    }


def _stub_handle_complete(
    self: AgentMemoryWorker,
    req: RuntimeRequestEnvelope,
) -> dict[str, object]:
    """Без live LLM: финальный complete (как task_2_2)."""
    _uc_stub_journal_store(self, req).append(
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


def test_uc01_memory_init_payload_has_memory_init_true_and_empty_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-01: payload — memory_init True, path пуст, goal не inspect path."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "x.py").write_text("x=1\n", encoding="utf-8")
    _apply_memory_init_isolation(tmp_path, monkeypatch)
    checked: dict[str, bool] = {}

    def _wrap(
        self: AgentMemoryWorker,
        req: RuntimeRequestEnvelope,
    ) -> dict[str, object]:
        if not checked:
            pl: dict[str, Any] = dict(req.payload or {})
            assert pl.get("memory_init") is True
            assert str(pl.get("path", "") or "").strip() == ""
            assert "path" not in pl or str(pl.get("path", "")).strip() == ""
            goal = str(pl.get("goal", "") or "").strip().lower()
            assert goal != "inspect path"
            assert MEMORY_INIT_CANONICAL_GOAL.lower() == goal
            sh = str(pl.get("memory_init_shadow_journal_path") or "").strip()
            assert sh.endswith(".journal.shadow.jsonl")
            checked["done"] = True
        return _stub_handle_complete(self, req)

    cli_dir = create_unique_cli_session_dir()
    bcid = "uc01-payload-chat"
    worker = _memory_init_stub_worker(
        namespace="ns-uc01-payload",
        broker_chat_id=bcid,
        cli_dir=cli_dir,
    )
    monkeypatch.setattr(AgentMemoryWorker, "handle", _wrap)
    invoke = _broker_invoke_worker(worker)
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=tmp_path / "memory-journal.jsonl",
        runtime_dir=tmp_path / "runtime",
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-uc01-payload",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    assert checked.get("done") is True


def test_uc01_pipeline_full_walk_sees_two_files_in_temp_project(
    tmp_path: Path,
) -> None:
    """
    UC-01: при memory_init и пустом explicit_paths walk даёт ≥2 relpath.

    Уровень наблюдаемости: прямой вызов ``_select_b_paths_for_w14`` с
    ``memory_init=True`` (LLM off не вызывает W14-runtime; см. task_3_1).
    """
    proj = tmp_path / "walkproj"
    proj.mkdir()
    (proj / "a").mkdir()
    (proj / "b").mkdir()
    (proj / "a" / "x.py").write_text("# a\n", encoding="utf-8")
    (proj / "b" / "y.py").write_text("# b\n", encoding="utf-8")
    mock_w = MagicMock()
    mock_w._cfg.namespace = "ns-walk"
    pl = AgentMemoryQueryPipeline(
        mock_w,
        MagicMock(enabled=False),
        MagicMock(),
    )
    limits = W14RuntimeLimits(
        max_turns=8,
        max_selected_b=32,
        max_c_per_b=4,
        max_total_c=64,
        max_reads_per_turn=4,
        max_summary_chars=4000,
        max_reason_chars=500,
        max_decision_chars=500,
        min_child_summary_coverage=0.0,
        summarize_c_llm_max_parallel=4,
    )
    selected = pl._select_b_paths_for_w14(
        root=proj.resolve(),
        goal=MEMORY_INIT_CANONICAL_GOAL,
        plan_obj={},
        explicit_paths=[],
        limits=limits,
        memory_init=True,
    )
    assert len(selected) >= 2
    norm = {str(p).replace("\\", "/") for p in selected}
    assert "a/x.py" in norm
    assert "b/y.py" in norm


def test_uc01_continuation_second_round_writes_complete_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-01: первый round continuation; второй — complete и exit 0."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("v=1\n", encoding="utf-8")
    _apply_memory_init_isolation(tmp_path, monkeypatch)
    call_n = {"i": 0}

    def _two_rounds(
        self: AgentMemoryWorker,
        req: RuntimeRequestEnvelope,
    ) -> dict[str, object]:
        call_n["i"] += 1
        n = call_n["i"]
        rid = f"stub-req-{n}"
        if n == 1:
            _uc_stub_journal_store(self, req).append(
                MemoryJournalRow(
                    chat_id=req.chat_id,
                    request_id=rid,
                    namespace=str(req.namespace or self._cfg.namespace),
                    event_name="memory.result.returned",
                    summary="stub-partial",
                    created_at="2026-05-01T10:00:00+00:00",
                    payload={
                        "query_id": "mem-stub-1",
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
                    "decision_summary": "r1",
                    "recommended_next_step": "more",
                    "agent_memory_result": {
                        "schema_version": "agent_memory_result.v1",
                        "memory_continuation_required": True,
                    },
                },
            }
        return _stub_handle_complete(self, req)

    cli_dir = create_unique_cli_session_dir()
    bcid = "uc01-cont-chat"
    worker = _memory_init_stub_worker(
        namespace="ns-uc01-cont",
        broker_chat_id=bcid,
        cli_dir=cli_dir,
    )
    monkeypatch.setattr(AgentMemoryWorker, "handle", _two_rounds)
    invoke = _broker_invoke_worker(worker)
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=tmp_path / "memory-journal.jsonl",
        runtime_dir=tmp_path / "runtime",
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-uc01-cont",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    assert call_n["i"] == 2


def test_uc02_final_summary_contains_labeled_metrics_and_compact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """UC-02: stderr — подписи D4, абсолютный compact_log=, status=."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "f.py").write_text("pass\n", encoding="utf-8")
    _apply_memory_init_isolation(tmp_path, monkeypatch)
    cli_dir = create_unique_cli_session_dir()
    bcid = "uc02-sum-chat"
    worker = _memory_init_stub_worker(
        namespace="ns-uc02-sum",
        broker_chat_id=bcid,
        cli_dir=cli_dir,
    )
    monkeypatch.setattr(AgentMemoryWorker, "handle", _stub_handle_complete)
    invoke = _broker_invoke_worker(worker)
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=tmp_path / "memory-journal.jsonl",
        runtime_dir=tmp_path / "runtime",
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-uc02-sum",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "compact_log=" in err
    assert re.search(r"status=(complete|partial|blocked)", err)
    assert "memory.why_llm:" in err
    assert "memory.pag_graph(node):" in err
    assert "memory.w14_graph_highlight:" in err
    assert "abort_reason=" not in err


def test_tc_uc06_summary_abort_reason_w14_on_partial_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """TC-UC06-SUMMARY: partial после W14; stderr с ``abort_reason=``."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "f.py").write_text("pass\n", encoding="utf-8")
    _apply_memory_init_isolation(tmp_path, monkeypatch)
    cli_dir = create_unique_cli_session_dir()
    bcid = "uc06-w14-chat"
    worker = _memory_init_stub_worker(
        namespace="ns-uc06-w14",
        broker_chat_id=bcid,
        cli_dir=cli_dir,
    )
    monkeypatch.setattr(
        AgentMemoryWorker,
        "handle",
        _stub_handle_w14_verify_fail_partial,
    )
    invoke = _broker_invoke_worker(worker)
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=tmp_path / "memory-journal.jsonl",
        runtime_dir=tmp_path / "runtime",
    )
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-uc06-w14",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "status=partial" in err
    assert "abort_reason=w14_command_output_invalid" in err


def test_uc02_final_summary_no_multiline_json_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """UC-02: нет multiline JSON envelope: ``{`` + NL + кавычка поля."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "f.py").write_text("pass\n", encoding="utf-8")
    _apply_memory_init_isolation(tmp_path, monkeypatch)
    cli_dir = create_unique_cli_session_dir()
    bcid = "uc02-noml-chat"
    worker = _memory_init_stub_worker(
        namespace="ns-uc02-noml",
        broker_chat_id=bcid,
        cli_dir=cli_dir,
    )
    monkeypatch.setattr(AgentMemoryWorker, "handle", _stub_handle_complete)
    invoke = _broker_invoke_worker(worker)
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=tmp_path / "memory-journal.jsonl",
        runtime_dir=tmp_path / "runtime",
    )
    MemoryInitOrchestrator(paths=paths).run(
        proj,
        "ns-uc02-noml",
        broker_invoke=invoke,
        broker_chat_id=bcid,
        cli_session_dir=cli_dir,
    )
    err = capsys.readouterr().err
    bad = re.search(r"\{\s*\n\s*\"", err)
    assert bad is None, "multiline JSON envelope proxy should not appear"


def test_uc02_compact_event_buckets_other_or_unknown(
    tmp_path: Path,
) -> None:
    """
    UC-02: неизвестный ``event=`` попадает в bucket ``other`` (task_2_1).

    Известная строка + кастомное событие вне whitelist labelled aggregation.
    """
    compact = tmp_path / "compact.log"
    lines = [
        (
            "timestamp=t1 init_session_id=s chat_id=c "
            "event=memory.why_llm x=1\n"
        ),
        (
            "timestamp=t2 init_session_id=s chat_id=c "
            "event=z_compact_unlisted_probe_event_zz\n"
        ),
    ]
    compact.write_text("".join(lines), encoding="utf-8")
    buf = io.StringIO()
    emit_memory_init_user_summary(
        compact,
        "complete",
        (1, 0, 0),
        out=buf,
    )
    text = buf.getvalue()
    assert "events_by_kind:" in text
    assert "memory.why_llm:" in text
    assert "other:" in text
    assert re.search(r"other:\s*[1-9]", text)


def test_uc03_cli_init_compact_and_legacy_paths_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-03: cli_init — ``ailit-cli-*`` с ``legacy.log`` и ``compact.log``."""
    log_root: Path = tmp_path / "chat_logs"
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_root))
    dbg = AgentMemoryChatDebugLog(
        _verbose_cfg(),
        session_log_mode="cli_init",
    )
    dbg.log_audit(
        raw_chat_id="uc03-chat",
        event="memory.init.layout",
        request_id="req-uc03",
        topic="uc03",
        body={"ok": True},
    )
    cmp_path = dbg.compact_log_path_for_write()
    assert cmp_path is not None
    one_line = (
        "timestamp=t init_session_id=i chat_id=c "
        "event=orch_memory_init_phase phase=prepare\n"
    )
    cmp_path.write_text(one_line, encoding="utf-8")
    cli_dirs: list[Path] = sorted(log_root.glob("ailit-cli-*"))
    assert len(cli_dirs) == 1
    assert (cli_dirs[0] / "legacy.log").is_file()
    assert (cli_dirs[0] / COMPACT_LOG_FILE_NAME).is_file()
