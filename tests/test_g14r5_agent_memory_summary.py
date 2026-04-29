"""
G14R.5: LLM summaries C и B, ``agent_memory_summary_service`` (G14R.5 W14).
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.agent_memory_runtime_contract import (
    AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
    AgentMemoryCommandName,
)
from agent_core.runtime.agent_memory_summary_service import (
    AgentMemorySummaryFingerprinting,
    AgentMemorySummaryService,
    SummarizeCNodeInputV1,
    SummarizeCLocator,
    W14CommandLimits,
)
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService


def _w14_out(
    *,
    command: str,
    command_id: str = "c1",
    status: str = "ok",
    payload: dict[str, object],
) -> str:
    o = {
        "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
        "command": command,
        "command_id": command_id,
        "status": status,
        "payload": payload,
        "decision_summary": "d",
        "violations": [],
    }
    return json.dumps(o, ensure_ascii=False)


def _open_store(
    path: Path,
) -> tuple[AgentMemorySummaryService, str]:
    store = SqlitePagStore(path)
    svc = AgentMemorySummaryService(PagGraphWriteService(store))
    return svc, "g14r5-test-ns"


def test_summarize_c_writes_summary_and_summary_fingerprint(
    tmp_path: Path,
) -> None:
    """
    C14R.2, G14R.5: после summarize_c в ноде summary и
    ``attrs['summary_fingerprint']``.
    """
    p = tmp_path / "p.sqlite3"
    svc, namespace = _open_store(p)
    c_id = "C:a.py:func:x"
    raw = "def x():\n  return 1"
    cfp0 = "stable-content-fp"
    gw = PagGraphWriteService(svc.store)
    _ = gw.upsert_node(
        namespace=namespace,
        node_id=c_id,
        level="C",
        kind="function",
        path="a.py",
        title="x",
        summary="",
        attrs={"content_fingerprint": cfp0},
        fingerprint="b_fp",
    )
    c_in = SummarizeCNodeInputV1(
        c_node_id=c_id,
        path="a.py",
        semantic_kind="function",
        text=raw,
        locator=SummarizeCLocator(start_line=1, end_line=4, symbol="x"),
    )
    sum_text = "x возвращает единицу"
    j = _w14_out(
        command=AgentMemoryCommandName.SUMMARIZE_C.value,
        payload={
            "summary": sum_text,
            "semantic_tags": ["t"],
            "important_lines": [],
            "claims": [],
            "refusal_reason": "",
        },
    )
    r = svc.apply_summarize_c(
        namespace=namespace,
        c_input=c_in,
        user_subgoal="понять",
        limits=W14CommandLimits(max_summary_chars=700, max_claims=8),
        command_id="cmd-c",
        query_id="q1",
        llm_json=j,
    )
    assert r.summary == sum_text
    n = svc.store.fetch_node(
        namespace=namespace, node_id=c_id,
    )
    assert n is not None
    assert n.summary == sum_text
    a = n.attrs
    sfp = str(a.get("summary_fingerprint", "") or "")
    assert sfp
    want = AgentMemorySummaryFingerprinting.c_summary_fingerprint(
        content_fingerprint=cfp0,
        summary_text=sum_text,
    )
    assert sfp == want
    # отпечаток смены summary ломается, если сменить текст
    other = want != AgentMemorySummaryFingerprinting.c_summary_fingerprint(
        content_fingerprint=cfp0,
        summary_text=sum_text + " ",
    )
    assert other is True


def test_summarize_b_file_uses_only_child_c_summaries(
    tmp_path: Path,
) -> None:
    """
    B-файл: вход summarize_b — только child.summary; не полный B text.
    """
    p = tmp_path / "p2.sqlite3"
    svc, namespace = _open_store(p)
    gw = PagGraphWriteService(svc.store)
    b_id = "B:src/secret.py"
    c1 = "C:src/secret.py:f1"
    c2 = "C:src/secret.py:f2"
    # «Полный файл» нигде не передаётся в W14 input — ловим утечку
    _full = "SECRET_FULL_FILE_BODY" + "x" * 3000
    for nid, t, s in (
        (c1, "a", "короткое 1"),
        (c2, "b", "короткое 2"),
    ):
        _ = gw.upsert_node(
            namespace=namespace,
            node_id=nid,
            level="C",
            kind="function",
            path="src/secret.py",
            title=t,
            summary=s,
            attrs={
                "summary_fingerprint": f"sf-{nid}",
            },
            fingerprint="cf",
        )
    _ = gw.upsert_node(
        namespace=namespace,
        node_id=b_id,
        level="B",
        kind="file",
        path="src/secret.py",
        title="secret",
        summary="",
        attrs={},
        fingerprint="b_fp0",
    )
    children = [
        svc.store.fetch_node(namespace=namespace, node_id=c1),
        svc.store.fetch_node(namespace=namespace, node_id=c2),
    ]
    assert all(x is not None for x in children)
    c_full_list = [c for c in children if c is not None]
    env = svc.build_summarize_b_input_envelope(
        command_id="x",
        query_id="q",
        b_node_id=b_id,
        path="src/secret.py",
        kind="file",
        child_nodes=c_full_list,
        user_subgoal="s",
        limits=W14CommandLimits(900, max_children=80),
    )
    sjson = json.dumps(
        env, ensure_ascii=False, sort_keys=True,
    )
    assert "SECRET_FULL_FILE_BODY" not in sjson
    # полный body не в envelope
    assert _full not in sjson
    b_out = _w14_out(
        command=AgentMemoryCommandName.SUMMARIZE_B.value,
        payload={
            "summary": "оба блока",
            "child_refs": [c1, c2],
            "missing_children": [],
            "confidence": 0.9,
            "refusal_reason": "",
        },
    )
    r = svc.apply_summarize_b(
        namespace=namespace,
        b_node_id=b_id,
        path="src/secret.py",
        kind="file",
        child_nodes=c_full_list,
        user_subgoal="s",
        limits=W14CommandLimits(900, max_children=80),
        command_id="x",
        query_id="q",
        llm_json=b_out,
    )
    assert "оба" in r.summary
    b_n = svc.store.fetch_node(
        namespace=namespace, node_id=b_id,
    )
    assert b_n is not None
    assert b_n.summary == "оба блока"


def test_summarize_b_directory_uses_child_b_or_c_summaries(
    tmp_path: Path,
) -> None:
    """
    B-папка: дочерний B и дочерний C — в envelope только их summary.
    """
    p = tmp_path / "p3.sqlite3"
    svc, namespace = _open_store(p)
    gw = PagGraphWriteService(svc.store)
    dir_b = "B:pkg"
    sub_b = "B:pkg/sub.py"
    c_only = "C:pkg/only:fn"
    _ = gw.upsert_node(
        namespace=namespace,
        node_id=sub_b,
        level="B",
        kind="file",
        path="pkg/sub.py",
        title="s",
        summary="sum-B-child",
        attrs={"summary_fingerprint": "b-ch-fp", "content_fingerprint": "x"},
        fingerprint="b1",
    )
    _ = gw.upsert_node(
        namespace=namespace,
        node_id=c_only,
        level="C",
        kind="function",
        path="pkg/only",
        title="f",
        summary="sum-c-only",
        attrs={"summary_fingerprint": "c-fp-1", "content_fingerprint": "y"},
        fingerprint="b2",
    )
    _ = gw.upsert_node(
        namespace=namespace,
        node_id=dir_b,
        level="B",
        kind="directory",
        path="pkg",
        title="pkg",
        summary="",
        attrs={},
        fingerprint="dir1",
    )
    ch: list[object] = [
        svc.store.fetch_node(namespace=namespace, node_id=sub_b),
        svc.store.fetch_node(namespace=namespace, node_id=c_only),
    ]
    assert ch[0] and ch[1]
    c_nodes = [x for x in ch if x is not None]
    lim = W14CommandLimits(900, max_children=80)
    env = svc.build_summarize_b_input_envelope(
        command_id="1",
        query_id="1",
        b_node_id=dir_b,
        path="pkg",
        kind="directory",
        child_nodes=c_nodes,
        user_subgoal="обзор",
        limits=lim,
    )
    s = json.dumps(
        env, ensure_ascii=False,
    )
    assert "sum-B-child" in s
    assert "sum-c-only" in s
    b_out = _w14_out(
        command=AgentMemoryCommandName.SUMMARIZE_B.value,
        payload={
            "summary": "каталог пакетов: файл и вспомогательная nода",
            "child_refs": [sub_b, c_only],
            "missing_children": [],
            "confidence": 0.85,
            "refusal_reason": "",
        },
    )
    r = svc.apply_summarize_b(
        namespace=namespace,
        b_node_id=dir_b,
        path="pkg",
        kind="directory",
        child_nodes=c_nodes,
        user_subgoal="",
        limits=lim,
        command_id="1",
        query_id="1",
        llm_json=b_out,
    )
    assert r.status == "ok"
    b_node = svc.store.fetch_node(
        namespace=namespace, node_id=dir_b,
    )
    assert b_node is not None
    assert "каталог" in b_node.summary


def test_b_summary_invalidates_when_child_summary_fingerprint_changes(
    tmp_path: Path,
) -> None:
    """
    C14R.2: смена дочернего ``summary_fingerprint`` — B summary устаревает.
    """
    p = tmp_path / "p4.sqlite3"
    svc, namespace = _open_store(p)
    gw = PagGraphWriteService(svc.store)
    b_id = "B:x.py"
    c1, c2 = "C:x.py:a", "C:x.py:b"
    for nid, t in ((c1, "a"), (c2, "b")):
        _ = gw.upsert_node(
            namespace=namespace,
            node_id=nid,
            level="C",
            kind="function",
            path="x.py",
            title=t,
            summary=f"sum {t}",
            attrs={
                "content_fingerprint": f"cp-{t}",
                "summary_fingerprint": f"sf-orig-{t}",
            },
            fingerprint="b",
        )
    _ = gw.upsert_node(
        namespace=namespace,
        node_id=b_id,
        level="B",
        kind="file",
        path="x.py",
        title="x",
        summary="B-old",
        attrs={},
        fingerprint="bfp",
    )
    kids = [
        svc.store.fetch_node(
            namespace=namespace, node_id=c1,
        ),
        svc.store.fetch_node(
            namespace=namespace, node_id=c2,
        ),
    ]
    kids2 = [k for k in kids if k is not None]
    lim = W14CommandLimits(500, max_children=80)
    b_json = _w14_out(
        command=AgentMemoryCommandName.SUMMARIZE_B.value,
        payload={
            "summary": "агрегат C",
            "child_refs": [c1, c2],
            "missing_children": [],
            "confidence": 1.0,
            "refusal_reason": "",
        },
    )
    _ = svc.apply_summarize_b(
        namespace=namespace,
        b_node_id=b_id,
        path="x.py",
        kind="file",
        child_nodes=kids2,
        user_subgoal="",
        limits=lim,
        command_id="c",
        query_id="q",
        llm_json=b_json,
    )
    b0 = svc.store.fetch_node(
        namespace=namespace, node_id=b_id,
    )
    assert b0 is not None
    current_basis0 = (
        AgentMemorySummaryService.compute_b_child_basis_from_nodes(
            kids2,
        )
    )
    assert not AgentMemorySummaryService.is_b_summary_stale(
        b_node=b0, current_child_basis=current_basis0,
    )
    c1n = svc.store.fetch_node(
        namespace=namespace, node_id=c1,
    )
    assert c1n is not None
    a1 = dict(
        c1n.attrs) if isinstance(c1n.attrs, dict) else {}
    a1["summary_fingerprint"] = "sf-CHANGED"
    # имитация пересчёта дочерней C после смены контента
    _ = gw.upsert_node(
        namespace=namespace,
        node_id=c1,
        level="C",
        kind="function",
        path="x.py",
        title="a",
        summary=c1n.summary,
        attrs=a1,
        fingerprint=c1n.fingerprint,
    )
    k_after = [
        svc.store.fetch_node(
            namespace=namespace, node_id=c1,
        ),
        svc.store.fetch_node(
            namespace=namespace, node_id=c2,
        ),
    ]
    k2 = [x for x in k_after if x is not None]
    new_basis = AgentMemorySummaryService.compute_b_child_basis_from_nodes(k2)
    assert new_basis != current_basis0
    b1 = svc.store.fetch_node(
        namespace=namespace, node_id=b_id,
    )
    assert b1 is not None
    assert AgentMemorySummaryService.is_b_summary_stale(
        b_node=b1, current_child_basis=new_basis,
    )
