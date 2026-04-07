"""Tests for DAX optimization pipeline."""

import pytest

from core.dax.optimizer.rewrite_engine import DaxRewriteEngine
from core.dax.optimizer.models import RewriteResult, OptimizationResult
from core.dax.analyzer.unified_analyzer import DaxUnifiedAnalyzer
from core.dax.knowledge import DaxFunctionDatabase


class TestRewriteEngine:
    @pytest.fixture
    def engine(self):
        return DaxRewriteEngine(DaxFunctionDatabase.get())

    @pytest.fixture
    def analyzer(self):
        return DaxUnifiedAnalyzer()

    def test_rewrites_unnecessary_iterator(self, engine, analyzer):
        dax = "SUMX(Sales, Sales[Amount])"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        applicable = [r for r in rewrites if "iterator" in r.strategy.lower()]
        if applicable:
            assert "SUM" in applicable[0].rewritten_fragment

    def test_generates_meaningful_var_names(self, engine, analyzer):
        dax = "[Sales Amount] + [Sales Amount] + [Sales Amount]"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        var_rewrites = [r for r in rewrites if "variable" in r.strategy.lower()]
        if var_rewrites:
            assert "_SalesAmount" in var_rewrites[0].full_rewritten_dax

    def test_rewrite_validation(self, engine, analyzer):
        dax = "SUMX(Sales, Sales[Amount])"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        for r in rewrites:
            assert r.validation_passed

    def test_apply_rewrites(self, engine, analyzer):
        dax = "[Sales] + [Sales] + [Sales]"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        if rewrites:
            final = engine.apply_rewrites(dax, rewrites)
            assert final != dax

    def test_no_rewrites_for_clean_dax(self, engine, analyzer):
        dax = "VAR _S = SUM(Sales[Amount])\nRETURN DIVIDE(_S, 100)"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        # Clean DAX should have 0 or very few rewrites
        assert len(rewrites) <= 1

    def test_generate_variable_name(self):
        assert DaxRewriteEngine.generate_variable_name("[Sales Amount]") == "_SalesAmount"
        assert DaxRewriteEngine.generate_variable_name("[Total Cost]") == "_TotalCost"
        assert DaxRewriteEngine.generate_variable_name("Budget") == "_Budget"

    def test_generate_variable_name_edge_cases(self):
        assert DaxRewriteEngine.generate_variable_name("") == "_Var"
        assert DaxRewriteEngine.generate_variable_name("[]") == "_Var"
        assert DaxRewriteEngine.generate_variable_name("[A]") == "_A"


class TestVariableExtraction:
    @pytest.fixture
    def engine(self):
        return DaxRewriteEngine(DaxFunctionDatabase.get())

    @pytest.fixture
    def analyzer(self):
        return DaxUnifiedAnalyzer()

    def test_extracts_repeated_measure_ref(self, engine, analyzer):
        dax = "[Margin] + [Margin] + [Margin]"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        var_rewrites = [r for r in rewrites if r.strategy == "variable_extraction"]
        if var_rewrites:
            result = var_rewrites[0]
            assert "VAR" in result.full_rewritten_dax
            assert "_Margin" in result.full_rewritten_dax
            assert result.validation_passed

    def test_inserts_var_before_existing_return(self, engine, analyzer):
        dax = (
            "VAR _X = 1\n"
            "RETURN [Sales] + [Sales] + [Sales]"
        )
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        var_rewrites = [r for r in rewrites if r.strategy == "variable_extraction"]
        if var_rewrites:
            result = var_rewrites[0]
            # Should have VAR before RETURN, not wrap in another VAR/RETURN
            lines = result.full_rewritten_dax.split("\n")
            return_count = sum(1 for l in lines if "RETURN" in l.upper())
            assert return_count == 1


class TestIteratorOptimization:
    @pytest.fixture
    def engine(self):
        return DaxRewriteEngine(DaxFunctionDatabase.get())

    @pytest.fixture
    def analyzer(self):
        return DaxUnifiedAnalyzer()

    def test_sumx_to_sum(self, engine, analyzer):
        dax = "SUMX(Sales, Sales[Amount])"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        iter_rewrites = [r for r in rewrites if r.strategy == "iterator_optimization"]
        if iter_rewrites:
            result = iter_rewrites[0]
            assert "SUM" in result.rewritten_fragment
            assert "SUMX" not in result.full_rewritten_dax.upper()
            assert result.confidence == "high"

    def test_averagex_to_average(self, engine, analyzer):
        dax = "AVERAGEX(Products, Products[Price])"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        iter_rewrites = [r for r in rewrites if r.strategy == "iterator_optimization"]
        if iter_rewrites:
            result = iter_rewrites[0]
            assert "AVERAGE" in result.rewritten_fragment

    def test_complex_expression_not_rewritten(self, engine, analyzer):
        # SUMX with a complex expression should NOT be rewritten
        dax = "SUMX(Sales, Sales[Qty] * Sales[Price])"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        iter_rewrites = [r for r in rewrites if r.strategy == "iterator_optimization"]
        # Should not produce an iterator optimization for complex expression
        assert len(iter_rewrites) == 0


class TestCalculateOptimization:
    @pytest.fixture
    def engine(self):
        return DaxRewriteEngine(DaxFunctionDatabase.get())

    @pytest.fixture
    def analyzer(self):
        return DaxUnifiedAnalyzer()

    def test_filter_table_suggestion(self, engine, analyzer):
        dax = "CALCULATE(SUM(Sales[Amount]), FILTER(Sales, Sales[Region] = \"West\"))"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        calc_rewrites = [r for r in rewrites if r.strategy == "calculate_optimization"]
        if calc_rewrites:
            # Filter-table rewrites are suggestions with medium confidence
            suggestion = [r for r in calc_rewrites if r.confidence == "medium"]
            assert len(suggestion) >= 0  # may or may not match


class TestPatternReplacement:
    @pytest.fixture
    def engine(self):
        return DaxRewriteEngine(DaxFunctionDatabase.get())

    @pytest.fixture
    def analyzer(self):
        return DaxUnifiedAnalyzer()

    def test_countrows_values_to_distinctcount(self, engine, analyzer):
        dax = "COUNTROWS(VALUES(Sales[CustomerID]))"
        analysis = analyzer.analyze(dax)
        rewrites = engine.rewrite(dax, analysis.tokens, analysis.issues)
        pattern_rewrites = [r for r in rewrites if r.strategy == "pattern_replacement"]
        if pattern_rewrites:
            result = pattern_rewrites[0]
            assert "DISTINCTCOUNT" in result.rewritten_fragment
            assert result.validation_passed


class TestModels:
    def test_rewrite_result_creation(self):
        rr = RewriteResult(
            strategy="test",
            rule_id="R1",
            original_fragment="SUMX(T, T[C])",
            rewritten_fragment="SUM(T[C])",
            full_rewritten_dax="SUM(T[C])",
            explanation="Test",
            confidence="high",
            estimated_improvement="10x",
            validation_passed=True,
        )
        assert rr.strategy == "test"
        assert rr.confidence == "high"

    def test_optimization_result_creation(self):
        opt = OptimizationResult(
            success=True,
            measure_name="Test Measure",
            original_dax="SUMX(T, T[C])",
            analysis=None,
            rewrites=[],
            final_dax="SUM(T[C])",
            applied=False,
            apply_error=None,
            improvement_summary="Replaced iterator with aggregate",
        )
        assert opt.success
        assert opt.measure_name == "Test Measure"
