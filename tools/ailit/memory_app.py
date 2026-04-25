"""Streamlit GUI: `ailit memory` (workflow arch-graph-7, G7.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from agent_core.memory.pag_indexer import PagIndexer
from agent_core.memory.sqlite_pag import PagNode, SqlitePagStore
from ailit.memory_export import build_dot_for_slice, build_pag_export


class _MemoryPageState:
    """Keys in streamlit session_state."""

    DB_PATH = "ailit_memory_db_path"
    NAMESPACE = "ailit_memory_namespace"
    SELECTED_NODE_ID = "ailit_memory_selected_node_id"
    FILTER = "ailit_memory_filter"


def _default_db_path() -> str:
    return str(PagIndexer.default_db_path())


def _store_from_state() -> SqlitePagStore:
    db_val = st.session_state.get(_MemoryPageState.DB_PATH, "")
    db_raw = str(db_val or "").strip()
    if db_raw:
        db_path = Path(db_raw).expanduser().resolve()
    else:
        db_path = Path(_default_db_path())
    return SqlitePagStore(db_path)


def _projects_options(store: SqlitePagStore) -> list[PagNode]:
    return store.list_projects(limit=200)


def _render_sidebar(store: SqlitePagStore) -> tuple[str | None, str]:
    st.sidebar.markdown("### ailit memory")
    st.sidebar.text_input(
        "PAG sqlite db",
        key=_MemoryPageState.DB_PATH,
        value=str(st.session_state.get(_MemoryPageState.DB_PATH) or "")
        or _default_db_path(),
        help="По умолчанию: ~/.ailit/pag/store.sqlite3",
    )
    projects = _projects_options(store)
    if not projects:
        st.sidebar.info(
            "Нет проектов в PAG. Сначала сделайте `ailit memory index`."
        )
        return None, ""
    labels = [f"{p.namespace} · {p.title}" for p in projects]
    ns_by_idx = [p.namespace for p in projects]
    cur_ns = str(
        st.session_state.get(_MemoryPageState.NAMESPACE, "") or ""
    ).strip()
    if cur_ns in ns_by_idx:
        idx = ns_by_idx.index(cur_ns)
    else:
        idx = 0
    pick = st.sidebar.selectbox(
        "Проект (namespace)",
        options=list(range(len(projects))),
        format_func=lambda i: labels[int(i)],
        index=idx,
        key="ailit_memory_ns_pick_idx",
    )
    ns = ns_by_idx[int(pick)]
    st.session_state[_MemoryPageState.NAMESPACE] = ns
    flt = st.sidebar.text_input(
        "Фильтр узлов (path/title содержит)",
        key=_MemoryPageState.FILTER,
        value=str(
            st.session_state.get(_MemoryPageState.FILTER) or ""
        ).strip(),
    )
    return ns, str(flt or "")


def _node_matches_filter(n: PagNode, flt: str) -> bool:
    if not flt:
        return True
    f = flt.lower()
    path_ok = (n.path or "").lower().find(f) >= 0
    title_ok = (n.title or "").lower().find(f) >= 0
    return bool(path_ok or title_ok)


def _pick_default_node_id(nodes: list[PagNode]) -> str | None:
    for n in nodes:
        if n.level == "A":
            return n.node_id
    return nodes[0].node_id if nodes else None


def _render_node_tree(
    *,
    nodes_b: list[PagNode],
    selected_id: str | None,
    flt: str,
) -> str | None:
    st.markdown("#### Дерево (B-level)")
    dirs = [n for n in nodes_b if n.kind == "dir"]
    files = [n for n in nodes_b if n.kind == "file"]
    shown_dirs = [n for n in dirs if _node_matches_filter(n, flt)]
    shown_files = [n for n in files if _node_matches_filter(n, flt)]

    st.caption(f"dir={len(shown_dirs)} · file={len(shown_files)}")
    picked: str | None = None

    with st.expander("Папки", expanded=False):
        for n in sorted(shown_dirs, key=lambda x: x.path):
            lab = n.path or n.title or n.node_id
            if st.button(lab, key=f"mem_pick_{n.node_id}"):
                picked = n.node_id
    with st.expander("Файлы", expanded=True):
        for n in sorted(shown_files, key=lambda x: x.path):
            lab = n.path or n.title or n.node_id
            if st.button(lab, key=f"mem_pick_{n.node_id}"):
                picked = n.node_id
    if picked is None:
        return selected_id
    return picked


def _render_node_panel(
    *,
    store: SqlitePagStore,
    namespace: str,
    selected_node_id: str,
) -> None:
    node = store.fetch_node(namespace=namespace, node_id=selected_node_id)
    if node is None:
        st.warning("Узел не найден (возможно stale).")
        return
    st.markdown("#### Узел")
    st.markdown(
        f"- **node_id**: `{node.node_id}`\n"
        f"- **level**: `{node.level}`\n"
        f"- **kind**: `{node.kind}`\n"
        f"- **path**: `{node.path}`\n"
        f"- **title**: `{node.title}`\n"
        f"- **staleness**: `{node.staleness_state}`\n"
        f"- **updated_at**: `{node.updated_at}`"
    )
    if node.summary.strip():
        st.caption(node.summary.strip())
    with st.expander("attrs (JSON)", expanded=True):
        st.json(node.attrs)


def _render_neighbors(
    *,
    store: SqlitePagStore,
    namespace: str,
    selected_node_id: str,
) -> None:
    st.markdown("#### Соседи (edges)")
    edges = store.list_edges_touching(
        namespace=namespace,
        node_ids=[selected_node_id],
        limit=2000,
    )
    if not edges:
        st.caption("Нет рёбер.")
        return
    out_rows: list[dict[str, Any]] = []
    for e in edges:
        out_rows.append(
            {
                "edge_type": e.edge_type,
                "edge_class": e.edge_class,
                "from": e.from_node_id,
                "to": e.to_node_id,
                "confidence": e.confidence,
            }
        )
    st.dataframe(out_rows, use_container_width=True, hide_index=True)


def main() -> None:
    """Streamlit entrypoint."""
    st.set_page_config(
        page_title="ailit memory",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    store = _store_from_state()
    ns, flt = _render_sidebar(store)
    st.markdown("### ailit memory")
    if ns is None:
        st.info("Сначала: `ailit memory index --project-root PATH`.")
        return

    nodes_all = store.list_nodes(namespace=ns, level=None, limit=50_000)
    if not nodes_all:
        st.info("В этом namespace пока нет узлов. Запустите индексацию.")
        return
    nodes_b = [n for n in nodes_all if n.level == "B"]
    nodes_a = [n for n in nodes_all if n.level == "A"]
    default_selected = _pick_default_node_id(nodes_a) or _pick_default_node_id(
        nodes_b,
    )
    selected = str(
        st.session_state.get(
            _MemoryPageState.SELECTED_NODE_ID,
            default_selected,
        )
        or default_selected
        or ""
    ).strip()
    if not selected:
        st.warning("Не удалось выбрать узел по умолчанию.")
        return

    col_l, col_r = st.columns([1, 2])
    with col_l:
        picked = _render_node_tree(
            nodes_b=nodes_b,
            selected_id=selected,
            flt=flt,
        )
        if picked and picked != selected:
            st.session_state[_MemoryPageState.SELECTED_NODE_ID] = picked
            selected = picked
    with col_r:
        _render_node_panel(
            store=store,
            namespace=ns,
            selected_node_id=selected,
        )
        st.divider()
        _render_neighbors(
            store=store,
            namespace=ns,
            selected_node_id=selected,
        )
        st.divider()
        st.markdown("#### Граф (DOT slice)")
        dot = build_dot_for_slice(
            store=store,
            namespace=ns,
            center_node_id=selected,
            max_edges=200,
        )
        st.graphviz_chart(dot)

    st.divider()
    st.markdown("#### Экспорт")
    exp = build_pag_export(store=store, namespace=ns)
    st.download_button(
        "Export JSON",
        data=exp.to_json() + "\n",
        file_name=f"pag-{ns}.json",
        mime="application/json",
        use_container_width=False,
        key="ailit_memory_export_json_btn",
    )


if __name__ == "__main__":
    main()
