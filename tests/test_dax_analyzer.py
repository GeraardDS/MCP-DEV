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


# ------------------------------------------------------------------
# JSON Rule Engine tests
# ------------------------------------------------------------------

from core.dax.analyzer.rule_engine import JsonRuleEngine
from core.dax.tokenizer import DaxLexer, TokenType
from core.dax.knowledge import DaxFunctionDatabase


class TestJsonRuleEngine:

    @pytest.fixture
    def engine(self):
        return JsonRuleEngine()

    @pytest.fixture
    def lexer(self):
        db = DaxFunctionDatabase.get()
        return DaxLexer(function_names=db.get_function_names())

    def test_loads_rules(self, engine):
        assert engine.rule_count() > 20

    def test_detects_sumx_filter_nesting(self, engine, lexer):
        dax = "SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        rule_ids = [i.rule_id for i in issues]
        assert any("SUMX_FILTER" in rid or "FILTER" in rid for rid in rule_ids)

    def test_detects_format_usage(self, engine, lexer):
        dax = 'FORMAT([Sales], "#,##0")'
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any("FORMAT" in i.rule_id for i in issues)

    def test_detects_iferror_usage(self, engine, lexer):
        dax = "IFERROR([Sales] / [Cost], 0)"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any("IFERROR" in i.rule_id for i in issues)

    def test_clean_dax_no_critical(self, engine, lexer):
        dax = "CALCULATE(SUM(Sales[Amount]), Sales[Year] = 2024)"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        critical = [i for i in issues if i.severity == "critical"]
        assert len(critical) == 0

    def test_detects_division_without_divide(self, engine, lexer):
        dax = "[Sales] / [Cost]"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any("DIVIDE" in i.rule_id or "DIVISION" in i.rule_id for i in issues)

    def test_detects_unused_var(self, engine, lexer):
        dax = "VAR _unused = 1\nVAR _used = 2\nRETURN _used"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any(
            "UNUSED" in i.rule_id.upper() or "VAR" in i.rule_id.upper()
            for i in issues
        )

    def test_detects_bare_table_in_filter(self, engine, lexer):
        dax = "FILTER(Sales, Sales[Amount] > 100)"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any(
            "BARE" in i.rule_id.upper() or "CB004" in i.rule_id for i in issues
        )

    def test_detects_if_in_iterator(self, engine, lexer):
        dax = "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        tokens = lexer.tokenize_code(dax)
        issues = engine.evaluate(tokens, dax)
        assert any(
            "CB001" in i.rule_id
            or ("IF" in i.rule_id.upper() and "ITERATOR" in i.rule_id.upper())
            for i in issues
        )


# ------------------------------------------------------------------
# Python rule engine tests
# ------------------------------------------------------------------

from core.dax.analyzer.rules import load_python_rules


class TestPythonRules:

    @pytest.fixture
    def rules(self):
        return load_python_rules()

    @pytest.fixture
    def lexer(self):
        db = DaxFunctionDatabase.get()
        return DaxLexer(function_names=db.get_function_names())

    @pytest.fixture
    def function_db(self):
        return DaxFunctionDatabase.get()

    def test_loads_all_rules(self, rules):
        assert len(rules) >= 15

    def test_nested_iterator_detected(self, rules, lexer, function_db):
        dax = "SUMX(Sales, SUMX(RELATEDTABLE(Products), Products[Price]))"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("NESTED" in i.rule_id.upper() for i in all_issues)

    def test_if_in_iterator_detected(self, rules, lexer, function_db):
        dax = "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("IF" in i.rule_id.upper() for i in all_issues)

    def test_unnecessary_iterator_detected(self, rules, lexer, function_db):
        dax = "SUMX(Sales, Sales[Amount])"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("UNNECESSARY" in i.rule_id.upper() for i in all_issues)

    def test_var_defeating_shortcircuit(self, rules, lexer, function_db):
        dax = (
            "VAR _A = CALCULATE([Sales], Filter1)\n"
            "VAR _B = CALCULATE([Sales LY], Filter2)\n"
            "VAR _C = CALCULATE([Sales YOY], Filter3)\n"
            "RETURN SWITCH(TRUE(), Sel = \"C\", _A, Sel = \"LY\", _B, _C)"
        )
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any(
            "SHORT" in i.rule_id.upper() or "VAR_DEFEAT" in i.rule_id.upper()
            for i in all_issues
        )

    def test_blank_propagation_1_minus(self, rules, lexer, function_db):
        dax = "1 - DIVIDE([Sales], [Budget])"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("BLANK" in i.rule_id.upper() for i in all_issues)

    def test_unused_var_detected(self, rules, lexer, function_db):
        dax = "VAR _unused = 42\nVAR _used = 10\nRETURN _used + 1"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("UNUSED" in i.rule_id.upper() for i in all_issues)

    def test_measure_ref_without_var(self, rules, lexer, function_db):
        dax = "[Sales] + [Sales] + [Sales] + [Cost]"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("MEASURE_REF" in i.rule_id.upper() for i in all_issues)

    def test_clean_dax_minimal_issues(self, rules, lexer, function_db):
        dax = (
            "VAR _Sales = SUM(Sales[Amount])\n"
            "VAR _Budget = SUM(Budget[Amount])\n"
            "RETURN DIVIDE(_Sales, _Budget)"
        )
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        critical = [i for i in all_issues if i.severity == "critical"]
        assert len(critical) == 0

    def test_direct_measure_reference(self, rules, lexer, function_db):
        dax = "[Other Measure]"
        tokens = lexer.tokenize_code(dax)
        all_issues = []
        for rule in rules:
            all_issues.extend(rule.evaluate(tokens, function_db))
        assert any("DIRECT" in i.rule_id.upper() for i in all_issues)
