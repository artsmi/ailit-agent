"""Runtime PAG adapter for SessionRunner (G7.4).

This module provides an in-process "AgentMemory" facade for the persisted PAG
store built by the indexer (G7.1/G7.2). The goal is pragmatic:
- inject a small PAG slice into the model context before raw grep/read;
- emit structured telemetry events about PAG usage and fallbacks;
- sync PAG after successful write_file operations.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from agent_core.memory.pag_indexer import ChangedRange, PagIndexer
from agent_core.memory.sqlite_pag import PagEdge, PagNode, SqlitePagStore


_WORD_RE = re.compile(r"[A-Za-zА-Яа-я0-9_./-]{2,}")


def _truthy_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return bool(default)
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return bool(default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


@dataclass(frozen=True, slots=True)
class PagRuntimeConfig:
    """Runtime config for PAG integration."""

    enabled: bool
    db_path: Path
    top_k_files: int = 12
    max_chars: int = 2400
    sync_on_write_file: bool = True

    @staticmethod
    def from_env() -> PagRuntimeConfig:
        """Parse environment variables for runtime integration."""
        enabled = _truthy_env("AILIT_PAG", True)
        db_raw = os.environ.get("AILIT_PAG_DB_PATH", "").strip()
        db_path = (
            Path(db_raw).expanduser().resolve()
            if db_raw
            else PagIndexer.default_db_path()
        )
        top_k = max(1, min(_env_int("AILIT_PAG_TOP_K", 12), 50))
        max_chars = max(
            400,
            min(_env_int("AILIT_PAG_MAX_CHARS", 2400), 50_000),
        )
        sync_on_write = _truthy_env("AILIT_PAG_SYNC_ON_WRITE", True)
        return PagRuntimeConfig(
            enabled=enabled,
            db_path=db_path,
            top_k_files=top_k,
            max_chars=max_chars,
            sync_on_write_file=sync_on_write,
        )


@dataclass(frozen=True, slots=True)
class PagSliceResult:
    """Slice result returned to AgentWork (SessionRunner)."""

    used: bool
    staleness_state: str
    fallback_reason: str | None
    namespace: str
    target_file_paths: tuple[str, ...]
    injected_text: str | None
    nodes: tuple[PagNode, ...] = ()
    edges: tuple[PagEdge, ...] = ()


class PagRuntimeAgentMemory:
    """In-process runtime facade for PAG store."""

    def __init__(self, cfg: PagRuntimeConfig) -> None:
        self._cfg = cfg
        self._store = SqlitePagStore(cfg.db_path)
        self._indexer = PagIndexer(self._store)

    @property
    def db_path(self) -> Path:
        return self._cfg.db_path

    def build_slice_for_goal(
        self,
        *,
        project_root: Path,
        namespace: str | None = None,
        goal: str,
        query_kind: str,
    ) -> PagSliceResult:
        """Build a small PAG slice to inject into model context."""
        from agent_core.session.repo_context import (  # noqa: WPS433
            detect_repo_context,
            namespace_for_repo,
        )

        if not self._cfg.enabled:
            return PagSliceResult(
                used=False,
                staleness_state="missing",
                fallback_reason="disabled",
                namespace="",
                target_file_paths=(),
                injected_text=None,
            )
        root = project_root.resolve()
        try:
            rc = detect_repo_context(root)
        except Exception:  # noqa: BLE001
            rc = None
        if rc is None:
            return PagSliceResult(
                used=False,
                staleness_state="missing",
                fallback_reason="repo_context_unavailable",
                namespace="",
                target_file_paths=(),
                injected_text=None,
            )
        ns = namespace_for_repo(
            repo_uri=rc.repo_uri,
            repo_path=rc.repo_path,
            branch=rc.branch,
        )
        if namespace is not None and str(namespace).strip():
            ns = str(namespace).strip()
            a_id = f"A:{ns}"
        else:
            a_id = PagIndexer._a_node_id(rc)  # type: ignore[attr-defined]
        a = self._store.fetch_node(namespace=ns, node_id=a_id)
        if a is None:
            return PagSliceResult(
                used=False,
                staleness_state="missing",
                fallback_reason="pag_missing",
                namespace=ns,
                target_file_paths=(),
                injected_text=None,
            )
        if str(a.staleness_state) != "fresh":
            return PagSliceResult(
                used=False,
                staleness_state=str(a.staleness_state),
                fallback_reason="pag_stale",
                namespace=ns,
                target_file_paths=(),
                injected_text=None,
            )
        # B-level shortlist: file nodes only, scored by goal keywords
        # + simple entrypoint heuristics.
        b_nodes = self._store.list_nodes(
            namespace=ns,
            level="B",
            limit=5000,
            include_stale=False,
        )
        files = [n for n in b_nodes if n.kind == "file"]
        if not files:
            return PagSliceResult(
                used=False,
                staleness_state="low_confidence",
                fallback_reason="pag_empty",
                namespace=ns,
                target_file_paths=(),
                injected_text=None,
            )
        scored = self._score_files(goal=goal, nodes=files)
        top = scored[: self._cfg.top_k_files]
        target_paths = tuple(n.path for _, n in top)
        # Attach local edges for those nodes (helps debug/export, even if we
        # only inject a compact text digest).
        node_ids = [self._node_id_for_path(files, p) for p in target_paths]
        node_ids2 = [nid for nid in node_ids if nid]
        if node_ids2:
            edges = tuple(
                self._store.list_edges_touching(
                    namespace=ns,
                    node_ids=node_ids2,
                ),
            )
        else:
            edges = ()
        injected = self._render_injected_text(
            namespace=ns,
            goal=goal,
            query_kind=query_kind,
            top_files=top,
            max_chars=self._cfg.max_chars,
        )
        return PagSliceResult(
            used=True,
            staleness_state="fresh",
            fallback_reason=None,
            namespace=ns,
            target_file_paths=target_paths,
            injected_text=injected,
            nodes=tuple(n for _, n in top),
            edges=edges,
        )

    def sync_after_write(
        self,
        *,
        project_root: Path,
        namespace: str,
        changed_paths: Sequence[str],
        changed_ranges: Sequence[ChangedRange] = (),
    ) -> None:
        """Incrementally sync PAG after successful write_file operations."""
        if not self._cfg.enabled or not self._cfg.sync_on_write_file:
            return
        root = project_root.resolve()
        ns = str(namespace).strip()
        if not ns:
            return
        self._indexer.sync_changes(
            namespace=ns,
            project_root=root,
            changed_paths=changed_paths,
            changed_ranges=changed_ranges,
        )

    @staticmethod
    def _node_id_for_path(nodes: Sequence[PagNode], path: str) -> str | None:
        p = str(path).strip()
        for n in nodes:
            if n.path == p and n.level == "B" and n.kind == "file":
                return n.node_id
        return None

    @staticmethod
    def _keywords(text: str) -> set[str]:
        out: set[str] = set()
        for m in _WORD_RE.finditer(text or ""):
            w = m.group(0).strip().lower()
            if len(w) >= 2:
                out.add(w)
        return out

    def _score_files(
        self,
        *,
        goal: str,
        nodes: Sequence[PagNode],
    ) -> list[tuple[int, PagNode]]:
        kws = self._keywords(goal)

        def score(n: PagNode) -> int:
            p = str(n.path or "").lower()
            t = str(n.title or "").lower()
            s = 0
            for w in kws:
                if w in p:
                    s += 6
                if w in t:
                    s += 4
            # entrypoint-ish heuristics:
            if p.endswith(("cli.py", "main.py", "app.py")):
                s += 10
            if "/tools/ailit/" in p or p.startswith("tools/ailit/"):
                s += 4
            if "/tools/agent_core/" in p or p.startswith("tools/agent_core/"):
                s += 3
            if p.endswith(".py"):
                s += 1
            return s

        scored = [(score(n), n) for n in nodes]
        scored.sort(key=lambda x: (-x[0], str(x[1].path)))
        return scored

    @staticmethod
    def _render_injected_text(
        *,
        namespace: str,
        goal: str,
        query_kind: str,
        top_files: Sequence[tuple[int, PagNode]],
        max_chars: int,
    ) -> str:
        lines: list[str] = []
        lines.append("PAG slice (AgentMemory → AgentWork)")
        lines.append(f"namespace={namespace}")
        lines.append(f"query_kind={query_kind}")
        if goal.strip():
            lines.append(f"goal={goal.strip()}")
        lines.append("")
        lines.append("Shortlist files (top):")
        for sc, n in top_files:
            lang = str(n.attrs.get("language") or "")
            hint = f" lang={lang}" if lang else ""
            lines.append(f"- {n.path} (score={sc}{hint})")
        txt = "\n".join(lines).strip() + "\n"
        if max_chars and len(txt) > max_chars:
            return txt[: max_chars - 1] + "\n"
        return txt


def changed_ranges_from_write(
    *,
    relative_paths: Sequence[str],
) -> tuple[ChangedRange, ...]:
    """Best-effort changed_ranges for write_file.

    Since we don't have an actual diff in runtime, we mark the whole file as
    changed.
    """
    out: list[ChangedRange] = []
    for p in relative_paths:
        rel = str(p).strip().lstrip("./")
        if not rel:
            continue
        out.append(
            ChangedRange(
                path=rel,
                start_line=1,
                end_line=1_000_000_000,
            ),
        )
    return tuple(out)


def safe_event_payload_for_slice(
    *,
    slice_result: PagSliceResult,
) -> dict[str, Any]:
    """Build a small, non-sensitive payload for telemetry."""
    return {
        "namespace": slice_result.namespace,
        "used": bool(slice_result.used),
        "staleness_state": str(slice_result.staleness_state),
        "fallback_reason": slice_result.fallback_reason,
        "target_file_paths": list(slice_result.target_file_paths),
        "nodes_count": len(slice_result.nodes),
        "edges_count": len(slice_result.edges),
    }


def safe_event_payload_for_sync(
    *,
    namespace: str,
    changed_paths: Sequence[str],
    changed_ranges: Sequence[ChangedRange],
) -> dict[str, Any]:
    return {
        "namespace": str(namespace),
        "changed_paths": list(changed_paths),
        "changed_ranges_count": len(list(changed_ranges)),
    }
