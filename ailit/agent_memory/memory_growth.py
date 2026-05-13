"""Query-driven PAG growth for AgentMemory."""

from __future__ import annotations

import os
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

from agent_memory.sqlite_pag import PagGraphTraceFn

from agent_memory.pag_indexer import PagIndexer
from agent_memory.sqlite_pag import SqlitePagStore
from agent_memory.pag_graph_write_service import PagGraphWriteService
from agent_work.session.repo_context import (
    detect_repo_context,
    project_namespace_for_repo,
)

_ENTRYPOINT_NAMES: tuple[str, ...] = (
    "README.md",
    "pyproject.toml",
    "package.json",
    "ailit/ailit_cli/cli.py",
    "main.py",
    "app.py",
)
_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    },
)


# Источник выбранных relpath в MemoryExplorationPlanner (аудит chat_logs).
PATH_SEL_EXPLICIT: Final[str] = "explicit"
PATH_SEL_GOAL_TERMS: Final[str] = "goal_terms"
PATH_SEL_ENTRYPOINT: Final[str] = "entrypoint"
PATH_SEL_NONE: Final[str] = "none"


@dataclass(frozen=True, slots=True)
class PathSelectOutcome:
    """Результат select_paths: пути и источник выбора (для аудита)."""

    paths: tuple[str, ...]
    source: str
    non_matching_explicit: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QueryDrivenGrowthResult:
    """Result of one query-driven PAG growth attempt."""

    namespace: str
    selected_paths: tuple[str, ...]
    node_ids: tuple[str, ...]
    partial: bool
    reason: str
    path_selection_source: str = PATH_SEL_NONE
    non_matching_explicit_paths: tuple[str, ...] = ()


class MemoryExplorationPlanner:
    """Select minimal files for query-driven PAG indexing."""

    def __init__(
        self,
        *,
        max_walk_files: int = 2000,
        max_selected: int = 8,
    ) -> None:
        self._max_walk_files = max(1, int(max_walk_files))
        self._max_selected = max(1, int(max_selected))

    def select_paths(
        self,
        *,
        project_root: Path,
        goal: str,
        explicit_paths: Sequence[str] = (),
    ) -> PathSelectOutcome:
        """Return minimal relpaths and how they were chosen."""
        root = project_root.resolve()
        selected: list[str] = []
        non_matched: list[str] = []
        for raw in explicit_paths:
            rel = self._norm_rel(raw)
            if not rel:
                continue
            if self._is_file(root, rel):
                selected.append(rel)
            else:
                non_matched.append(rel)
        if selected:
            return PathSelectOutcome(
                paths=tuple(
                    dict.fromkeys(selected[: self._max_selected]),
                ),
                source=PATH_SEL_EXPLICIT,
                non_matching_explicit=tuple(non_matched),
            )

        terms = self._terms(goal)
        if terms:
            for rel in self._walk_files(root):
                path_l = rel.lower()
                name_l = Path(rel).name.lower()
                if any(t in path_l or t in name_l for t in terms):
                    selected.append(rel)
                    if len(selected) >= self._max_selected:
                        break
        if selected:
            return PathSelectOutcome(
                paths=tuple(dict.fromkeys(selected)),
                source=PATH_SEL_GOAL_TERMS,
                non_matching_explicit=tuple(non_matched),
            )

        for rel in _ENTRYPOINT_NAMES:
            if self._is_file(root, rel):
                selected.append(rel)
                if len(selected) >= min(3, self._max_selected):
                    break
        paths = tuple(dict.fromkeys(selected))
        return PathSelectOutcome(
            paths=paths,
            source=PATH_SEL_ENTRYPOINT if paths else PATH_SEL_NONE,
            non_matching_explicit=tuple(non_matched),
        )

    @staticmethod
    def _norm_rel(raw: str) -> str:
        return str(raw or "").replace("\\", "/").strip().lstrip("./")

    @staticmethod
    def _is_file(root: Path, rel: str) -> bool:
        try:
            p = (root / rel).resolve()
            p.relative_to(root)
        except ValueError:
            return False
        return p.is_file()

    @staticmethod
    def _terms(goal: str) -> tuple[str, ...]:
        out: list[str] = []
        for raw in str(goal or "").replace("\\", "/").split():
            token = raw.strip(".,:;()[]{}'\"`").lower()
            if len(token) >= 3:
                out.append(token)
        return tuple(dict.fromkeys(out))

    def _walk_files(self, root: Path) -> tuple[str, ...]:
        out: list[str] = []
        seen = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
            rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
            if rel_dir == ".":
                rel_dir = ""
            for filename in filenames:
                if filename.startswith(".") and filename != ".gitignore":
                    continue
                rel = f"{rel_dir}/{filename}" if rel_dir else filename
                out.append(rel)
                seen += 1
                if seen >= self._max_walk_files:
                    return tuple(out)
        return tuple(out)


