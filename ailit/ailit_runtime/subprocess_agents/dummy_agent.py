"""Internal AgentDummy subprocess for contract/routing tests (G8.4.4).

Protocol: read RuntimeRequestEnvelope JSON-lines from stdin, write
RuntimeResponseEnvelope JSON-lines to stdout.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from ailit_runtime.models import (
    CONTRACT_VERSION,
    RuntimeRequestEnvelope,
    RuntimeResponseEnvelope,
    make_response_envelope,
)


@dataclass(frozen=True, slots=True)
class DummyAgentConfig:
    """Конфиг dummy агента."""

    chat_id: str
    broker_id: str
    namespace: str


class AgentDummy:
    """Dummy: echo service и короткая action emulation."""

    def __init__(self, cfg: DummyAgentConfig) -> None:
        self._cfg = cfg
        self._me = f"AgentDummy:{cfg.chat_id}"

    def handle(self, req: RuntimeRequestEnvelope) -> RuntimeResponseEnvelope:
        if req.type == "service.request":
            payload = dict(req.payload)
            msg = str(payload.get("message", ""))
            return make_response_envelope(
                request=req,
                ok=True,
                payload={"echo": msg},
                error=None,
            )
        if req.type == "action.start":
            return make_response_envelope(
                request=req,
                ok=True,
                payload={"started": True},
                error=None,
            )
        return make_response_envelope(
            request=req,
            ok=False,
            payload={},
            error={"code": "unsupported", "message": req.type},
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent-dummy")
    p.add_argument("--chat-id", type=str, required=True)
    p.add_argument("--broker-id", type=str, required=True)
    p.add_argument("--namespace", type=str, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    cfg = DummyAgentConfig(
        chat_id=str(args.chat_id),
        broker_id=str(args.broker_id),
        namespace=str(args.namespace),
    )
    agent = AgentDummy(cfg)
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
        resp = agent.handle(req)
        sys.stdout.write(resp.to_json_line() + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
