"""Shim: реализация в ``ailit_runtime.broker_json_client`` (G20.3)."""

from __future__ import annotations

from ailit_runtime.broker_json_client import (  # noqa: F401
    BrokerJsonRpcClient,
    BrokerResponseError,
    BrokerTraceBackgroundCapture,
    BrokerTraceSubscriber,
    BrokerTransportError,
    call_on_trace_capture,
    decode_json_line,
    encode_json_line,
    resolve_broker_socket_for_cli,
    unix_path_from_broker_endpoint,
    wait_for_path,
)
