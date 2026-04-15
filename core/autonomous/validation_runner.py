"""
DAX Assertion Runner

Executes a list of assertions after a refresh / reload to verify the model
returned to a sane state. Each assertion is:

    {
      "name": "Measure count > 0",
      "dax": "EVALUATE ROW(\"v\", COUNTROWS(INFO.MEASURES()))",
      "expected": 1,              # optional — omit for "succeeded" semantics
      "op": "gte"                 # eq|ne|lt|lte|gt|gte|in|not_null|truthy
    }

The runner never raises. Each assertion records pass/fail + error. An overall
`passed` / `failed` count is returned alongside the per-assertion details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


SUPPORTED_OPS = {
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "in",
    "not_null",
    "truthy",
}


@dataclass
class AssertionResult:
    name: str
    passed: bool
    op: str
    expected: Any = None
    actual: Any = None
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    error_type: Optional[str] = None
    dax: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": self.name,
            "passed": self.passed,
            "op": self.op,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        if self.error:
            out["error"] = self.error
        if self.error_type:
            out["error_type"] = self.error_type
        return out


class ValidationRunner:
    """Run a batch of DAX assertions against the active connection."""

    def __init__(self, query_executor=None) -> None:  # type: ignore[no-untyped-def]
        """
        Args:
            query_executor: Any object exposing
                `validate_and_execute_dax(query, top_n=0, bypass_cache=False)`.
                If None, the runner resolves it lazily from connection_state.
        """
        self._query_executor = query_executor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(
        self,
        assertions: List[Dict[str, Any]],
        bypass_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute each assertion sequentially.

        Returns:
            {
              "success": bool,   # True iff all passed
              "passed": N,
              "failed": M,
              "total": N+M,
              "results": [AssertionResult.to_dict(), ...],
              "elapsed_seconds": float,
            }
        """
        start = time.time()
        results: List[AssertionResult] = []

        for idx, spec in enumerate(assertions or []):
            name = str(spec.get("name") or f"assertion_{idx + 1}")
            dax = (spec.get("dax") or "").strip()
            op = str(spec.get("op") or "truthy").lower()
            expected = spec.get("expected")

            if not dax:
                results.append(
                    AssertionResult(
                        name=name,
                        passed=False,
                        op=op,
                        dax="",
                        error="Missing 'dax' field",
                        error_type="invalid_assertion",
                    )
                )
                continue
            if op not in SUPPORTED_OPS:
                results.append(
                    AssertionResult(
                        name=name,
                        passed=False,
                        op=op,
                        dax=dax,
                        error=f"Unsupported op '{op}'. " f"Supported: {sorted(SUPPORTED_OPS)}",
                        error_type="invalid_op",
                    )
                )
                continue

            results.append(self._run_one(name, dax, op, expected, bypass_cache))

        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        return {
            "success": failed == 0,
            "passed": passed,
            "failed": failed,
            "total": len(results),
            "results": [r.to_dict() for r in results],
            "elapsed_seconds": round(time.time() - start, 2),
        }

    # ------------------------------------------------------------------
    # One assertion
    # ------------------------------------------------------------------
    def _run_one(
        self,
        name: str,
        dax: str,
        op: str,
        expected: Any,
        bypass_cache: bool,
    ) -> AssertionResult:
        t0 = time.time()
        qe = self._resolve_executor()
        if qe is None:
            return AssertionResult(
                name=name,
                passed=False,
                op=op,
                expected=expected,
                dax=dax,
                elapsed_ms=(time.time() - t0) * 1000,
                error="No query executor available (not connected?)",
                error_type="no_executor",
            )

        try:
            result = qe.validate_and_execute_dax(
                dax,
                top_n=0,
                bypass_cache=bypass_cache,
            )
        except Exception as e:  # noqa: BLE001
            return AssertionResult(
                name=name,
                passed=False,
                op=op,
                expected=expected,
                dax=dax,
                elapsed_ms=(time.time() - t0) * 1000,
                error=str(e),
                error_type="query_exception",
            )

        if not result or not result.get("success"):
            return AssertionResult(
                name=name,
                passed=False,
                op=op,
                expected=expected,
                dax=dax,
                elapsed_ms=(time.time() - t0) * 1000,
                error=(result or {}).get("error", "Query failed"),
                error_type=(result or {}).get("error_type", "query_failed"),
            )

        actual = self._extract_scalar(result)
        passed, detail = self._compare(op, actual, expected)
        return AssertionResult(
            name=name,
            passed=passed,
            op=op,
            expected=expected,
            actual=actual,
            dax=dax,
            elapsed_ms=(time.time() - t0) * 1000,
            error=None if passed else detail,
            error_type=None if passed else "assertion_failed",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_executor(self):
        if self._query_executor is not None:
            return self._query_executor
        try:
            from core.infrastructure.connection_state import connection_state

            return connection_state.query_executor
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _extract_scalar(result: Dict[str, Any]) -> Any:
        """
        Pull a single scalar out of a DAX result. If result is a table with
        one row and one column, return that value; otherwise return the raw
        rows list so 'in' / 'not_null' can still be evaluated sensibly.
        """
        data = result.get("data") or result.get("rows") or []
        if isinstance(data, list) and len(data) == 1:
            row = data[0]
            if isinstance(row, dict) and len(row) == 1:
                return next(iter(row.values()))
            if isinstance(row, (list, tuple)) and len(row) == 1:
                return row[0]
        return data

    @staticmethod
    def _compare(op: str, actual: Any, expected: Any) -> tuple[bool, Optional[str]]:
        try:
            if op == "truthy":
                return bool(actual), (None if bool(actual) else f"Value is falsy: {actual!r}")
            if op == "not_null":
                ok = actual is not None and actual != ""
                return ok, (None if ok else "Value is null/empty")
            if op == "eq":
                return actual == expected, (
                    None if actual == expected else f"{actual!r} != {expected!r}"
                )
            if op == "ne":
                return actual != expected, (
                    None if actual != expected else f"{actual!r} == {expected!r}"
                )
            if op == "in":
                if not isinstance(expected, (list, tuple, set)):
                    return False, f"'expected' must be a list for 'in' op"
                ok = actual in expected
                return ok, (None if ok else f"{actual!r} not in {list(expected)!r}")
            # Numeric comparisons
            af = float(actual)  # type: ignore[arg-type]
            ef = float(expected)  # type: ignore[arg-type]
            if op == "lt":
                return af < ef, None if af < ef else f"{af} !< {ef}"
            if op == "lte":
                return af <= ef, None if af <= ef else f"{af} !<= {ef}"
            if op == "gt":
                return af > ef, None if af > ef else f"{af} !> {ef}"
            if op == "gte":
                return af >= ef, None if af >= ef else f"{af} !>= {ef}"
        except (TypeError, ValueError) as e:
            return False, f"Comparison failed: {e}"
        return False, "Unknown op"
