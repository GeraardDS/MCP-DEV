"""CALCULATE-related structural analysis rules."""

from typing import List, Set

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from .base import PythonRule

_CALCULATE_FUNCS: Set[str] = {"CALCULATE", "CALCULATETABLE"}


class NestedCalculateRule(PythonRule):
    """Detect CALCULATE nested inside the first argument of another CALCULATE."""

    rule_id = "PY_NESTED_CALCULATE"
    category = "performance"
    severity = "medium"
    title = "Nested CALCULATE (can often be flattened)"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, _CALCULATE_FUNCS)
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if not args:
                continue
            # First arg is the expression — check for nested CALCULATE.
            if self._tokens_contain_function(args[0], _CALCULATE_FUNCS):
                issues.append(
                    self._make_issue(
                        "CALCULATE nested in the expression argument of another CALCULATE. "
                        "The outer filters apply AFTER the inner context transition.",
                        "Flatten into a single CALCULATE with combined filter arguments.",
                    )
                )
        return issues


class FilterTableNotColumnRule(PythonRule):
    """Detect FILTER(BareTable, ...) used as a CALCULATE filter argument."""

    rule_id = "PY_FILTER_TABLE_NOT_COLUMN"
    category = "performance"
    severity = "critical"
    title = "FILTER(table) in CALCULATE instead of column predicate"
    rewrite_strategy = "filter_to_column_predicate"

    # Functions that wrap a table intentionally (not a bare scan).
    _TABLE_WRAPPERS: Set[str] = {
        "ALL",
        "ALLSELECTED",
        "ALLNOBLANKROW",
        "ALLEXCEPT",
        "VALUES",
        "DISTINCT",
        "SUMMARIZE",
        "SUMMARIZECOLUMNS",
        "ADDCOLUMNS",
        "SELECTCOLUMNS",
        "FILTER",
        "GENERATE",
        "CALCULATETABLE",
        "TOPN",
        "SAMPLE",
        "DATATABLE",
        "UNION",
        "INTERSECT",
        "EXCEPT",
        "CROSSJOIN",
    }

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        calc_hits = self._find_functions(tokens, _CALCULATE_FUNCS)
        for calc_idx in calc_hits:
            args = self._get_function_args(tokens, calc_idx)
            # Filter arguments are args[1:].
            for filter_arg in args[1:]:
                if self._is_filter_bare_table(filter_arg):
                    issues.append(
                        self._make_issue(
                            "FILTER iterating a bare table inside CALCULATE. "
                            "This forces full-table materialization instead of using "
                            "the optimized column predicate shortcut (up to 117x slower "
                            "per SQLBI benchmarks).",
                            "Replace FILTER(Table, condition) with a direct column "
                            "predicate: Table[Column] = value.",
                            rewrite_strategy=self.rewrite_strategy,
                        )
                    )
                    break  # one issue per CALCULATE
        return issues

    def _is_filter_bare_table(self, arg_tokens: List[Token]) -> bool:
        """True if arg is FILTER(BareTable, ...)."""
        if not arg_tokens:
            return False
        # First meaningful token should be FILTER function.
        first = arg_tokens[0]
        if first.type != TokenType.FUNCTION or first.value.upper() != "FILTER":
            return False
        # Get FILTER's own arguments.
        inner_args = self._get_function_args(arg_tokens, 0)
        if not inner_args:
            return False
        table_arg = inner_args[0]
        return self._is_bare_table(table_arg)

    def _is_bare_table(self, table_tokens: List[Token]) -> bool:
        """True if *table_tokens* is a bare table reference (not wrapped)."""
        meaningful = [
            t for t in table_tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)
        ]
        if not meaningful:
            return False
        # Single IDENTIFIER or TABLE_REF is a bare table.
        if len(meaningful) == 1 and meaningful[0].type in (
            TokenType.IDENTIFIER,
            TokenType.TABLE_REF,
        ):
            # Make sure it's not a function.
            return meaningful[0].type != TokenType.FUNCTION
        return False


class KeepfiltersOpportunityRule(PythonRule):
    """Detect FILTER(VALUES(col), ...) or FILTER(ALL(col), ...) patterns."""

    rule_id = "PY_KEEPFILTERS_OPPORTUNITY"
    category = "performance"
    severity = "low"
    title = "FILTER(VALUES/ALL(col)) can use KEEPFILTERS"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        filter_hits = self._find_functions(tokens, {"FILTER"})
        for idx in filter_hits:
            args = self._get_function_args(tokens, idx)
            if not args:
                continue
            table_arg = args[0]
            if self._is_values_or_all_column(table_arg):
                issues.append(
                    self._make_issue(
                        "FILTER(VALUES/ALL(column), ...) can be simplified.",
                        "Consider using KEEPFILTERS with a direct column predicate "
                        "in CALCULATE for better readability and equivalent semantics.",
                    )
                )
        return issues

    @staticmethod
    def _is_values_or_all_column(table_tokens: List[Token]) -> bool:
        """True if the table argument is VALUES(col) or ALL(col)."""
        meaningful = [
            t for t in table_tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)
        ]
        if not meaningful:
            return False
        first = meaningful[0]
        if first.type == TokenType.FUNCTION and first.value.upper() in ("VALUES", "ALL"):
            return True
        return False


class AllTableVsColumnRule(PythonRule):
    """Detect ALL(Table) when ALL(Table[Col]) might be intended."""

    rule_id = "PY_ALL_TABLE_VS_COLUMN"
    category = "performance"
    severity = "medium"
    title = "ALL(Table) removes all filters from entire table"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        all_hits = self._find_functions(tokens, {"ALL"})
        for idx in all_hits:
            args = self._get_function_args(tokens, idx)
            if len(args) != 1:
                continue  # ALL with multiple args = column list, fine
            arg = args[0]
            meaningful = [t for t in arg if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)]
            if not meaningful:
                continue
            # Single IDENTIFIER or TABLE_REF = table reference (not a column).
            if len(meaningful) == 1 and meaningful[0].type in (
                TokenType.IDENTIFIER,
                TokenType.TABLE_REF,
            ):
                issues.append(
                    self._make_issue(
                        f"ALL({meaningful[0].value}) removes filters from every column "
                        f"in the table. This may remove more filters than intended.",
                        "If you only need to clear specific columns, use "
                        "ALL(Table[Col1], Table[Col2]) to be explicit.",
                    )
                )
        return issues