class QueryDrivenPagGrowth:
    """Grow PAG by indexing only query-selected files."""

    def __init__(
        self,
        *,
        db_path: Path | None = None,
        planner: MemoryExplorationPlanner | None = None,
    ) -> None:
        self._store = SqlitePagStore(db_path or PagIndexer.default_db_path())
        self._write = PagGraphWriteService(self._store)
        self._indexer = PagIndexer(self._store)
        self._planner = planner or MemoryExplorationPlanner()

    def grow(
        self,
        *,
        project_root: Path,
        goal: str,
        explicit_paths: Sequence[str] = (),
        namespace: str | None = None,
        graph_trace_hook: PagGraphTraceFn | None = None,
    ) -> QueryDrivenGrowthResult:
        """Index only files selected for this memory query."""
        ctx = nullcontext()
        if graph_trace_hook is not None:
            ctx = self._store.graph_trace(graph_trace_hook)
        with ctx:
            return self._grow_impl(
                project_root=project_root,
                goal=goal,
                explicit_paths=explicit_paths,
                namespace=namespace,
            )

    def _grow_impl(
        self,
        *,
        project_root: Path,
        goal: str,
        explicit_paths: Sequence[str],
        namespace: str | None,
    ) -> QueryDrivenGrowthResult:
        root = project_root.resolve()
        ctx = detect_repo_context(root)
        ns = str(namespace or "").strip() or project_namespace_for_repo(
            repo_uri=ctx.repo_uri,
            repo_path=ctx.repo_path,
        )
        outcome = self._planner.select_paths(
            project_root=root,
            goal=goal,
            explicit_paths=explicit_paths,
        )
        selected = outcome.paths
        if not selected:
            return QueryDrivenGrowthResult(
                namespace=ns,
                selected_paths=(),
                node_ids=(),
                partial=True,
                reason="no_query_relevant_files",
                path_selection_source=outcome.source,
                non_matching_explicit_paths=outcome.non_matching_explicit,
            )
        self._ensure_project_node(namespace=ns, project_root=root)
        self._indexer.sync_changes(
            namespace=ns,
            project_root=root,
            changed_paths=selected,
        )
        self._ensure_edges_and_branch_attrs(
            namespace=ns,
            project_root=root,
            selected_paths=selected,
        )
        node_ids = tuple(f"B:{rel}" for rel in selected)
        return QueryDrivenGrowthResult(
            namespace=ns,
            selected_paths=selected,
            node_ids=node_ids,
            partial=False,
            reason="query_driven_sync",
            path_selection_source=outcome.source,
            non_matching_explicit_paths=outcome.non_matching_explicit,
        )

    def _ensure_project_node(
        self,
        *,
        namespace: str,
        project_root: Path,
    ) -> None:
        ctx = detect_repo_context(project_root)
        attrs = {
            "repo_uri": ctx.repo_uri,
            "repo_path": ctx.repo_path,
            "branch": ctx.branch,
            "commit": ctx.commit,
            "default_branch": ctx.default_branch,
            "namespace": namespace,
        }
        self._write.upsert_node(
            namespace=namespace,
            node_id=f"A:{namespace}",
            level="A",
            kind="project",
            path=".",
            title=project_root.name,
            summary="PAG project",
            attrs=attrs,
            fingerprint=str(ctx.commit or "not_git"),
            staleness_state="fresh",
            source_contract="ailit_pag_store_v1",
        )

    def _ensure_edges_and_branch_attrs(
        self,
        *,
        namespace: str,
        project_root: Path,
        selected_paths: Sequence[str],
    ) -> None:
        ctx = detect_repo_context(project_root)
        branch_key = ctx.branch or "__no_branch__"
        for rel in selected_paths:
            b_id = f"B:{rel}"
            self._write.upsert_edge(
                namespace=namespace,
                edge_id=f"containment:contains:A:{namespace}->{b_id}",
                edge_class="containment",
                edge_type="contains",
                from_node_id=f"A:{namespace}",
                to_node_id=b_id,
                confidence=1.0,
                source_contract="ailit_pag_store_v1",
            )
            node = self._store.fetch_node(namespace=namespace, node_id=b_id)
            if node is None:
                continue
            attrs = dict(node.attrs)
            by_branch = attrs.get("by_branch")
            if not isinstance(by_branch, dict):
                by_branch = {}
            by_branch[branch_key] = {
                "commit": ctx.commit,
                "file_hash": attrs.get("hash"),
                "summary": node.summary,
            }
            attrs["by_branch"] = by_branch
            attrs["last_seen_branch"] = ctx.branch
            attrs["last_seen_commit"] = ctx.commit
            self._write.upsert_node(
                namespace=namespace,
                node_id=node.node_id,
                level=node.level,
                kind=node.kind,
                path=node.path,
                title=node.title,
                summary=node.summary,
                attrs=attrs,
                fingerprint=node.fingerprint,
                staleness_state=node.staleness_state,
                source_contract=node.source_contract,
            )
