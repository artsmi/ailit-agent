"""G14R.9: AgentMemory journal + chat_logs по C14R.11 (без raw prompt)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ailit_base.models import (
    ChatRequest,
    FinishReason,
    NormalizedChatResponse,
    NormalizedUsage,
)
from ailit_base.providers.protocol import ChatProvider
from agent_memory.agent_memory_config import (
    AgentMemoryFileConfig,
    MemoryDebugSubConfig,
)
from agent_memory.agent_memory_chat_log import log_file_path_for_chat
from agent_memory.memory_journal import MemoryJournalStore
from ailit_runtime.models import RuntimeIdentity, make_request_envelope
from ailit_runtime.subprocess_agents.memory_agent import (
    AgentMemoryWorker,
    MemoryAgentConfig,
)


class _SeqProvider:
    """Провайдер с заранее заданными ответами (порядок фиксирован)."""

    def __init__(self, bodies: list[str]) -> None:
        self._bodies: list[str] = list(bodies)
        self.calls: list[ChatRequest] = []

    @property
    def provider_id(self) -> str:
        return "seq-mock"

    def complete(self, request: ChatRequest) -> NormalizedChatResponse:
        self.calls.append(request)
        body = self._bodies.pop(0) if self._bodies else '{"c_upserts":[]}'
        return NormalizedChatResponse(
            text_parts=(body,),
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            usage=NormalizedUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
            provider_metadata={"mock": "seq"},
            raw_debug_payload=None,
        )

    def stream(self, request: ChatRequest) -> Any:
        raise NotImplementedError


def _am_verbose() -> AgentMemoryFileConfig:
    base: AgentMemoryFileConfig = AgentMemoryFileConfig()
    return replace(
        base,
        memory=replace(
            base.memory,
            debug=MemoryDebugSubConfig(verbose=1),
        ),
    )


def _env(
    *,
    project_root: Path,
    path: str,
    goal: str,
    query_id: str = "q-trace-1",
) -> object:
    ident = RuntimeIdentity(
        runtime_id="rt",
        chat_id="c-g14logs",
        broker_id="b1",
        trace_id="t1",
        goal_id="g1",
        namespace="ns-t",
    )
    return make_request_envelope(
        identity=ident,
        message_id="m1",
        parent_message_id=None,
        from_agent="AgentWork:c1",
        to_agent="AgentMemory:global",
        msg_type="service.request",
        payload={
            "service": "memory.query_context",
            "request_id": "r1",
            "path": path,
            "goal": goal,
            "query_id": query_id,
            "project_root": str(project_root),
        },
    )


def _block_for_topic(text: str, topic_sub: str) -> str:
    """
    Фрагмент chat log: от ``topic=...`` до следующего разделителя.
    """
    key: str = f"topic={topic_sub}"
    i: int = text.find(key)
    if i < 0:
        return ""
    rest: str = text[i:]
    j: int = rest.find("\n" + "=" * 40, 1)
    if j < 0:
        j = rest.find("\n" + "=" * 80, 1)
    if j < 0:
        return rest
    return rest[:j]


def _minimal_w14() -> str:
    o: dict[str, object] = {
        "schema_version": "agent_memory_command_output.v1",
        "command": "plan_traversal",
        "command_id": "cmd-shared-42",
        "status": "ok",
        "payload": {"actions": []},
        "decision_summary": "d",
        "violations": [],
    }
    return json.dumps(o, ensure_ascii=False)


def test_agent_memory_chat_log_records_command_requested_without_raw_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    C14R.11: блок memory.command.requested — только stats/prompt_id,
    не полные тексты user JSON (огромный goal не попадает в log как целиком).
    """
    db: Path = tmp_path / "p.sqlite3"
    log_dir: Path = tmp_path / "chat_logs"
    jpath: Path = tmp_path / "j.jsonl"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jpath))
    huge: str = "B" * 20_000
    (tmp_path / "f.py").write_text("x=1\n", encoding="utf-8")
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14logs",
            broker_id="b1",
            namespace="ns-t",
        ),
    )
    vcfg: AgentMemoryFileConfig = _am_verbose()
    monkeypatch.setattr(w, "_am_file", vcfg, raising=False)
    w._chat_debug = (  # noqa: SLF001
        __import__(
            "agent_memory.agent_memory_chat_log",
            fromlist=["AgentMemoryChatDebugLog"],
        ).AgentMemoryChatDebugLog(
            vcfg,
        )
    )
    prov: ChatProvider = _SeqProvider([_minimal_w14()])
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(
        _env(
            project_root=tmp_path,
            path="f.py",
            goal=huge,
        ),
    )
    logf: Path = log_file_path_for_chat("c-g14logs")
    text: str = logf.read_text(encoding="utf-8")
    assert "memory.command.requested" in text
    cmd_req_block: str = _block_for_topic(
        text,
        "memory.command.requested",
    )
    assert cmd_req_block, "ожидаем блок memory.command.requested"
    assert (
        huge not in cmd_req_block
    ), "memory.command.requested: только compact stats, не полный goal"
    jstore: MemoryJournalStore = MemoryJournalStore(jpath)
    jrows: list = list(
        jstore.filter_rows(event_name="memory.command.requested"),
    )
    assert jrows, "ожидаем journal memory.command.requested"
    pld0: object = jrows[0].payload
    assert isinstance(pld0, dict)
    pld: dict[str, object] = pld0
    nchars: int = int(pld.get("input_user_payload_chars") or 0)
    # goal в pl_user проходит через clamp (порядка 12k), не 20k сырых.
    assert 10_000 < nchars <= 13_000
    jline: str = jpath.read_text(encoding="utf-8")
    assert huge not in jline


