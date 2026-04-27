"""Unit tests for runtime/models.py — coverage of uncovered lines.

Covers:
- RuntimeIdentity.to_dict()
- RuntimeNow.iso() / RuntimeNow
- ServiceResponse.to_payload()
- ActionStarted / ActionFeedback / ActionCompleted / ActionFailed .to_payload()
- MemoryGrantRange.to_dict()
- MemoryGrant.from_dict() with invalid ranges
- MemoryGrant.to_dict()
- make_request_envelope / make_response_envelope
- ensure_json_object / ensure_json_mapping / ensure_json_list with non-dict/non-list
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
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
    def test_to_dict(self) -> None:
        ident = RuntimeIdentity(
            runtime_id="r1",
            chat_id="c1",
            broker_id="b1",
            trace_id="t1",
            goal_id="g1",
            namespace="ns1",
        )
        d = ident.to_dict()
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
        assert iso1 == iso2  # same instant


# ---------------------------------------------------------------------------
# ServiceResponse
# ---------------------------------------------------------------------------

class TestServiceResponse:
    def test_to_payload(self) -> None:
        resp = ServiceResponse(
            status="ok",
            data={"result": 42},
            error=None,
        )
        p = resp.to_payload()
        assert p["status"] == "ok"
        assert p["data"] == {"result": 42}
        assert p["error"] is None

    def test_to_payload_with_error(self) -> None:
        resp = ServiceResponse(
            status="error",
            data=None,
            error="something went wrong",
        )
        p = resp.to_payload()
        assert p["status"] == "error"
        assert p["error"] == "something went wrong"


# ---------------------------------------------------------------------------
# Action lifecycle payloads
# ---------------------------------------------------------------------------

class TestActionPayloads:
    def test_action_started(self) -> None:
        a = ActionStarted(
            action_id="act-1",
            action_type="read_file",
            params={"path": "/tmp/x.txt"},
        )
        p = a.to_payload()
        assert p["action_id"] == "act-1"
        assert p["action_type"] == "read_file"
        assert p["params"] == {"path": "/tmp/x.txt"}

    def test_action_feedback(self) -> None:
        a = ActionFeedback(
            action_id="act-1",
            status="in_progress",
            progress=0.5,
            message="halfway there",
        )
        p = a.to_payload()
        assert p["action_id"] == "act-1"
        assert p["status"] == "in_progress"
        assert p["progress"] == 0.5
        assert p["message"] == "halfway there"

    def test_action_completed(self) -> None:
        a = ActionCompleted(
            action_id="act-1",
            result={"lines": ["a", "b"]},
        )
        p = a.to_payload()
        assert p["action_id"] == "act-1"
        assert p["result"] == {"lines": ["a", "b"]}

    def test_action_failed(self) -> None:
        a = ActionFailed(
            action_id="act-1",
            error="permission denied",
        )
        p = a.to_payload()
        assert p["action_id"] == "act-1"
        assert p["error"] == "permission denied"


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
        with pytest.raises(RuntimeProtocolError, match="start_line/end_line must be int"):
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
        with pytest.raises(RuntimeProtocolError, match="start_line/end_line must be int"):
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
        # created_at and now.iso() may differ by microseconds; compare up to seconds
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
        with pytest.raises(RuntimeProtocolError, match="expected dict payload"):
            ensure_json_object("not dict")

    def test_ensure_json_mapping_ok(self) -> None:
        m: Mapping[str, Any] = OrderedDict([("a", 1)])
        assert ensure_json_mapping(m) is m

    def test_ensure_json_mapping_fail(self) -> None:
        with pytest.raises(RuntimeProtocolError, match="expected mapping payload"):
            ensure_json_mapping("not mapping")

    def test_ensure_json_list_ok(self) -> None:
        assert ensure_json_list([1, 2, 3]) == [1, 2, 3]

    def test_ensure_json_list_fail(self) -> None:
        with pytest.raises(RuntimeProtocolError, match="expected list payload"):
            ensure_json_list("not list")
