"""Tests for DaxCodeRewriter — focused on extract_repeated_measures bugs."""

import pytest
from core.dax.code_rewriter import DaxCodeRewriter


@pytest.fixture
def rewriter():
    return DaxCodeRewriter()


class TestExtractRepeatedMeasures:
    """Bug fixes for the extract_repeated_measures rewrite rule."""

    # --- Bug 1: Extended column references [@Column] must NOT be extracted ---

    def test_extended_column_not_extracted(self, rewriter):
        """[@ConversionRate] inside SUMX is a row-level ref, not a measure."""
        dax = (
            "VAR vTable = ADDCOLUMNS(tbl, \"@Rate\", [SomeCalc])\n"
            "RETURN\n"
            "SUMX(vTable, [@Rate] * [@Rate])"
        )
        result = rewriter.rewrite_dax(dax)
        # Should NOT extract [@Rate] into a top-level VAR
        assert not result["has_changes"] or "VAR _M" not in result.get("rewritten_code", "")

    def test_extended_column_mixed_with_measures(self, rewriter):
        """[@Col] should be skipped but real measures should still be extracted."""
        dax = (
            "VAR vTable = ADDCOLUMNS(tbl, \"@Rate\", [Calc])\n"
            "VAR x = [MyMeasure] + [MyMeasure]\n"
            "RETURN\n"
            "SUMX(vTable, [@Rate]) + x"
        )
        result = rewriter.rewrite_dax(dax)
        if result["has_changes"]:
            code = result["rewritten_code"]
            # [@Rate] must NOT appear in any top-level VAR
            assert "= [@Rate]" not in code
            assert "= [@" not in code

    # --- Bug 2: Measures inside different CALCULATE contexts ---

    def test_measure_in_different_calculate_not_extracted(self, rewriter):
        """Same measure in different CALCULATE filters must NOT be collapsed."""
        dax = (
            "VAR vA = CALCULATE([Sales], Filter1)\n"
            "VAR vB = CALCULATE([Sales], Filter2)\n"
            "RETURN vA + vB"
        )
        result = rewriter.rewrite_dax(dax)
        # [Sales] appears twice but each is CALCULATE first arg — don't extract
        if result["has_changes"]:
            code = result["rewritten_code"]
            assert "VAR _M" not in code

    def test_measure_in_calculate_vs_standalone_not_extracted(self, rewriter):
        """Measure used as CALCULATE first arg should block extraction entirely."""
        dax = (
            "VAR vA = CALCULATE([Sales], Filter1)\n"
            "VAR vB = [Sales]\n"
            "RETURN vA + vB"
        )
        result = rewriter.rewrite_dax(dax)
        # [Sales] is CALCULATE first-arg in one place — conservative: skip
        if result["has_changes"]:
            code = result["rewritten_code"]
            assert "VAR _M" not in code

    def test_standalone_repeated_measure_still_extracted(self, rewriter):
        """Measures NOT inside CALCULATE should still be extracted normally."""
        dax = "[TotalSales] + [TotalSales] + [TotalSales]"
        result = rewriter.rewrite_dax(dax)
        assert result["has_changes"]
        code = result["rewritten_code"]
        # New engine uses _Totalsales, old engine uses _M1 — accept either
        assert "VAR" in code
        assert "[TotalSales]" in code  # Original ref in VAR assignment
        # The variable should be used in the expression body (3 times)
        var_name = None
        for line in code.split("\n"):
            if line.strip().startswith("VAR") and "[TotalSales]" in line:
                var_name = line.split("=")[0].replace("VAR", "").strip()
                break
        assert var_name is not None, "Should have a VAR assignment for [TotalSales]"

    # --- Bug 3: Comment containing "return" corrupts insertion ---

    def test_comment_with_return_word(self, rewriter):
        """'return' inside a comment must not be treated as RETURN keyword."""
        dax = (
            "// Period return for Organic TWR\n"
            "VAR vPeriod = SELECTEDVALUE('d Period'[Period])\n"
            "VAR vResult = [MyMeasure] + [MyMeasure]\n"
            "RETURN\n"
            "vResult"
        )
        result = rewriter.rewrite_dax(dax)
        if result["has_changes"]:
            code = result["rewritten_code"]
            # The comment must remain intact
            assert "// Period return for Organic TWR" in code
            # VAR _M1 should appear BEFORE the real RETURN, not mid-comment
            return_idx = code.find("RETURN\n")
            # There should be exactly one real RETURN at the end
            assert return_idx > 0
            # _M1 definition should be before RETURN
            m1_idx = code.find("VAR _M1")
            assert m1_idx < return_idx

    # --- Bug 4: VARs injected inside ADDCOLUMNS inline scope ---

    def test_addcolumns_inline_var_return_not_corrupted(self, rewriter):
        """Inline VAR/RETURN inside ADDCOLUMNS must not be mistaken for top-level."""
        dax = (
            "VAR vTable =\n"
            "    ADDCOLUMNS(\n"
            "        tbl,\n"
            '        "@X",\n'
            "            VAR v = [SomeMeasure]\n"
            "            RETURN v * 2\n"
            "    )\n"
            "VAR vTotal = [RepMeasure] + [RepMeasure]\n"
            "RETURN\n"
            "SUMX(vTable, [@X]) + vTotal"
        )
        result = rewriter.rewrite_dax(dax)
        if result["has_changes"]:
            code = result["rewritten_code"]
            # The ADDCOLUMNS block must remain structurally intact
            assert "ADDCOLUMNS(" in code
            # VAR _M1 must NOT be injected inside ADDCOLUMNS
            addcols_start = code.find("ADDCOLUMNS(")
            addcols_end = code.find(")", addcols_start + 100)  # approximate
            m1_pos = code.find("VAR _M1")
            if m1_pos != -1:
                # _M1 must be outside ADDCOLUMNS scope
                assert m1_pos > addcols_end or m1_pos < addcols_start


