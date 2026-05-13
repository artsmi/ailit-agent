"""Семантический remap C-нод после file change (G12.7)."""

from __future__ import annotations

import ast
import hashlib
import re
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from agent_memory.sqlite_pag import (
    PagGraphTraceFn,
    PagNode,
    SqlitePagStore,
)
from agent_memory.agent_memory_contracts import (
    EXTRACTION_CONTRACT_VERSION,
    MemoryLineHintV1,
    MemorySemanticLocatorV1,
)
from agent_memory.link_claim_resolver import LinkClaimResolver
from agent_memory.memory_c_segmentation import FingerprintService
from agent_memory.memory_llm_optimization_policy import (
    MemoryLlmOptimizationPolicy,
)
from agent_memory.memory_c_size_limits import C_NODE_FULL_B_MAX_CHARS
from agent_memory.pag_graph_write_service import PagGraphWriteService

_RE_FULL_FILE_CONF: Final[float] = 0.86
_SEM_WINDOW_CONF: Final[float] = 0.88
_SEM_PRIME_CONF: Final[float] = 0.95


@dataclass(frozen=True, slots=True)
class CRemapBatchResult:
    """Сводка по одному файлу."""

    path: str
    updated: int
    needs_llm_remap: int
    b_fingerprint: str


@dataclass(frozen=True, slots=True)
class CRemapSpanResult:
    """Итог поиска span для C: mechanical только при confidence >= policy."""

    applied: bool = False
    needs_llm: bool = False
    start: int = 0
    end: int = 0
    mode: str = ""
    confidence: float = 0.0


def _read_text_lines(abs_file: Path) -> tuple[str, list[str]] | None:
    try:
        raw = abs_file.read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    return text, text.splitlines()


def _b_node_id(rel: str) -> str:
    r = str(rel or "").replace("\\", "/").strip().lstrip("./")
    return f"B:{r}"


def _attrs_line_hint(attrs: Mapping[str, Any]) -> MemoryLineHintV1 | None:
    lh = attrs.get("line_hint")
    if isinstance(lh, dict):
        hit = MemoryLineHintV1.from_json(lh)
        if hit is not None:
            return hit
    try:
        sl = int(attrs.get("start_line", 0) or 0)
        el = int(attrs.get("end_line", 0) or 0)
    except (TypeError, ValueError):
        return None
    if sl > 0 and el > 0:
        return MemoryLineHintV1(start=sl, end=max(sl, el))
    return None


def _stable_key_from_attrs(attrs: Mapping[str, Any], title: str) -> str:
    sk = str(attrs.get("stable_key", "") or "").strip()
    if sk:
        return sk
    kind = str(attrs.get("kind", "") or "")
    name = str(attrs.get("name", "") or title)
    if kind and name:
        return f"{kind}:{name}"
    return f"node:{title}"


def _semantic_from_attrs(
    attrs: Mapping[str, Any],
) -> MemorySemanticLocatorV1 | None:
    sl = attrs.get("semantic_locator")
    if isinstance(sl, dict):
        return MemorySemanticLocatorV1.from_mapping(sl)
    return None


class _PythonLocater:
    """AST: top-level def/class по имени."""

    @staticmethod
    def find_span(
        text: str,
        *,
        name: str,
        kind: str,
    ) -> tuple[int, int] | None:
        n = (name or "").strip()
        if not n:
            return None
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        klow = (kind or "").lower()
        if "class" in klow:
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and str(node.name) == n:
                    s = int(getattr(node, "lineno", 0) or 0)
                    e = int(getattr(node, "end_lineno", 0) or s)
                    if s > 0:
                        return s, max(e, s)
            return None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if str(node.name) == n:
                    s = int(getattr(node, "lineno", 0) or 0)
                    e = int(getattr(node, "end_lineno", 0) or s)
                    if s > 0:
                        return s, max(e, s)
        return None


class _MarkdownLocater:
    """Поиск heading по path из semantic_locator."""

    _H = re.compile(
        r"^(#{1,6})\s+(.+?)\s*$",
    )

    @classmethod
    def find_heading_lines(
        cls,
        lines: list[str],
        heading_path: Sequence[str],
    ) -> tuple[int, int] | None:
        if not heading_path:
            return None
        target = str(heading_path[-1] or "").strip()
        if not target:
            return None
        return cls.find_title(lines, target)

    @classmethod
    def _span_from_heading_line(
        cls,
        lines: list[str],
        first: int,
        m: re.Match[str],
    ) -> tuple[int, int]:
        base_level = len(str(m.group(1) or ""))
        end = len(lines)
        for j in range(first, len(lines)):
            line2 = lines[j]
            m2 = cls._H.match(line2.strip())
            if not m2:
                continue
            level = len(str(m2.group(1) or ""))
            cond_level = 0 < level <= base_level
            if j + 1 > first and cond_level:
                end = j
                break
        return first, max(first, end)

    @classmethod
    def find_title(
        cls,
        lines: list[str],
        title: str,
    ) -> tuple[int, int] | None:
        w0 = (title or "").strip().lower()
        if not w0:
            return None
        for i, line in enumerate(lines, start=1):
            m = cls._H.match(line.strip())
            if not m:
                continue
            t = str(m.group(2) or "").strip().lower()
            if t == w0:
                return cls._span_from_heading_line(lines, i, m)
        return None


