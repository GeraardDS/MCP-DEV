"""Filter-related structural analysis rules."""

from typing import List, Set

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from .base import PythonRule


class FilterBareTableRule(PythonRule):
    """Detect FILTER(BareTable, ...) — iterates the expanded table."""

    rule_id = "PY_FILTER_BARE_TABLE"
    category = "performance"
    severity = "high"
    title = "FILTER iterating bare table (expanded table risk)"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, {"FILTER"})
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if not args:
                continue
            table_arg = args[0]
            if self._is_bare_table(table_arg):
                issues.append(
                    self._make_issue(
                        "FILTER iterates the expanded table (including columns "
                        "pulled in via relationships). This can materialize far "
                        "more data than expected.",
                        "Use FILTER(ALL(Table[Column]), ...) or "
                        "FILTER(VALUES(Table[Column]), ...) to restrict the scan.",
                    )
                )
        return issues

    @staticmethod
    def _is_bare_table(table_tokens: List[Token]) -> bool:
        """True if *table_tokens* is a bare table identifier."""
        meaningful = [
            t for t in table_tokens if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)
        ]
        if not meaningful:
            return False
        if len(meaningful) == 1 and meaningful[0].type in (
            TokenType.IDENTIFIER,
            TokenType.TABLE_REF,
        ):
            return True
        return False


class FilterAllMaterializationRule(PythonRule):
    """Detect FILTER(ALL/ALLSELECTED(...), ...) — full materialization."""

    rule_id = "PY_FILTER_ALL_MATERIALIZATION"
    category = "performance"
    severity = "high"
    title = "FILTER(ALL/ALLSELECTED) causes full materialization"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, {"FILTER"})
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if not args:
                continue
            table_arg = args[0]
            if self._first_func_is(table_arg, {"ALL", "ALLSELECTED"}):
                issues.append(
                    self._make_issue(
                        "FILTER(ALL/ALLSELECTED(...)) materializes the entire "
                        "table/column set in memory before applying the predicate.",
                        "If used inside CALCULATE, consider replacing with a "
                        "direct column predicate or KEEPFILTERS.",
                    )
                )
        return issues

    @staticmethod
    def _first_func_is(table_tokens: List[Token], names: Set[str]) -> bool:
        """True if the first token in *table_tokens* is a FUNCTION in *names*."""
        for t in table_tokens:
            if t.type in (TokenType.WHITESPACE, TokenType.NEWLINE):
                continue
            return t.type == TokenType.FUNCTION and t.value.upper() in names
        return False


class IntersectVsTreatasRule(PythonRule):
    """Detect INTERSECT usage — TREATAS is often more efficient."""

    rule_id = "PY_INTERSECT_VS_TREATAS"
    category = "performance"
    severity = "medium"
    title = "INTERSECT may be replaceable with TREATAS"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, {"INTERSECT"})
        for _ in hits:
            issues.append(
                self._make_issue(
                    "INTERSECT materializes both arguments. TREATAS can "
                    "apply the same filter with fewer materializations.",
                    "Consider replacing INTERSECT with TREATAS for "
                    "column-to-column filter propagation.",
                )
            )
            break  # one issue per expression
        return issues


class AddcolumnsSummarizeRule(PythonRule):
    """Detect ADDCOLUMNS(SUMMARIZE(...), ...) — use SUMMARIZECOLUMNS."""

    rule_id = "PY_ADDCOLUMNS_SUMMARIZE"
    category = "performance"
    severity = "medium"
    title = "ADDCOLUMNS(SUMMARIZE) → use SUMMARIZECOLUMNS"
    rewrite_strategy = "addcolumns_summarize_to_summarizecolumns"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, {"ADDCOLUMNS"})
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if not args:
                continue
            # Check if first arg contains SUMMARIZE function.
            if self._tokens_contain_function(args[0], {"SUMMARIZE"}):
                issues.append(
                    self._make_issue(
                        "ADDCOLUMNS(SUMMARIZE(...), ...) is the legacy pattern. "
                        "SUMMARIZECOLUMNS is optimized by the engine to avoid "
                        "unnecessary table scans.",
                        "Replace with SUMMARIZECOLUMNS(groupby_cols, "
                        '"ColName", expression, ...).',
                        rewrite_strategy=self.rewrite_strategy,
                    )
                )
        return issues
