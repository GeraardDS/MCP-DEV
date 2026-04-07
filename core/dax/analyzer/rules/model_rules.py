"""Model-level structural analysis rules."""

from typing import List

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from .base import PythonRule


class DirectMeasureReferenceRule(PythonRule):
    """Detect measures that are just pass-through references to another measure."""

    rule_id = "PY_DIRECT_MEASURE_REF"
    category = "maintainability"
    severity = "low"
    title = "Pass-through measure reference"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []

        # The entire expression (after tokenize_code stripping) is a single COLUMN_REF.
        meaningful = [
            t
            for t in tokens
            if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)
        ]
        if len(meaningful) == 1 and meaningful[0].type == TokenType.COLUMN_REF:
            ref = meaningful[0].value
            issues.append(
                self._make_issue(
                    f"This measure is a direct reference to {ref} — "
                    f"a pass-through that adds indirection without logic.",
                    "Consider referencing the target measure directly, "
                    "or add documentation explaining why the indirection exists.",
                )
            )
        return issues


class SemiAdditivePatternRule(PythonRule):
    """Detect LASTNONBLANK usage — suggest faster alternatives."""

    rule_id = "PY_SEMI_ADDITIVE_RANKING"
    category = "performance"
    severity = "medium"
    title = "LASTNONBLANK may be slower than LASTDATE/MAX"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []
        hits = self._find_functions(tokens, {"LASTNONBLANK"})
        if hits:
            issues.append(
                self._make_issue(
                    "LASTNONBLANK evaluates its expression for each date "
                    "to find the last non-blank. For simple semi-additive "
                    "measures this is slower than alternatives.",
                    "If the date column has no gaps, use "
                    "CALCULATE([Measure], LASTDATE(DateTable[Date])). "
                    "For the last date with data, consider MAX + CALCULATE.",
                )
            )
        return issues