def _search_signature_in_text(
    text: str,
    name: str,
    *,
    rel_lower: str = "",
) -> tuple[int, int] | None:
    n = re.escape((name or "").strip())
    if not n:
        return None
    pats: list[re.Pattern[str]] = [
        re.compile(rf"^def\s+{n}\b", re.MULTILINE),
        re.compile(rf"^class\s+{n}\b", re.MULTILINE),
    ]
    if rel_lower.endswith((".ts", ".tsx", ".js", ".jsx")):
        pats.extend(
            [
                re.compile(rf"^export\s+function\s+{n}\b", re.MULTILINE),
                re.compile(rf"function\s+{n}\s*\(", re.MULTILINE),
            ],
        )
    for pat in pats:
        m = pat.search(text)
        if m is not None:
            pre = text[: m.start()]
            s = pre.count("\n") + 1
            e = s + m.group(0).count("\n")
            return s, max(s, e)
    return None


def _line_hint_search_windows(
    hint: MemoryLineHintV1,
    nlines: int,
    text: str,
) -> list[tuple[int, int]]:
    """G13.4: old range, ±100, ±200, ±500, затем весь B если len <= cap."""
    s, e = int(hint.start), int(hint.end)
    out: list[tuple[int, int]] = [
        (max(1, s), min(nlines, e)),
    ]
    for margin in (100, 200, 500):
        out.append(
            (
                max(1, s - margin),
                min(nlines, e + margin),
            ),
        )
    if len(text) <= C_NODE_FULL_B_MAX_CHARS:
        out.append((1, nlines))
    return out


def _structural_hits_in_range(
    lines: list[str],
    lo: int,
    hi: int,
    *,
    name: str,
    kind: str,
) -> list[int]:
    n = re.escape((name or "").strip())
    if not n:
        return []
    hits: list[int] = []
    k = (kind or "").lower()
    a = max(1, min(lo, len(lines) or 1))
    b = min(len(lines), max(hi, 1))
    for i in range(a, b + 1):
        line = lines[i - 1]
        if "class" in k and re.search(rf"^\s*class\s+{n}\b", line):
            hits.append(i)
        elif re.search(rf"^\s*(async\s+)?def\s+{n}\b", line):
            if "class" not in k:
                hits.append(i)
        elif re.search(rf"export\s+function\s+{n}\b", line) or re.search(
            rf"^\s*function\s+{n}\s*\(",
            line,
        ):
            if "class" not in k:
                hits.append(i)
    return hits


def _count_global_name_structural_hits(
    text: str,
    *,
    name: str,
    kind: str,
) -> int:
    lines = text.splitlines()
    if not lines:
        return 0
    return len(
        _structural_hits_in_range(lines, 1, len(lines), name=name, kind=kind),
    )


def _span_from_line_run(
    lines: list[str],
    name: str,
    kind: str,
    *,
    line_start: int,
) -> tuple[int, int] | None:
    """AST по полному файлу, иначе грубый диапазон вокруг найденной строки."""
    text = "\n".join(lines)
    pl = _PythonLocater.find_span(text, name=name, kind=kind)
    if pl is not None:
        return pl[0], pl[1]
    nlines = len(lines)
    if line_start < 1:
        return None
    e = min(nlines, line_start + 200)
    return line_start, e


def _line_slice_text(lines: list[str], s: int, e: int) -> str:
    a = max(0, s - 1)
    b = min(len(lines), e)
    return "\n".join(lines[a:b])


def _content_fp_for_slice(lines: list[str], s: int, e: int) -> str:
    return FingerprintService.sha256_text(_line_slice_text(lines, s, e))