def test_agent_memory_chat_log_records_command_rejected_with_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    C14R.11: memory.command.rejected — error_code в journal + chat.
    """
    db = tmp_path / "p2.sqlite3"
    log_dir = tmp_path / "chat_logs2"
    jpath = tmp_path / "j2.jsonl"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jpath))
    (tmp_path / "g.py").write_text("y=1\n", encoding="utf-8")
    bad = "preamble " + _minimal_w14()
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14logs",
            broker_id="b1",
            namespace="ns-t",
        ),
    )
    vcfg2: AgentMemoryFileConfig = _am_verbose()
    monkeypatch.setattr(w, "_am_file", vcfg2, raising=False)
    w._chat_debug = (  # noqa: SLF001
        __import__(
            "agent_memory.agent_memory_chat_log",
            fromlist=["AgentMemoryChatDebugLog"],
        ).AgentMemoryChatDebugLog(
            vcfg2,
        )
    )
    prov: ChatProvider = _SeqProvider([bad])
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(_env(project_root=tmp_path, path="g.py", goal="g"))
    logf: Path = log_file_path_for_chat("c-g14logs")
    tlog: str = logf.read_text(encoding="utf-8")
    assert "memory.command.rejected" in tlog
    assert "w14_command_parse" in tlog
    jrows2 = list(
        MemoryJournalStore(jpath).filter_rows(
            event_name="memory.command.rejected",
        ),
    )
    assert jrows2
    pld2: object = jrows2[0].payload
    assert isinstance(pld2, dict)
    assert pld2.get("error_code") == "w14_command_parse"


def test_memory_journal_and_chat_log_share_command_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Один command_id (из envelope) в journal + chat при успешном parse W14.
    """
    db = tmp_path / "p3.sqlite3"
    log_dir = tmp_path / "chat_logs3"
    jpath = tmp_path / "j3.jsonl"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jpath))
    (tmp_path / "h.py").write_text("z=1\n", encoding="utf-8")
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14logs",
            broker_id="b1",
            namespace="ns-t",
        ),
    )
    vcfg3: AgentMemoryFileConfig = _am_verbose()
    monkeypatch.setattr(w, "_am_file", vcfg3, raising=False)
    w._chat_debug = (  # noqa: SLF001
        __import__(
            "agent_memory.agent_memory_chat_log",
            fromlist=["AgentMemoryChatDebugLog"],
        ).AgentMemoryChatDebugLog(
            vcfg3,
        )
    )
    prov: ChatProvider = _SeqProvider([_minimal_w14()])
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(_env(project_root=tmp_path, path="h.py", goal="ok"))
    chat_txt: str = log_file_path_for_chat("c-g14logs").read_text(encoding="utf-8")
    jrows3 = list(
        MemoryJournalStore(jpath).filter_rows(
            event_name="memory.command.parsed",
        ),
    )
    assert jrows3, "ожидаем memory.command.parsed"
    pld3: object = jrows3[0].payload
    assert isinstance(pld3, dict)
    cid: str = str(pld3.get("command_id", "") or "")
    assert cid == "cmd-shared-42"
    assert f'"command_id": "{cid}"' in chat_txt


def _max_str_len_in_obj(obj: object, depth: int = 0) -> int:
    if depth > 24:
        return 0
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, dict):
        return max(
            (_max_str_len_in_obj(v, depth + 1) for v in obj.values()),
            default=0,
        )
    if isinstance(obj, list):
        return max(
            (_max_str_len_in_obj(v, depth + 1) for v in obj),
            default=0,
        )
    return 0


