"""
G14R.7: сборка agent_memory_result.v1 из finish_decision (plan W14 §1.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from agent_memory.sqlite_pag import PagNode, SqlitePagStore
from agent_work.tool_runtime.multi_root_paths import (
    validate_agent_memory_relative_path,
)


@dataclass(frozen=True, slots=True)
class PathValidationRecord:
    """Отклонённый путь (лог/частичный результат)."""

    raw: str
    code: str


@dataclass
class FinishDecisionAssemblyState:
    """Состояние прохода assemble_finish_decision_results."""

    results: list[dict[str, Any]] = field(default_factory=list)
    path_rejects: list[PathValidationRecord] = field(default_factory=list)


class FileLineRangeReader:
    """Чтение диапазона строк из UTF-8 файла (одна ответственность)."""

    @staticmethod
    def read_range(
        file_path: Path,
        *,
        start_line: int,
        end_line: int,
    ) -> str:
        if start_line < 1 or end_line < start_line:
            return ""
        lines: list[str] = []
        with file_path.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                if i > end_line:
                    break
                if i >= start_line:
                    lines.append(line)
        return "".join(lines).rstrip("\n")


class PagBackedEvidenceReader:
    """C-ноды PAG: summary и границы строк для read_lines."""

    def __init__(self, store: SqlitePagStore) -> None:
        self._store = store

    def fetch_c_node(
        self,
        *,
        namespace: str,
        node_id: str,
    ) -> PagNode | None:
        n = self._store.fetch_node(namespace=namespace, node_id=node_id)
        if n is None or str(n.level or "").upper() != "C":
            return None
        return n

    @staticmethod
    def line_span_from_node(node: PagNode) -> tuple[int, int] | None:
        attrs: Mapping[str, Any] = node.attrs or {}
        try:
            sl = int(attrs.get("start_line", 0) or 0)
            el = int(attrs.get("end_line", 0) or 0)
        except (TypeError, ValueError):
            return None
        if sl < 1 or el < sl:
            return None
        return (sl, el)


class FinishDecisionResultAssembler:
    """
    Сборка results[] для agent_memory_result.v1 (finish_decision).

    §1.3: c_summary; read_lines; b_path (см. plan §1.3 поля).
    """

    def __init__(
        self,
        *,
        project_root: Path,
        namespace: str,
        store: SqlitePagStore,
    ) -> None:
        self._root = project_root.expanduser().resolve()
        self._ns = str(namespace or "").strip()
        self._store = store
        self._evidence = PagBackedEvidenceReader(store)
        self._line_reader = FileLineRangeReader()

    def assemble_finish_decision_results(
        self,
        selected_results: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[PathValidationRecord]]:
        state = FinishDecisionAssemblyState()
        for raw in selected_results:
            if not isinstance(raw, dict):
                continue
            self._one_item(state, raw)
        return (state.results, state.path_rejects)

    def _one_item(
        self,
        state: FinishDecisionAssemblyState,
        item: Mapping[str, Any],
    ) -> None:
        kind = str(item.get("kind", "") or "").strip()
        path_in = str(item.get("path", "") or "")
        reason = str(item.get("reason", "") or "")[:1_200]
        node_id = str(item.get("node_id", "") or "").strip()
        safe_path = validate_agent_memory_relative_path(path_in)
        if safe_path is None:
            state.path_rejects.append(
                PathValidationRecord(
                    raw=path_in,
                    code="invalid_relative_path",
                ),
            )
            return
        if kind == "b_path":
            state.results.append(
                {
                    "kind": "b_path",
                    "path": safe_path,
                    "c_node_id": None,
                    "summary": None,
                    "read_lines": [],
                    "reason": reason or "b_path_target",
                },
            )
            return
        if kind == "c_summary":
            if not node_id:
                state.path_rejects.append(
                    PathValidationRecord(
                        raw=path_in,
                        code="c_summary_missing_node_id",
                    ),
                )
                return
            node = self._evidence.fetch_c_node(
                namespace=self._ns,
                node_id=node_id,
            )
            if node is None:
                state.path_rejects.append(
                    PathValidationRecord(
                        raw=node_id,
                        code="c_node_not_found",
                    ),
                )
                return
            summ = str(node.summary or "").strip() or "(no summary)"
            state.results.append(
                {
                    "kind": "c_summary",
                    "path": safe_path,
                    "c_node_id": node_id,
                    "summary": summ,
                    "read_lines": [],
                    "reason": reason or "c_summary",
                },
            )
            return
        if kind == "read_lines":
            if not node_id:
                state.path_rejects.append(
                    PathValidationRecord(
                        raw=path_in,
                        code="read_lines_missing_node_id",
                    ),
                )
                return
            node: PagNode | None = self._evidence.fetch_c_node(
                namespace=self._ns,
                node_id=node_id,
            )
            span: tuple[int, int] | None = self._span_from_item_or_node(
                item,
                node,
            )
            if span is None:
                state.path_rejects.append(
                    PathValidationRecord(
                        raw=node_id,
                        code="read_lines_no_line_span",
                    ),
                )
                return
            sl, el = span
            abs_path = (self._root / safe_path).resolve()
            try:
                abs_r = abs_path
                abs_r.relative_to(self._root)
            except ValueError:
                state.path_rejects.append(
                    PathValidationRecord(
                        raw=safe_path,
                        code="path_outside_project_root",
                    ),
                )
                return
            except OSError:
                state.path_rejects.append(
                    PathValidationRecord(
                        raw=safe_path,
                        code="path_resolve_error",
                    ),
                )
                return
            if not abs_r.is_file():
                state.path_rejects.append(
                    PathValidationRecord(
                        raw=safe_path,
                        code="read_lines_file_not_found",
                    ),
                )
                return
            text = self._line_reader.read_range(
                abs_r,
                start_line=sl,
                end_line=el,
            )
            state.results.append(
                {
                    "kind": "read_lines",
                    "path": safe_path,
                    "c_node_id": node_id,
                    "summary": None,
                    "read_lines": [
                        {
                            "start_line": sl,
                            "end_line": el,
                            "text": text,
                        },
                    ],
                    "reason": reason or "read_lines",
                },
            )
            return
        state.path_rejects.append(
            PathValidationRecord(
                raw=kind,
                code="unknown_result_kind",
            ),
        )

    def _span_from_item_or_node(
        self,
        item: Mapping[str, Any],
        node: PagNode | None,
    ) -> tuple[int, int] | None:
        spans = item.get("read_line_spans")
        if isinstance(spans, list) and spans:
            first = spans[0]
            if isinstance(first, dict):
                try:
                    sl = int(first.get("start_line", 0) or 0)
                    el = int(first.get("end_line", 0) or 0)
                except (TypeError, ValueError):
                    return None
                if sl >= 1 and el >= sl:
                    return (sl, el)
        if node is not None:
            return self._evidence.line_span_from_node(node)
        return None
