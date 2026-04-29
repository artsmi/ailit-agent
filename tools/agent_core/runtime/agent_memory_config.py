"""Global AgentMemory config: ~/.ailit/agent-memory/config.yaml (G12.5)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, MutableMapping, Sequence

import yaml

from agent_core.runtime.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)


@dataclass(frozen=True, slots=True)
class MemoryLlmSubConfig:
    """Пороги LLM-payload и обхода графа из YAML."""

    max_full_b_bytes: int = 32_768
    max_full_b_chars: int = 32_768
    max_turns: int = 4
    max_selected_b: int = 8
    max_c_per_b: int = 40
    max_reads_per_turn: int = 8
    max_summary_chars: int = 160
    max_reason_chars: int = 80
    max_decision_chars: int = 240


@dataclass(frozen=True, slots=True)
class MemoryRuntimeSubConfig:
    """W14 runtime loop limits."""

    max_turns: int = 50
    max_selected_b: int = 50
    max_c_per_b: int = 100
    max_total_c: int = 1_000
    max_reads_per_turn: int = 10
    max_summary_chars: int = 150
    max_reason_chars: int = 50
    max_decision_chars: int = 150
    min_child_summary_coverage: float = 0.5


@dataclass(frozen=True, slots=True)
class DPolicySubConfig:
    """Политика D-нод (YAML)."""

    max_d_per_query: int = 1
    min_linked_nodes: int = 2
    allowed_kinds: tuple[str, ...] = (
        "query_digest",
        "compact_summary",
        "decision_digest",
        "restored_context",
    )


@dataclass(frozen=True, slots=True)
class ArtifactsSubConfig:
    """Семантика артефактов (YAML)."""

    allow_explicit_artifact_content: bool = True


@dataclass(frozen=True, slots=True)
class MemoryDebugSubConfig:
    """Отладка: полные LLM-логи в ~/.ailit/agent-memory/chat_logs/."""

    verbose: int = 0


@dataclass(frozen=True, slots=True)
class MemoryYamlRoot:
    """Корневой объект `memory:` в config.yaml."""

    llm: MemoryLlmSubConfig
    runtime: MemoryRuntimeSubConfig
    llm_optimization: MemoryLlmOptimizationPolicy
    d_policy: DPolicySubConfig
    artifacts: ArtifactsSubConfig
    debug: MemoryDebugSubConfig


@dataclass(frozen=True, slots=True)
class AgentMemoryFileConfig:
    """Содержимое ~/.ailit/agent-memory/config.yaml."""

    memory: MemoryYamlRoot = field(
        default_factory=lambda: MemoryYamlRoot(
            llm=MemoryLlmSubConfig(),
            runtime=MemoryRuntimeSubConfig(),
            llm_optimization=MemoryLlmOptimizationPolicy.default(),
            d_policy=DPolicySubConfig(),
            artifacts=ArtifactsSubConfig(),
            debug=MemoryDebugSubConfig(),
        )
    )

    def to_nested_dict(self) -> dict[str, Any]:
        """Сериализация для YAML (человеко-читаемо)."""
        m = self.memory
        opt = m.llm_optimization
        return {
            "memory": {
                "llm": {
                    "max_full_b_bytes": m.llm.max_full_b_bytes,
                    "max_full_b_chars": m.llm.max_full_b_chars,
                    "max_turns": m.llm.max_turns,
                    "max_selected_b": m.llm.max_selected_b,
                    "max_c_per_b": m.llm.max_c_per_b,
                    "max_reads_per_turn": m.llm.max_reads_per_turn,
                    "max_summary_chars": m.llm.max_summary_chars,
                    "max_reason_chars": m.llm.max_reason_chars,
                    "max_decision_chars": m.llm.max_decision_chars,
                    "enabled": opt.enabled,
                    "model": opt.model,
                    "temperature": opt.temperature,
                    "max_memory_turns": opt.max_memory_turns,
                    "thinking": {
                        "enabled": opt.thinking_enabled,
                        "allow_for_remap": opt.thinking_allow_for_remap,
                        "effort": opt.thinking_effort,
                    },
                    "planner": {
                        "max_input_chars": opt.planner_max_input_chars,
                        "max_output_tokens": opt.planner_max_output_tokens,
                        "max_candidates": opt.planner_max_candidates,
                    },
                    "extractor": {
                        "max_excerpt_chars": opt.extractor_max_excerpt_chars,
                        "max_output_tokens": opt.extractor_max_output_tokens,
                        "max_candidates": opt.extractor_max_candidates,
                    },
                    "remap": {
                        "max_excerpt_chars": opt.remap_max_excerpt_chars,
                        "max_output_tokens": opt.remap_max_output_tokens,
                        "max_candidates": opt.remap_max_candidates,
                    },
                    "thresholds": {
                        "mechanical_accept": opt.threshold_mechanical_accept,
                        "ambiguous_min": opt.threshold_ambiguous_min,
                    },
                    "cache": {
                        "enabled": opt.cache_enabled,
                    },
                },
                "runtime": {
                    "max_turns": m.runtime.max_turns,
                    "max_selected_b": m.runtime.max_selected_b,
                    "max_c_per_b": m.runtime.max_c_per_b,
                    "max_total_c": m.runtime.max_total_c,
                    "max_reads_per_turn": m.runtime.max_reads_per_turn,
                    "max_summary_chars": m.runtime.max_summary_chars,
                    "max_reason_chars": m.runtime.max_reason_chars,
                    "max_decision_chars": m.runtime.max_decision_chars,
                    "min_child_summary_coverage": (
                        m.runtime.min_child_summary_coverage
                    ),
                },
                "d_policy": {
                    "max_d_per_query": m.d_policy.max_d_per_query,
                    "min_linked_nodes": m.d_policy.min_linked_nodes,
                    "allowed_kinds": list(m.d_policy.allowed_kinds),
                },
                "artifacts": {
                    "allow_explicit_artifact_content": (
                        m.artifacts.allow_explicit_artifact_content
                    ),
                },
                "debug": {
                    "verbose": m.debug.verbose,
                },
            }
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AgentMemoryFileConfig:
        """Разбор YAML-дерева с дефолтами на отсутствующих ключах."""
        mem: Any = raw.get("memory", {})
        if not isinstance(mem, Mapping):
            mem = {}
        llm: Any = mem.get("llm", {})
        runtime: Any = mem.get("runtime", {})
        dp: Any = mem.get("d_policy", {})
        art: Any = mem.get("artifacts", {})
        llm_d = (
            {
                "max_full_b_bytes": int(llm.get("max_full_b_bytes", 32_768)),
                "max_full_b_chars": int(llm.get("max_full_b_chars", 32_768)),
                "max_turns": int(llm.get("max_turns", 4)),
                "max_selected_b": int(llm.get("max_selected_b", 8)),
                "max_c_per_b": int(llm.get("max_c_per_b", 40)),
                "max_reads_per_turn": int(llm.get("max_reads_per_turn", 8)),
                "max_summary_chars": int(llm.get("max_summary_chars", 160)),
                "max_reason_chars": int(llm.get("max_reason_chars", 80)),
                "max_decision_chars": int(llm.get("max_decision_chars", 240)),
            }
            if isinstance(llm, Mapping)
            else {}
        )
        rt_d = (
            {
                "max_turns": int(runtime.get("max_turns", 50)),
                "max_selected_b": int(runtime.get("max_selected_b", 50)),
                "max_c_per_b": int(runtime.get("max_c_per_b", 100)),
                "max_total_c": int(runtime.get("max_total_c", 1_000)),
                "max_reads_per_turn": int(
                    runtime.get("max_reads_per_turn", 10),
                ),
                "max_summary_chars": int(
                    runtime.get("max_summary_chars", 150),
                ),
                "max_reason_chars": int(runtime.get("max_reason_chars", 50)),
                "max_decision_chars": int(
                    runtime.get("max_decision_chars", 150),
                ),
                "min_child_summary_coverage": float(
                    runtime.get("min_child_summary_coverage", 0.5),
                ),
            }
            if isinstance(runtime, Mapping)
            else {}
        )
        kinds: tuple[str, ...] = (
            "query_digest",
            "compact_summary",
            "decision_digest",
            "restored_context",
        )
        if isinstance(dp, Mapping) and "allowed_kinds" in dp and isinstance(
            dp["allowed_kinds"],
            list,
        ):
            kinds = tuple(
                str(x).strip() for x in dp["allowed_kinds"] if str(x).strip()
            ) or kinds
        d_d = {
            "max_d_per_query": int(dp.get("max_d_per_query", 1)) if isinstance(
                dp,
                Mapping,
            ) else 1,
            "min_linked_nodes": (
                int(dp.get("min_linked_nodes", 2))
                if isinstance(dp, Mapping)
                else 2
            ),
            "allowed_kinds": kinds,
        }
        a_d = {
            "allow_explicit_artifact_content": bool(
                art.get("allow_explicit_artifact_content", True),
            )
            if isinstance(art, Mapping)
            else True,
        }
        llm_opt = MemoryLlmOptimizationPolicy.from_memory_llm_mapping(
            dict(llm) if isinstance(llm, Mapping) else {},
        )
        dbg: Any = mem.get("debug", {})
        verbose_i = 0
        if isinstance(dbg, Mapping):
            try:
                verbose_i = int(dbg.get("verbose", 0))
            except (TypeError, ValueError):
                verbose_i = 0
        verbose_i = 1 if verbose_i == 1 else 0
        return cls(
            memory=MemoryYamlRoot(
                llm=MemoryLlmSubConfig(
                    max_full_b_bytes=max(
                        1,
                        min(llm_d["max_full_b_bytes"], 1_000_000),
                    ),
                    max_full_b_chars=max(
                        1,
                        min(llm_d["max_full_b_chars"], 1_000_000),
                    ),
                    max_turns=max(1, min(llm_d["max_turns"], 64)),
                    max_selected_b=max(
                        0,
                        min(llm_d["max_selected_b"], 10_000),
                    ),
                    max_c_per_b=max(0, min(llm_d["max_c_per_b"], 10_000)),
                    max_reads_per_turn=max(
                        0,
                        min(llm_d["max_reads_per_turn"], 1_000),
                    ),
                    max_summary_chars=max(
                        0,
                        min(llm_d["max_summary_chars"], 2_000),
                    ),
                    max_reason_chars=max(
                        0,
                        min(llm_d["max_reason_chars"], 1_000),
                    ),
                    max_decision_chars=max(
                        0,
                        min(llm_d["max_decision_chars"], 2_000),
                    ),
                ),
                runtime=MemoryRuntimeSubConfig(
                    max_turns=max(1, min(rt_d["max_turns"], 1_000)),
                    max_selected_b=max(0, min(rt_d["max_selected_b"], 10_000)),
                    max_c_per_b=max(0, min(rt_d["max_c_per_b"], 10_000)),
                    max_total_c=max(0, min(rt_d["max_total_c"], 100_000)),
                    max_reads_per_turn=max(
                        0,
                        min(rt_d["max_reads_per_turn"], 1_000),
                    ),
                    max_summary_chars=max(
                        0,
                        min(rt_d["max_summary_chars"], 2_000),
                    ),
                    max_reason_chars=max(
                        0,
                        min(rt_d["max_reason_chars"], 1_000),
                    ),
                    max_decision_chars=max(
                        0,
                        min(rt_d["max_decision_chars"], 2_000),
                    ),
                    min_child_summary_coverage=max(
                        0.0,
                        min(rt_d["min_child_summary_coverage"], 1.0),
                    ),
                ),
                llm_optimization=llm_opt,
                d_policy=DPolicySubConfig(
                    max_d_per_query=max(0, min(d_d["max_d_per_query"], 1_000)),
                    min_linked_nodes=max(0, d_d["min_linked_nodes"]),
                    allowed_kinds=d_d["allowed_kinds"],
                ),
                artifacts=ArtifactsSubConfig(
                    allow_explicit_artifact_content=bool(
                        a_d["allow_explicit_artifact_content"]
                    )
                ),
                debug=MemoryDebugSubConfig(verbose=verbose_i),
            )
        )


class AgentMemoryConfigPaths:
    """Пути к config AgentMemory (переопределяемые env для тестов)."""

    @staticmethod
    def default_file_path() -> Path:
        """Return AgentMemory config path with env override."""
        ex = os.environ.get("AILIT_AGENT_MEMORY_CONFIG", "").strip()
        if ex:
            return Path(ex).expanduser().resolve()
        return (
            Path.home() / ".ailit" / "agent-memory" / "config.yaml"
        ).resolve()

    @staticmethod
    def ensure_parent(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)


def load_or_create_agent_memory_config() -> AgentMemoryFileConfig:
    """
    Загрузить или создать `AgentMemory` config с дефолтами.

    При отсутствии файла создаётся каталог и пишется YAML.
    """
    p = AgentMemoryConfigPaths.default_file_path()
    if not p.is_file():
        AgentMemoryConfigPaths.ensure_parent(p)
        cfg = AgentMemoryFileConfig()
        header = (
            "# Auto-created by ailit (G12.5) — "
            "see plan/12-pag-trace-delta-desktop-sync.md\n"
        )
        p.write_text(
            header
            + yaml.safe_dump(
                cfg.to_nested_dict(),
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return cfg
    raw: Any
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f.read()) or {}
    if not isinstance(raw, Mapping):
        return AgentMemoryFileConfig()
    return AgentMemoryFileConfig.from_mapping(dict(raw))


class SourceBoundaryFilter:
    """Механический pre-filter: запрещённые сегменты/суффиксы (Workflow 12)."""

    _FORBIDDEN_DIR_SEGMENTS: Final[frozenset[str]] = frozenset(
        {
            "node_modules",
            "vendor",
            ".venv",
            "venv",
            "site-packages",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".cache",
            ".git",
            ".hg",
            ".svn",
            ".idea",
            ".vscode",
            "build",
            "dist",
            "out",
            "target",
            "install",
            "log",
        }
    )

    _FORBIDDEN_SUFFIX: Final[tuple[str, ...]] = (
        ".pyc",
        ".pyo",
        ".o",
        ".obj",
        ".so",
        ".dll",
        ".dylib",
        ".a",
        ".lib",
        ".class",
        ".jar",
        ".wasm",
        ".min.js",
        ".bundle.js",
    )

    def __init__(self, config: ArtifactsSubConfig) -> None:
        self._artifacts: ArtifactsSubConfig = config

    def is_forbidden_source_path(self, posixish: str) -> bool:
        """
        True, если путь (относительный) матчит forbidden-правила.

        `artifacts.allow_explicit_artifact_content` влияет на эвристику «жёстко
        нельзя» (всё равно true для VCS/кэшей, если не расширять политику).
        """
        s = str(posixish or "").strip().replace("\\", "/").lstrip("/")
        if not s:
            return True
        parts: list[str] = [
            x for x in s.split("/") if x and x not in (".", "..")
        ]
        for part in parts:
            low = part.lower()
            for seg in self._FORBIDDEN_DIR_SEGMENTS:
                if self._segment_matches(seg, low, part):
                    return True
        for suf in self._FORBIDDEN_SUFFIX:
            if s.lower().endswith(suf):
                return True
        return bool(re.search(r"cmake-build-", s, re.IGNORECASE))

    @staticmethod
    def _segment_matches(seg: str, low: str, part: str) -> bool:
        if low == seg or low.startswith(f"{seg}/"):
            return True
        if part == seg or part.lower() == seg:
            return True
        return False


def _json_extract_object(text: str) -> str | None:
    """Первый балансный JSON-object в строке."""
    t = (text or "").strip()
    start: int = t.find("{")
    if start < 0:
        return None
    depth: int = 0
    for i, ch in enumerate(t[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    return None


@dataclass(frozen=True, slots=True)
class ResultOnlyClamp:
    """Локальное ужатие полей LLM-ответа по config."""

    def apply_to_memory_decision(
        self,
        raw: MutableMapping[str, Any],
        *,
        max_summary: int,
        max_reason: int,
        max_decision: int,
    ) -> None:
        for key, mx in (
            ("decision_summary", max_decision),
            ("recommended_next_step", max_decision),
            ("next_action", max_reason),
        ):
            v = raw.get(key)
            if isinstance(v, str) and len(v) > mx:
                raw[key] = v[:mx] + "…"
        s_nodes = raw.get("selected_nodes")
        if isinstance(s_nodes, list):
            raw["selected_nodes"] = [str(x) for x in s_nodes[: max(0, 500)]]


def parse_memory_json_with_retry(
    text: str,
) -> dict[str, Any]:
    """
    JSON-only: при невалидном JSON — повтор с извлечением подстроки `{...}`.
    """
    t = (text or "").strip()
    try:
        o = json.loads(t)
    except json.JSONDecodeError as exc0:
        sub: str | None = _json_extract_object(t)
        if sub is None:
            raise ValueError(f"invalid memory json: {exc0}") from exc0
        try:
            o = json.loads(sub)
        except json.JSONDecodeError as exc1:
            raise ValueError(f"invalid memory json: {exc1}") from exc1
    if not isinstance(o, dict):
        raise ValueError("memory json must be an object")
    return o


@dataclass(frozen=True, slots=True)
class MemoryPlannerResultV1:
    """`agent_memory.planner_result.v1` (compact)."""

    action: str
    selected: tuple[Mapping[str, Any], ...]
    exclude: tuple[Mapping[str, Any], ...]
    decision: str

    @classmethod
    def parse(
        cls,
        text: str,
        *,
        max_decision: int,
    ) -> MemoryPlannerResultV1:
        """Разбор + обрезка `decision`."""
        raw: dict[str, Any] = parse_memory_json_with_retry(text)
        sch = str(raw.get("schema", "") or "")
        if (
            sch
            and "planner" not in sch
            and sch != "agent_memory.planner_result.v1"
        ):
            raise ValueError("unexpected planner schema id")
        action: str = str(raw.get("action", "") or "stop")
        sel: Any = raw.get("selected", [])
        ex: Any = raw.get("exclude", [])
        if not isinstance(sel, list):
            sel = []
        if not isinstance(ex, list):
            ex0 = raw.get("excluded_nodes", [])
            ex = list(ex0) if isinstance(ex0, list) else []
        dec: str = str(raw.get("decision", "") or raw.get("stop", "") or "")
        if len(dec) > max_decision:
            dec = dec[:max_decision] + "…"
        out_sel: list[Mapping[str, Any]] = [
            dict(x) for x in sel if isinstance(x, Mapping)
        ][:8]
        out_ex: list[Mapping[str, Any]] = [
            dict(x) for x in ex if isinstance(x, Mapping)
        ][:16]
        return cls(
            action=action,
            selected=tuple(out_sel),
            exclude=tuple(out_ex),
            decision=dec,
        )


@dataclass(frozen=True, slots=True)
class CompactJournalFields:
    """Поля compact journal (без raw excerpt)."""

    task: str
    action: str
    selected: tuple[Mapping[str, Any], ...]
    exclude: tuple[Mapping[str, Any], ...]
    reads: tuple[Mapping[str, Any], ...]
    decision: str
    request_id: str
    event_name: str
    d_creation_gate: str = ""
    d_creation_reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        o: dict[str, Any] = {
            "schema": "agent_memory.journal.compact_v1",
            "task": self.task,
            "action": self.action,
            "selected": [dict(x) for x in self.selected],
            "exclude": [dict(x) for x in self.exclude],
            "reads": [dict(x) for x in self.reads],
            "decision": self.decision,
            "request_id": self.request_id,
            "event_name": self.event_name,
        }
        if self.d_creation_gate:
            o["d_creation"] = {
                "gate": self.d_creation_gate,
                "reason": self.d_creation_reason,
            }
        return o


def build_compact_query_journal(
    *,
    event_name: str,
    request_id: str,
    task_summary: str,
    decision_summary: str,
    node_ids: Sequence[str] | None = None,
    d_creation_gate: str = "",
    d_creation_reason: str = "",
) -> CompactJournalFields:
    """Compact query_context response wrapper without raw artifacts."""
    t = (task_summary or "")[:2_000]
    d = (decision_summary or "")[:1_000]
    sel: tuple[Mapping[str, Any], ...] = tuple(
        ({"id": n} for n in (node_ids or ())),
    )
    return CompactJournalFields(
        task=t,
        action=event_name,
        selected=sel,
        exclude=(),
        reads=(),
        decision=d,
        request_id=request_id,
        event_name=event_name,
        d_creation_gate=(d_creation_gate or "")[:32],
        d_creation_reason=(d_creation_reason or "")[:240],
    )
