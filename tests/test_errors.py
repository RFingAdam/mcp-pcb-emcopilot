"""Tests for structured error types and validation helpers."""
import math
import pytest
from mcp_pcb_emcopilot.errors import (
    PCBError, ParseError, ValidationError, AnalysisError, SessionError,
    error_response, validate_positive, validate_non_negative,
    validate_range, validate_session, validate_string,
)


class TestErrorTypes:
    def test_pcb_error_str(self):
        e = PCBError("TEST_CODE", "test message")
        assert str(e) == "[TEST_CODE] test message"

    def test_pcb_error_to_dict(self):
        e = PCBError("CODE", "msg", {"key": "val"})
        d = e.to_dict()
        assert d["error_type"] == "PCBError"
        assert d["code"] == "CODE"
        assert d["message"] == "msg"
        assert d["context"] == {"key": "val"}

    def test_parse_error_inherits(self):
        e = ParseError("MALFORMED", "bad file", {"file": "x.pcb"})
        assert isinstance(e, PCBError)
        assert e.to_dict()["error_type"] == "ParseError"

    def test_validation_error_inherits(self):
        e = ValidationError("INVALID", "bad input")
        assert isinstance(e, PCBError)

    def test_analysis_error_inherits(self):
        e = AnalysisError("CALC_FAIL", "overflow")
        assert isinstance(e, PCBError)

    def test_session_error_inherits(self):
        e = SessionError("NO_SESSION", "not found")
        assert isinstance(e, PCBError)


class TestErrorResponse:
    def test_basic(self):
        r = error_response("CODE", "message")
        assert r["success"] is False
        assert r["error"]["code"] == "CODE"
        assert r["error"]["message"] == "message"
        assert r["error"]["context"] == {}

    def test_with_context(self):
        r = error_response("CODE", "msg", {"width": -1})
        assert r["error"]["context"]["width"] == -1


class TestValidatePositive:
    def test_valid(self):
        assert validate_positive(1.0, "w") == 1.0
        assert validate_positive(0.001, "w") == 0.001

    def test_zero(self):
        with pytest.raises(ValidationError, match="positive"):
            validate_positive(0.0, "width")

    def test_negative(self):
        with pytest.raises(ValidationError, match="positive"):
            validate_positive(-1.0, "width")

    def test_nan(self):
        with pytest.raises(ValidationError, match="finite"):
            validate_positive(float("nan"), "width")

    def test_inf(self):
        with pytest.raises(ValidationError, match="finite"):
            validate_positive(float("inf"), "width")

    def test_string_input(self):
        with pytest.raises(ValidationError, match="finite"):
            validate_positive("abc", "width")


class TestValidateNonNegative:
    def test_zero_ok(self):
        assert validate_non_negative(0.0, "x") == 0.0

    def test_positive_ok(self):
        assert validate_non_negative(5.0, "x") == 5.0

    def test_negative_fails(self):
        with pytest.raises(ValidationError):
            validate_non_negative(-0.1, "x")


class TestValidateRange:
    def test_in_range(self):
        assert validate_range(4.3, 1.0, 20.0, "Er") == 4.3

    def test_at_bounds(self):
        assert validate_range(1.0, 1.0, 20.0, "Er") == 1.0
        assert validate_range(20.0, 1.0, 20.0, "Er") == 20.0

    def test_below_range(self):
        with pytest.raises(ValidationError, match="between"):
            validate_range(0.5, 1.0, 20.0, "Er")

    def test_above_range(self):
        with pytest.raises(ValidationError, match="between"):
            validate_range(25.0, 1.0, 20.0, "Er")

    def test_nan_fails(self):
        with pytest.raises(ValidationError):
            validate_range(float("nan"), 1.0, 20.0, "Er")


class TestValidateSession:
    def test_valid_session(self):
        class MockManager:
            def get(self, sid):
                return {"data": True} if sid == "abc" else None
        result = validate_session("abc", MockManager())
        assert result == {"data": True}

    def test_invalid_session(self):
        class MockManager:
            def get(self, sid):
                return None
        with pytest.raises(SessionError, match="No active session"):
            validate_session("nonexistent", MockManager())


class TestValidateString:
    def test_valid(self):
        assert validate_string("hello", "name") == "hello"

    def test_empty(self):
        with pytest.raises(ValidationError, match="non-empty"):
            validate_string("", "name")

    def test_none(self):
        with pytest.raises(ValidationError, match="non-empty"):
            validate_string(None, "name")

    def test_allowed_values(self):
        assert validate_string("png", "fmt", ["png", "svg"]) == "png"

    def test_disallowed_value(self):
        with pytest.raises(ValidationError, match="must be one of"):
            validate_string("pdf", "fmt", ["png", "svg"])