def test_memory_runtime_step_journal_has_compact_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    G14R.10: ``memory.runtime.step`` — только state/next/action/counters,
    без сырого listing и без текста файлов.
    """
    db = tmp_path / "p-rtstep.sqlite3"
    jpath = tmp_path / "j-rtstep.jsonl"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jpath))
    (tmp_path / "f_rt.py").write_text("a=1\n", encoding="utf-8")
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-rt",
            broker_id="b1",
            namespace="ns-rt",
        ),
    )
    monkeypatch.setattr(w, "_am_file", _am_verbose(), raising=False)
    prov: ChatProvider = _SeqProvider([_minimal_w14()])
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(
        _env(
            project_root=tmp_path,
            path="f_rt.py",
            goal="g",
            query_id="q-rt-1",
        ),
    )
    jstore: MemoryJournalStore = MemoryJournalStore(jpath)
    rstep: list = list(jstore.filter_rows(event_name="memory.runtime.step"))
    assert rstep, "ожидаем memory.runtime.step"
    for row in rstep:
        p0: object = row.payload
        assert isinstance(p0, dict)
        p: dict[str, object] = p0
        for key in (
            "step_id",
            "state",
            "next_state",
            "action_kind",
            "query_id",
        ):
            assert str(p.get(key, "") or "").strip(), f"missing {key}"
        mlen: int = _max_str_len_in_obj(p)
        assert mlen < 4000, (row.event_name, mlen)


def test_memory_command_rejected_logs_error_code_without_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    G14R.10: journal ``memory.command.rejected`` — error_code, без
    вложенного сырого ответа LLM (уникальная long preamble не попадает).
    """
    db = tmp_path / "p-rejpr.sqlite3"
    jpath = tmp_path / "j-rejpr.jsonl"
    log_dir = tmp_path / "chat_rej"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jpath))
    monkeypatch.setenv("AILIT_AGENT_MEMORY_CHAT_LOG_DIR", str(log_dir))
    (tmp_path / "g_rej.py").write_text("y=1\n", encoding="utf-8")
    secret_pre: str = "RAWLLM" + "Z" * 6_000
    bad: str = secret_pre + " " + _minimal_w14()
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-rejpr",
            broker_id="b1",
            namespace="ns-t",
        ),
    )
    monkeypatch.setattr(w, "_am_file", _am_verbose(), raising=False)
    w._chat_debug = (  # noqa: SLF001
        __import__(
            "agent_memory.agent_memory_chat_log",
            fromlist=["AgentMemoryChatDebugLog"],
        ).AgentMemoryChatDebugLog(
            _am_verbose(),
        )
    )
    prov: ChatProvider = _SeqProvider([bad])
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(
        _env(
            project_root=tmp_path,
            path="g_rej.py",
            goal="g",
        ),
    )
    jt: str = jpath.read_text(encoding="utf-8")
    assert "RAWLLM" not in jt, "журнал не хранит полный body LLM"
    rj = list(
        MemoryJournalStore(jpath).filter_rows(
            event_name="memory.command.rejected",
        ),
    )
    assert rj
    assert rj[0].payload.get("error_code") == "w14_command_parse"


def test_memory_result_returned_logs_counts_not_raw_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    G14R.10: ``memory.result.returned`` — только kind counts / n,
    без вложенного текста C-summary из ``agent_memory_result``.
    """
    db = tmp_path / "p-mrr.sqlite3"
    jpath = tmp_path / "j-mrr.jsonl"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jpath))
    (tmp_path / "f_mrr.py").write_text("k=0\n", encoding="utf-8")
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-mrr",
            broker_id="b1",
            namespace="ns-mrr",
        ),
    )
    # Большой goal -> большой ``compat`` c_summary в results (если не
    # finish); журнал result.returned не должен копировать summary.
    long_goal: str = "D" * 3_000
    monkeypatch.setattr(w, "_am_file", _am_verbose(), raising=False)
    prov: ChatProvider = _SeqProvider([_minimal_w14()])
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(
        _env(
            project_root=tmp_path,
            path="f_mrr.py",
            goal=long_goal,
            query_id="q-mrr-1",
        ),
    )
    rrows = list(
        MemoryJournalStore(jpath).filter_rows(
            event_name="memory.result.returned",
        ),
    )
    assert rrows, "ожидаем memory.result.returned"
    for row in rrows:
        pl = row.to_dict()
        dmp: str = json.dumps(pl, ensure_ascii=False)
        assert "D" * 200 not in dmp, "result.returned: без копий длинного text"
    p0: object = rrows[0].payload
    assert isinstance(p0, dict)
    p: dict[str, object] = p0
    assert p.get("query_id")
    assert p.get("status") in ("complete", "partial", "blocked")
    assert "result_kind_counts" in p
    mlen2: int = _max_str_len_in_obj(p)
    assert mlen2 < 2_000, mlen2


def test_memory_logs_do_not_store_full_file_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    События memory.command.* в journal не содержат мегастрок (сырой файл
    / полный ответ), только компактные поля.
    """
    db = tmp_path / "p4.sqlite3"
    jpath = tmp_path / "j4.jsonl"
    monkeypatch.setenv("AILIT_PAG_DB_PATH", str(db))
    monkeypatch.setenv("AILIT_MEMORY_JOURNAL_PATH", str(jpath))
    (tmp_path / "k.py").write_text("k=1\n", encoding="utf-8")
    w = AgentMemoryWorker(
        MemoryAgentConfig(
            chat_id="c-g14logs",
            broker_id="b1",
            namespace="ns-t",
        ),
    )
    monkeypatch.setattr(w, "_am_file", _am_verbose(), raising=False)
    prov: ChatProvider = _SeqProvider([_minimal_w14()])
    monkeypatch.setattr(w, "_provider", prov, raising=False)
    w.handle(_env(project_root=tmp_path, path="k.py", goal="x"))
    store = MemoryJournalStore(jpath)
    for name in (
        "memory.command.requested",
        "memory.command.parsed",
    ):
        for row in store.filter_rows(event_name=name):
            mlen: int = _max_str_len_in_obj(row.payload)
            assert mlen < 4_000, (name, mlen)
