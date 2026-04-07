"""Tests for unified DAX analyzer."""

import pytest

from core.dax.analyzer.models import (
    AnalysisContext,
    AnalysisIssue,
    UnifiedAnalysisResult,
    RewriteCandidate,
)


class TestAnalyzerModels:
    def test_analysis_issue_creation(self):
        issue = AnalysisIssue(
            rule_id="PERF_SUMX_FILTER",
            category="performance",
            severity="critical",
            title="SUMX(FILTER()) anti-pattern",
            description="Forces row-by-row evaluation",
            fix_suggestion="Use CALCULATE instead",
            source="static",
        )
        assert issue.rule_id == "PERF_SUMX_FILTER"
        assert issue.confidence == "high"

    def test_analysis_context_defaults(self):
        ctx = AnalysisContext()
        assert ctx.vertipaq_data is None
        assert ctx.table_row_counts is None
        assert ctx.trace_data is None

    def test_unified_result_from_issues(self):
        issues = [
            AnalysisIssue("R1", "performance", "critical", "T", "D", "F", "static"),
            AnalysisIssue("R2", "performance", "high", "T", "D", "F", "static"),
            AnalysisIssue("R3", "maintainability", "low", "T", "D", "F", "static"),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        assert 0 <= result.health_score <= 100
        assert result.total_issues == 3
        assert result.critical_issues == 1
        assert result.high_issues == 1
        assert result.health_score == 100 - 20 - 10 - 2  # 68

    def test_to_best_practices_format(self):
        issues = [
            AnalysisIssue(
                "R1",
                "performance",
                "critical",
                "Title",
                "Desc",
                "Fix",
                "static",
                code_before="BAD",
                code_after="GOOD",
                estimated_improvement="5x",
                references=[{"source": "SQLBI", "url": "https://sqlbi.com/x"}],
            ),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        bp = result.to_best_practices_format()
        assert bp["success"] is True
        assert bp["total_issues"] == 1
        assert bp["overall_score"] == 80
        assert len(bp["issues"]) == 1
        assert len(bp["articles_referenced"]) == 1
        assert bp["complexity_level"] == "complex"

    def test_to_rules_engine_format(self):
        issues = [
            AnalysisIssue(
                "PERF001",
                "performance",
                "high",
                "T",
                "D",
                "Fix",
                "static",
                line=5,
                match_text="SUMX(",
            ),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        re_fmt = result.to_rules_engine_format()
        assert re_fmt["health_score"] == 90
        assert re_fmt["issue_count"] == 1
        assert re_fmt["issues"][0]["rule_id"] == "PERF001"
        assert re_fmt["issues"][0]["line"] == 5
        assert "performance" in re_fmt["categories"]

    def test_to_callback_format(self):
        issues = [
            AnalysisIssue(
                "CB001", "performance", "critical", "T", "D", "F", "static"
            ),
            AnalysisIssue(
                "PERF001", "performance", "high", "T", "D", "F", "static"
            ),
        ]
        result = UnifiedAnalysisResult.from_issues(issues, tier_used=1)
        cb = result.to_callback_format()
        assert cb["success"] is True
        assert cb["total_detections"] == 1
        assert len(cb["detections"]) == 1
        assert cb["detections"][0]["rule_id"] == "CB001"

    def test_rewrite_candidates_extracted(self):
        issues = [
            AnalysisIssue(
                "R1",
                "performance",
                "high",
                "T",
                "D",
                "F",
                "static",
                rewrite_strategy="variable_extraction",
            ),
            AnalysisIssue(
                "R2", "performance", "medium", "T", "D", "F", "static"
            ),
        ]
        result = UnifiedAnalysisResult.from_issues(issues)
        assert len(result.rewrite_candidates) == 1
        assert result.rewrite_candidates[0].strategy_name == "variable_extraction"

    def test_empty_issues(self):
        result = UnifiedAnalysisResult.from_issues([])
        assert result.health_score == 100
        assert result.total_issues == 0
        assert result.summary == "0 issues found (score: 100/100)"

    def test_issue_to_dict(self):
        issue = AnalysisIssue(
            "R1",
            "performance",
            "critical",
            "Title",
            "Desc",
            "Fix",
            "static",
            code_before="BAD",
            code_after="GOOD",
            references=[{"source": "SQLBI", "url": "https://x.com"}],
        )
        d = issue.to_dict()
        assert d["rule_id"] == "R1"
        assert d["severity"] == "critical"
        assert d["code_example_before"] == "BAD"
        assert d["code_example_after"] == "GOOD"
        assert d["article_reference"]["source"] == "SQLBI"
