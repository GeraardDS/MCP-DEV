"""Unit tests for core.autonomous.validation_runner (DAX-free, mock executor)."""

from typing import Any, Dict

import pytest

from core.autonomous.validation_runner import ValidationRunner


class MockExecutor:
    """Minimal stand-in for OptimizedQueryExecutor.validate_and_execute_dax."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def validate_and_execute_dax(self, query, top_n=0, bypass_cache=False):
        self.calls.append(query)
        if callable(self._responses):
            return self._responses(query)
        # Otherwise pop from a list-in-order
        return self._responses.pop(0)


def _ok(value: Any) -> Dict[str, Any]:
    """Wrap a scalar into a dict matching validate_and_execute_dax shape."""
    return {"success": True, "data": [{"[v]": value}]}


def test_no_assertions_returns_zero_totals():
    runner = ValidationRunner(query_executor=MockExecutor([]))
    out = runner.run([])
    assert out["total"] == 0
    assert out["passed"] == 0
    assert out["failed"] == 0
    assert out["success"] is True


def test_missing_dax_is_rejected():
    runner = ValidationRunner(query_executor=MockExecutor([]))
    out = runner.run([{"name": "bad", "dax": ""}])
    assert out["failed"] == 1
    assert out["results"][0]["error_type"] == "invalid_assertion"


def test_unsupported_op_is_rejected():
    runner = ValidationRunner(query_executor=MockExecutor([]))
    out = runner.run([{"name": "bad", "dax": "X", "op": "bogus"}])
    assert out["failed"] == 1
    assert out["results"][0]["error_type"] == "invalid_op"


def test_truthy_passes_on_truthy_scalar():
    runner = ValidationRunner(query_executor=MockExecutor([_ok(5)]))
    out = runner.run([{"name": "ok", "dax": "X"}])
    assert out["success"] is True
    assert out["results"][0]["actual"] == 5


def test_truthy_fails_on_zero():
    runner = ValidationRunner(query_executor=MockExecutor([_ok(0)]))
    out = runner.run([{"name": "zero", "dax": "X"}])
    assert out["failed"] == 1
    assert out["results"][0]["error"] is not None


def test_eq_op():
    runner = ValidationRunner(query_executor=MockExecutor([_ok(42)]))
    out = runner.run([{"name": "eq", "dax": "X", "op": "eq", "expected": 42}])
    assert out["success"] is True


def test_gte_op_numeric():
    runner = ValidationRunner(query_executor=MockExecutor([_ok(10)]))
    out = runner.run([{"name": "gte", "dax": "X", "op": "gte", "expected": 5}])
    assert out["success"] is True


def test_lt_fails_when_equal():
    runner = ValidationRunner(query_executor=MockExecutor([_ok(5)]))
    out = runner.run([{"name": "lt", "dax": "X", "op": "lt", "expected": 5}])
    assert out["failed"] == 1


def test_in_op():
    runner = ValidationRunner(query_executor=MockExecutor([_ok("B")]))
    out = runner.run([{"name": "in", "dax": "X", "op": "in", "expected": ["A", "B", "C"]}])
    assert out["success"] is True


def test_not_null_op():
    runner = ValidationRunner(query_executor=MockExecutor([_ok(None)]))
    out = runner.run([{"name": "nn", "dax": "X", "op": "not_null"}])
    assert out["failed"] == 1


def test_query_failure_surfaces_as_failed_assertion():
    fail_result = {"success": False, "error": "bad dax", "error_type": "syntax_error"}
    runner = ValidationRunner(query_executor=MockExecutor([fail_result]))
    out = runner.run([{"name": "q", "dax": "X"}])
    assert out["failed"] == 1
    assert out["results"][0]["error_type"] == "syntax_error"


def test_no_executor_returns_structured_error():
    runner = ValidationRunner(query_executor=None)
    out = runner.run([{"name": "q", "dax": "X"}])
    # Runner tries to resolve from connection_state — in a unit test that
    # typically returns None too, so we expect a failed assertion either way.
    assert out["failed"] == 1


def test_comparison_type_error_caught():
    runner = ValidationRunner(query_executor=MockExecutor([_ok("text")]))
    out = runner.run([{"name": "gt", "dax": "X", "op": "gt", "expected": 5}])
    assert out["failed"] == 1
    assert "Comparison failed" in out["results"][0]["error"]


def test_aggregate_success_flag():
    """All assertions must pass for overall success."""
    runner = ValidationRunner(query_executor=MockExecutor([_ok(1), _ok(0)]))
    out = runner.run(
        [
            {"name": "a", "dax": "X"},
            {"name": "b", "dax": "Y"},
        ]
    )
    assert out["success"] is False
    assert out["passed"] == 1
    assert out["failed"] == 1
