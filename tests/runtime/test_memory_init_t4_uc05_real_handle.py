"""UC-05 T4: MemoryInitOrchestrator exit 0 без stub ``handle``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest

from ailit_base.capabilities import Capability, capability_set_for
from agent_memory.pag_runtime import PagRuntimeConfig
from agent_memory.sqlite_pag import SqlitePagStore
from ailit_base.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
)
from agent_memory.agent_memory_runtime_contract import (
    AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
)
from agent_memory.memory_init_orchestrator import (
    MemoryInitOrchestrator,
    verify_memory_init_journal_complete_marker,
)
from agent_memory.memory_init_transaction import MemoryInitPaths as MIP
from agent_memory.agent_memory_chat_log import create_unique_cli_session_dir
from ailit_runtime.models import RuntimeRequestEnvelope
from ailit_runtime.subprocess_agents import (
    memory_agent as memory_agent_mod,
)
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


def _apply_memory_init_isolation_t4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tmp + env; LLM enabled; tight ``max_selected_b`` для continuation."""
    logs = tmp_path / "chat_logs"
    logs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(logs))
    am_cfg = tmp_path / "am.yaml"
    am_cfg.write_text(
        'schema_version: "1"\n'
        "memory:\n"
        "  llm:\n"
        "    enabled: true\n"
        "  runtime:\n"
        "    max_selected_b: 1\n"
        "    min_child_summary_coverage: 0.0\n"
        "  debug:\n"
        "    verbose: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CONFIG", str(am_cfg))
    jr = tmp_path / "memory-journal.jsonl"
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jr))
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(tmp_path / "pag.sqlite3"))
    monkeypatch.setenv("AILIT_KB_DB_PATH", str(tmp_path / "kb.sqlite3"))
    rt = tmp_path / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AILIT_RUNTIME_DIR", str(rt))


_FROZEN_PLAN_IN_PROGRESS: Final[dict[str, Any]] = {
    "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
    "command": "plan_traversal",
    "command_id": "w14-t4-frozen-1",
    "status": "in_progress",
    "payload": {
        "is_final": False,
        "actions": [
            {"action": "list_children", "path": "docs/README.md"},
        ],
    },
    "decision_summary": "Continue plan traversal (T4 frozen)",
    "violations": [],
}


def _json_resp(obj: dict[str, Any]) -> NormalizedChatResponse:
    body = json.dumps(obj, ensure_ascii=False)
    return NormalizedChatResponse(
        text_parts=(body,),
        tool_calls=(),
        finish_reason=FinishReason.STOP,
        usage=NormalizedUsage(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            usage_missing=False,
        ),
        provider_metadata={"mock": "t4-uc05"},
        raw_debug_payload=None,
    )


def _summarize_c_envelope() -> dict[str, Any]:
    return {
        "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
        "command": "summarize_c",
        "command_id": "sc-t4",
        "status": "ok",
        "payload": {
            "summary": "t4 minimal c summary",
            "semantic_tags": [],
            "important_lines": [],
            "claims": [],
            "refusal_reason": "",
        },
        "decision_summary": "d",
        "violations": [],
    }


def _summarize_b_envelope() -> dict[str, Any]:
    return {
        "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
        "command": "summarize_b",
        "command_id": "sb-t4",
        "status": "ok",
        "payload": {
            "summary": "t4 minimal b summary",
            "child_refs": [],
            "missing_children": [],
            "confidence": 1.0,
            "refusal_reason": "",
        },
        "decision_summary": "d",
        "violations": [],
    }


def _finish_from_store(namespace: str) -> dict[str, Any]:
    cfg = PagRuntimeConfig.from_env()
    store = SqlitePagStore(cfg.db_path)
    c_nodes = store.list_nodes(namespace=namespace, level="C", limit=80)
    chosen: Any = None
    for n in c_nodes:
        attrs = n.attrs if isinstance(n.attrs, dict) else {}
        if str(attrs.get("summary_fingerprint", "") or "").strip():
            chosen = n
            break
    if chosen is None and c_nodes:
        chosen = c_nodes[0]
    if chosen is None:
        raise RuntimeError("T4 provider: no C nodes for finish_decision")
    pl: dict[str, Any] = {
        "finish": True,
        "status": "complete",
        "selected_results": [
            {
                "kind": "c_summary",
                "path": str(chosen.path or ""),
                "node_id": str(chosen.node_id or ""),
                "summary": None,
                "read_lines": [],
                "reason": "t4-second-round",
            },
        ],
        "decision_summary": "t4 complete",
        "recommended_next_step": "",
    }
    return {
        "schema_version": AGENT_MEMORY_COMMAND_OUTPUT_SCHEMA,
        "command": "finish_decision",
        "command_id": "fd-t4-second",
        "status": "ok",
        "payload": pl,
        "decision_summary": "t4 complete",
        "violations": [],
    }