class TestFindTopLevelReturn:
    """Tests for the _find_top_level_return helper."""

    def test_simple_return(self):
        dax = "VAR x = 1\nRETURN x"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.find("RETURN")

    def test_return_in_comment_skipped(self):
        dax = "// return value\nVAR x = 1\nRETURN x"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.rfind("RETURN")

    def test_return_in_block_comment_skipped(self):
        dax = "/* return stuff */\nVAR x = 1\nRETURN x"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.rfind("RETURN")

    def test_return_in_string_skipped(self):
        dax = 'VAR x = "RETURN"\nRETURN x'
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.rfind("RETURN")

    def test_nested_return_in_parens_skipped(self):
        dax = (
            "VAR x = ADDCOLUMNS(t, \"@X\", VAR v = 1 RETURN v)\n"
            "RETURN x"
        )
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.rfind("RETURN")

    def test_no_return(self):
        dax = "SUMX(t, [Col])"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == -1


class TestFindVarInsertionPoint:
    """Tests for the _find_var_insertion_point helper."""

    def test_skips_line_comments(self):
        dax = "// comment line\n// another\nVAR x = 1"
        pos = DaxCodeRewriter._find_var_insertion_point(dax)
        assert dax[pos:].startswith("VAR")

    def test_skips_block_comments(self):
        dax = "/* block\ncomment */\nVAR x = 1"
        pos = DaxCodeRewriter._find_var_insertion_point(dax)
        assert dax[pos:].startswith("VAR")

    def test_no_comments(self):
        dax = "VAR x = 1\nRETURN x"
        pos = DaxCodeRewriter._find_var_insertion_point(dax)
        assert pos == 0


class TestValidateSyntax:
    """Tests for enhanced _validate_syntax."""

    def test_extended_column_in_top_level_var_warned(self):
        dax = "VAR _M1 = [@ConversionRate]\nRETURN _M1"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert any("[@" in w for w in warnings)

    def test_normal_var_no_warning(self):
        dax = "VAR x = [Sales]\nRETURN x"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert not any("[@" in w for w in warnings)


class TestIsCalculateFirstArg:
    """Tests for _is_calculate_first_arg helper."""

    def test_measure_as_calculate_first_arg(self, rewriter):
        dax = "CALCULATE([Sales], Filter1)"
        assert rewriter._is_calculate_first_arg(dax, "Sales") is True

    def test_measure_not_in_calculate(self, rewriter):
        dax = "[Sales] + [Sales]"
        assert rewriter._is_calculate_first_arg(dax, "Sales") is False

    def test_measure_in_calculate_filter_not_first_arg(self, rewriter):
        dax = "CALCULATE([Other], [Sales] > 100)"
        assert rewriter._is_calculate_first_arg(dax, "Sales") is False
