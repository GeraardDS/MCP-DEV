"""Tests for BPA expression evaluation engine.

Covers:
- _eval_depth always decremented (even on exception) via finally block
- max_depth guard prevents stack overflow
- OR / AND expression splitting
- Basic property evaluation
- Boolean negation
"""

import pytest
from core.analysis.bpa_analyzer import BPAAnalyzer


@pytest.fixture
def analyzer():
    """BPAAnalyzer with no rules loaded (we test the evaluator directly)."""
    a = BPAAnalyzer.__new__(BPAAnalyzer)
    a.rules = []
    a.violations = []
    a._eval_depth = 0
    a._max_depth = 50
    a._regex_cache = {}
    a._run_notes = []
    a._fast_cfg = {}
    a._expression_cache = {}
    a._cache_hits = 0
    a._cache_misses = 0
    return a


# ---------------------------------------------------------------------------
# Depth tracking
# ---------------------------------------------------------------------------

class TestEvalDepth:

    def test_depth_zero_after_evaluation(self, analyzer):
        """After any evaluation, _eval_depth should return to 0."""
        analyzer.evaluate_expression("true", {"obj": {}})
        assert analyzer._eval_depth == 0

    def test_depth_zero_after_complex_expression(self, analyzer):
        """Even nested expressions should leave depth at 0."""
        ctx = {"obj": {"Name": "test", "IsHidden": False}}
        analyzer.evaluate_expression('Name == "test"', ctx)
        assert analyzer._eval_depth == 0

    def test_depth_zero_after_error(self, analyzer):
        """Depth must be decremented even when evaluation hits an error path."""
        # An unhandled expression returns False but should still decrement
        analyzer.evaluate_expression("$$$weird$$$", {"obj": {}})
        assert analyzer._eval_depth == 0

    def test_max_depth_guard(self, analyzer):
        """When _eval_depth exceeds _max_depth, evaluation returns False."""
        analyzer._max_depth = 2
        # Manually set depth near the limit
        analyzer._eval_depth = 2
        # Direct call to impl -- should hit the guard
        result = analyzer._evaluate_expression_impl("Name == \"x\"", {"obj": {"Name": "x"}})
        assert result is False
        # Depth should still be decremented back
        assert analyzer._eval_depth == 2  # Was 2 before, +1 then -1 in finally

    def test_depth_reset_between_evaluations(self, analyzer):
        """Multiple sequential evaluations should each start/end at depth 0."""
        for _ in range(5):
            analyzer.evaluate_expression("true", {"obj": {}})
            assert analyzer._eval_depth == 0


# ---------------------------------------------------------------------------
# OR / AND splitting
# ---------------------------------------------------------------------------

class TestOrAndSplitting:

    def test_or_true_when_one_side_true(self, analyzer):
        ctx = {"obj": {"Name": "hello", "Description": ""}}
        result = analyzer.evaluate_expression(
            'Name == "hello" or Name == "world"', ctx
        )
        assert result is True

    def test_or_false_when_both_false(self, analyzer):
        ctx = {"obj": {"Name": "other"}}
        result = analyzer.evaluate_expression(
            'Name == "hello" or Name == "world"', ctx
        )
        assert result is False

    def test_and_true_when_both_true(self, analyzer):
        ctx = {"obj": {"Name": "hello", "IsHidden": True}}
        result = analyzer.evaluate_expression(
            'Name == "hello" and IsHidden == true', ctx
        )
        assert result is True

    def test_and_false_when_one_false(self, analyzer):
        ctx = {"obj": {"Name": "hello", "IsHidden": False}}
        result = analyzer.evaluate_expression(
            'Name == "hello" and IsHidden == true', ctx
        )
        assert result is False

    def test_double_pipe_or(self, analyzer):
        ctx = {"obj": {"Name": "world"}}
        result = analyzer.evaluate_expression(
            'Name == "hello" || Name == "world"', ctx
        )
        assert result is True

    def test_double_ampersand_and(self, analyzer):
        ctx = {"obj": {"Name": "hello", "IsHidden": True}}
        result = analyzer.evaluate_expression(
            'Name == "hello" && IsHidden == true', ctx
        )
        assert result is True


# ---------------------------------------------------------------------------
# Boolean and property evaluation
# ---------------------------------------------------------------------------

class TestPropertyEvaluation:

    def test_simple_equality_true(self, analyzer):
        ctx = {"obj": {"Name": "Sales"}}
        result = analyzer.evaluate_expression('Name == "Sales"', ctx)
        assert result is True

    def test_simple_equality_false(self, analyzer):
        ctx = {"obj": {"Name": "Costs"}}
        result = analyzer.evaluate_expression('Name == "Sales"', ctx)
        assert result is False

    def test_inequality(self, analyzer):
        ctx = {"obj": {"Name": "Costs"}}
        result = analyzer.evaluate_expression('Name != "Sales"', ctx)
        assert result is True

    def test_not_expression(self, analyzer):
        ctx = {"obj": {"IsHidden": True}}
        result = analyzer.evaluate_expression("not IsHidden == true", ctx)
        assert result is False

    def test_null_comparison(self, analyzer):
        ctx = {"obj": {"Description": None}}
        result = analyzer.evaluate_expression("Description == null", ctx)
        assert result is True

    def test_empty_expression_returns_false(self, analyzer):
        result = analyzer.evaluate_expression("", {"obj": {}})
        assert result is False

    def test_none_expression_returns_false(self, analyzer):
        result = analyzer.evaluate_expression(None, {"obj": {}})
        assert result is False


# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------

class TestNumericComparisons:

    def test_greater_than(self, analyzer):
        ctx = {"obj": {"ColumnCount": 5}}
        result = analyzer.evaluate_expression("ColumnCount > 3", ctx)
        assert result is True

    def test_less_than(self, analyzer):
        ctx = {"obj": {"ColumnCount": 2}}
        result = analyzer.evaluate_expression("ColumnCount < 3", ctx)
        assert result is True

    def test_greater_equal(self, analyzer):
        ctx = {"obj": {"ColumnCount": 3}}
        result = analyzer.evaluate_expression("ColumnCount >= 3", ctx)
        assert result is True
