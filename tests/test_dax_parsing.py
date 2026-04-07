"""Tests for DAX parsing logic in DaxCodeRewriter.

Covers:
- _validate_syntax: bracket/paren balance with escaped quotes, string literals
- _find_top_level_return: escaped double-quote handling, edge cases
- Bracket depth correctness when strings contain brackets
"""

import pytest
from core.dax.code_rewriter import DaxCodeRewriter


# ---------------------------------------------------------------------------
# _validate_syntax
# ---------------------------------------------------------------------------

class TestValidateSyntaxEscapedQuotes:
    """Escaped double-quotes ("") must not break bracket/paren counting."""

    def test_escaped_quote_in_string_no_warnings(self):
        """A string containing escaped quotes should not cause false warnings."""
        dax = 'VAR x = "He said ""hello"" to her"\nRETURN x'
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert warnings == []

    def test_escaped_quote_with_bracket_inside_string(self):
        """Brackets inside a quoted string (with escaped quotes) are not real refs."""
        dax = 'VAR x = "some ""[fake]"" text"\nRETURN x'
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert not any("bracket" in w.lower() for w in warnings)

    def test_unbalanced_paren_detected(self):
        dax = "CALCULATE([Sales], (Filter1)"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert any("parenthes" in w.lower() for w in warnings)

    def test_balanced_parens_no_warning(self):
        dax = "CALCULATE([Sales], (Filter1))"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert not any("parenthes" in w.lower() for w in warnings)

    def test_unbalanced_bracket_detected(self):
        dax = "[Sales + [Cost]"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert any("bracket" in w.lower() for w in warnings)

    def test_balanced_brackets_no_warning(self):
        dax = "[Sales] + [Cost]"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert not any("bracket" in w.lower() for w in warnings)

    def test_var_without_return_warned(self):
        dax = "VAR x = [Sales]"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert any("RETURN" in w for w in warnings)

    def test_var_with_return_no_warning(self):
        dax = "VAR x = [Sales]\nRETURN x"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert not any("RETURN" in w for w in warnings)

    def test_empty_string_no_crash(self):
        warnings = DaxCodeRewriter._validate_syntax("")
        assert isinstance(warnings, list)

    def test_string_with_only_escaped_quotes(self):
        """Edge case: string that is just escaped quotes."""
        dax = 'VAR x = """"""\nRETURN x'
        warnings = DaxCodeRewriter._validate_syntax(dax)
        # Should not crash; may or may not warn depending on parsing
        assert isinstance(warnings, list)

    def test_extra_closing_paren_detected(self):
        dax = "SUM([Sales]))"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert any("closing parenthesis" in w.lower() for w in warnings)

    def test_extra_closing_bracket_detected(self):
        dax = "[Sales]]"
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert any("closing bracket" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# _find_top_level_return with escaped quotes
# ---------------------------------------------------------------------------

class TestFindTopLevelReturnEscapedQuotes:
    """Escaped double-quotes must not confuse RETURN detection."""

    def test_return_after_string_with_escaped_quotes(self):
        dax = 'VAR x = "he said ""hi"" ok"\nRETURN x'
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos != -1
        assert dax[pos:pos + 6].upper() == "RETURN"

    def test_return_word_inside_escaped_string_skipped(self):
        """RETURN inside a string (even with escaped quotes) must not match."""
        dax = 'VAR x = "RETURN ""value"""\nRETURN x'
        pos = DaxCodeRewriter._find_top_level_return(dax)
        # Should find the second RETURN (the real one), not the one in string
        assert pos == dax.rfind("RETURN")

    def test_no_return_in_dax(self):
        dax = "SUM([Sales])"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == -1

    def test_return_inside_nested_parens_skipped(self):
        dax = "VAR t = ADDCOLUMNS(x, \"@c\", VAR v = 1 RETURN v)\nRETURN t"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.rfind("RETURN")

    def test_return_in_line_comment_skipped(self):
        dax = "// return something\nVAR x = 1\nRETURN x"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert dax[pos:pos + 6] == "RETURN"
        assert pos > dax.find("\n")

    def test_return_in_block_comment_skipped(self):
        dax = "/* RETURN */ VAR x = 1\nRETURN x"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.rfind("RETURN")

    def test_return_case_insensitive(self):
        dax = "VAR x = 1\nreturn x"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        assert pos == dax.find("return")

    def test_return_not_part_of_identifier(self):
        """RETURNVALUE should not be matched as RETURN."""
        dax = "VAR RETURNVALUE = 1\nRETURN RETURNVALUE"
        pos = DaxCodeRewriter._find_top_level_return(dax)
        # Should find the standalone RETURN, not RETURNVALUE
        assert dax[pos:pos + 6] == "RETURN"
        # After the matched RETURN there should be a space (not more alpha chars)
        assert pos + 6 < len(dax) and dax[pos + 6] == " "


# ---------------------------------------------------------------------------
# Bracket depth - string literals should not affect counting
# ---------------------------------------------------------------------------

class TestBracketDepthWithStrings:
    """Verify brackets inside string literals are properly ignored."""

    def test_brackets_in_string_ignored(self):
        dax = 'VAR x = "[NotARef]"\nRETURN [RealMeasure]'
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert not any("bracket" in w.lower() for w in warnings)

    def test_mixed_brackets_strings_and_real_refs(self):
        dax = (
            'VAR label = "Total [Sales]"\n'
            'VAR val = [Sales] + [Cost]\n'
            'RETURN val'
        )
        warnings = DaxCodeRewriter._validate_syntax(dax)
        assert not any("bracket" in w.lower() for w in warnings)
