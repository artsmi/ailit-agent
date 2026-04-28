"""G13.4: canonical C-node identity, line windows, caps (D13.6, D13.5)."""

from __future__ import annotations

import json

from agent_core.memory.sqlite_pag import PagNode
from agent_core.runtime.agent_memory_contracts import (
    MemoryExtractorResultV1,
    MemoryLineHintV1,
    MemorySemanticLocatorV1,
)
from agent_core.runtime.memory_c_extractor_prompt import (
    MemoryExtractorPromptBuilder,
)
from agent_core.runtime.memory_c_remap import (
    CRemapSpanResult,
    SemanticCRemapService,
    _line_hint_search_windows,
    _remap_node_span,
)
from agent_core.runtime.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)
from agent_core.runtime.semantic_c_extraction import (
    C_NODE_EXCERPT_MAX_CHARS,
    C_NODE_FULL_B_MAX_CHARS,
    SemanticCNodeCandidate,
    SemanticCNodeValidator,
    SemanticLocatorNormalizer,
    StableKeyNormalizer,
    clamp_b_text_for_policy,
)


def test_line_hint_is_not_identity() -> None:
    """Два разных stable_key при одинаковом line_hint — разные сущности."""
    loc = MemorySemanticLocatorV1(
        kind="function",
        raw={"name": "a", "signature": "a()"},
    )
    lh = MemoryLineHintV1(start=10, end=20)
    c1 = SemanticCNodeCandidate(
        stable_key="py:function:a",
        semantic_locator=loc,
        level="C",
        kind="function",
        title="a",
        summary="s",
        line_hint=lh,
        content_fingerprint="x",
        summary_fingerprint="y",
        confidence=0.9,
        source_boundary_decision="allowed",
        b_node_id="B:f.py",
        b_fingerprint="bfp",
    )
    c2 = SemanticCNodeCandidate(
        stable_key="py:function:b",
        semantic_locator=MemorySemanticLocatorV1(
            kind="function",
            raw={"name": "b", "signature": "b()"},
        ),
        level="C",
        kind="function",
        title="b",
        summary="s",
        line_hint=lh,
        content_fingerprint="x",
        summary_fingerprint="y",
        confidence=0.9,
        source_boundary_decision="allowed",
        b_node_id="B:f.py",
        b_fingerprint="bfp",
    )
    assert c1.stable_key != c2.stable_key
    assert c1.to_pag_attrs()["stable_key"] != c2.to_pag_attrs()["stable_key"]


def test_lookup_expands_100_200_500_then_llm() -> None:
    """Окна: old range, ±100/200/500, full-B только если len(B) <= cap."""
    n = 200
    text = "\n".join("l" for _ in range(n))
    assert len(text) < C_NODE_FULL_B_MAX_CHARS
    hint = MemoryLineHintV1(start=50, end=60)
    wins = _line_hint_search_windows(hint, n, text)
    assert wins[0] == (50, 60)
    assert wins[1] == (1, 160)
    assert wins[2] == (1, 200)
    huge = ("x" * 120 + "\n") * 400
    assert len(huge) > C_NODE_FULL_B_MAX_CHARS
    hn = len(huge.splitlines())
    wh = _line_hint_search_windows(
        MemoryLineHintV1(5, 6),
        hn,
        huge,
    )
    assert len(wh) == len(wins) - 1


def test_full_b_above_cap_is_not_sent_to_llm() -> None:
    """Экстрактор: clamp к policy, не сырой full B."""
    pol = MemoryLlmOptimizationPolicy.default()
    huge = "Z" * (C_NODE_FULL_B_MAX_CHARS + 10_000)
    out = clamp_b_text_for_policy(huge, pol, phase="extractor")
    assert len(out) <= C_NODE_EXCERPT_MAX_CHARS + 2
    p2 = MemoryExtractorPromptBuilder.build_user_payload(
        b_path="x.py",
        b_fingerprint="fp",
        b_text=huge,
        full_b=True,
        chunk_catalog=(),
        excluded_nodes=(),
        policy=pol,
    )
    assert p2.get("full_b") is False
    assert "b_text_omitted" in p2


def test_mechanical_thresholds_default() -> None:
    p = MemoryLlmOptimizationPolicy.default()
    assert p.threshold_mechanical_accept == 0.85
    assert p.threshold_ambiguous_min == 0.5


