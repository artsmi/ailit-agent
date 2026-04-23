"""Repository identity and version context (M4).

Goal: provide stable keys for memory across different local paths:
- repo_uri: canonical remote identifier (when available)
- branch/default_branch/commit: version context for retrieval/write policies
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_GIT_TIMEOUT_S = 0.25


def _safe_ns_part(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "unknown"
    s = s.replace("\\", "/")
    s = s.replace("://", "/")
    s = s.replace("/", "_").replace(":", "_").replace("@", "_")
    s = s.replace(" ", "_")
    return s[:128] if len(s) > 128 else s


def namespace_for_repo(
    *,
    repo_uri: str | None,
    repo_path: str,
    branch: str | None,
) -> str:
    """Stable namespace for KB partitioning: repo_id + optional branch."""
    base = _safe_ns_part(repo_uri or repo_path)
    if branch:
        return f"{base}:{_safe_ns_part(branch)}"
    return base


@dataclass(frozen=True, slots=True)
class RepoContext:
    """Stable identity and version information for a git worktree."""

    repo_path: str
    repo_uri: str | None
    branch: str | None
    commit: str | None
    default_branch: str | None
    default_branch_source: str

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "repo_path": self.repo_path,
            "repo_uri": self.repo_uri,
            "branch": self.branch,
            "commit": self.commit,
            "default_branch": self.default_branch,
            "default_branch_source": self.default_branch_source,
        }


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    try:
        cp = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    out = (cp.stdout or "").strip()
    return out or None


_SSH_RE = re.compile(r"^(?P<host>[^@:/]+)[:/](?P<path>.+)$")


def canonicalize_repo_uri(raw: str) -> str | None:
    """Best-effort canonical repo identifier from remote URL.

    Examples:
    - git@github.com:introlab/odas.git -> github.com/introlab/odas
    - https://github.com/introlab/odas.git -> github.com/introlab/odas
    """
    s = (raw or "").strip()
    if not s:
        return None
    if s.endswith(".git"):
        s = s[: -len(".git")]
    if "://" in s:
        s = s.split("://", 1)[1]
    if "@" in s and ":" in s:
        s = s.split("@", 1)[1]
    s = s.strip("/")
    m = _SSH_RE.match(s)
    if m:
        host = m.group("host").strip("/")
        path = m.group("path").strip("/")
        return f"{host}/{path}" if host and path else None
    return s or None


def detect_repo_context(repo_root: Path) -> RepoContext:
    """Detect repo context; safe to call even outside git."""
    root = repo_root.resolve()
    repo_path = str(root)
    inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if inside != "true":
        return RepoContext(
            repo_path=repo_path,
            repo_uri=None,
            branch=None,
            commit=None,
            default_branch=None,
            default_branch_source="not_git",
        )
    raw_uri = _run_git(root, ["config", "--get", "remote.origin.url"])
    repo_uri = canonicalize_repo_uri(raw_uri or "")
    branch = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch == "HEAD":
        branch = None
    commit = _run_git(root, ["rev-parse", "HEAD"])
    default_branch: str | None = None
    src = "unknown"
    sym = _run_git(root, ["symbolic-ref", "refs/remotes/origin/HEAD"])
    if sym and sym.startswith("refs/remotes/origin/"):
        default_branch = (
            sym.split("refs/remotes/origin/", 1)[1].strip() or None
        )
        src = "origin_head"
    if default_branch is None:
        for cand in ("main", "master", "develop"):
            ok = _run_git(root, ["show-ref", "--verify", f"refs/heads/{cand}"])
            if ok is not None:
                default_branch = cand
                src = "heuristic"
                break
    return RepoContext(
        repo_path=repo_path,
        repo_uri=repo_uri,
        branch=branch,
        commit=commit,
        default_branch=default_branch,
        default_branch_source=src,
    )
