from __future__ import annotations

from pathlib import Path

from agent_memory.sqlite_pag import SqlitePagStore
from agent_memory.memory_growth import (
    MemoryExplorationPlanner,
    QueryDrivenPagGrowth,
)
from agent_work.session.repo_context import (
    detect_repo_context,
    project_namespace_for_repo,
)


def _namespace(root: Path) -> str:
    ctx = detect_repo_context(root)
    return project_namespace_for_repo(
        repo_uri=ctx.repo_uri,
        repo_path=ctx.repo_path,
    )


def test_planner_selects_explicit_path_without_scanning_all(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text(
        "def main():\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text(
        "def other():\n    pass\n",
        encoding="utf-8",
    )
    planner = MemoryExplorationPlanner(max_walk_files=1, max_selected=4)

    out = planner.select_paths(
        project_root=tmp_path,
        goal="unrelated",
        explicit_paths=("target.py",),
    )

    assert out.paths == ("target.py",)
    assert out.source == "explicit"


def test_planner_uses_entrypoint_seed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\n",
        encoding="utf-8",
    )
    (tmp_path / "huge.py").write_text(
        "def huge():\n    pass\n",
        encoding="utf-8",
    )

    out = MemoryExplorationPlanner().select_paths(
        project_root=tmp_path,
        goal="разберись что тут происходит",
    )

    assert out.paths == ("pyproject.toml",)
    assert out.source == "entrypoint"


def test_query_driven_growth_indexes_selected_path(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def selected() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text(
        "def skipped() -> int:\n    return 2\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "pag.sqlite3"

    result = QueryDrivenPagGrowth(db_path=db_path).grow(
        project_root=tmp_path,
        goal="target",
        explicit_paths=("target.py",),
    )

    ns = _namespace(tmp_path)
    store = SqlitePagStore(db_path)
    assert result.partial is False
    assert result.selected_paths == ("target.py",)
    assert result.path_selection_source == "explicit"
    assert store.fetch_node(namespace=ns, node_id="B:target.py") is not None
    assert store.fetch_node(namespace=ns, node_id=f"A:{ns}") is not None
    assert store.fetch_node(namespace=ns, node_id="B:other.py") is None
    b_node = store.fetch_node(namespace=ns, node_id="B:target.py")
    assert b_node is not None
    assert "by_branch" in b_node.attrs
    c_nodes = store.list_nodes(namespace=ns, level="C")
    assert c_nodes
    assert all(node.path == "target.py" for node in c_nodes)


def test_query_driven_growth_uses_request_namespace(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def selected() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "pag.sqlite3"

    result = QueryDrivenPagGrowth(db_path=db_path).grow(
        project_root=tmp_path,
        goal="target",
        explicit_paths=("target.py",),
        namespace="custom-ns",
    )

    store = SqlitePagStore(db_path)
    assert result.namespace == "custom-ns"
    assert store.fetch_node(namespace="custom-ns", node_id="A:custom-ns")
    assert store.fetch_node(namespace="custom-ns", node_id="B:target.py")
    assert (
        store.fetch_node(namespace=_namespace(tmp_path), node_id="B:target.py")
        is None
    )