def _remap_node_span(
    *,
    text: str,
    lines: list[str],
    rel_lower: str,
    node: PagNode,
    policy: MemoryLlmOptimizationPolicy,
) -> CRemapSpanResult:
    """
    semantic (AST/md) -> line_hint окна ±100/200/500 -> full-B при cap.

    Identity: stable_key/semantic; line_hint — подсказка (G13.4).
    """
    th_ok = float(policy.threshold_mechanical_accept)
    th_amb = float(policy.threshold_ambiguous_min)
    attrs = dict(node.attrs)
    sem = _semantic_from_attrs(attrs)
    title = str(node.title or "")
    name = str(attrs.get("name", "") or title)
    kind = str(node.kind or "function")
    nlines = len(lines)

    def mech(
        s: int,
        e: int,
        mode: str,
        conf: float,
    ) -> CRemapSpanResult:
        s2 = max(1, min(s, max(1, nlines)))
        e2 = max(s2, min(e, max(1, nlines)))
        if conf >= th_ok:
            return CRemapSpanResult(
                applied=True,
                start=s2,
                end=e2,
                mode=mode,
                confidence=conf,
            )
        if conf >= th_amb:
            return CRemapSpanResult(needs_llm=True, confidence=conf)
        return CRemapSpanResult(needs_llm=True, confidence=conf)

    if rel_lower.endswith(".py"):
        if _count_global_name_structural_hits(text, name=name, kind=kind) <= 1:
            pl = _PythonLocater.find_span(
                text,
                name=name,
                kind=kind,
            )
            if pl is not None:
                return mech(pl[0], pl[1], "python_ast", _SEM_PRIME_CONF)
    if rel_lower.endswith(".md"):
        hp: list[str] = []
        if sem and isinstance(sem.raw.get("heading_path"), list):
            hp = [str(x) for x in sem.raw["heading_path"]]
        md: tuple[int, int] | None
        if hp:
            md = _MarkdownLocater.find_heading_lines(lines, hp)
        else:
            md = None
        if md is None and title:
            md = _MarkdownLocater.find_title(lines, title)
        if md is not None:
            return mech(md[0], md[1], "md_heading", _SEM_PRIME_CONF)
    if rel_lower.endswith((".xml", ".launch", ".urdf")) and sem is not None:
        tag = str(sem.raw.get("tag", "") or "").strip()
        if tag:
            hits: list[int] = []
            for i, line in enumerate(lines, start=1):
                if f"<{tag}" in line or f"</{tag}" in line:
                    hits.append(i)
            if len(hits) == 1:
                a, b = hits[0], min(nlines, hits[0] + 60)
                return mech(a, b, "markup_tag", _SEM_WINDOW_CONF)
            if len(hits) > 1:
                return CRemapSpanResult(needs_llm=True, confidence=0.55)

    hint = _attrs_line_hint(attrs)
    if hint is not None and nlines >= 1:
        for lo, hi in _line_hint_search_windows(hint, nlines, text):
            hlist = _structural_hits_in_range(
                lines,
                lo,
                hi,
                name=name,
                kind=kind,
            )
            if len(hlist) > 1:
                return CRemapSpanResult(needs_llm=True, confidence=0.55)
            if len(hlist) == 0:
                continue
            gh = _count_global_name_structural_hits(
                text,
                name=name,
                kind=kind,
            )
            if gh > 1:
                return CRemapSpanResult(needs_llm=True, confidence=0.55)
            if rel_lower.endswith(".py"):
                pl2 = _PythonLocater.find_span(text, name=name, kind=kind)
                if pl2 is not None:
                    return mech(
                        pl2[0],
                        pl2[1],
                        "line_windows_ast",
                        _SEM_WINDOW_CONF,
                    )
            if rel_lower.endswith((".ts", ".tsx", ".js", ".jsx")):
                rts = _search_signature_in_text(
                    text,
                    name,
                    rel_lower=rel_lower,
                )
                if rts is not None:
                    return mech(
                        rts[0],
                        rts[1],
                        "ts_line_windows",
                        _SEM_WINDOW_CONF,
                    )
            he = _span_from_line_run(
                lines,
                name,
                kind,
                line_start=hlist[0],
            )
            if he is not None:
                return mech(
                    he[0],
                    he[1],
                    "line_windows_struct",
                    _SEM_WINDOW_CONF,
                )

    gcount = _count_global_name_structural_hits(
        text,
        name=name,
        kind=kind,
    )
    alt = _search_signature_in_text(
        text,
        name=attrs.get("name") or title,
        rel_lower=rel_lower,
    )
    if alt is not None and gcount == 1:
        return mech(alt[0], alt[1], "regex_fn_full_file", _RE_FULL_FILE_CONF)
    if alt is not None and gcount > 1:
        return CRemapSpanResult(needs_llm=True, confidence=0.55)
    return CRemapSpanResult(needs_llm=True, confidence=0.0)


