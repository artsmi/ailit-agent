"""G12.6: mechanical chunks, full-B policy, artifacts boundary."""

from __future__ import annotations

import json

from agent_memory.config.agent_memory_config import ArtifactsSubConfig, MemoryLlmSubConfig
from agent_memory.contracts.agent_memory_contracts import MemoryExtractorResultV1
from agent_memory.services.memory_c_segmentation import (
    FullBIngestionPolicy,
    MechanicalChunkCatalogBuilder,
    is_text_like_path,
    should_read_artifact_bytes,
)


def test_forbidden_path_is_not_ingested() -> None:
    pol = FullBIngestionPolicy(ArtifactsSubConfig())
    llm = MemoryLlmSubConfig(max_full_b_bytes=100_000)
    assert pol.classify("pkg/__pycache__/x.pyc", size_bytes=10, llm=llm) == "forbidden"


def test_small_text_file_full_ingest() -> None:
    pol = FullBIngestionPolicy(ArtifactsSubConfig())
    llm = MemoryLlmSubConfig(max_full_b_bytes=32_768)
    assert pol.classify("src/a.py", size_bytes=100, llm=llm) == "full"


def test_oversize_text_uses_chunked() -> None:
    pol = FullBIngestionPolicy(ArtifactsSubConfig())
    llm = MemoryLlmSubConfig(max_full_b_bytes=100)
    m = pol.classify("long.md", size_bytes=5_000_000, llm=llm)
    assert m == "chunked"


def test_markdown_headings_in_catalog() -> None:
    b = MechanicalChunkCatalogBuilder()
    text = "# A\n\nx\n\n## B\n\ny\n"
    ch = b.build(text, "doc.md")
    assert any(c.chunk_kind == "md_section" for c in ch)
    assert ch[0].start_line >= 1


def test_line_windows_for_generic_text() -> None:
    b = MechanicalChunkCatalogBuilder(line_window=20, max_chunks=20)
    lines = "\n".join(f"line {i}" for i in range(1, 55))
    ch = b.build(lines, "f.txt")
    assert len(ch) >= 2
    assert ch[0].chunk_kind == "line_window"


def test_is_text_like_unknown_extension() -> None:
    assert is_text_like_path("Jenkinsfile") is True


def test_artifact_read_requires_explicit() -> None:
    from agent_memory.config.agent_memory_config import SourceBoundaryFilter

    b = ArtifactsSubConfig(allow_explicit_artifact_content=True)
    sf = SourceBoundaryFilter(b)
    assert should_read_artifact_bytes("a/node_modules/x.js", boundary=sf, allow_explicit=True) is True


def test_extractor_result_parses_c_nodes() -> None:
    js = json.dumps(
        {
            "schema": "agent_memory.extractor_result.v1",
            "source": "B:README.md",
            "nodes": [
                {
                    "level": "C",
                    "kind": "md_section",
                    "stable_key": "md:Workflow",
                    "title": "W",
                    "summary": "s",
                    "semantic_locator": {
                        "kind": "md",
                        "heading_path": ["W"],
                    },
                    "line_hint": {"start": 1, "end": 3},
                    "content_fingerprint": "a",
                    "summary_fingerprint": "b",
                    "b_fingerprint": "c",
                    "confidence": 0.9,
                },
            ],
            "link_claims": [],
            "decision": "d",
        },
        separators=(",", ":"),
    )
    r = MemoryExtractorResultV1.from_llm_json(js)
    assert r.source_b_path in ("B:README.md", "README.md")
    assert len(r.nodes) == 1
    assert r.nodes[0].stable_key == "md:Workflow"
