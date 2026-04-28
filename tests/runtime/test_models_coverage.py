"""Unit tests for runtime/models.py — coverage of uncovered lines.

Covers:
- RuntimeIdentity (dataclass fields via asdict)
- RuntimeNow.iso() / RuntimeNow
- ServiceResponse.to_payload()
- Action payloads (started/feedback/completed/failed): ``.to_payload()``
- MemoryGrantRange.to_dict()
- MemoryGrant.from_dict() with invalid ranges
- MemoryGrant.to_dict()
- make_request_envelope / make_response_envelope
- ensure_json_object / ensure_json_mapping / ensure_json_list
  (non-dict / non-list inputs)
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Any

import pytest

from agent_core.runtime.errors import RuntimeProtocolError
from agent_core.runtime.models import (
    ActionCompleted,
    ActionFailed,
    ActionFeedback,
    ActionStarted,
    MemoryGrant,
    MemoryGrantRange,
    RuntimeIdentity,
    RuntimeNow,
    ServiceResponse,
    ensure_json_list,
    ensure_json_mapping,
    ensure_json_object,
    make_request_envelope,
    make_response_envelope,
)


# ---------------------------------------------------------------------------
# RuntimeIdentity
# ---------------------------------------------------------------------------

class TestRuntimeIdentity:
    def test_fields_asdict(self) -> None:
        ident = RuntimeIdentity(
            runtime_id="r1",
            chat_id="c1",
            broker_id="b1",
            trace_id="t1",
            goal_id="g1",
            namespace="ns1",
        )
        d = asdict(ident)
        assert d["runtime_id"] == "r1"
        assert d["chat_id"] == "c1"
        assert d["broker_id"] == "b1"
        assert d["trace_id"] == "t1"
        assert d["goal_id"] == "g1"
        assert d["namespace"] == "ns1"


# ---------------------------------------------------------------------------
# RuntimeNow
# ---------------------------------------------------------------------------

class TestRuntimeNow:
    def test_iso(self) -> None:
        now = RuntimeNow()
        iso = now.iso()
        assert isinstance(iso, str)
        assert iso.endswith("+00:00") or iso.endswith("Z") or "+" in iso

    def test_iso_consistency(self) -> None:
        now = RuntimeNow()
        iso1 = now.iso()
        iso2 = now.iso()

        def _parse_utc(s: str) -> datetime:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)

        assert abs((_parse_utc(iso2) - _parse_utc(iso1)).total_seconds()) < 1.0


# ---------------------------------------------------------------------------
# ServiceResponse
# ---------------------------------------------------------------------------

class TestServiceResponse:
    def test_to_payload(self) -> None:
        resp = ServiceResponse(
            service="test.svc",
            request_id="req-1",
            ok=True,
            payload={"result": 42},
            error=None,
        )
        p = resp.to_payload()
        assert p["type"] == "service.response"
        assert p["ok"] is True
        assert p["service"] == "test.svc"
        assert p["request_id"] == "req-1"
        assert p["payload"] == {"result": 42}
        assert p["error"] is None

    def test_to_payload_with_error(self) -> None:
        resp = ServiceResponse(
            service="test.svc",
            request_id="req-1",
            ok=False,
            payload={},
            error={"code": "failed", "message": "something went wrong"},
        )
        p = resp.to_payload()
        assert p["ok"] is False
        expect_err = {"code": "failed", "message": "something went wrong"}
        assert p["error"] == expect_err


# ---------------------------------------------------------------------------
# Action lifecycle payloads
# ---------------------------------------------------------------------------

class TestActionPayloads:
    def test_action_started(self) -> None:
        a = ActionStarted(
            action="read_file",
            action_id="act-1",
            payload={"path": "/tmp/x.txt"},
        )
        p = a.to_payload()
        assert p["type"] == "action.started"
        assert p["action_id"] == "act-1"
        assert p["action"] == "read_file"
        assert p["payload"] == {"path": "/tmp/x.txt"}

    def test_action_feedback(self) -> None:
        a = ActionFeedback(
            action="read_file",
            action_id="act-1",
            payload={
                "status": "in_progress",
                "progress": 0.5,
                "message": "halfway there",
            },
        )
        p = a.to_payload()
        assert p["type"] == "action.feedback"
        assert p["action_id"] == "act-1"
        assert p["payload"]["status"] == "in_progress"
        assert p["payload"]["progress"] == 0.5
        assert p["payload"]["message"] == "halfway there"

    def test_action_completed(self) -> None:
        a = ActionCompleted(
            action="read_file",
            action_id="act-1",
            payload={"result": {"lines": ["a", "b"]}},
        )
        p = a.to_payload()
        assert p["type"] == "action.completed"
        assert p["action_id"] == "act-1"
        assert p["payload"] == {"result": {"lines": ["a", "b"]}}

    def test_action_failed(self) -> None:
        a = ActionFailed(
            action="read_file",
            action_id="act-1",
            error={"code": "denied", "message": "permission denied"},
        )
        p = a.to_payload()
        assert p["type"] == "action.failed"
        assert p["action_id"] == "act-1"
        assert p["error"] == {"code": "denied", "message": "permission denied"}


# ---------------------------------------------------------------------------
# MemoryGrant / MemoryGrantRange
# ---------------------------------------------------------------------------

class TestMemoryGrantRange:
    def test_to_dict(self) -> None:
        r = MemoryGrantRange(start_line=10, end_line=20)
        d = r.to_dict()
        assert d["start_line"] == 10
        assert d["end_line"] == 20


class TestMemoryGrant:
    def test_to_dict(self) -> None:
        grant = MemoryGrant(
            grant_id="g1",
            issued_by="agent_a",
            issued_to="agent_b",
            namespace="ns1",
            path="/tmp/x.txt",
            ranges=(MemoryGrantRange(start_line=1, end_line=5),),
            whole_file=False,
            reason="testing",
            expires_at="2025-12-31T23:59:59Z",
        )
        d = grant.to_dict()
        assert d["grant_id"] == "g1"
        assert d["whole_file"] is False
        assert len(d["ranges"]) == 1
        assert d["ranges"][0]["start_line"] == 1

    def test_from_dict_ok(self) -> None:
        raw: dict[str, Any] = {
            "grant_id": "g1",
            "issued_by": "a",
            "issued_to": "b",
            "namespace": "ns",
            "path": "/f",
            "ranges": [{"start_line": 1, "end_line": 5}],
            "whole_file": False,
            "reason": "test",
            "expires_at": "2025-12-31T23:59:59Z",
        }
        grant = MemoryGrant.from_dict(raw)
        assert grant.grant_id == "g1"
        assert len(grant.ranges) == 1

    def test_from_dict_ranges_not_list(self) -> None:
        raw: dict[str, Any] = {
            "grant_id": "g1",
            "issued_by": "a",
            "issued_to": "b",
            "namespace": "ns",
            "path": "/f",
            "ranges": "not a list",
            "whole_file": False,
            "reason": "test",
            "expires_at": "2025-12-31T23:59:59Z",
        }
        with pytest.raises(RuntimeProtocolError, match="ranges must be list"):
            MemoryGrant.from_dict(raw)

    def test_from_dict_range_bad_type(self) -> None:
        raw: dict[str, Any] = {
            "grant_id": "g1",
            "issued_by": "a",
            "issued_to": "b",
            "namespace": "ns",
            "path": "/f",
            "ranges": [{"start_line": "x", "end_line": 5}],
            "whole_file": False,
            "reason": "test",
            "expires_at": "2025-12-31T23:59:59Z",
        }
        with pytest.raises(
            RuntimeProtocolError,
            match="start_line/end_line must be int",
        ):
            MemoryGrant.from_dict(raw)

    def test_from_dict_range_missing_keys(self) -> None:
        raw: dict[str, Any] = {
            "grant_id": "g1",
            "issued_by": "a",
            "issued_to": "b",
            "namespace": "ns",
            "path": "/f",
            "ranges": [{"start_line": 1}],  # missing end_line
            "whole_file": False,
            "reason": "test",
            "expires_at": "2025-12-31T23:59:59Z",
        }
        with pytest.raises(
            RuntimeProtocolError,
            match="start_line/end_line must be int",
        ):
            MemoryGrant.from_dict(raw)


# ---------------------------------------------------------------------------
# Envelope factories
# ---------------------------------------------------------------------------

class TestEnvelopeFactories:
    def test_make_request_envelope(self) -> None:
        ident = RuntimeIdentity(
            runtime_id="r1",
            chat_id="c1",
            broker_id="b1",
            trace_id="t1",
            goal_id="g1",
            namespace="ns1",
        )
        env = make_request_envelope(
            identity=ident,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent="b",
            msg_type="t",
            payload={},
        )
        assert env.message_id == "m1"
        assert env.from_agent == "a"
        assert env.to_agent == "b"
        assert env.type == "t"
        assert env.payload == {}
        assert env.parent_message_id is None

    def test_make_request_envelope_with_now(self) -> None:
        ident = RuntimeIdentity(
            runtime_id="r1",
            chat_id="c1",
            broker_id="b1",
            trace_id="t1",
            goal_id="g1",
            namespace="ns1",
        )
        now = RuntimeNow()
        env = make_request_envelope(
            identity=ident,
            message_id="m2",
            parent_message_id="m1",
            from_agent="a",
            to_agent="b",
            msg_type="t",
            payload={},
            now=now,
        )
        # created_at и now.iso() могут отличаться микросекундами — до секунд
        assert env.created_at[:19] == now.iso()[:19]

    def test_make_response_envelope(self) -> None:
        ident = RuntimeIdentity(
            runtime_id="r1",
            chat_id="c1",
            broker_id="b1",
            trace_id="t1",
            goal_id="g1",
            namespace="ns1",
        )
        req = make_request_envelope(
            identity=ident,
            message_id="m1",
            parent_message_id=None,
            from_agent="a",
            to_agent="b",
            msg_type="request",
            payload={},
        )
        env = make_response_envelope(
            request=req,
            ok=True,
            payload={"result": 42},
            error=None,
        )
        assert env.message_id == "m1"
        assert env.from_agent == "b"
        assert env.to_agent == "a"
        assert env.ok is True
        assert env.payload == {"result": 42}
        assert env.error is None

    def test_make_response_envelope_with_now(self) -> None:
        ident = RuntimeIdentity(
            runtime_id="r1",
            chat_id="c1",
            broker_id="b1",
            trace_id="t1",
            goal_id="g1",
            namespace="ns1",
        )
        req = make_request_envelope(
            identity=ident,
            message_id="m2",
            parent_message_id="m1",
            from_agent="a",
            to_agent="b",
            msg_type="request",
            payload={},
        )
        now = RuntimeNow()
        env = make_response_envelope(
            request=req,
            ok=True,
            payload={},
            error=None,
            now=now,
        )
        assert env.created_at[:19] == now.iso()[:19]


# ---------------------------------------------------------------------------
# ensure_json_*
# ---------------------------------------------------------------------------

class TestEnsureJson:
    def test_ensure_json_object_ok(self) -> None:
        assert ensure_json_object({"a": 1}) == {"a": 1}

    def test_ensure_json_object_fail(self) -> None:
        with pytest.raises(
            RuntimeProtocolError,
            match="expected dict payload",
        ):
            ensure_json_object("not dict")

    def test_ensure_json_mapping_ok(self) -> None:
        m: Mapping[str, Any] = OrderedDict([("a", 1)])
        assert ensure_json_mapping(m) is m

    def test_ensure_json_mapping_fail(self) -> None:
        with pytest.raises(
            RuntimeProtocolError,
            match="expected mapping payload",
        ):
            ensure_json_mapping("not mapping")

    def test_ensure_json_list_ok(self) -> None:
        assert ensure_json_list([1, 2, 3]) == [1, 2, 3]

    def test_ensure_json_list_fail(self) -> None:
        with pytest.raises(
            RuntimeProtocolError,
            match="expected list payload",
        ):
            ensure_json_list("not list")
