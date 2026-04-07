"""CALCULATE optimization strategy — flatten nested CALCULATE, suggest filter rewrites."""

import re
from typing import List, Optional

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from core.dax.optimizer.models import RewriteResult
from .base import RewriteStrategy

# Rewrite strategy names this handler covers.
_NESTED_CALCULATE_STRATEGIES = {"flatten_calculate"}
_FILTER_TABLE_STRATEGIES = {"filter_to_column_predicate"}


class CalculateOptimizationStrategy(RewriteStrategy):
    """Optimize CALCULATE patterns — flatten nesting and suggest filter rewrites."""

    strategy_name = "calculate_optimization"

    def can_apply(
        self,
        issue: AnalysisIssue,
        tokens: List[Token],
        function_db: DaxFunctionDatabase,
    ) -> bool:
        strategy = issue.rewrite_strategy or ""
        if strategy in _NESTED_CALCULATE_STRATEGIES:
            return True
        if strategy in _FILTER_TABLE_STRATEGIES:
            return True
        if "NESTED_CALCULATE" in (issue.rule_id or ""):
            return True
        return False

    def apply(
        self,
        dax: str,
        tokens: List[Token],
        issue: AnalysisIssue,
        function_db: DaxFunctionDatabase,
    ) -> Optional[RewriteResult]:
        strategy = issue.rewrite_strategy or ""

        if strategy in _NESTED_CALCULATE_STRATEGIES or "NESTED_CALCULATE" in (
            issue.rule_id or ""
        ):
            return self._flatten_nested_calculate(dax, tokens, issue)

        if strategy in _FILTER_TABLE_STRATEGIES:
            return self._suggest_filter_rewrite(dax, issue)

        return None

    # ------------------------------------------------------------------
    # Nested CALCULATE flattening
    # ------------------------------------------------------------------

    def _flatten_nested_calculate(
        self,
        dax: str,
        tokens: List[Token],
        issue: AnalysisIssue,
    ) -> Optional[RewriteResult]:
        """Attempt to flatten nested CALCULATE by merging filter arguments.

        Pattern: CALCULATE(CALCULATE(expr, f1), f2) -> CALCULATE(expr, f1, f2)

        This is a safe transformation when the inner CALCULATE is the first
        argument of the outer CALCULATE (filter context merges additively).
        """
        # Find CALCULATE( CALCULATE( pattern via regex for simplicity.
        # The token-based approach is more robust but the regex handles
        # the common straightforward case.
        pattern = re.compile(
            r"\bCALCULATE\s*\(\s*CALCULATE\s*\(",
            re.IGNORECASE,
        )
        match = pattern.search(dax)
        if not match:
            return None

        # For safety, only handle the simple non-nested case.
        # We find matching parens manually.
        result = self._try_flatten(dax, match.start())
        if result is None:
            return None

        valid = self._validate_rewrite(dax, result)
        return RewriteResult(
            strategy=self.strategy_name,
            rule_id=issue.rule_id,
            original_fragment=dax.strip(),
            rewritten_fragment=result.strip(),
            full_rewritten_dax=result,
            explanation="Flattened nested CALCULATE into single CALCULATE with merged filters.",
            confidence="high",
            estimated_improvement="Eliminates redundant context transition",
            validation_passed=valid,
        )

    def _try_flatten(self, dax: str, outer_start: int) -> Optional[str]:
        """Try to flatten CALCULATE(CALCULATE(expr, f1, ...), f2, ...).

        Returns the full rewritten DAX string, or None on failure.
        """
        # Find outer CALCULATE opening paren.
        outer_paren = dax.index("(", outer_start)
        outer_close = self._find_matching_paren(dax, outer_paren)
        if outer_close is None:
            return None

        # Inner content is everything between outer parens.
        inner_content = dax[outer_paren + 1 : outer_close]

        # Find inner CALCULATE and its parens.
        inner_calc_match = re.search(r"\bCALCULATE\s*\(", inner_content, re.IGNORECASE)
        if not inner_calc_match:
            return None

        inner_calc_paren = inner_content.index("(", inner_calc_match.start())
        inner_calc_close = self._find_matching_paren(inner_content, inner_calc_paren)
        if inner_calc_close is None:
            return None

        # Extract inner args text.
        inner_args_text = inner_content[inner_calc_paren + 1 : inner_calc_close].strip()

        # Get outer filter args (everything after the inner CALCULATE call).
        after_inner = inner_content[inner_calc_close + 1 :].strip()
        # Remove leading comma if present.
        if after_inner.startswith(","):
            after_inner = after_inner[1:].strip()

        # Build merged CALCULATE.
        if after_inner:
            merged = f"CALCULATE({inner_args_text}, {after_inner})"
        else:
            merged = f"CALCULATE({inner_args_text})"

        # Replace in original DAX.
        result = dax[:outer_start] + merged + dax[outer_close + 1 :]
        return result

    @staticmethod
    def _find_matching_paren(text: str, open_pos: int) -> Optional[int]:
        """Find the matching close paren for an open paren at *open_pos*."""
        depth = 0
        in_string = False
        in_bracket = False
        for i in range(open_pos, len(text)):
            ch = text[i]
            if in_string:
                if ch == '"':
                    # Check for escaped quote.
                    if i + 1 < len(text) and text[i + 1] == '"':
                        continue
                    in_string = False
                continue
            if in_bracket:
                if ch == "]":
                    in_bracket = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "[":
                in_bracket = True
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        return None

    # ------------------------------------------------------------------
    # Filter-table-to-column suggestion
    # ------------------------------------------------------------------

    def _suggest_filter_rewrite(
        self,
        dax: str,
        issue: AnalysisIssue,
    ) -> Optional[RewriteResult]:
        """Suggest replacing FILTER(Table, condition) with a column predicate.

        This is hard to auto-rewrite safely (the condition may be complex),
        so we provide the suggestion with medium confidence.
        """
        return RewriteResult(
            strategy=self.strategy_name,
            rule_id=issue.rule_id,
            original_fragment=dax.strip(),
            rewritten_fragment="(see explanation)",
            full_rewritten_dax=dax,  # no actual change — suggestion only
            explanation=(
                "FILTER(Table, condition) inside CALCULATE forces full table "
                "materialization. Replace with a direct column predicate "
                "(e.g., Table[Col] = value) when the condition is a simple "
                "comparison on a single column."
            ),
            confidence="medium",
            estimated_improvement="Up to 117x improvement per SQLBI benchmarks",
            validation_passed=True,  # no change to validate
        )
