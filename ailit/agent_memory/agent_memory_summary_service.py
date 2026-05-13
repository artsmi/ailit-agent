"""
W14: LLM summaries для C и B (``agent_memory_command_output.v1``).

Связь: G14R.5, C14R.2, D14R.4.
SoT: этот модуль + ``agent_memory_runtime_contract``.

Граница планер vs internal (S1 / llm-commands.md): входные JSON для
``summarize_c`` / ``summarize_b`` сериализуются как
``agent_memory_command_input.v1`` (см. ``build_*_input_envelope``).
Ответы LLM на эти фазы остаются ``agent_memory_command_output.v1`` с
``command=summarize_c|summarize_b`` — это **не** верхнеуровневый envelope
планерского раунда ``memory.query_context`` (там разрешены только
``plan_traversal``, ``finish_decision``, ``propose_links``).

Не импортируйте ``semantic_c_extraction`` / ``memory_c_extractor_prompt``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar

from agent_memory.sqlite_pag import PagNode, SqlitePagStore
from agent_memory.agent_memory_runtime_contract import (
    AGENT_MEMORY_COMMAND_INPUT_SCHEMA,
    AgentMemoryCommandName,
    W14CommandParseError,
    W14CommandParseResult,
    parse_w14_internal_command_output_llm_text_result,
)
from agent_memory.pag_graph_write_service import PagGraphWriteService

# Запись summarize_c / summarize_b в PAG не зависит от пользовательского goal;
# см. ``context/proto/pag-stable-indexing.md``.
PAG_NEUTRAL_USER_SUBGOAL: str = ""


# --- Fingerprint: одна правка логики — тут (G14R.5) ------------------------


def _sha256_hex(prefix: str, s: str) -> str:
    h = hashlib.sha256()
    h.update(f"{prefix}\0".encode("utf-8"))
    h.update(s.encode("utf-8"))
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class AgentMemorySummaryFingerprinting:
    """Отпечатки summary и агрегат дочерних C/B для B (C14R.2)."""

    c_content_token: ClassVar[str] = "c_content_v1"
    c_summary_token: ClassVar[str] = "c_sum_v1"
    b_child_basis_token: ClassVar[str] = "b_child_basis_v1"
    b_summary_token: ClassVar[str] = "b_sum_v1"

    @classmethod
    def c_content_fingerprint(cls, text: str) -> str:
        t = cls.c_content_token
        h = _sha256_hex(t, text)
        return f"{t}:sha256-{h}"

    @classmethod
    def c_summary_fingerprint(
        cls,
        *,
        content_fingerprint: str,
        summary_text: str,
    ) -> str:
        s = f"{content_fingerprint}\n{summary_text}"
        tok = cls.c_summary_token
        return f"{tok}:sha256-{_sha256_hex(tok, s)}"

    @classmethod
    def b_child_basis_fingerprint(
        cls,
        children: Sequence[tuple[str, str, str]],
    ) -> str:
        """
        Упорядоченный список (node_id, level, summary_fingerprint) — базис B.

        Все пары child fingerprint участвуют: при смене любой дочерней
        `summary_fingerprint` меняется весь агрегат.
        """
        rows: list[str] = []
        for node_id, level, sum_fp in sorted(
            list(children), key=lambda x: (x[0], x[1]),
        ):
            rows.append(f"{node_id}|{level}|{sum_fp}")
        joined = "\n".join(rows)
        return (
            f"{cls.b_child_basis_token}:"
            f"sha256-{_sha256_hex(cls.b_child_basis_token, joined)}"
        )

    @classmethod
    def b_summary_fingerprint(
        cls,
        *,
        child_basis_fingerprint: str,
        summary_text: str,
    ) -> str:
        s = f"{child_basis_fingerprint}\n{summary_text}"
        tok = cls.b_summary_token
        return f"{tok}:sha256-{_sha256_hex(tok, s)}"


@dataclass(frozen=True, slots=True)
class W14CommandLimits:
    max_summary_chars: int
    max_claims: int = 8
    max_children: int = 80


@dataclass(frozen=True, slots=True)
class SummarizeCLocator:
    start_line: int
    end_line: int
    symbol: str | None = None

    def to_dict(self) -> dict[str, Any]:
        o: dict[str, Any] = {
            "start_line": int(self.start_line),
            "end_line": int(self.end_line),
        }
        if self.symbol is not None and str(self.symbol).strip():
            o["symbol"] = str(self.symbol)
        return o


# --- DTO: вход/выход summarize_c / summarize_b (payload в envelope) --------


@dataclass(frozen=True, slots=True)
class SummarizeCNodeInputV1:
    c_node_id: str
    path: str
    semantic_kind: str
    text: str
    locator: SummarizeCLocator

    def to_c_node_dict(self) -> dict[str, Any]:
        return {
            "c_node_id": self.c_node_id,
            "path": self.path,
            "semantic_kind": self.semantic_kind,
            "locator": self.locator.to_dict(),
            "text": self.text,
        }


def _merge_attrs(
    existing: dict[str, Any] | None,
    patch: dict[str, Any],
) -> dict[str, Any]:
    base: dict[str, Any] = dict(existing or {})
    base.update(patch)
    return base


def _child_summary_fingerprint_from_node(n: PagNode) -> str:
    if isinstance(n.attrs, dict):
        sfp = n.attrs.get("summary_fingerprint", "")
        if sfp is not None and str(sfp).strip():
            return str(sfp)
    return n.fingerprint


@dataclass(frozen=True, slots=True)
class SummarizeCResultV1:
    c_node_id: str
    summary: str
    summary_fingerprint: str
    status: str


@dataclass(frozen=True, slots=True)
class SummarizeBResultV1:
    b_node_id: str
    summary: str
    summary_fingerprint: str
    child_basis_fingerprint: str
    status: str


@dataclass(frozen=True, slots=True)
class AgentMemorySummaryService:
    """
    Запись summary C/B в PAG (``PagGraphWriteService``) по ответу LLM W14.
    """

    _write: PagGraphWriteService

    @property
    def store(self) -> SqlitePagStore:
        return self._write.store

    @staticmethod
    def build_summarize_c_input_envelope(
        *,
        command_id: str,
        query_id: str,
        c: SummarizeCNodeInputV1,
        user_subgoal: str,
        limits: W14CommandLimits,
    ) -> dict[str, Any]:
        return {
            "schema_version": AGENT_MEMORY_COMMAND_INPUT_SCHEMA,
            "command": AgentMemoryCommandName.SUMMARIZE_C.value,
            "command_id": command_id,
            "query_id": query_id,
            "c_node": c.to_c_node_dict(),
            "user_subgoal": user_subgoal,
            "limits": {
                "max_summary_chars": int(limits.max_summary_chars),
                "max_claims": int(limits.max_claims),
            },
        }

    @staticmethod
    def _parse_summarize_c_payload(
        envelope: Mapping[str, Any],
    ) -> dict[str, Any]:
        p = envelope.get("payload", {})
        if not isinstance(p, dict):
            raise W14CommandParseError("summarize_c payload must be an object")
        if "summary" not in p or not isinstance(p.get("summary"), str):
            raise W14CommandParseError("payload.summary must be a string")
        return {str(a): b for a, b in p.items()}

    @staticmethod
    def _parse_summarize_b_payload(
        envelope: Mapping[str, Any],
    ) -> dict[str, Any]:
        p = envelope.get("payload", {})
        if not isinstance(p, dict):
            raise W14CommandParseError("summarize_b payload must be an object")
        if "summary" not in p or not isinstance(p.get("summary"), str):
            raise W14CommandParseError("payload.summary must be a string")
        return {str(a): b for a, b in p.items()}

    @classmethod
    def _build_b_children_for_command(
        cls,
        child_nodes: Sequence[PagNode],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in child_nodes:
            sfp = _child_summary_fingerprint_from_node(n)
            out.append(
                {
                    "node_id": n.node_id,
                    "level": n.level,
                    "title": n.title,
                    "summary": n.summary,
                    "fingerprint": sfp,
                },
            )
        return out

    @staticmethod
    def build_summarize_b_input_envelope(
        *,
        command_id: str,
        query_id: str,
        b_node_id: str,
        path: str,
        kind: str,
        child_nodes: Sequence[PagNode],
        user_subgoal: str,
        limits: W14CommandLimits,
    ) -> dict[str, Any]:
        ch = AgentMemorySummaryService._build_b_children_for_command(
            child_nodes,
        )
        if len(ch) > int(limits.max_children):
            raise ValueError("limits.max_children exceeded for summarize_b")
        b_node: dict[str, Any] = {
            "b_node_id": b_node_id,
            "path": path,
            "kind": str(kind).strip() or "file",
            "children": ch,
        }
        return {
            "schema_version": AGENT_MEMORY_COMMAND_INPUT_SCHEMA,
            "command": AgentMemoryCommandName.SUMMARIZE_B.value,
            "command_id": command_id,
            "query_id": query_id,
            "b_node": b_node,
            "user_subgoal": user_subgoal,
            "limits": {
                "max_summary_chars": int(limits.max_summary_chars),
                "max_children": int(limits.max_children),
            },
        }

    @staticmethod
    def compute_b_child_basis_from_nodes(
        child_nodes: Sequence[PagNode],
    ) -> str:
        rowz: list[tuple[str, str, str]] = [
            (n.node_id, n.level, _child_summary_fingerprint_from_node(n))
            for n in child_nodes
        ]
        return AgentMemorySummaryFingerprinting.b_child_basis_fingerprint(
            rowz,
        )

    @staticmethod
    def is_b_summary_stale(
        *,
        b_node: PagNode,
        current_child_basis: str,
    ) -> bool:
        """
        True если дочерний агрегат изменился (B summary не валиден).
        """
        a = b_node.attrs if isinstance(b_node.attrs, dict) else {}
        prev = a.get("child_basis_fingerprint", "")
        if not str(prev or "").strip():
            return True
        return str(prev) != str(current_child_basis).strip()

    @staticmethod
    def llm_text_for_json_command(command_input: Mapping[str, Any]) -> str:
        """
        Сериализация machine input для LLM. Только JSON — без сырого B, кроме
        явных дочерних `summary` в `b_node.children` / `c_node.text` для C.
        """
        return json.dumps(
            command_input, ensure_ascii=False, sort_keys=True, indent=0,
        )

    def _resolve_c_content_fingerprint(
        self,
        c_node: PagNode,
        c_input: SummarizeCNodeInputV1,
    ) -> str:
        a = c_node.attrs if isinstance(c_node.attrs, dict) else {}
        cfp = a.get("content_fingerprint", "")
        if cfp and str(cfp).strip():
            return str(cfp)
        return AgentMemorySummaryFingerprinting.c_content_fingerprint(
            c_input.text,
        )

    def apply_summarize_c(
        self,
        *,
        namespace: str,
        c_input: SummarizeCNodeInputV1,
        user_subgoal: str,
        limits: W14CommandLimits,
        command_id: str,
        query_id: str,
        llm_json: str,
        on_summarize_apply_ready: Callable[[W14CommandParseResult], None]
        | None = None,
    ) -> SummarizeCResultV1:
        n = self.store.fetch_node(
            namespace=namespace, node_id=c_input.c_node_id,
        )
        if n is None:
            raise KeyError(
                f"c node not in store: {namespace!r} {c_input.c_node_id!r}",
            )
        pr = parse_w14_internal_command_output_llm_text_result(
            llm_json,
            runtime_command_id=command_id,
            expected_envelope_command=AgentMemoryCommandName.SUMMARIZE_C.value,
        )
        env = pr.obj
        cmd = str(env.get("command", "") or "")
        if cmd != AgentMemoryCommandName.SUMMARIZE_C.value:
            msg = f"expected summarize_c, got {cmd!r}"
            raise W14CommandParseError(msg)
        payload = self._parse_summarize_c_payload(env)
        st = str(env.get("status", "") or "ok")
        text_summary = str(payload.get("summary", "")).strip()
        if st not in ("ok", "partial", "refuse"):
            raise W14CommandParseError(f"invalid status: {st!r}")
        if st in ("ok",) and not text_summary:
            raise W14CommandParseError("summary empty for status ok")
        if on_summarize_apply_ready is not None:
            on_summarize_apply_ready(pr)
        cfp = self._resolve_c_content_fingerprint(n, c_input)
        old_attrs: dict[str, Any] = (
            dict(n.attrs) if isinstance(n.attrs, dict) else {}
        )
        if st == "refuse":
            attrs2 = _merge_attrs(
                old_attrs,
                {
                    "content_fingerprint": cfp,
                    "w14_refusal_reason": str(
                        payload.get("refusal_reason", "") or "",
                    ),
                },
            )
            _ = self._write.upsert_node(
                namespace=namespace,
                node_id=c_input.c_node_id,
                level=n.level,
                kind=n.kind,
                path=n.path,
                title=n.title,
                summary=n.summary,
                attrs=attrs2,
                fingerprint=n.fingerprint,
            )
            prev_sfp = str(old_attrs.get("summary_fingerprint", "") or "")
            return SummarizeCResultV1(
                c_node_id=c_input.c_node_id,
                summary=n.summary,
                summary_fingerprint=prev_sfp,
                status=st,
            )
        sfp = AgentMemorySummaryFingerprinting.c_summary_fingerprint(
            content_fingerprint=cfp,
            summary_text=text_summary,
        )
        attrs2 = _merge_attrs(
            old_attrs,
            {
                "content_fingerprint": cfp,
                "summary_fingerprint": sfp,
                "w14_command": "summarize_c",
            },
        )
        ex = payload.get("semantic_tags")
        if isinstance(ex, list) and ex:
            attrs2["w14_semantic_tags"] = [str(x) for x in ex]
        ex2 = payload.get("important_lines")
        if isinstance(ex2, list) and ex2:
            attrs2["w14_important_lines"] = ex2
        ex3 = payload.get("claims")
        if isinstance(ex3, list) and ex3:
            attrs2["w14_claims"] = ex3
        rr = payload.get("refusal_reason")
        if isinstance(rr, str) and rr.strip():
            attrs2["w14_refusal_reason"] = str(rr)
        _ = self._write.upsert_node(
            namespace=namespace,
            node_id=c_input.c_node_id,
            level=n.level,
            kind=n.kind,
            path=n.path,
            title=n.title,
            summary=text_summary,
            attrs=attrs2,
            fingerprint=n.fingerprint,
        )
        return SummarizeCResultV1(
            c_node_id=c_input.c_node_id,
            summary=text_summary,
            summary_fingerprint=sfp,
            status=st,
        )

    def apply_summarize_b(
        self,
        *,
        namespace: str,
        b_node_id: str,
        path: str,
        kind: str,
        child_nodes: Sequence[PagNode],
        user_subgoal: str,
        limits: W14CommandLimits,
        command_id: str,
        query_id: str,
        llm_json: str,
        on_summarize_apply_ready: Callable[[W14CommandParseResult], None]
        | None = None,
    ) -> SummarizeBResultV1:
        n = self.store.fetch_node(
            namespace=namespace, node_id=b_node_id,
        )
        if n is None:
            raise KeyError(f"b node not in store: {namespace!r} {b_node_id!r}")
        pr = parse_w14_internal_command_output_llm_text_result(
            llm_json,
            runtime_command_id=command_id,
            expected_envelope_command=AgentMemoryCommandName.SUMMARIZE_B.value,
        )
        env = pr.obj
        cmd = str(env.get("command", "") or "")
        if cmd != AgentMemoryCommandName.SUMMARIZE_B.value:
            msg = f"expected summarize_b, got {cmd!r}"
            raise W14CommandParseError(msg)
        pl = self._parse_summarize_b_payload(env)
        st = str(env.get("status", "") or "ok")
        if st not in ("ok", "partial", "refuse"):
            raise W14CommandParseError(f"invalid status: {st!r}")
        text_summary = str(pl.get("summary", "")).strip()
        if st in ("ok",) and not text_summary:
            raise W14CommandParseError("summary empty for status ok")
        if on_summarize_apply_ready is not None:
            on_summarize_apply_ready(pr)
        basis = self.compute_b_child_basis_from_nodes(child_nodes)
        old_attrs2: dict[str, Any] = (
            dict(n.attrs) if isinstance(n.attrs, dict) else {}
        )
        pl_keys: tuple[str, ...] = (
            "child_refs",
            "missing_children",
            "confidence",
            "refusal_reason",
        )
        if st == "refuse" and not text_summary:
            at = _merge_attrs(
                old_attrs2,
                {
                    "w14_b_summary_refused": True,
                    "w14_command": "summarize_b",
                },
            )
            for key in pl_keys:
                if key in pl:
                    at[f"w14_{key}"] = pl.get(key)
            _ = self._write.upsert_node(
                namespace=namespace,
                node_id=b_node_id,
                level=n.level,
                kind=n.kind,
                path=path,
                title=n.title,
                summary=n.summary,
                attrs=at,
                fingerprint=n.fingerprint,
            )
            return SummarizeBResultV1(
                b_node_id=b_node_id,
                summary=n.summary,
                summary_fingerprint=str(
                    old_attrs2.get("summary_fingerprint", "") or "",
                ),
                child_basis_fingerprint=str(
                    old_attrs2.get("child_basis_fingerprint", "") or "",
                ),
                status=st,
            )
        sfp = AgentMemorySummaryFingerprinting.b_summary_fingerprint(
            child_basis_fingerprint=basis,
            summary_text=text_summary,
        )
        at2 = _merge_attrs(
            old_attrs2,
            {
                "summary_fingerprint": sfp,
                "child_basis_fingerprint": basis,
                "w14_command": "summarize_b",
            },
        )
        for key in pl_keys:
            if key in pl:
                at2[f"w14_{key}"] = pl.get(key)
        _ = self._write.upsert_node(
            namespace=namespace,
            node_id=b_node_id,
            level=n.level,
            kind=n.kind,
            path=path,
            title=n.title,
            summary=text_summary,
            attrs=at2,
            fingerprint=n.fingerprint,
        )
        return SummarizeBResultV1(
            b_node_id=b_node_id,
            summary=text_summary,
            summary_fingerprint=sfp,
            child_basis_fingerprint=basis,
            status=st,
        )

    def summarize_c_call_llm(
        self,
        *,
        namespace: str,
        c_input: SummarizeCNodeInputV1,
        user_subgoal: str,
        limits: W14CommandLimits,
        command_id: str,
        query_id: str,
        complete: Callable[[str], str],
    ) -> SummarizeCResultV1:
        env = self.build_summarize_c_input_envelope(
            command_id=command_id,
            query_id=query_id,
            c=c_input,
            user_subgoal=user_subgoal,
            limits=limits,
        )
        raw = self.llm_text_for_json_command(env)
        out = complete(raw)
        return self.apply_summarize_c(
            namespace=namespace,
            c_input=c_input,
            user_subgoal=user_subgoal,
            limits=limits,
            command_id=command_id,
            query_id=query_id,
            llm_json=out,
        )

    def summarize_b_call_llm(
        self,
        *,
        namespace: str,
        b_node_id: str,
        path: str,
        kind: str,
        child_nodes: Sequence[PagNode],
        user_subgoal: str,
        limits: W14CommandLimits,
        command_id: str,
        query_id: str,
        complete: Callable[[str], str],
    ) -> SummarizeBResultV1:
        env = self.build_summarize_b_input_envelope(
            command_id=command_id,
            query_id=query_id,
            b_node_id=b_node_id,
            path=path,
            kind=kind,
            child_nodes=child_nodes,
            user_subgoal=user_subgoal,
            limits=limits,
        )
        raw = self.llm_text_for_json_command(env)
        out = complete(raw)
        return self.apply_summarize_b(
            namespace=namespace,
            b_node_id=b_node_id,
            path=path,
            kind=kind,
            child_nodes=child_nodes,
            user_subgoal=user_subgoal,
            limits=limits,
            command_id=command_id,
            query_id=query_id,
            llm_json=out,
        )
