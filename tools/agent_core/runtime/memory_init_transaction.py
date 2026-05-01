"""Memory init transaction: lock, PAG/KB snapshot, journal shadow, phases.

Phases: PREPARE → EXECUTE (destructive) → VERIFY → COMMIT or ABORT.

**Snapshot predicate (single rule, D5 / task 2.1):**
``namespace_has_durable_graph_materialization`` is true iff PAG has at least
one node for ``pag_namespace_key``. The ``kb_db_path`` parameter exists only
for API symmetry with :func:`resolve_memory_init_paths`. Extra snapshots when
false are allowed; skipping snapshot when true is not.

Lock: exclusive lock file under ``AILIT_RUNTIME_DIR`` (default
``~/.ailit/runtime``) with JSON payload ``until_unix`` for stale recovery
after crash (TTL).

Journal: shadow file next to the canonical journal; COMMIT merges into
canonical via ``append_rows_from_jsonl_file``; ABORT discards shadow so
init rows never reach the canonical file.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from agent_core.memory.kb_tools import kb_tools_config_from_env
from agent_core.memory.pag_runtime import PagRuntimeConfig
from agent_core.memory.sqlite_kb import SqliteKb
from agent_core.memory.sqlite_pag import SqlitePagStore
from agent_core.runtime.errors import RuntimeProtocolError
from agent_core.runtime.memory_journal import MemoryJournalStore

PhaseName = Literal[
    "NEW",
    "PREPARED",
    "EXECUTED",
    "VERIFIED",
    "COMMITTED",
    "ABORTED",
]

_DEFAULT_LOCK_TTL_SEC: Final[int] = 3600
_LOCK_ACQUIRE_ATTEMPTS: Final[int] = 80
_LOCK_RETRY_SLEEP_SEC: Final[float] = 0.05


def namespace_has_durable_graph_materialization(
    *,
    pag_db_path: Path,
    kb_db_path: Path,
    pag_namespace_key: str,
) -> bool:
    """Return true when PAG materialization exists (see module docstring)."""
    _ = kb_db_path
    ns = str(pag_namespace_key).strip()
    if not ns:
        return False
    return SqlitePagStore(pag_db_path).count_nodes(namespace=ns) > 0


def _runtime_dir_default() -> Path:
    raw = os.environ.get("AILIT_RUNTIME_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ailit" / "runtime").resolve()


def _lock_path_for_namespace(
    runtime_dir: Path,
    pag_namespace_key: str,
) -> Path:
    ns = str(pag_namespace_key).strip() or "default"
    digest = hashlib.sha256(ns.encode("utf-8")).hexdigest()[:24]
    safe_chars = (c if c.isalnum() or c in ("-", "_") else "_" for c in ns)
    safe = "".join(safe_chars)[:48]
    locks = runtime_dir / "locks"
    return locks / f"memory-init-{safe}-{digest}.lock"


def _journal_canonical_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    return MemoryJournalStore().path


def _mtime_age_sec(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return float(_DEFAULT_LOCK_TTL_SEC) + 1.0


def _lock_payload_is_stale(lock_path: Path, *, ttl_sec: int) -> bool:
    if not lock_path.exists():
        return True
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _mtime_age_sec(lock_path) > float(ttl_sec)
    if not isinstance(raw, dict):
        return _mtime_age_sec(lock_path) > float(ttl_sec)
    until = raw.get("until_unix")
    if isinstance(until, (int, float)):
        return time.time() > float(until)
    return _mtime_age_sec(lock_path) > float(ttl_sec)


@dataclass(frozen=True, slots=True)
class MemoryInitPaths:
    """Resolved SoT paths for one init transaction."""

    pag_db: Path
    kb_db: Path
    journal_canonical: Path
    runtime_dir: Path


def resolve_memory_init_paths(
    *,
    pag_db_path: Path | None = None,
    kb_db_path: Path | None = None,
    journal_path: Path | None = None,
    runtime_dir: Path | None = None,
) -> MemoryInitPaths:
    """Resolve PAG/KB/journal/runtime paths from parameters or environment."""
    pag = (
        pag_db_path.resolve()
        if pag_db_path is not None
        else PagRuntimeConfig.from_env().db_path
    )
    kb = (
        kb_db_path.resolve()
        if kb_db_path is not None
        else kb_tools_config_from_env().db_path
    )
    jr = _journal_canonical_path(journal_path)
    if runtime_dir is not None:
        rt = runtime_dir.resolve()
    else:
        rt = _runtime_dir_default()
    return MemoryInitPaths(
        pag_db=pag,
        kb_db=kb,
        journal_canonical=jr,
        runtime_dir=rt,
    )


class MemoryInitTransaction:
    """PREPARE / EXECUTE / VERIFY / COMMIT / ABORT for one ``memory init``."""

    def __init__(
        self,
        *,
        init_session_id: str,
        chat_id: str,
        pag_namespace_key: str,
        paths: MemoryInitPaths | None = None,
        lock_ttl_sec: int = _DEFAULT_LOCK_TTL_SEC,
    ) -> None:
        sid = str(init_session_id).strip()
        cid = str(chat_id).strip()
        ns = str(pag_namespace_key).strip()
        if not sid:
            raise RuntimeProtocolError(
                code="memory_init_missing_session_id",
                message="init_session_id is required",
            )
        if not cid:
            raise RuntimeProtocolError(
                code="memory_init_missing_chat_id",
                message="chat_id is required",
            )
        if not ns:
            raise RuntimeProtocolError(
                code="memory_init_missing_namespace",
                message="pag_namespace_key is required",
            )
        self._init_session_id: str = sid
        self._chat_id: str = cid
        self._namespace: str = ns
        self._paths: MemoryInitPaths = paths or resolve_memory_init_paths()
        self._ttl: int = max(60, int(lock_ttl_sec))
        self._phase: PhaseName = "NEW"
        self._lock_path: Path = _lock_path_for_namespace(
            self._paths.runtime_dir,
            self._namespace,
        )
        self._held_lock: bool = False
        self._snapshot_required: bool = False
        self._snapshot_staging: Path | None = None
        self._snap_pag: Path | None = None
        self._snap_kb: Path | None = None
        self._shadow_journal: Path | None = None
        self._destructive_applied: bool = False
        self._verify_ok: bool | None = None

    @property
    def init_session_id(self) -> str:
        return self._init_session_id

    @property
    def chat_id(self) -> str:
        return self._chat_id

    @property
    def pag_namespace_key(self) -> str:
        return self._namespace

    @property
    def shadow_journal_path(self) -> Path | None:
        return self._shadow_journal

    @property
    def phase(self) -> PhaseName:
        return self._phase

    def journal_store_shadow(self) -> MemoryJournalStore:
        """Return a store for the shadow journal (after PREPARE)."""
        if self._shadow_journal is None:
            raise RuntimeProtocolError(
                code="memory_init_journal_not_ready",
                message="call phase_prepare before journal_store_shadow",
            )
        return MemoryJournalStore(self._shadow_journal)

    def phase_prepare(self) -> None:
        """PREPARE: lock, optional PAG/KB snapshot, shadow journal."""
        if self._phase != "NEW":
            raise RuntimeProtocolError(
                code="memory_init_invalid_phase",
                message=f"phase_prepare expects NEW, got {self._phase!r}",
            )
        self._paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._acquire_lock_file()
        self._held_lock = True
        try:
            need_snap = namespace_has_durable_graph_materialization(
                pag_db_path=self._paths.pag_db,
                kb_db_path=self._paths.kb_db,
                pag_namespace_key=self._namespace,
            )
            self._snapshot_required = need_snap
            staging_root = (
                self._paths.runtime_dir
                / "memory-init-snapshots"
                / self._init_session_id
            )
            if self._snapshot_required:
                staging_root.mkdir(parents=True, exist_ok=True)
                self._snapshot_staging = staging_root
                self._snap_pag = staging_root / "pag.sqlite3"
                self._snap_kb = staging_root / "kb.sqlite3"
                if self._paths.pag_db.exists():
                    shutil.copy2(self._paths.pag_db, self._snap_pag)
                else:
                    self._snap_pag = None
                if self._paths.kb_db.exists():
                    shutil.copy2(self._paths.kb_db, self._snap_kb)
                else:
                    self._snap_kb = None
            else:
                self._snapshot_staging = None
                self._snap_pag = None
                self._snap_kb = None
            parent = self._paths.journal_canonical.parent
            parent.mkdir(parents=True, exist_ok=True)
            shadow = parent / (
                f".memory-init-{self._init_session_id}.journal.shadow.jsonl"
            )
            shadow.write_text("", encoding="utf-8")
            self._shadow_journal = shadow
        except BaseException:
            self._release_lock_file()
            self._held_lock = False
            raise
        self._phase = "PREPARED"

    def phase_execute_destructive_namespace_clear(self) -> None:
        """EXECUTE: destructive clear of PAG/KB namespace (§4.2).

        When ``_snapshot_required`` is true, snapshot files must exist from
        PREPARE before this runs (restore is possible on ABORT).
        """
        if self._phase != "PREPARED":
            raise RuntimeProtocolError(
                code="memory_init_invalid_phase",
                message=(
                    "phase_execute_destructive_namespace_clear "
                    f"expects PREPARED, got {self._phase!r}"
                ),
            )
        if self._snapshot_required:
            if self._snapshot_staging is None:
                raise RuntimeProtocolError(
                    code="memory_init_snapshot_missing",
                    message="snapshot required but staging path missing",
                )
        pag = SqlitePagStore(self._paths.pag_db)
        kb = SqliteKb(self._paths.kb_db)
        pag.delete_all_data_for_namespace(
            namespace=self._namespace,
        )
        kb.delete_all_for_namespace(namespace=self._namespace)
        self._destructive_applied = True
        self._phase = "EXECUTED"

    def phase_verify(self, ok: bool) -> None:
        """VERIFY: record whether the pipeline passed verification."""
        if self._phase != "EXECUTED":
            raise RuntimeProtocolError(
                code="memory_init_invalid_phase",
                message=f"phase_verify expects EXECUTED, got {self._phase!r}",
            )
        self._verify_ok = bool(ok)
        self._phase = "VERIFIED"

    def phase_commit(self) -> None:
        """COMMIT: merge shadow journal, drop snapshots, release lock."""
        if self._phase != "VERIFIED":
            raise RuntimeProtocolError(
                code="memory_init_invalid_phase",
                message=f"phase_commit expects VERIFIED, got {self._phase!r}",
            )
        if self._verify_ok is not True:
            raise RuntimeProtocolError(
                code="memory_init_verify_failed",
                message="cannot COMMIT after failed VERIFY; use phase_abort",
            )
        try:
            sj = self._shadow_journal
            if sj is not None and sj.exists():
                main = MemoryJournalStore(self._paths.journal_canonical)
                main.append_rows_from_jsonl_file(sj)
                sj.unlink(missing_ok=True)
            stg = self._snapshot_staging
            if stg is not None and stg.exists():
                shutil.rmtree(stg, ignore_errors=True)
        finally:
            self._release_lock_file()
            self._held_lock = False
        self._phase = "COMMITTED"

    def phase_abort(self) -> None:
        """ABORT: restore or clean DBs; drop shadow; unlock."""
        if self._phase == "ABORTED":
            return
        if self._phase == "COMMITTED":
            return
        if self._phase == "NEW":
            raise RuntimeProtocolError(
                code="memory_init_invalid_phase",
                message="phase_abort cannot run from NEW",
            )
        if self._phase == "VERIFIED" and self._verify_ok is True:
            raise RuntimeProtocolError(
                code="memory_init_abort_after_success_verify",
                message="use phase_commit after successful VERIFY",
            )
        try:
            if self._destructive_applied:
                has_snap_files = (
                    self._snap_pag is not None or self._snap_kb is not None
                )
                if self._snapshot_required and has_snap_files:
                    pag_par = self._paths.pag_db.parent
                    kb_par = self._paths.kb_db.parent
                    pag_par.mkdir(parents=True, exist_ok=True)
                    kb_par.mkdir(parents=True, exist_ok=True)
                    sp = self._snap_pag
                    if sp is not None and sp.exists():
                        shutil.copy2(sp, self._paths.pag_db)
                    sk = self._snap_kb
                    if sk is not None and sk.exists():
                        shutil.copy2(sk, self._paths.kb_db)
                else:
                    pag = SqlitePagStore(self._paths.pag_db)
                    kb = SqliteKb(self._paths.kb_db)
                    pag.delete_all_data_for_namespace(
                        namespace=self._namespace,
                    )
                    kb.delete_all_for_namespace(namespace=self._namespace)
            sj2 = self._shadow_journal
            if sj2 is not None:
                sj2.unlink(missing_ok=True)
            stg2 = self._snapshot_staging
            if stg2 is not None and stg2.exists():
                shutil.rmtree(stg2, ignore_errors=True)
        finally:
            if self._held_lock:
                self._release_lock_file()
                self._held_lock = False
        self._phase = "ABORTED"

    def _acquire_lock_file(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        until = time.time() + float(self._ttl)
        payload = json.dumps(
            {
                "init_session_id": self._init_session_id,
                "pag_namespace_key": self._namespace,
                "chat_id": self._chat_id,
                "pid": os.getpid(),
                "until_unix": until,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        for _ in range(_LOCK_ACQUIRE_ATTEMPTS):
            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                try:
                    os.write(fd, payload)
                finally:
                    os.close(fd)
                return
            except FileExistsError:
                if _lock_payload_is_stale(self._lock_path, ttl_sec=self._ttl):
                    try:
                        self._lock_path.unlink()
                    except OSError:
                        pass
                else:
                    time.sleep(_LOCK_RETRY_SLEEP_SEC)
        raise RuntimeProtocolError(
            code="memory_init_lock_busy",
            message=f"could not acquire init lock: {self._lock_path}",
        )

    def _release_lock_file(self) -> None:
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass
