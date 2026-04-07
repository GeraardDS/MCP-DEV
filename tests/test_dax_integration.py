"""End-to-end integration tests for DAX engine overhaul.

Tests the full pipeline: tokenize -> analyze -> rewrite -> validate.
Also verifies backward compatibility of all existing APIs.
"""

import pytest


class TestEndToEndPipeline:
    """Full pipeline: analyze -> rewrite -> validate."""

    def test_complex_measure_full_pipeline(self):
        from core.dax.optimizer.pipeline import OptimizationPipeline

        dax = """
        SUMX(
            FILTER(ALL('Product'), 'Product'[Category] = "Electronics"),
            [Sales Amount] + [Sales Amount]
        )
        """
        pipeline = OptimizationPipeline()
        result = pipeline.optimize_expression(dax)
        assert result.success
        assert result.analysis.total_issues > 0

    def test_clean_measure_no_critical(self):
        from core.dax.optimizer.pipeline import OptimizationPipeline

        dax = """
        VAR _Sales = SUM(Sales[Amount])
        VAR _Budget = SUM(Budget[Amount])
        RETURN DIVIDE(_Sales, _Budget)
        """
        pipeline = OptimizationPipeline()
        result = pipeline.optimize_expression(dax)
        assert result.success
        critical = [i for i in result.analysis.issues if i.severity == "critical"]
        assert len(critical) == 0

    def test_tokenizer_to_analyzer_integration(self):
        from core.dax.tokenizer import DaxLexer, TokenType
        from core.dax.knowledge import DaxFunctionDatabase
        from core.dax.analyzer import DaxUnifiedAnalyzer

        db = DaxFunctionDatabase.get()
        lexer = DaxLexer(function_names=db.get_function_names())

        dax = "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        tokens = lexer.tokenize_code(dax)

        # Verify tokenization
        functions = [t for t in tokens if t.type == TokenType.FUNCTION]
        assert any(t.value.upper() == "SUMX" for t in functions)
        assert any(t.value.upper() == "IF" for t in functions)

        # Verify analysis finds the IF-in-iterator issue
        analyzer = DaxUnifiedAnalyzer()
        result = analyzer.analyze(dax)
        assert result.total_issues > 0
        rule_ids = [i.rule_id.upper() for i in result.issues]
        assert any("IF" in rid for rid in rule_ids)

    def test_rewriter_produces_valid_dax(self):
        from core.dax.optimizer.pipeline import OptimizationPipeline
        from core.dax.tokenizer import DaxLexer, TokenType

        pipeline = OptimizationPipeline()
        dax = "SUMX(Sales, Sales[Amount])"
        result = pipeline.optimize_expression(dax)

        if result.final_dax:
            # Verify the rewritten DAX can be tokenized without errors
            lexer = DaxLexer()
            tokens = lexer.tokenize_code(result.final_dax)
            assert len(tokens) > 0
            # Check paren balance
            opens = sum(1 for t in tokens if t.type == TokenType.PAREN_OPEN)
            closes = sum(1 for t in tokens if t.type == TokenType.PAREN_CLOSE)
            assert opens == closes

    def test_function_db_informs_analysis(self):
        from core.dax.knowledge import DaxFunctionDatabase
        from core.dax.analyzer import DaxUnifiedAnalyzer

        db = DaxFunctionDatabase.get()
        analyzer = DaxUnifiedAnalyzer()

        # FORMAT is fe_only with high callback risk
        assert db.get_se_classification("FORMAT") == "fe_only"
        assert db.get_callback_risk("FORMAT") == "high"

        # Analysis should flag FORMAT usage
        result = analyzer.analyze('FORMAT([Sales], "#,##0")')
        format_issues = [i for i in result.issues if "FORMAT" in i.rule_id.upper()]
        assert len(format_issues) > 0

    def test_multiple_issues_detected(self):
        from core.dax.analyzer import DaxUnifiedAnalyzer

        dax = """
        SUMX(
            FILTER(Sales, Sales[Qty] > 10),
            IF(Sales[Amount] > 0,
                FORMAT(Sales[Amount], "#,##0"),
                0
            )
        )
        """
        analyzer = DaxUnifiedAnalyzer()
        result = analyzer.analyze(dax)
        # Should detect: SUMX(FILTER), IF in iterator, FORMAT usage, etc.
        assert result.total_issues >= 2
        rule_ids = [i.rule_id.upper() for i in result.issues]
        assert any("FILTER" in rid for rid in rule_ids)

    def test_health_score_reflects_severity(self):
        from core.dax.analyzer import DaxUnifiedAnalyzer

        analyzer = DaxUnifiedAnalyzer()

        # Clean DAX -> high score
        clean = analyzer.analyze("SUM(Sales[Amount])")
        # Bad DAX -> low score
        bad = analyzer.analyze(
            'SUMX(FILTER(Sales, Sales[Qty] > 0), '
            'IF(Sales[Amount] > 0, FORMAT(Sales[Amount], "#"), 0))'
        )
        assert clean.health_score > bad.health_score

    def test_pipeline_with_no_connection(self):
        from core.dax.optimizer.pipeline import OptimizationPipeline

        pipeline = OptimizationPipeline(connection_state=None)
        result = pipeline.optimize_expression("SUM(Sales[Amount])")
        assert result.success
        assert result.applied is False
        assert result.apply_error is None

    def test_analysis_result_from_issues_factory(self):
        from core.dax.analyzer.models import AnalysisIssue, UnifiedAnalysisResult

        issues = [
            AnalysisIssue(
                rule_id="TEST_001",
                category="performance",
                severity="critical",
                title="Test critical",
                description="A critical issue",
                fix_suggestion="Fix it",
                source="static",
            ),
            AnalysisIssue(
                rule_id="TEST_002",
                category="maintainability",
                severity="low",
                title="Test low",
                description="A low issue",
                fix_suggestion="Minor fix",
                source="static",
            ),
        ]
        result = UnifiedAnalysisResult.from_issues(issues)
        assert result.success
        assert result.total_issues == 2
        assert result.critical_issues == 1
        assert result.health_score < 100  # Deducted for critical
        # Issues should be sorted by severity (critical first)
        assert result.issues[0].severity == "critical"


