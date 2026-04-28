"""PAG indexer (G7.2).

Implements: tree scan + Python C-level extraction + incremental sync.
"""

from __future__ import annotations

import ast
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.pag_graph_write_service import PagGraphWriteService
from agent_core.session.repo_context import (
    detect_repo_context,
    namespace_for_repo,
)


_DEFAULT_IGNORE_DIRS: tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
)

_DEFAULT_IGNORE_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
    ".o",
    ".obj",
    ".so",
    ".dll",
    ".dylib",
)


@dataclass(frozen=True, slots=True)
class PagIndexConfig:
    """Configuration for indexing a project into PAG."""

    project_root: Path
    db_path: Path
    full: bool = False
    max_files: int = 200_000
    max_bytes_per_file: int = 8_000_000


@dataclass(frozen=True, slots=True)
class ChangedRange:
    """Changed range for incremental sync."""

    path: str
    start_line: int
    end_line: int


class GitignoreMatcher:
    """Very small .gitignore matcher (subset) for MVP.

    Supports:
    - empty lines and comments
    - patterns with '*' and '?'
    - trailing '/' => directory ignore
    - leading '/' => anchored to repo root
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._rules = self._load_rules()

    def _load_rules(self) -> list[str]:
        p = self._root / ".gitignore"
        if not p.is_file():
            return []
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            lines = raw.splitlines()
        except OSError:
            return []
        out: list[str] = []
        for raw in lines:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("!"):
                # Negation is intentionally ignored in MVP.
                continue
            out.append(s)
        return out

    def is_ignored(self, rel_posix: str, *, is_dir: bool) -> bool:
        import fnmatch

        rel = rel_posix.strip().lstrip("./")
        if not rel:
            return False
        for pat in self._rules:
            anchored = pat.startswith("/")
            p = pat.lstrip("/")
            dir_only = p.endswith("/")
            p2 = p[:-1] if dir_only else p
            if dir_only and not is_dir:
                continue
            if anchored:
                if fnmatch.fnmatch(rel, p2):
                    return True
            else:
                # Unanchored: match anywhere on path components.
                if fnmatch.fnmatch(rel, p2) or fnmatch.fnmatch(
                    Path(rel).name,
                    p2,
                ):
                    return True
        return False


class PagIndexer:
    """Index a project root into SqlitePagStore."""

    def __init__(self, store: SqlitePagStore) -> None:
        self._store = store
        self._write = PagGraphWriteService(store)

    @staticmethod
    def default_db_path() -> Path:
        return Path("~/.ailit/pag/store.sqlite3").expanduser().resolve()

    def index_project(self, cfg: PagIndexConfig) -> str:
        root = cfg.project_root.resolve()
        ctx = detect_repo_context(root)
        ns = namespace_for_repo(
            repo_uri=ctx.repo_uri,
            repo_path=ctx.repo_path,
            branch=ctx.branch,
        )
        a_node_id = self._a_node_id(ctx)
        self._upsert_project_node(ns, a_node_id, ctx)

        matcher = GitignoreMatcher(root)
        files: list[str] = []
        dirs: list[str] = []
        for rel, is_dir in self._walk_relpaths(
            root,
            matcher=matcher,
            max_files=cfg.max_files,
        ):
            if is_dir:
                dirs.append(rel)
            else:
                files.append(rel)
        self._upsert_tree(ns, a_node_id, root, dirs=dirs, files=files)
        self._index_python_files(
            ns,
            root,
            files=files,
            max_bytes=cfg.max_bytes_per_file,
        )
        return ns

    def sync_changes(
        self,
        *,
        namespace: str,
        project_root: Path,
        changed_paths: Sequence[str],
        changed_ranges: Sequence[ChangedRange] = (),
        max_bytes_per_file: int = 8_000_000,
    ) -> None:
        """Incremental update: re-index B(file) and its C nodes/edges."""
        root = project_root.resolve()
        ns = str(namespace).strip()
        if not ns:
            return
        rels = [self._norm_rel(p) for p in changed_paths if self._norm_rel(p)]
        uniq = sorted(set(rels))
        _ = list(changed_ranges)
        for rel in uniq:
            abs_p = (root / rel).resolve()
            if not abs_p.exists():
                self._store.mark_stale(
                    namespace=ns,
                    node_ids=[self._b_node_id(rel)],
                )
                continue
            self._upsert_file_b_node(ns, root, rel)
            if abs_p.suffix.lower() == ".py":
                self._reindex_python_file(
                    ns,
                    root,
                    rel,
                    max_bytes=max_bytes_per_file,
                )

    def _reindex_python_file(
        self,
        ns: str,
        root: Path,
        rel: str,
        *,
        max_bytes: int,
    ) -> None:
        b_id = self._b_node_id(rel)
        self._store.delete_edges_touching_node_ids(
            namespace=ns,
            node_ids=[b_id],
        )
        self._store.delete_nodes_by_level_and_path(
            namespace=ns,
            level="C",
            path=rel,
        )
        self._index_python_files(ns, root, files=[rel], max_bytes=max_bytes)

    def _upsert_project_node(
        self,
        ns: str,
        a_node_id: str,
        ctx: object,
    ) -> None:
        from agent_core.session.repo_context import RepoContext

        rc = ctx if isinstance(ctx, RepoContext) else None
        attrs: dict[str, Any] = {}
        if rc is not None:
            attrs = {
                "repo_uri": rc.repo_uri,
                "branch": rc.branch,
                "commit": rc.commit,
                "default_branch": rc.default_branch,
                "repo_path": rc.repo_path,
                "namespace": ns,
                "staleness_state": "fresh",
            }
        fp = str(getattr(rc, "commit", None) or "") if rc is not None else ""
        if not fp:
            fp = "not_git"
        self._write.upsert_node(
            namespace=ns,
            node_id=a_node_id,
            level="A",
            kind="project",
            path=".",
            title=Path(getattr(rc, "repo_path", "") or ".").name,
            summary="PAG project",
            attrs=attrs,
            fingerprint=fp,
            staleness_state="fresh",
            source_contract="ailit_pag_store_v1",
        )

    @staticmethod
    def _a_node_id(ctx: object) -> str:
        repo_uri = str(getattr(ctx, "repo_uri", "") or "").strip()
        branch = str(getattr(ctx, "branch", "") or "").strip()
        repo_path = str(getattr(ctx, "repo_path", "") or "").strip()
        if repo_uri:
            b = f"@{branch}" if branch else ""
            return f"A:{repo_uri}{b}"
        return f"A:{repo_path or 'not_git'}"

    @staticmethod
    def _norm_rel(p: str) -> str:
        s = str(p or "").replace("\\", "/").strip().lstrip("./")
        return s

    @staticmethod
    def _b_node_id(rel: str) -> str:
        return f"B:{rel}"

    @staticmethod
    def _c_node_id(
        rel: str,
        kind: str,
        name: str,
        start: int,
        end: int,
    ) -> str:
        base = f"{rel}#{kind}:{name}:{start}:{end}"
        h = hashlib.sha1(
            base.encode("utf-8", errors="replace"),
        ).hexdigest()[:16]
        return f"C:{rel}#{h}"

    def _walk_relpaths(
        self,
        root: Path,
        *,
        matcher: GitignoreMatcher,
        max_files: int,
    ) -> Iterator[tuple[str, bool]]:
        seen = 0
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
            if rel_dir == ".":
                rel_dir = ""
            parts = [p for p in rel_dir.split("/") if p]
            if any(p in _DEFAULT_IGNORE_DIRS for p in parts):
                dirnames[:] = []
                continue
            if rel_dir:
                if matcher.is_ignored(rel_dir, is_dir=True):
                    dirnames[:] = []
                    continue
                yield (rel_dir, True)
            keep_dirs: list[str] = []
            for d in dirnames:
                if d in _DEFAULT_IGNORE_DIRS:
                    continue
                rel = f"{rel_dir}/{d}" if rel_dir else d
                if matcher.is_ignored(rel, is_dir=True):
                    continue
                keep_dirs.append(d)
            dirnames[:] = keep_dirs
            for fn in filenames:
                if fn.startswith(".") and fn not in (".gitignore",):
                    # Hidden files are skipped in MVP except .gitignore itself.
                    continue
                if fn.endswith(_DEFAULT_IGNORE_SUFFIXES):
                    continue
                rel = f"{rel_dir}/{fn}" if rel_dir else fn
                if matcher.is_ignored(rel, is_dir=False):
                    continue
                seen += 1
                if seen > max_files:
                    return
                yield (rel, False)

    def _upsert_tree(
        self,
        ns: str,
        a_node_id: str,
        root: Path,
        *,
        dirs: Sequence[str],
        files: Sequence[str],
    ) -> None:
        self._write.upsert_edge(
            namespace=ns,
            edge_id=self._edge_id(
                "containment",
                "contains",
                a_node_id,
                a_node_id,
            ),
            edge_class="containment",
            edge_type="contains",
            from_node_id=a_node_id,
            to_node_id=a_node_id,
            confidence=1.0,
            source_contract="ailit_pag_store_v1",
        )
        for d in sorted(set(dirs)):
            self._upsert_dir_b_node(ns, d)
        for f in sorted(set(files)):
            self._upsert_file_b_node(ns, root, f)
        for d in sorted(set(dirs)):
            parent = str(Path(d).parent.as_posix())
            if parent == ".":
                parent = ""
            from_id = a_node_id if not parent else self._b_node_id(parent)
            to_id = self._b_node_id(d)
            self._write.upsert_edge(
                namespace=ns,
                edge_id=self._edge_id(
                    "containment",
                    "contains",
                    from_id,
                    to_id,
                ),
                edge_class="containment",
                edge_type="contains",
                from_node_id=from_id,
                to_node_id=to_id,
                confidence=1.0,
                source_contract="ailit_pag_store_v1",
            )
        for f in sorted(set(files)):
            parent = str(Path(f).parent.as_posix())
            if parent == ".":
                parent = ""
            from_id = a_node_id if not parent else self._b_node_id(parent)
            to_id = self._b_node_id(f)
            self._write.upsert_edge(
                namespace=ns,
                edge_id=self._edge_id(
                    "containment",
                    "contains",
                    from_id,
                    to_id,
                ),
                edge_class="containment",
                edge_type="contains",
                from_node_id=from_id,
                to_node_id=to_id,
                confidence=1.0,
                source_contract="ailit_pag_store_v1",
            )

    def _upsert_dir_b_node(self, ns: str, rel_dir: str) -> None:
        nid = self._b_node_id(rel_dir)
        self._write.upsert_node(
            namespace=ns,
            node_id=nid,
            level="B",
            kind="dir",
            path=rel_dir,
            title=Path(rel_dir).name or ".",
            summary="Directory",
            attrs={"child_count": 0},
            fingerprint="dir",
            staleness_state="fresh",
            source_contract="ailit_pag_store_v1",
        )

    def _upsert_file_b_node(self, ns: str, root: Path, rel_file: str) -> None:
        p = (root / rel_file).resolve()
        st = p.stat()
        raw = p.read_bytes()
        h = hashlib.sha1(raw).hexdigest()
        lang = self._language_for(p)
        attrs = {
            "language": lang,
            "size_bytes": int(st.st_size),
            "mtime": float(st.st_mtime),
            "hash": h,
        }
        self._write.upsert_node(
            namespace=ns,
            node_id=self._b_node_id(rel_file),
            level="B",
            kind="file",
            path=rel_file,
            title=p.name,
            summary="File",
            attrs=attrs,
            fingerprint=h,
            staleness_state="fresh",
            source_contract="ailit_pag_store_v1",
        )

    def _index_python_files(
        self,
        ns: str,
        root: Path,
        *,
        files: Sequence[str],
        max_bytes: int,
    ) -> None:
        py_files = [f for f in files if f.lower().endswith(".py")]
        if not py_files:
            return
        module_to_rel = self._build_module_index(py_files)
        for rel in py_files:
            p = (root / rel).resolve()
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            if len(raw) > max_bytes:
                # Whole-file ingest (capped): decode with 'replace'.
                text = raw[:max_bytes].decode("utf-8", errors="replace")
                truncated = True
            else:
                text = raw.decode("utf-8", errors="replace")
                truncated = False
            self._index_python_file(
                ns,
                rel,
                text,
                module_to_rel=module_to_rel,
                truncated=truncated,
            )

    def _index_python_file(
        self,
        ns: str,
        rel: str,
        text: str,
        *,
        module_to_rel: Mapping[str, str],
        truncated: bool,
    ) -> None:
        b_id = self._b_node_id(rel)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        imports = self._py_imports(tree)
        symbols = self._py_top_level_symbols(tree)
        c_node_ids: list[str] = []
        for s in symbols:
            c_id = self._c_node_id(
                rel,
                s["kind"],
                s["name"],
                s["start"],
                s["end"],
            )
            c_node_ids.append(c_id)
            self._write.upsert_node(
                namespace=ns,
                node_id=c_id,
                level="C",
                kind=s["kind"],
                path=rel,
                title=s["name"],
                summary=f"{s['kind']} {s['name']}",
                attrs={
                    "name": s["name"],
                    "kind": s["kind"],
                    "start_line": s["start"],
                    "end_line": s["end"],
                    "truncated_source": bool(truncated),
                },
                fingerprint=f"{s['start']}:{s['end']}",
                staleness_state="fresh",
                source_contract="ailit_pag_store_v1",
            )
            self._write.upsert_edge(
                namespace=ns,
                edge_id=self._edge_id(
                    "containment",
                    "contains",
                    b_id,
                    c_id,
                ),
                edge_class="containment",
                edge_type="contains",
                from_node_id=b_id,
                to_node_id=c_id,
                confidence=1.0,
                source_contract="ailit_pag_store_v1",
            )
        for mod in imports:
            target = module_to_rel.get(mod)
            if target is None:
                continue
            to_b = self._b_node_id(target)
            self._write.upsert_edge(
                namespace=ns,
                edge_id=self._edge_id(
                    "cross_link",
                    "imports",
                    b_id,
                    to_b,
                ),
                edge_class="cross_link",
                edge_type="imports",
                from_node_id=b_id,
                to_node_id=to_b,
                confidence=0.6,
                source_contract="ailit_pag_store_v1",
            )

    @staticmethod
    def _py_imports(tree: ast.AST) -> list[str]:
        out: list[str] = []
        for node in getattr(tree, "body", []):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name:
                        out.append(n.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    out.append(node.module.split(".", 1)[0])
        return sorted(set(out))

    @staticmethod
    def _py_top_level_symbols(tree: ast.AST) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for node in getattr(tree, "body", []):
            if isinstance(node, ast.FunctionDef):
                out.append(_sym(node.name, "function", node))
            elif isinstance(node, ast.AsyncFunctionDef):
                out.append(_sym(node.name, "async_function", node))
            elif isinstance(node, ast.ClassDef):
                out.append(_sym(node.name, "class", node))
        return out

    @staticmethod
    def _build_module_index(py_files: Sequence[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for rel in py_files:
            p = Path(rel)
            if p.name == "__init__.py":
                mod = p.parent.as_posix().replace("/", ".")
            else:
                mod = p.with_suffix("").as_posix().replace("/", ".")
            if mod:
                out[mod.split(".", 1)[0]] = rel
        return out

    @staticmethod
    def _language_for(p: Path) -> str:
        suf = p.suffix.lower()
        if suf == ".py":
            return "python"
        if suf in (".md", ".markdown"):
            return "markdown"
        if suf in (".c", ".h", ".cpp", ".hpp", ".cc"):
            return "cpp"
        return suf.lstrip(".") or "unknown"

    @staticmethod
    def _edge_id(
        edge_class: str,
        edge_type: str,
        from_id: str,
        to_id: str,
    ) -> str:
        raw = f"{edge_class}:{edge_type}:{from_id}->{to_id}"
        h = hashlib.sha1(
            raw.encode("utf-8", errors="replace"),
        ).hexdigest()[:16]
        return f"e:{h}"


def _sym(name: str, kind: str, node: ast.AST) -> dict[str, Any]:
    start = int(getattr(node, "lineno", 1) or 1)
    end_raw = getattr(node, "end_lineno", None)
    end = int(end_raw) if end_raw is not None else start
    return {"name": str(name), "kind": str(kind), "start": start, "end": end}


def index_project_to_default_store(
    *,
    project_root: Path,
    db_path: Path | None = None,
    full: bool = False,
) -> str:
    """Convenience entrypoint for CLI (G7.2.4)."""
    store = SqlitePagStore(db_path or PagIndexer.default_db_path())
    idx = PagIndexer(store)
    cfg = PagIndexConfig(
        project_root=project_root,
        db_path=store.path,
        full=full,
    )
    return idx.index_project(cfg)