class _T4SequentialMemoryProvider:
    """
    Первый ответ — frozen ``plan_traversal`` + ``in_progress``.

    Без подмены ``AgentMemoryWorker.handle`` на complete-stub.
    """

    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self.planner_passes = 0

    @property
    def provider_id(self) -> str:
        return "t4-seq-memory"

    def capabilities(self) -> frozenset[Capability]:
        return capability_set_for(self.provider_id)

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        last_msg = request.messages[-1]
        last = str(last_msg.content or "")

        if "validation_error" in last:
            fixed = dict(_FROZEN_PLAN_IN_PROGRESS)
            fixed["status"] = "ok"
            fixed["command_id"] = "w14-t4-repair-ok"
            return _json_resp(fixed)

        if '"command": "finish_decision"' in last:
            return _json_resp(json.loads(last))

        if '"command": "summarize_c"' in last:
            return _json_resp(_summarize_c_envelope())

        if '"command": "summarize_b"' in last:
            return _json_resp(_summarize_b_envelope())

        if '"explicit_paths"' in last and '"namespace"' in last:
            self.planner_passes += 1
            if self.planner_passes == 1:
                return _json_resp(dict(_FROZEN_PLAN_IN_PROGRESS))
            return _json_resp(_finish_from_store(self._namespace))

        return _json_resp(dict(_FROZEN_PLAN_IN_PROGRESS))

    def stream(self, request: ChatRequest) -> None:
        raise NotImplementedError


def test_t4_memory_init_orchestrator_exit0_real_handle_sequential_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    TC-T4: реальный ``AgentMemoryWorker.handle``, continuation W14.

    TC-NO-STUB: не патчим ``handle`` на complete-stub; первый ответ
    fake-провайдера — frozen ``plan_traversal`` + ``in_progress``.
    """
    proj = tmp_path / "proj-t4"
    proj.mkdir()
    (proj / "one.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "two.py").write_text("y = 2\n", encoding="utf-8")
    _apply_memory_init_isolation_t4(tmp_path, monkeypatch)
    ns = "ns-t4-uc05"
    prov = _T4SequentialMemoryProvider(namespace=ns)

    def _build_provider(_merged: dict[str, Any]):
        return prov

    monkeypatch.setattr(
        memory_agent_mod,
        "build_chat_provider_for_agent_memory",
        _build_provider,
    )
    paths = MIP(
        pag_db=tmp_path / "pag.sqlite3",
        kb_db=tmp_path / "kb.sqlite3",
        journal_canonical=tmp_path / "memory-journal.jsonl",
        runtime_dir=tmp_path / "runtime",
    )
    cid = "chat-t4-orchestrator"
    cli_dir = create_unique_cli_session_dir()
    cfg = MemoryAgentConfig(
        chat_id=cid,
        broker_id=f"broker-{cid}",
        namespace=ns,
        session_log_mode="cli_init",
        cli_session_dir=cli_dir,
        broker_trace_stdout=False,
    )
    worker = AgentMemoryWorker(cfg)

    def invoke(env: Mapping[str, Any]) -> dict[str, Any]:
        req = RuntimeRequestEnvelope.from_dict(dict(env))
        return dict(worker.handle(req))

    journal_main = tmp_path / "memory-journal.jsonl"
    code = MemoryInitOrchestrator(paths=paths).run(
        proj,
        ns,
        broker_invoke=invoke,
        broker_chat_id=cid,
        cli_session_dir=cli_dir,
    )
    assert code == 0
    assert prov.planner_passes == 2
    assert journal_main.is_file()
    assert (
        verify_memory_init_journal_complete_marker(journal_main, cid) is True
    )
