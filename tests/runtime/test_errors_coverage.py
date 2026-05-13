"""Unit tests for runtime/errors.py — coverage.

Covers:
- RuntimeProtocolError.__str__
"""

from ailit_runtime.errors import RuntimeProtocolError


class TestRuntimeProtocolError:
    def test_str(self) -> None:
        err = RuntimeProtocolError(code="ERR001", message="something went wrong")
        assert str(err) == "ERR001: something went wrong"

    def test_str_empty(self) -> None:
        err = RuntimeProtocolError(code="", message="")
        assert str(err) == ": "
