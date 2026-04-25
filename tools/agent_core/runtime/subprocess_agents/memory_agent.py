"""AgentMemory subprocess worker (G8.4.2, minimal adapter).

This is a lightweight worker that can issue MemoryGrant objects via
`memory.query_context` service. The full PAG/KB integration is handled
elsewhere in the codebase; here we expose a stable runtime contract.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from agent_core.runtime.models import (
    CONTRACT_VERSION,
    MemoryGrant,
    MemoryGrantRange,
    RuntimeRequestEnvelope,
    make_response_envelope,
)


@dataclass(frozen=True, slots=True)
class MemoryAgentConfig:
    """Конфиг AgentMemory."""

    chat_id: str
    broker_id: str
    namespace: str


class AgentMemoryWorker:
    """Минимальная реализация memory.query_context -> MemoryGrant."""

    def __init__(self, cfg: MemoryAgentConfig) -> None:
        self._cfg = cfg

    def _issue_grant(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
    ) -> MemoryGrant:
        return MemoryGrant(
            grant_id=str(uuid.uuid4()),
            issued_by=f"AgentMemory:{self._cfg.chat_id}",
            issued_to=f"AgentWork:{self._cfg.chat_id}",
            namespace=self._cfg.namespace,
            path=path,
            ranges=(
                MemoryGrantRange(
                    start_line=start_line,
                    end_line=end_line,
                ),
            ),
            whole_file=False,
            reason="query_context",
            expires_at="2099-01-01T00:00:00Z",
        )

    def handle(self, req: RuntimeRequestEnvelope) -> Mapping[str, Any]:
        if req.type != "service.request":
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={"code": "unsupported", "message": req.type},
            ).to_dict()
        service = str(req.payload.get("service", "") or "")
        if service and service != "memory.query_context":
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={"code": "unknown_service", "message": service},
            ).to_dict()
        want_path = str(req.payload.get("path", "") or "")
        if not want_path:
            want_path = str(req.payload.get("hint_path", "") or "")
        if not want_path:
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={"code": "invalid_args", "message": "path required"},
            ).to_dict()
        grant = self._issue_grant(want_path, start_line=1, end_line=200)
        return make_response_envelope(
            request=req,
            ok=True,
            payload={"grants": [grant.to_dict()]},
            error=None,
        ).to_dict()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent-memory")
    p.add_argument("--chat-id", type=str, required=True)
    p.add_argument("--broker-id", type=str, required=True)
    p.add_argument("--namespace", type=str, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    cfg = MemoryAgentConfig(
        chat_id=str(args.chat_id),
        broker_id=str(args.broker_id),
        namespace=str(args.namespace),
    )
    worker = AgentMemoryWorker(cfg)
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            req = RuntimeRequestEnvelope.from_json_line(raw)
        except Exception:
            continue
        if req.contract_version != CONTRACT_VERSION:
            continue
        out = worker.handle(req)
        sys.stdout.write(json_dumps_single_line(out))
        sys.stdout.flush()
    return 0


def json_dumps_single_line(obj: Mapping[str, Any]) -> str:
    import json

    return (
        json.dumps(dict(obj), ensure_ascii=False, separators=(",", ":"))
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
