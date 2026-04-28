from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_core.memory.sqlite_pag import SqlitePagStore


def test_memory_pag_slice_outputs_json_with_nodes(tmp_path: Path) -> None:
    root: Path = Path(__file__).resolve().parents[1]
    db: Path = tmp_path / "slice.sqlite3"
    store: SqlitePagStore = SqlitePagStore(db)
    store.upsert_node(
        namespace="ns-test",
        node_id="B:foo.py",
        level="B",
        kind="file",
        path="foo.py",
        title="foo.py",
        summary="",
        attrs={},
        fingerprint="fp1",
        staleness_state="fresh",
        source_contract="ailit_pag_store_v1",
        updated_at="2026-01-01T00:00:00Z",
    )
    code: str = f"""
import os, sys, json
os.environ["PYTHONPATH"] = {str(root / "tools")!r}
from ailit.memory_cli import cmd_memory_pag_slice

class Args:
    namespace = "ns-test"
    db_path = {str(db)!r}
    level = None
    node_limit = 50
    node_offset = 0
    edge_limit = 50
    edge_offset = 0

sys.exit(cmd_memory_pag_slice(Args()))
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    line: str = r.stdout.strip().splitlines()[-1]
    data: dict[str, object] = json.loads(line)
    assert data.get("ok") is True
    assert data.get("namespace") == "ns-test"
    assert data.get("kind") == "ailit_pag_graph_slice_v1"
    gr: object = data.get("graph_rev", 0)
    assert isinstance(gr, int) and gr >= 1
    nodes: list[object] = data.get("nodes", [])  # type: ignore[assignment]
    assert len(nodes) == 1
    n0: dict[str, object] = nodes[0] if isinstance(nodes[0], dict) else {}
    assert n0.get("node_id") == "B:foo.py"


def test_memory_pag_slice_missing_db_code(tmp_path: Path) -> None:
    root: Path = Path(__file__).resolve().parents[1]
    missing: Path = tmp_path / "nope.sqlite3"
    code: str = f"""
import os, sys, json
os.environ["PYTHONPATH"] = {str(root / "tools")!r}
from ailit.memory_cli import cmd_memory_pag_slice

class Args:
    namespace = "x"
    db_path = {str(missing)!r}
    level = None
    node_limit = 10
    node_offset = 0
    edge_limit = 10
    edge_offset = 0

sys.exit(cmd_memory_pag_slice(Args()))
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert r.returncode == 0
    data: dict[str, object] = json.loads(r.stdout.strip().splitlines()[-1])
    assert data.get("ok") is False
    assert data.get("code") == "missing_db"
