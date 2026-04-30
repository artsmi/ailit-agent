"""
G14R.7: agent_memory_result.v1 (c_summary, read_lines, b_path) и гранты.
План: plan/14-agent-memory-runtime.md §G14R.7.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.agent_memory_result_assembly import (
    FinishDecisionResultAssembler,
)
from agent_core.runtime.agent_memory_result_v1 import (
    FIX_MEMORY_LLM_JSON_STEP,
    build_agent_memory_result_v1,
    resolve_memory_continuation_required,
)
from agent_core.runtime.models import (
    MemoryGrant,
    MemoryGrantRange,
)
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService
from agent_core.tool_runtime.memory_grants import MemoryGrantChecker
from agent_core.tool_runtime.multi_root_paths import (
    validate_agent_memory_relative_path,
)


def test_memory_result_contains_c_summary_without_raw_b_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """c_summary берётся из summary C-ноды PAG, не из сырого текста файла."""
    db = tmp_path / "p.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    root = tmp_path / "proj"
    root.mkdir()
    big = root / "big.txt"
    big.write_text("X" * 12_000, encoding="utf-8")
    ns = "ns-g14r7"
    cid = "C:big.txt:chunk1"
    store = SqlitePagStore(db)
    gw = PagGraphWriteService(store)
    gw.upsert_node(
        namespace=ns,
        node_id=cid,
        level="C",
        kind="chunk",
        path="big.txt",
        title="chunk",
        summary="кратко: только суть фрагмента",
        attrs={"start_line": 1, "end_line": 3},
        fingerprint="fp1",
        staleness_state="fresh",
        source_contract="test",
    )
    asm = FinishDecisionResultAssembler(
        project_root=root,
        namespace=ns,
        store=store,
    )
    results, rejects = asm.assemble_finish_decision_results(
        [
            {
                "kind": "c_summary",
                "path": "big.txt",
                "node_id": cid,
                "reason": "explain",
            },
        ],
    )
    assert not rejects
    assert len(results) == 1
    assert results[0]["kind"] == "c_summary"
    summ = str(results[0].get("summary") or "")
    assert "кратко" in summ
    assert "X" * 100 not in summ
    amr = build_agent_memory_result_v1(
        query_id="q1",
        status="complete",
        memory_slice=None,
        partial=False,
        decision_summary="d",
        recommended_next_step="",
        explicit_results=results,
        explicit_status="complete",
    )
    assert amr["results"][0]["summary"] == summ
    assert amr["results"][0]["read_lines"] == []


def test_memory_result_read_lines_are_granted_ranges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_lines: MemoryGrantChecker принимает те же line ranges."""
    db = tmp_path / "p2.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    root = tmp_path / "prj"
    root.mkdir()
    f = root / "a.py"
    f.write_text(
        "\n".join(f"line {i}" for i in range(1, 21)),
        encoding="utf-8",
    )
    ns = "ns2"
    cid = "C:a.py:fn"
    store = SqlitePagStore(db)
    gw = PagGraphWriteService(store)
    gw.upsert_node(
        namespace=ns,
        node_id=cid,
        level="C",
        kind="function",
        path="a.py",
        title="f",
        summary="s",
        attrs={"start_line": 2, "end_line": 5},
        fingerprint="fp",
        staleness_state="fresh",
        source_contract="test",
    )
    asm = FinishDecisionResultAssembler(
        project_root=root,
        namespace=ns,
        store=store,
    )
    results, _rej = asm.assemble_finish_decision_results(
        [
            {
                "kind": "read_lines",
                "path": "a.py",
                "node_id": cid,
                "reason": "check",
            },
        ],
    )
    assert len(results) == 1
    rl = results[0]["read_lines"]
    assert isinstance(rl, list) and len(rl) == 1
    sl = int(rl[0]["start_line"])
    el = int(rl[0]["end_line"])
    grants = [
        MemoryGrant(
            grant_id="g1",
            issued_by="t",
            issued_to="u",
            namespace=ns,
            path="a.py",
            ranges=(
                MemoryGrantRange(
                    start_line=sl,
                    end_line=el,
                ),
            ),
            whole_file=False,
            reason="q",
            expires_at="2099-01-01T00:00:00Z",
        ),
    ]
    chk = MemoryGrantChecker(grants)
    for seg in rl:
        off = int(seg["start_line"])
        lim = int(seg["end_line"]) - int(seg["start_line"]) + 1
        res = chk.check_read_file(
            path="a.py",
            offset_line=off,
            limit_line=lim,
        )
        assert res.ok is True