class SemanticCRemapService:
    """B.fingerprint с диска; remap C по stable_key+semantic, не lines-only."""

    def __init__(
        self,
        pag: PagGraphWriteService,
        policy: MemoryLlmOptimizationPolicy | None = None,
    ) -> None:
        self._write: PagGraphWriteService = pag
        self._store: SqlitePagStore = pag.store
        self._policy: MemoryLlmOptimizationPolicy = (
            policy or MemoryLlmOptimizationPolicy.default()
        )

    def process_changes(
        self,
        *,
        namespace: str,
        project_root: Path,
        relative_paths: Sequence[str],
        graph_trace_hook: PagGraphTraceFn | None,
    ) -> list[CRemapBatchResult]:
        out: list[CRemapBatchResult] = []
        for raw in relative_paths:
            rel = str(raw or "").replace("\\", "/").strip().lstrip("./")
            if not rel:
                continue
            ctx: AbstractContextManager[object] = nullcontext()
            if graph_trace_hook is not None:
                ctx = self._store.graph_trace(graph_trace_hook)
            with ctx:
                r = self._remap_one_file(
                    namespace=namespace,
                    project_root=project_root,
                    rel_path=rel,
                )
            if r is not None:
                out.append(r)
        return out

    def _remap_one_file(
        self,
        *,
        namespace: str,
        project_root: Path,
        rel_path: str,
    ) -> CRemapBatchResult | None:
        root = project_root.resolve()
        abs_f = (root / rel_path).resolve()
        if not abs_f.is_file():
            return None
        tlines = _read_text_lines(abs_f)
        if tlines is None:
            return None
        text, lines = tlines
        raw_bytes = abs_f.read_bytes()
        b_fp = FingerprintService.b_fingerprint_file_bytes(
            raw_bytes,
        )
        ns = str(namespace).strip()
        bid = _b_node_id(rel_path)
        b_node = self._store.fetch_node(namespace=ns, node_id=bid)
        b_attrs: dict[str, Any] = (
            dict(b_node.attrs) if b_node is not None else {}
        )
        b_attrs.update(
            {
                "size_bytes": len(raw_bytes),
                "hash": hashlib.sha1(raw_bytes).hexdigest(),
            },
        )
        self._write.upsert_node(
            namespace=ns,
            node_id=bid,
            level="B",
            kind="file",
            path=rel_path,
            title=abs_f.name,
            summary=b_node.summary if b_node is not None else "File",
            attrs=b_attrs,
            fingerprint=b_fp,
            staleness_state="fresh",
            source_contract="ailit_pag_store_v1",
        )
        c_nodes = self._store.list_nodes_for_path(
            namespace=ns,
            path=rel_path,
            level="C",
            limit=2000,
        )
        if not c_nodes:
            return CRemapBatchResult(
                path=rel_path,
                updated=0,
                needs_llm_remap=0,
                b_fingerprint=b_fp,
            )
        rel_l = rel_path.lower()
        upd = 0
        need = 0
        for c in c_nodes:
            a = self._remap_c_node(
                namespace=ns,
                rel_path=rel_path,
                b_fp=b_fp,
                lines=lines,
                text=text,
                rel_lower=rel_l,
                c=c,
            )
            if a == "updated":
                upd += 1
            elif a == "need_llm":
                need += 1
        LinkClaimResolver().resolve_all_pending(
            self._write,
            namespace=ns,
        )
        return CRemapBatchResult(
            path=rel_path,
            updated=upd,
            needs_llm_remap=need,
            b_fingerprint=b_fp,
        )

    def _remap_c_node(
        self,
        *,
        namespace: str,
        rel_path: str,
        b_fp: str,
        lines: list[str],
        text: str,
        rel_lower: str,
        c: PagNode,
    ) -> str:
        res = _remap_node_span(
            text=text,
            lines=lines,
            rel_lower=rel_lower,
            node=c,
            policy=self._policy,
        )
        attrs: dict[str, Any] = dict(c.attrs)
        if res.applied:
            s, e = res.start, res.end
            sk = _stable_key_from_attrs(attrs, c.title)
            attrs["stable_key"] = sk
            attrs["b_fingerprint"] = b_fp
            attrs["line_hint"] = {"start": s, "end": e}
            attrs["extraction_contract_version"] = str(
                attrs.get("extraction_contract_version", "") or ""
            ) or EXTRACTION_CONTRACT_VERSION
            c_fp = _content_fp_for_slice(lines, s, e)
            _ = FingerprintService.sha256_text(
                f"{c.summary}::{b_fp}::{c_fp}"[:1_200],
            )
            self._write.upsert_node(
                namespace=namespace,
                node_id=c.node_id,
                level=c.level,
                kind=c.kind,
                path=c.path,
                title=c.title,
                summary=c.summary,
                attrs=attrs,
                fingerprint=c_fp,
                staleness_state="fresh",
                source_contract=c.source_contract,
            )
            return "updated"
        attrs["staleness_state"] = "needs_llm_remap"
        attrs["b_fingerprint"] = b_fp
        self._write.upsert_node(
            namespace=namespace,
            node_id=c.node_id,
            level=c.level,
            kind=c.kind,
            path=c.path,
            title=c.title,
            summary=c.summary,
            attrs=attrs,
            fingerprint=c.fingerprint,
            staleness_state="needs_llm_remap",
            source_contract=c.source_contract,
        )
        return "need_llm"
