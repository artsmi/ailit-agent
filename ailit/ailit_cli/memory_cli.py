"""CLI: PAG indexing utilities (workflow arch-graph-7, G7.2)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from agent_memory.pag_indexer import PagIndexer
from ailit_runtime.errors import RuntimeProtocolError
from agent_memory.memory_init_orchestrator import (
    MemoryInitOrchestrator,
)
from agent_memory.agent_memory_ailit_config import (
    agent_memory_rpc_timeout_s,
    load_merged_ailit_config_for_memory,
)
from agent_memory.memory_query_orchestrator import (
    MemoryQueryOrchestrator,
)
from ailit_runtime.broker_json_client import (
    BrokerJsonRpcClient,
    BrokerResponseError,
    BrokerTransportError,
    resolve_broker_socket_for_cli,
)
from ailit_runtime.models import (
    RuntimeIdentity,
    RuntimeNow,
    make_request_envelope,
)
from ailit_runtime.paths import default_runtime_dir
from agent_work.session.repo_context import (
    detect_repo_context,
    namespace_for_repo,
)
from agent_memory.pag_slice_caps import (
    PAG_SLICE_MAX_EDGES,
    PAG_SLICE_MAX_NODES,
)
from agent_memory.sqlite_pag import PagEdge, PagNode, SqlitePagStore


def _node_json(n: PagNode) -> dict[str, Any]:
    return {
        "namespace": n.namespace,
        "node_id": n.node_id,
        "level": n.level,
        "kind": n.kind,
        "path": n.path,
        "title": n.title,
        "summary": n.summary,
        "attrs": dict(n.attrs),
        "fingerprint": n.fingerprint,
        "staleness_state": n.staleness_state,
        "source_contract": n.source_contract,
        "updated_at": n.updated_at,
    }


def _edge_json(e: PagEdge) -> dict[str, Any]:
    return {
        "namespace": e.namespace,
        "edge_id": e.edge_id,
        "edge_class": e.edge_class,
        "edge_type": e.edge_type,
        "from_node_id": e.from_node_id,
        "to_node_id": e.to_node_id,
        "confidence": float(e.confidence),
        "source_contract": e.source_contract,
        "updated_at": e.updated_at,
    }


def memory_cli_resolve_broker_socket(
    args: object,
) -> tuple[Path, str] | None:
    """Путь к сокету broker и chat_id; None без ``--broker-chat-id``."""
    bcid = str(getattr(args, "broker_chat_id", "") or "").strip()
    if not bcid:
        return None
    bs_raw = getattr(args, "broker_socket", None)
    rt_raw = getattr(args, "memory_runtime_dir", None)
    explicit = (
        Path(str(bs_raw)).expanduser().resolve()
        if bs_raw and str(bs_raw).strip()
        else None
    )
    rd = (
        Path(str(rt_raw)).expanduser().resolve()
        if rt_raw and str(rt_raw).strip()
        else default_runtime_dir()
    )
    sock = resolve_broker_socket_for_cli(
        explicit_socket=explicit,
        runtime_dir=rd,
        broker_chat_id=bcid,
    )
    return sock, bcid


def cmd_memory_index(args: object) -> int:
    """Индексация PAG через broker RPC ``memory.index_project`` (G20.4)."""
    root_raw = getattr(args, "project_root", None)
    root = Path(str(root_raw)).resolve() if root_raw else Path.cwd().resolve()
    db_raw = getattr(args, "db_path", None)
    db_path_opt = (
        Path(str(db_raw)).expanduser().resolve()
        if db_raw and str(db_raw).strip()
        else None
    )
    full = bool(getattr(args, "full", False))

    try:
        pair = memory_cli_resolve_broker_socket(args)
    except RuntimeProtocolError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if pair is None:
        sys.stderr.write(
            "memory index: --broker-chat-id required "
            "(G20: index via runtime broker; "
            "see plan/20-memory-cli-broker-viz.md).\n",
        )
        return 2
    sock_path, bcid = pair
    try:
        merged = load_merged_ailit_config_for_memory()
    except Exception:
        merged = {}
    timeout_s = max(float(agent_memory_rpc_timeout_s(merged)), 3600.0)
    client = BrokerJsonRpcClient(sock_path)

    ctx = detect_repo_context(root)
    ns = namespace_for_repo(
        repo_uri=ctx.repo_uri,
        repo_path=ctx.repo_path,
        branch=ctx.branch,
    )
    sid = uuid.uuid4().hex[:12]
    identity = RuntimeIdentity(
        runtime_id=f"rt-idx-{sid}",
        chat_id=bcid,
        broker_id=f"broker-{bcid}",
        trace_id=f"tr-idx-{sid}",
        goal_id="memory_index",
        namespace=str(ns) if str(ns).strip() else "",
    )
    pl: dict[str, Any] = {
        "service": "memory.index_project",
        "request_id": f"req-idx-{sid}",
        "project_root": str(root),
        "full": full,
    }
    if db_path_opt is not None:
        pl["db_path"] = str(db_path_opt)
    req = make_request_envelope(
        identity=identity,
        message_id=f"msg-idx-{sid}",
        parent_message_id=None,
        from_agent=f"AgentWork:{bcid}",
        to_agent="AgentMemory:global",
        msg_type="service.request",
        payload=pl,
        now=RuntimeNow(),
    )
    try:
        out = client.call(req.to_dict(), timeout_s=timeout_s)
    except RuntimeProtocolError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    except (BrokerTransportError, BrokerResponseError) as exc:
        sys.stderr.write(f"memory index: broker RPC failed: {exc}\n")
        return 2
    if not isinstance(out, dict) or out.get("ok") is not True:
        err = out.get("error") if isinstance(out, dict) else None
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("code") or out)
        else:
            msg = str(out)
        sys.stderr.write(f"memory index: {msg}\n")
        return 2
    payload = out.get("payload")
    if not isinstance(payload, dict):
        sys.stderr.write("memory index: invalid response payload\n")
        return 2
    line_obj = {
        "ok": True,
        "namespace": str(payload.get("namespace", "") or ""),
        "db_path": str(payload.get("db_path", "") or ""),
        "project_root": str(payload.get("project_root", "") or str(root)),
    }
    os.write(1, (json.dumps(line_obj, ensure_ascii=False) + "\n").encode())
    return 0


def cmd_memory_init(args: object) -> int:
    """Initialize agent memory for a project root (PAG namespace; §4.2)."""
    root_raw = getattr(args, "project_root", None)
    if root_raw is None or not str(root_raw).strip():
        sys.stderr.write("memory init: path required\n")
        return 2
    root = Path(str(root_raw)).expanduser().resolve()
    ctx = detect_repo_context(root)
    ns = namespace_for_repo(
        repo_uri=ctx.repo_uri,
        repo_path=ctx.repo_path,
        branch=ctx.branch,
    )
    try:
        return int(MemoryInitOrchestrator().run(root, ns))
    except RuntimeProtocolError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2


def cmd_memory_query(args: object) -> int:
    """Раунды ``memory.query_context`` через broker; summary на stderr."""
    text = str(getattr(args, "query_text", "") or "").strip()
    if not text:
        sys.stderr.write("memory query: non-empty text required\n")
        return 2
    try:
        pair = memory_cli_resolve_broker_socket(args)
    except RuntimeProtocolError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if pair is None:
        sys.stderr.write(
            "memory query: --broker-chat-id required "
            "(G20: AgentMemory via broker only; "
            "see plan/20-memory-cli-broker-viz.md).\n",
        )
        return 2
    sock_path, bcid = pair
    proj = getattr(args, "project", None)
    root = (
        Path(str(proj)).expanduser().resolve()
        if proj and str(proj).strip()
        else Path.cwd().resolve()
    )
    try:
        merged = load_merged_ailit_config_for_memory()
    except Exception:
        merged = {}
    timeout_s = float(agent_memory_rpc_timeout_s(merged))
    client = BrokerJsonRpcClient(sock_path)

    def invoke(env: Mapping[str, Any]) -> dict[str, Any]:
        return client.call(env, timeout_s=timeout_s)

    try:
        return int(
            MemoryQueryOrchestrator().run(
                root,
                text,
                broker_invoke=invoke,
                broker_chat_id=bcid,
            ),
        )
    except RuntimeProtocolError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2


def _pag_slice_payload(
    *,
    namespace: str,
    db_path: Path,
    level: str | None,
    node_limit: int,
    node_offset: int,
    edge_limit: int,
    edge_offset: int,
) -> dict[str, Any]:
    store = SqlitePagStore(db_path)
    # limit+1: has_more без ложного True на последней полной странице;
    # при node_limit=max кап store не даёт +1 — COUNT.
    if node_limit < PAG_SLICE_MAX_NODES:
        nodes_raw = store.list_nodes(
            namespace=namespace,
            level=level,
            limit=node_limit + 1,
            offset=node_offset,
            include_stale=True,
        )
        has_more_nodes = len(nodes_raw) > node_limit
        nodes = nodes_raw[:node_limit]
    else:
        nodes = store.list_nodes(
            namespace=namespace,
            level=level,
            limit=node_limit,
            offset=node_offset,
            include_stale=True,
        )
        total_n = store.count_nodes(
            namespace=namespace,
            level=level,
            include_stale=True,
        )
        has_more_nodes = node_offset + len(nodes) < total_n
    if edge_limit < PAG_SLICE_MAX_EDGES:
        edges_raw = store.list_edges(
            namespace=namespace,
            limit=edge_limit + 1,
            offset=edge_offset,
        )
        has_more_edges = len(edges_raw) > edge_limit
        edges = edges_raw[:edge_limit]
    else:
        edges = store.list_edges(
            namespace=namespace,
            limit=edge_limit,
            offset=edge_offset,
        )
        total_e = store.count_edges(namespace=namespace)
        has_more_edges = edge_offset + len(edges) < total_e
    graph_rev: int = store.get_graph_rev(namespace=namespace)
    return {
        "ok": True,
        "kind": "ailit_pag_graph_slice_v1",
        "namespace": namespace,
        "db_path": str(db_path),
        "graph_rev": graph_rev,
        "level_filter": level,
        "nodes": [_node_json(n) for n in nodes],
        "edges": [_edge_json(e) for e in edges],
        "limits": {
            "node_limit": node_limit,
            "node_offset": node_offset,
            "edge_limit": edge_limit,
            "edge_offset": edge_offset,
        },
        "has_more": {
            "nodes": has_more_nodes,
            "edges": has_more_edges,
        },
    }


def cmd_memory_pag_slice(args: object) -> int:
    """JSON slice of PAG for ailit desktop (G9.8), main bridge only."""
    namespace = str(getattr(args, "namespace", "") or "").strip()
    db_arg = getattr(args, "db_path", None)
    level_raw = getattr(args, "level", None)
    if namespace == "":
        out = {
            "ok": False,
            "kind": "ailit_pag_graph_slice_v1",
            "code": "bad_args",
            "error": "namespace required",
        }
        os.write(1, (json.dumps(out, ensure_ascii=False) + "\n").encode())
        return 2
    level: str | None
    if level_raw in (None, "", "all", "ALL"):
        level = None
    else:
        lv = str(level_raw).strip().upper()
        if lv not in ("A", "B", "C"):
            out = {
                "ok": False,
                "kind": "ailit_pag_graph_slice_v1",
                "code": "bad_args",
                "error": "level must be one of: A, B, C, all",
            }
            os.write(1, (json.dumps(out, ensure_ascii=False) + "\n").encode())
            return 2
        level = lv
    db_path = (
        Path(str(db_arg)).expanduser().resolve()
        if db_arg
        else PagIndexer.default_db_path()
    )
    if not db_path.is_file():
        out = {
            "ok": False,
            "kind": "ailit_pag_graph_slice_v1",
            "code": "missing_db",
            "error": f"sqlite not found: {db_path}",
            "namespace": namespace,
        }
        os.write(1, (json.dumps(out, ensure_ascii=False) + "\n").encode())
        return 0
    nlim = max(
        1,
        min(int(getattr(args, "node_limit", 500)), PAG_SLICE_MAX_NODES),
    )
    noff = max(0, int(getattr(args, "node_offset", 0)))
    elim = max(
        1,
        min(int(getattr(args, "edge_limit", 500)), PAG_SLICE_MAX_EDGES),
    )
    eoff = max(0, int(getattr(args, "edge_offset", 0)))
    payload = _pag_slice_payload(
        namespace=namespace,
        db_path=db_path,
        level=level,
        node_limit=nlim,
        node_offset=noff,
        edge_limit=elim,
        edge_offset=eoff,
    )
    st = "ok"
    empty_page = not payload["nodes"] and not payload["edges"]
    empty_page = empty_page and noff == 0 and eoff == 0
    if empty_page:
        n1 = SqlitePagStore(db_path).list_nodes(
            namespace=namespace,
            level=None,
            limit=1,
            offset=0,
            include_stale=True,
        )
        if not n1:
            st = "empty"
    out = dict(payload)
    out["pag_state"] = st
    line = json.dumps(out, ensure_ascii=False) + "\n"
    os.write(1, line.encode())
    return 0