def test_memory_result_rejects_absolute_and_parent_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A14R.9: абсолют / ``..``; невалидные пути отбрасываются при сборке."""
    assert validate_agent_memory_relative_path("/tmp/x") is None
    assert validate_agent_memory_relative_path("../p") is None
    assert validate_agent_memory_relative_path("a/../b") is None
    assert validate_agent_memory_relative_path("src/ok.py") == "src/ok.py"
    db = tmp_path / "prej.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    root = tmp_path / "rroot"
    root.mkdir()
    store = SqlitePagStore(db)
    asm = FinishDecisionResultAssembler(
        project_root=root,
        namespace="nsR",
        store=store,
    )
    res, rej = asm.assemble_finish_decision_results(
        [
            {
                "kind": "b_path",
                "path": "/etc/passwd",
                "node_id": "B:x",
                "reason": "",
            },
            {
                "kind": "b_path",
                "path": "valid/place.py",
                "node_id": "B:valid",
                "reason": "ok",
            },
        ],
    )
    assert len(res) == 1
    assert res[0]["path"] == "valid/place.py"
    assert len(rej) >= 1


def test_create_file_subgoal_may_return_b_path_without_c_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """b_path: ``c_node_id`` null, без C-текста."""
    db = tmp_path / "p3.sqlite3"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    root = tmp_path / "pr"
    root.mkdir()
    store = SqlitePagStore(db)
    asm = FinishDecisionResultAssembler(
        project_root=root,
        namespace="ns3",
        store=store,
    )
    results, _ = asm.assemble_finish_decision_results(
        [
            {
                "kind": "b_path",
                "path": "new/module.py",
                "node_id": "B:ignored",
                "reason": "create file here",
            },
        ],
    )
    assert len(results) == 1
    r0 = results[0]
    assert r0["kind"] == "b_path"
    assert r0["c_node_id"] is None
    assert r0["summary"] is None
    assert r0["read_lines"] == []


def test_am_assembly_memory_continuation_required_shape() -> None:
    """Поле ``memory_continuation_required`` добавляется только если задано."""
    base = dict(
        query_id="q-shape",
        status="complete",
        memory_slice=None,
        partial=False,
        decision_summary="d",
        recommended_next_step="",
    )
    omit = build_agent_memory_result_v1(
        **base,
        memory_continuation_required=None,
    )
    assert "memory_continuation_required" not in omit
    on = build_agent_memory_result_v1(
        **base,
        memory_continuation_required=True,
    )
    assert on.get("memory_continuation_required") is True
    off = build_agent_memory_result_v1(
        **base,
        memory_continuation_required=False,
    )
    assert off.get("memory_continuation_required") is False


def test_am_result_uc03_terminal_blocked_diagnostic_memory_continuation_not_required() -> None:  # noqa: E501
    """UC-03: терминальные ветки не задают continuation True."""
    assert (
        resolve_memory_continuation_required(
            w14_contract_failure=True,
            pipeline_recommended_next_step="",
            am_v1_status="partial",
            w14_finish=True,
            final_partial=True,
        )
        is None
    )
    assert (
        resolve_memory_continuation_required(
            w14_contract_failure=False,
            pipeline_recommended_next_step=FIX_MEMORY_LLM_JSON_STEP,
            am_v1_status="partial",
            w14_finish=True,
            final_partial=True,
        )
        is None
    )
    assert (
        resolve_memory_continuation_required(
            w14_contract_failure=False,
            pipeline_recommended_next_step="retry",
            am_v1_status="blocked",
            w14_finish=True,
            final_partial=True,
        )
        is None
    )


def test_am_result_uc04_machine_requires_second_query_sets_memory_continuation_required() -> None:  # noqa: E501
    """UC-04: partial W14 + finish — сигнал второго запроса."""
    assert (
        resolve_memory_continuation_required(
            w14_contract_failure=False,
            pipeline_recommended_next_step="next w14 step",
            am_v1_status="partial",
            w14_finish=True,
            final_partial=True,
        )
        is True
    )
    assert (
        resolve_memory_continuation_required(
            w14_contract_failure=False,
            pipeline_recommended_next_step="next w14 step",
            am_v1_status="complete",
            w14_finish=True,
            final_partial=True,
        )
        is None
    )
