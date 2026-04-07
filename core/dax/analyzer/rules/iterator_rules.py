"""Iterator-related structural analysis rules."""

from typing import List, Set

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from .base import PythonRule

# Standard iterator functions whose 2nd argument is the expression.
_STANDARD_ITERATORS: Set[str] = {
    "SUMX",
    "AVERAGEX",
    "COUNTX",
    "MAXX",
    "MINX",
    "PRODUCTX",
    "RANKX",
    "CONCATENATEX",
}

# All iterators (including those where the table arg can also nest).
_ALL_ITERATORS: Set[str] = _STANDARD_ITERATORS | {
    "FILTER",
    "ADDCOLUMNS",
    "GENERATE",
}

# Iterators that can be trivially replaced by aggregates.
_REPLACEABLE_ITERATORS = {
    "SUMX": "SUM",
    "AVERAGEX": "AVERAGE",
    "MINX": "MIN",
    "MAXX": "MAX",
    "COUNTX": "COUNTROWS",
}


class NestedIteratorRule(PythonRule):
    """Detect iterator functions nested inside another iterator's expression."""

    rule_id = "PY_NESTED_ITERATOR"
    category = "performance"
    severity = "critical"
    title = "Nested iterator (Cartesian product risk)"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, _ALL_ITERATORS)
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            # For standard iterators, expression is arg[1]; for FILTER it's arg[1] too.
            expr_args = args[1:] if len(args) > 1 else []
            for arg_tokens in expr_args:
                if self._tokens_contain_function(arg_tokens, _ALL_ITERATORS):
                    outer = tokens[idx].value.upper()
                    inner_names = [
                        t.value
                        for t in arg_tokens
                        if t.type == TokenType.FUNCTION and t.value.upper() in _ALL_ITERATORS
                    ]
                    inner = inner_names[0] if inner_names else "iterator"
                    issues.append(
                        self._make_issue(
                            f"{inner} nested inside {outer} may cause a Cartesian product "
                            f"— O(N*M) row scans.",
                            f"Flatten the expression or pre-aggregate with "
                            f"SUMMARIZE/SUMMARIZECOLUMNS before iterating.",
                        )
                    )
                    break  # one issue per outer call
        return issues


class IfSwitchInIteratorRule(PythonRule):
    """Detect IF/SWITCH inside an iterator expression argument."""

    rule_id = "PY_IF_IN_ITERATOR"
    category = "performance"
    severity = "high"
    title = "IF/SWITCH in iterator (CallbackDataID risk)"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, _STANDARD_ITERATORS | {"FILTER", "ADDCOLUMNS"})
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if len(args) < 2:
                continue
            expr_tokens = args[1]
            # IF/SWITCH are FUNCTION when followed by (, KEYWORD otherwise.
            branching = {
                t.value.upper()
                for t in expr_tokens
                if t.type in (TokenType.KEYWORD, TokenType.FUNCTION)
            }
            if branching & {"IF", "SWITCH"}:
                issues.append(
                    self._make_issue(
                        f"IF/SWITCH inside {tokens[idx].value.upper()} forces row-by-row "
                        f"FE evaluation (CallbackDataID in query plan).",
                        "Move branching outside the iterator or "
                        "pre-compute the condition in a column with ADDCOLUMNS.",
                    )
                )
        return issues


class DivideInIteratorRule(PythonRule):
    """Detect DIVIDE inside an iterator expression argument."""

    rule_id = "PY_DIVIDE_IN_ITERATOR"
    category = "performance"
    severity = "medium"
    title = "DIVIDE in iterator (CallbackDataID risk)"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, _STANDARD_ITERATORS | {"FILTER", "ADDCOLUMNS"})
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if len(args) < 2:
                continue
            if self._tokens_contain_function(args[1], {"DIVIDE"}):
                issues.append(
                    self._make_issue(
                        f"DIVIDE inside {tokens[idx].value.upper()} creates a "
                        f"CallbackDataID in the SE query plan.",
                        "Use the / operator instead (handle BLANK separately) "
                        "or pre-compute the ratio.",
                    )
                )
        return issues


class UnnecessaryIteratorRule(PythonRule):
    """Detect SUMX/AVERAGEX/etc. where expression is just a column reference."""

    rule_id = "PY_UNNECESSARY_ITERATOR"
    category = "performance"
    severity = "medium"
    title = "Unnecessary iterator (simple column reference)"
    rewrite_strategy = "unnecessary_iterator_to_agg"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, set(_REPLACEABLE_ITERATORS.keys()))
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if len(args) < 2:
                continue
            expr = args[1]
            if self._is_simple_column_ref(expr):
                func_name = tokens[idx].value.upper()
                replacement = _REPLACEABLE_ITERATORS.get(func_name, "aggregate")
                issues.append(
                    self._make_issue(
                        f"{func_name} with a plain column reference is equivalent to "
                        f"{replacement} — the iterator adds overhead for no benefit.",
                        f"Replace with {replacement}(column).",
                        rewrite_strategy=self.rewrite_strategy,
                    )
                )
        return issues

    @staticmethod
    def _is_simple_column_ref(expr_tokens: List[Token]) -> bool:
        """True if *expr_tokens* is only a single column reference."""
        # Filter out any stray whitespace/newline (should already be stripped).
        meaningful = [t for t in expr_tokens if t.type not in (TokenType.WHITESPACE,)]
        if not meaningful:
            return False
        # Single QUALIFIED_REF  e.g. Sales[Amount]
        if len(meaningful) == 1 and meaningful[0].type == TokenType.QUALIFIED_REF:
            return True
        # IDENTIFIER + COLUMN_REF  e.g. Sales [Amount] (unlikely after tokenize_code
        # but handle defensively).
        if (
            len(meaningful) == 2
            and meaningful[0].type == TokenType.IDENTIFIER
            and meaningful[1].type == TokenType.COLUMN_REF
        ):
            return True
        # Single bare COLUMN_REF  e.g. [Amount] (for current table context)
        if len(meaningful) == 1 and meaningful[0].type == TokenType.COLUMN_REF:
            return True
        return False


class RelatedInIteratorRule(PythonRule):
    """Detect RELATED inside an iterator expression argument."""

    rule_id = "PY_RELATED_IN_ITERATOR"
    category = "performance"
    severity = "medium"
    title = "RELATED in iterator (row-by-row relationship traversal)"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, _STANDARD_ITERATORS | {"FILTER", "ADDCOLUMNS"})
        for idx in hits:
            args = self._get_function_args(tokens, idx)
            if len(args) < 2:
                continue
            if self._tokens_contain_function(args[1], {"RELATED", "RELATEDTABLE"}):
                issues.append(
                    self._make_issue(
                        f"RELATED/RELATEDTABLE inside {tokens[idx].value.upper()} "
                        f"triggers row-by-row relationship traversal.",
                        "Consider using SUMMARIZE or SUMMARIZECOLUMNS "
                        "to group at the relationship boundary.",
                    )
                )
        return issues
