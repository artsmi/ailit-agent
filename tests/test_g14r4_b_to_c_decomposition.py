"""G14R.4: runtime B -> C (plan/14-agent-memory-runtime.md, G14R.4)."""

from __future__ import annotations

from agent_core.runtime.agent_memory_config import (
    ArtifactsSubConfig,
    MemoryLlmSubConfig,
)
from agent_core.runtime.memory_c_segmentation import (
    BToCDecompositionService,
    FullBIngestionPolicy,
)


def _policy() -> FullBIngestionPolicy:
    return FullBIngestionPolicy(ArtifactsSubConfig())


def _llm() -> MemoryLlmSubConfig:
    return MemoryLlmSubConfig()


def test_decompose_b_to_c_python_function_boundaries() -> None:
    """Top-level def -> C с kind function и валидным line range."""
    svc = BToCDecompositionService()
    code = (
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "def beta():\n"
        "    return 2\n"
    )
    path = "pkg/mod.py"
    raw = code.encode("utf-8")
    bounds = svc.decompose_b_to_c(
        path,
        code,
        size_bytes=len(raw),
        policy=_policy(),
        llm=_llm(),
    )
    assert len(bounds) == 2
    titles = {b.title for b in bounds}
    assert titles == {"alpha", "beta"}
    for b in bounds:
        assert b.semantic_kind == "function"
        assert b.pag_kind == "function"
        assert b.start_line >= 1
        assert b.end_line >= b.start_line


def test_decompose_b_to_c_markdown_sections() -> None:
    """Markdown: секции по заголовкам -> semantic_kind section."""
    svc = BToCDecompositionService()
    text = (
        "# Title\n"
        "\n"
        "## First\n"
        "body one\n"
        "\n"
        "## Second\n"
        "body two\n"
    )
    path = "doc/a.md"
    b = svc.decompose_b_to_c(
        path,
        text,
        size_bytes=len(text.encode("utf-8")),
        policy=_policy(),
        llm=_llm(),
    )
    assert b
    for x in b:
        assert x.semantic_kind == "section"
        assert x.pag_kind == "section"
    line_spans = {
        (x.start_line, x.end_line) for x in b
    }
    assert len(line_spans) == len(b)


def test_decompose_b_to_c_text_line_windows_when_no_structure() -> None:
    """Плоский .txt без структуры -> line_window чанки."""
    svc = BToCDecompositionService()
    text = "\n".join(f"line {i}" for i in range(1, 500))
    path = "notes/flat.txt"
    raw = text.encode("utf-8")
    bounds = svc.decompose_b_to_c(
        path,
        text,
        size_bytes=len(raw),
        policy=_policy(),
        llm=_llm(),
    )
    assert bounds
    assert all(b.semantic_kind == "line_window" for b in bounds)
    for b in bounds:
        assert b.start_line <= b.end_line


def test_decompose_b_to_c_respects_source_boundary_policy() -> None:
    """forbidden path -> пустой список C."""
    svc = BToCDecompositionService()
    code = "def x():\n    return 0\n"
    path = "node_modules/some-pkg/legacy.py"
    b = svc.decompose_b_to_c(
        path,
        code,
        size_bytes=len(code.encode("utf-8")),
        policy=_policy(),
        llm=_llm(),
    )
    assert b == []
