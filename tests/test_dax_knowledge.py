"""Tests for DAX function knowledge base."""

import pytest
from core.dax.knowledge.function_db import DaxFunctionDatabase


class TestDaxFunctionDatabase:

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        DaxFunctionDatabase.reset()
        yield
        DaxFunctionDatabase.reset()

    @pytest.fixture
    def db(self):
        return DaxFunctionDatabase.get()

    def test_singleton(self):
        db1 = DaxFunctionDatabase.get()
        db2 = DaxFunctionDatabase.get()
        assert db1 is db2

    def test_lookup_sum(self, db):
        func = db.lookup("SUM")
        assert func is not None
        assert func.name == "SUM"
        assert func.category == "aggregation"

    def test_lookup_case_insensitive(self, db):
        assert db.lookup("sumx") is not None
        assert db.lookup("SUMX") is not None
        assert db.lookup("SumX") is not None

    def test_lookup_nonexistent(self, db):
        assert db.lookup("NOTAREALFUNCTION") is None

    def test_is_function(self, db):
        assert db.is_function("CALCULATE")
        assert db.is_function("SUMX")
        assert db.is_function("DIVIDE")
        assert not db.is_function("VAR")
        assert not db.is_function("RETURN")

    def test_se_classification_sum(self, db):
        assert db.get_se_classification("SUM") == "se_safe"

    def test_se_classification_format(self, db):
        assert db.get_se_classification("FORMAT") == "fe_only"

    def test_creates_row_context(self, db):
        assert db.creates_row_context("SUMX")
        assert db.creates_row_context("FILTER")
        assert not db.creates_row_context("SUM")
        assert not db.creates_row_context("CALCULATE")

    def test_creates_filter_context(self, db):
        assert db.creates_filter_context("CALCULATE")
        assert db.creates_filter_context("CALCULATETABLE")
        assert not db.creates_filter_context("SUM")

    def test_get_alternatives(self, db):
        alts = db.get_alternatives("SUMX")
        assert len(alts) > 0

    def test_get_callback_risk(self, db):
        assert db.get_callback_risk("FORMAT") == "high"
        assert db.get_callback_risk("SUM") == "none"

    def test_function_count_minimum(self, db):
        """Must have at least 150 functions."""
        assert db.count() >= 150

    def test_all_functions_have_category(self, db):
        for func in db.all_functions():
            assert func.category, f"{func.name} missing category"

    def test_get_function_names_set(self, db):
        names = db.get_function_names()
        assert isinstance(names, set)
        assert "SUM" in names
        assert "CALCULATE" in names
        assert len(names) >= 150

    def test_get_by_category(self, db):
        agg_funcs = db.get_by_category("aggregation")
        assert len(agg_funcs) >= 10
        for func in agg_funcs:
            assert func.category == "aggregation"

    def test_se_classification_unknown_function(self, db):
        assert db.get_se_classification("NOTAFUNCTION") == "unknown"

    def test_callback_risk_unknown_function(self, db):
        assert db.get_callback_risk("NOTAFUNCTION") == "none"

    def test_creates_row_context_unknown_function(self, db):
        assert not db.creates_row_context("NOTAFUNCTION")

    def test_creates_filter_context_unknown_function(self, db):
        assert not db.creates_filter_context("NOTAFUNCTION")

    def test_alternatives_unknown_function(self, db):
        assert db.get_alternatives("NOTAFUNCTION") == []

    def test_time_intelligence_functions_exist(self, db):
        ti_funcs = db.get_by_category("time_intelligence")
        assert len(ti_funcs) >= 25
        names = {f.name for f in ti_funcs}
        assert "DATEADD" in names
        assert "SAMEPERIODLASTYEAR" in names
        assert "TOTALYTD" in names

    def test_iterator_functions_create_row_context(self, db):
        iterators = db.get_by_category("iterator")
        for func in iterators:
            assert func.creates_row_context, (
                f"Iterator {func.name} should create row context"
            )

    def test_all_functions_have_se_classification(self, db):
        valid = {"se_safe", "fe_only", "expression_dependent"}
        for func in db.all_functions():
            assert func.se_pushable in valid, (
                f"{func.name} has invalid se_pushable: {func.se_pushable}"
            )

    def test_function_count_over_200(self, db):
        """Must have at least 200 functions for comprehensive coverage."""
        assert db.count() >= 200, (
            f"Expected 200+ functions, got {db.count()}"
        )
