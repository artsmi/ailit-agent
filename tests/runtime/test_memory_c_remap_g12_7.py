"""G12.7: semantic C remap + list_nodes_for_path."""

from __future__ import annotations

from pathlib import Path

from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.memory_c_remap import SemanticCRemapService
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService


def test_remap_python_function_by_name_after_line_shift(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite3"
    py = tmp_path / "mod.py"
    src = "\n" * 45 + "def moved() -> int:\n" "    return 7\n"
    py.write_text(src, encoding="utf-8")
    store = SqlitePagStore(db)
    ns = "ns-x"
    store.upsert_node(
        namespace=ns,
        node_id="B:mod.py",
        level="B",
        kind="file",
        path="mod.py",
        title="mod.py",
        summary="File",
        attrs={"hash": "x", "size_bytes": len(src.encode("utf-8"))},
        fingerprint="oldb",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
    )
    store.upsert_node(
        namespace=ns,
        node_id="C:mod#f1",
        level="C",
        kind="function",
        path="mod.py",
        title="moved",
        summary="fn",
        attrs={
            "name": "moved",
            "line_hint": {"start": 1, "end": 2},
        },
        fingerprint="oldc",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
    )
    found = store.list_nodes_for_path(namespace=ns, path="mod.py", level="C")
    assert len(found) == 1
    svc = SemanticCRemapService(PagGraphWriteService(store))
    res = svc.process_changes(
        namespace=ns,
        project_root=tmp_path,
        relative_paths=("mod.py",),
        graph_trace_hook=None,
    )
    assert res[0].updated == 1
    assert res[0].needs_llm_remap == 0
    c2 = store.fetch_node(namespace=ns, node_id="C:mod#f1")
    assert c2 is not None
    assert int(c2.attrs.get("line_hint", {}).get("start", 0) or 0) >= 40


def test_remap_markdown_section_by_title(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite3"
    md = tmp_path / "d.md"
    text = "intro\n\n" * 20 + "## SectionX\n\ntext\n"
    md.write_text(text, encoding="utf-8")
    store = SqlitePagStore(db)
    ns = "ns-md"
    store.upsert_node(
        namespace=ns,
        node_id="B:d.md",
        level="B",
        kind="file",
        path="d.md",
        title="d.md",
        summary="File",
        attrs={},
        fingerprint="b0",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
    )
    store.upsert_node(
        namespace=ns,
        node_id="C:md#1",
        level="C",
        kind="md_section",
        path="d.md",
        title="SectionX",
        summary="s",
        attrs={
            "name": "SectionX",
            "line_hint": {"start": 1, "end": 1},
            "semantic_locator": {
                "kind": "md_heading",
                "heading_path": ["SectionX"],
            },
        },
        fingerprint="c0",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
    )
    svc = SemanticCRemapService(PagGraphWriteService(store))
    res = svc.process_changes(
        namespace=ns,
        project_root=tmp_path,
        relative_paths=("d.md",),
        graph_trace_hook=None,
    )
    assert res[0].updated == 1
    c2 = store.fetch_node(namespace=ns, node_id="C:md#1")
    assert c2 is not None
    assert int(c2.attrs.get("line_hint", {}).get("start", 0) or 0) > 3
