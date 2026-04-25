"""AgentWork subprocess worker (G8.4.3, minimal adapter).

This worker exposes `work.handle_user_prompt` action as a contract surface.
Full session loop + tool execution wiring will be integrated in later tasks.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from agent_core.runtime.models import (
    CONTRACT_VERSION,
    RuntimeRequestEnvelope,
    make_response_envelope,
)


@dataclass(frozen=True, slots=True)
class WorkAgentConfig:
    """Конфиг AgentWork."""

    chat_id: str
    broker_id: str
    namespace: str


class AgentWorkWorker:
    """Минимальный worker: ack на action.start."""

    def __init__(self, cfg: WorkAgentConfig) -> None:
        self._cfg = cfg

    def handle(self, req: RuntimeRequestEnvelope) -> Mapping[str, Any]:
        if req.type == "action.start":
            action = str(
                req.payload.get("action", "") or "work.handle_user_prompt"
            )
            return make_response_envelope(
                request=req,
                ok=True,
                payload={"action": action, "action_id": str(uuid.uuid4())},
                error=None,
            ).to_dict()
        if req.type == "service.request":
            return make_response_envelope(
                request=req,
                ok=False,
                payload={},
                error={
                    "code": "unsupported",
                    "message": "services not implemented",
                },
            ).to_dict()
        return make_response_envelope(
            request=req,
            ok=False,
            payload={},
            error={"code": "unsupported", "message": req.type},
        ).to_dict()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent-work")
    p.add_argument("--chat-id", type=str, required=True)
    p.add_argument("--broker-id", type=str, required=True)
    p.add_argument("--namespace", type=str, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    cfg = WorkAgentConfig(
        chat_id=str(args.chat_id),
        broker_id=str(args.broker_id),
        namespace=str(args.namespace),
    )
    worker = AgentWorkWorker(cfg)
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
        sys.stdout.write(
            json.dumps(
                dict(out),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