class TestBackwardCompatibility:
    """Verify all existing APIs still work identically."""

    def test_best_practices_analyzer_api(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer

        result = DaxBestPracticesAnalyzer().analyze("SUM(Sales[Amount])")
        assert result["success"] is True
        assert "total_issues" in result
        assert "issues" in result
        assert "overall_score" in result
        assert isinstance(result["overall_score"], int)

    def test_best_practices_with_bad_dax(self):
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer

        result = DaxBestPracticesAnalyzer().analyze(
            "SUMX(FILTER(Sales, Sales[Qty] > 10), Sales[Amount])"
        )
        assert result["total_issues"] > 0

    def test_rules_engine_api(self):
        from core.dax.dax_rules_engine import DaxRulesEngine

        result = DaxRulesEngine().analyze("SUM(Sales[Amount])")
        assert "health_score" in result
        assert "issues" in result
        assert isinstance(result["health_score"], int)

    def test_callback_detector_detect_dict(self):
        from core.dax.callback_detector import CallbackDetector

        result = CallbackDetector().detect_dict("SUM(Sales[Amount])")
        assert "callback_detections" in result
        assert "summary" in result

    def test_callback_detector_detect_list(self):
        from core.dax.callback_detector import CallbackDetector

        result = CallbackDetector().detect(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        assert isinstance(result, list)

    def test_code_rewriter_api(self):
        from core.dax.code_rewriter import DaxCodeRewriter

        result = DaxCodeRewriter().rewrite_dax("SUM(Sales[Amount])")
        assert result["success"] is True
        assert "has_changes" in result
        assert "transformations" in result

    def test_analysis_pipeline_functions(self):
        from core.dax.analysis_pipeline import (
            run_context_analysis,
            run_best_practices,
            run_optimization_pipeline,
        )

        _, ctx = run_context_analysis("SUM(Sales[Amount])")
        bp = run_best_practices("SUM(Sales[Amount])")
        opt = run_optimization_pipeline("SUM(Sales[Amount])")

        assert ctx is None or isinstance(ctx, dict)
        assert bp is None or isinstance(bp, dict)
        assert opt is not None and opt["success"] is True

    def test_dax_utilities_still_work(self):
        from core.dax.dax_utilities import (
            normalize_dax,
            extract_variables,
            get_line_column,
            validate_dax_identifier,
        )

        # normalize_dax strips comments
        assert "comment" not in normalize_dax("SUM(x) // comment")

        # extract_variables finds VARs
        vars = extract_variables("VAR x = 1\nVAR y = 2\nRETURN x + y")
        assert "x" in vars
        assert "y" in vars

        # get_line_column works
        line, col = get_line_column("abc\ndef", 4)
        assert line == 2
        assert col == 1

        # validate_dax_identifier works
        assert validate_dax_identifier("MyVar")
        assert not validate_dax_identifier("")

    def test_tokenizer_available_from_dax_init(self):
        from core.dax import DaxLexer, Token, TokenType

        tokens = DaxLexer().tokenize("VAR x = 1")
        assert len(tokens) > 0

    def test_function_db_available_from_dax_init(self):
        from core.dax import DaxFunctionDatabase

        db = DaxFunctionDatabase.get()
        assert db.count() >= 150

    def test_unified_analyzer_available_from_dax_init(self):
        from core.dax import DaxUnifiedAnalyzer

        result = DaxUnifiedAnalyzer().analyze("SUM(Sales[Amount])")
        assert result.success

    def test_best_practices_result_format_keys(self):
        """Verify the full set of keys in best-practices result dict."""
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer

        result = DaxBestPracticesAnalyzer().analyze(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        expected_keys = {
            "success",
            "total_issues",
            "critical_issues",
            "high_issues",
            "medium_issues",
            "issues",
            "summary",
            "articles_referenced",
            "overall_score",
            "complexity_level",
        }
        assert expected_keys.issubset(result.keys())

    def test_rules_engine_result_format_keys(self):
        """Verify the full set of keys in rules-engine result dict."""
        from core.dax.dax_rules_engine import DaxRulesEngine

        result = DaxRulesEngine().analyze(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        expected_keys = {"health_score", "issues", "issue_count", "categories"}
        assert expected_keys.issubset(result.keys())

    def test_callback_detector_with_issues(self):
        """Verify detect_dict returns detections for problematic DAX."""
        from core.dax.callback_detector import CallbackDetector

        result = CallbackDetector().detect_dict(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        assert result["summary"]["total"] > 0
        assert len(result["callback_detections"]) > 0

    def test_code_rewriter_transformation_format(self):
        """Verify transformation dicts have expected keys when changes exist."""
        from core.dax.code_rewriter import DaxCodeRewriter

        result = DaxCodeRewriter().rewrite_dax(
            "SUMX(Sales, IF(Sales[Qty] > 0, Sales[Amount], 0))"
        )
        assert result["success"] is True
        if result["has_changes"]:
            assert result["transformation_count"] > 0
            for t in result["transformations"]:
                assert "type" in t
                assert "explanation" in t