def test_remap_py_moves_within_window_mechanical() -> None:
    """Сдвиг def: AST находит span (пример G13.4)."""
    lines = [""] * 200
    lines[129] = "def applyPagGraphTraceDelta(x: int) -> int:"
    lines[130] = "    return x"
    text = "\n".join(lines)
    n = PagNode(
        namespace="n",
        node_id="C:x#1",
        level="C",
        kind="function",
        path="x.py",
        title="applyPagGraphTraceDelta",
        summary="s",
        attrs={
            "name": "applyPagGraphTraceDelta",
            "line_hint": {"start": 80, "end": 90},
        },
        fingerprint="f",
        staleness_state="fresh",
        source_contract="v1",
        updated_at="",
    )
    r = _remap_node_span(
        text=text,
        lines=lines,
        rel_lower="x.py",
        node=n,
        policy=MemoryLlmOptimizationPolicy.default(),
    )
    assert isinstance(r, CRemapSpanResult)
    assert r.applied
    assert r.start >= 128


def test_ambiguous_two_defs_needs_llm() -> None:
    """Два `function dup` в окне (TS) — needs_llm_remap."""
    src = "function dup(){}\nfunction dup(){}\n"
    lines = src.splitlines()
    text = "\n".join(lines)
    n = PagNode(
        namespace="n",
        node_id="C:m#1",
        level="C",
        kind="function",
        path="m.ts",
        title="dup",
        summary="s",
        attrs={
            "name": "dup",
            "line_hint": {"start": 1, "end": 1},
        },
        fingerprint="f",
        staleness_state="fresh",
        source_contract="v1",
        updated_at="",
    )
    r = _remap_node_span(
        text=text,
        lines=lines,
        rel_lower="m.ts",
        node=n,
        policy=MemoryLlmOptimizationPolicy.default(),
    )
    assert r.needs_llm and not r.applied


def test_semantic_c_validator_bounds() -> None:
    v = SemanticCNodeValidator(max_summary_chars=100)
    loc = MemorySemanticLocatorV1(kind="x", raw={"a": 1})
    c = SemanticCNodeCandidate(
        stable_key="k",
        semantic_locator=loc,
        level="C",
        kind="k",
        title="t",
        summary="a" * 200,
        line_hint=MemoryLineHintV1(1, 1),
        content_fingerprint="c",
        summary_fingerprint="s",
        confidence=1.0,
        source_boundary_decision="ok",
        b_node_id="B:p",
        b_fingerprint="b",
    )
    ok, _msg = v.validate(c, b_path="p.py", n_lines=5)
    assert not ok
    c3 = SemanticCNodeCandidate(
        stable_key="k2",
        semantic_locator=loc,
        level="C",
        kind="k",
        title="t",
        summary="s",
        line_hint=MemoryLineHintV1(3, 3),
        content_fingerprint="c",
        summary_fingerprint="s",
        confidence=1.0,
        source_boundary_decision="ok",
        b_node_id="B:p",
        b_fingerprint="b",
    )
    ok3, _ = v.validate(c3, b_path="p.py", n_lines=1)
    assert not ok3


def test_extractor_result_requires_semantic_locator() -> None:
    """Без semantic_locator C-нода не принимается."""
    raw = {
        "schema": "agent_memory.extractor_result.v1",
        "source": "a.py",
        "nodes": [
            {
                "level": "C",
                "stable_key": "k",
                "title": "t",
                "summary": "s",
            },
        ],
    }
    r = MemoryExtractorResultV1.from_llm_json(json.dumps(raw))
    assert r.nodes == ()


def test_extractor_excluded_nodes_in_prompt() -> None:
    pol = MemoryLlmOptimizationPolicy.default()
    js = MemoryExtractorPromptBuilder.build_user_json(
        b_path="a.png",
        b_fingerprint="fp",
        b_text="x",
        full_b=False,
        chunk_catalog=(),
        excluded_nodes=["cache/artifact"],
        policy=pol,
    )
    o = json.loads(js)
    assert o["excluded_nodes"] == ["cache/artifact"]


def test_stable_key_normalize_and_dedupe() -> None:
    a = StableKeyNormalizer.normalize("  a/B:c  ")
    b = StableKeyNormalizer.normalize("  a/B:c  ")
    assert a == b
    s = StableKeyNormalizer.with_conflict_suffix("key", {"key"})
    assert s.startswith("key#")


def test_code_locator_normalization() -> None:
    loc = MemorySemanticLocatorV1(
        kind="function",
        raw={
            "name": "f",
            "signature": "f  (  \n)  // x",
        },
    )
    n2 = SemanticLocatorNormalizer.normalize(loc, module_path="m.py")
    assert "f" in n2.raw.get("signature", "")


def test_service_accepts_injected_policy(tmp_path) -> None:
    from agent_core.memory.sqlite_pag import SqlitePagStore
    from agent_core.runtime.pag_graph_write_service import PagGraphWriteService

    pol = MemoryLlmOptimizationPolicy.default()
    db = tmp_path / "z.sqlite3"
    store = SqlitePagStore(db)
    s = SemanticCRemapService(PagGraphWriteService(store), policy=pol)
    assert s._policy is pol
