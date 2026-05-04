"""TC-2_1: MemoryInitTransaction — snapshot, lock, ABORT, journal shadow."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from agent_core.memory.sqlite_kb import SqliteKb
from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.memory_init_transaction import (
    MemoryInitPaths,
    MemoryInitTransaction,
    namespace_has_durable_graph_materialization,
)
from agent_core.runtime.memory_journal import (
    MemoryJournalRow,
    MemoryJournalStore,
)
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService


def _seed_pag_ns(db: Path, namespace: str, n_nodes: int) -> None:
    store = SqlitePagStore(db)
    w = PagGraphWriteService(store)
    for i in range(n_nodes):
        w.upsert_node(
            namespace=namespace,
            node_id=f"A:{i}",
            level="A",
            kind="project",
            path=".",
            title=f"t{i}",
            summary="s",
            attrs={},
            fingerprint=f"f{i}",
        )


def _count_pag_ns(db: Path, namespace: str) -> int:
    return SqlitePagStore(db).count_nodes(namespace=namespace)


def _journal_has_complete_result(*, journal_path: Path, chat_id: str) -> bool:
    store = MemoryJournalStore(journal_path)
    for row in store.filter_rows(
        chat_id=chat_id,
        event_name="memory.result.returned",
    ):
        st = str(row.payload.get("status", "") or "")
        if st == "complete":
            return True
    return False


def test_tc_2_1_abort_restore_pag_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-2_1-ABORT: abort не трогает PAG/KB (инкрементальный init)."""
    runtime = tmp_path / "rt"
    pag = tmp_path / "pag.sqlite3"
    kb = tmp_path / "kb.sqlite3"
    journal = tmp_path / "mem.jsonl"
    ns = "ns-restore"
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(pag))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(kb))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(journal))
    _seed_pag_ns(pag, ns, 3)
    SqliteKb(kb).write(
        record_id="r1",
        kind="note",
        scope="s",
        namespace=ns,
        title="x",
        summary="y",
        body="z",
    )
    before_pag = pag.read_bytes()
    before_kb = kb.read_bytes()
    assert namespace_has_durable_graph_materialization(
        pag_db_path=pag,
        kb_db_path=kb,
        pag_namespace_key=ns,
    )
    paths = MemoryInitPaths(
        pag_db=pag,
        kb_db=kb,
        journal_canonical=journal,
        runtime_dir=runtime,
    )
    tx = MemoryInitTransaction(
        init_session_id=str(uuid.uuid4()),
        chat_id=str(uuid.uuid4()),
        pag_namespace_key=ns,
        paths=paths,
    )
    tx.phase_prepare()
    assert _count_pag_ns(pag, ns) == 3
    tx.phase_execute_destructive_namespace_clear()
    assert _count_pag_ns(pag, ns) == 3
    tx.phase_abort()
    assert pag.read_bytes() == before_pag
    assert kb.read_bytes() == before_kb
    assert _count_pag_ns(pag, ns) == 3


def test_tc_2_1_first_init_clean_partial_on_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-2_1-FIRST-INIT: пустой store; partial write; ABORT не чистит PAG."""
    runtime = tmp_path / "rt2"
    pag = tmp_path / "p2.sqlite3"
    kb = tmp_path / "k2.sqlite3"
    journal = tmp_path / "m2.jsonl"
    ns = "ns-fresh"
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(pag))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(kb))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(journal))
    SqlitePagStore(pag)
    assert not namespace_has_durable_graph_materialization(
        pag_db_path=pag,
        kb_db_path=kb,
        pag_namespace_key=ns,
    )
    paths = MemoryInitPaths(
        pag_db=pag,
        kb_db=kb,
        journal_canonical=journal,
        runtime_dir=runtime,
    )
    tx = MemoryInitTransaction(
        init_session_id=str(uuid.uuid4()),
        chat_id=str(uuid.uuid4()),
        pag_namespace_key=ns,
        paths=paths,
    )
    tx.phase_prepare()
    tx.phase_execute_destructive_namespace_clear()
    w = PagGraphWriteService(SqlitePagStore(pag))
    w.upsert_node(
        namespace=ns,
        node_id="A:partial",
        level="A",
        kind="project",
        path=".",
        title="p",
        summary="s",
        attrs={},
        fingerprint="fp",
    )
    assert _count_pag_ns(pag, ns) == 1
    tx.phase_abort()
    assert _count_pag_ns(pag, ns) == 1


def test_tc_2_1_journal_no_false_complete_after_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-2_1-JOURNAL: ABORT drops shadow; primary has no false complete."""
    runtime = tmp_path / "rt3"
    pag = tmp_path / "p3.sqlite3"
    kb = tmp_path / "k3.sqlite3"
    primary = tmp_path / "primary.jsonl"
    ns = "ns-j"
    chat_id = "chat-journal-1"
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(pag))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(kb))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(primary))
    SqlitePagStore(pag)
    paths = MemoryInitPaths(
        pag_db=pag,
        kb_db=kb,
        journal_canonical=primary,
        runtime_dir=runtime,
    )
    tx = MemoryInitTransaction(
        init_session_id=str(uuid.uuid4()),
        chat_id=chat_id,
        pag_namespace_key=ns,
        paths=paths,
    )
    tx.phase_prepare()
    tx.journal_store_shadow().append(
        MemoryJournalRow(
            chat_id=chat_id,
            event_name="memory.result.returned",
            request_id="r1",
            namespace=ns,
            summary="x",
            payload={"status": "complete", "query_id": "q"},
        ),
    )
    shadow = tx.shadow_journal_path
    assert shadow is not None
    assert _journal_has_complete_result(journal_path=shadow, chat_id=chat_id)
    prim_empty = (
        not primary.exists()
        or primary.read_text(encoding="utf-8").strip() == ""
    )
    assert prim_empty
    tx.phase_abort()
    assert not shadow.exists()
    assert not _journal_has_complete_result(
        journal_path=primary,
        chat_id=chat_id,
    )


def test_tc_2_1_commit_merges_shadow_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shadow lines append to primary on COMMIT."""
    runtime = tmp_path / "rt4"
    pag = tmp_path / "p4.sqlite3"
    kb = tmp_path / "k4.sqlite3"
    primary = tmp_path / "pri.jsonl"
    ns = "ns-c"
    chat_id = "c-merge"
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(pag))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(kb))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(primary))
    SqlitePagStore(pag)
    paths = MemoryInitPaths(
        pag_db=pag,
        kb_db=kb,
        journal_canonical=primary,
        runtime_dir=runtime,
    )
    tx = MemoryInitTransaction(
        init_session_id=str(uuid.uuid4()),
        chat_id=chat_id,
        pag_namespace_key=ns,
        paths=paths,
    )
    tx.phase_prepare()
    tx.journal_store_shadow().append(
        MemoryJournalRow(
            chat_id=chat_id,
            event_name="memory.runtime.step",
            request_id="r0",
            namespace=ns,
            summary="s",
            payload={"step_id": "1"},
        ),
    )
    tx.phase_execute_destructive_namespace_clear()
    tx.phase_verify(True)
    tx.phase_commit()
    rows = list(MemoryJournalStore(primary).filter_rows(chat_id=chat_id))
    assert len(rows) == 1
    assert rows[0].event_name == "memory.runtime.step"
