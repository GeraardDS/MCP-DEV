"""Tests verifying backward compatibility of facade classes."""

import pytest


class TestBestPracticesFacade:
    def test_analyze_returns_expected_keys(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer

        analyzer = DaxBestPracticesAnalyzer()
        result = analyzer.analyze("SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])")
        assert result["success"] is True
        assert "total_issues" in result
        assert "critical_issues" in result
        assert "high_issues" in result
        assert "medium_issues" in result
        assert "issues" in result
        assert "summary" in result
        assert "overall_score" in result
        assert isinstance(result["issues"], list)

    def test_analyze_with_none_params(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer

        result = DaxBestPracticesAnalyzer().analyze("SUM(Sales[Amount])", None, None)
        assert result["success"] is True

    def test_detects_issues(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer

        result = DaxBestPracticesAnalyzer().analyze(
            "SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])"
        )
        assert result["total_issues"] > 0


class TestRulesEngineFacade:
    def test_analyze_returns_expected_keys(self):
        from core.dax.dax_rules_engine import DaxRulesEngine

        result = DaxRulesEngine().analyze("SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))")
        assert "health_score" in result
        assert "issues" in result
        assert "issue_count" in result
        assert isinstance(result["health_score"], int)
        assert 0 <= result["health_score"] <= 100

    def test_issue_format(self):
        from core.dax.dax_rules_engine import DaxRulesEngine

        result = DaxRulesEngine().analyze("SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))")
        if result["issue_count"] > 0:
            issue = result["issues"][0]
            assert "rule_id" in issue
            assert "severity" in issue
            assert "description" in issue
            assert "fix_suggestion" in issue


class TestCallbackDetectorFacade:
    def test_detect_dict_returns_expected_keys(self):
        from core.dax.callback_detector import CallbackDetector

        result = CallbackDetector().detect_dict(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        assert "callback_detections" in result
        assert "summary" in result
        assert isinstance(result["callback_detections"], list)
        assert "total" in result["summary"]

    def test_detect_returns_list(self):
        from core.dax.callback_detector import CallbackDetector

        result = CallbackDetector().detect(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        assert isinstance(result, list)

    def test_detect_returns_callback_detections(self):
        from core.dax.callback_detector import CallbackDetector, CallbackDetection

        result = CallbackDetector().detect(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        assert len(result) > 0
        for detection in result:
            assert isinstance(detection, CallbackDetection)
            assert detection.rule_id.startswith("CB")
