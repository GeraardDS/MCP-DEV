"""Pattern replacement strategy — direct text substitutions for well-known anti-patterns."""

import re
from typing import List, Optional, Tuple

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from core.dax.optimizer.models import RewriteResult
from .base import RewriteStrategy

# Well-known pattern replacements.
# Each tuple: (rewrite_strategy_name, pattern_regex, replacement_func_name, explanation)
_PATTERN_RULES: List[Tuple[str, str, str, str]] = [
    (
        "countrows_values_to_distinctcount",
        r"\bCOUNTROWS\s*\(\s*VALUES\s*\(\s*([^)]+)\s*\)\s*\)",
        "DISTINCTCOUNT(\\1)",
        "COUNTROWS(VALUES(col)) is equivalent to DISTINCTCOUNT(col) "
        "but DISTINCTCOUNT is optimized by the engine.",
    ),
    (
        "countrows_distinct_to_distinctcount",
        r"\bCOUNTROWS\s*\(\s*DISTINCT\s*\(\s*([^)]+)\s*\)\s*\)",
        "DISTINCTCOUNT(\\1)",
        "COUNTROWS(DISTINCT(col)) is equivalent to DISTINCTCOUNT(col) "
        "but DISTINCTCOUNT is optimized by the engine.",
    ),
]

# Strategy names this handler covers.
_HANDLED_STRATEGIES = {rule[0] for rule in _PATTERN_RULES}


class PatternReplacementStrategy(RewriteStrategy):
    """Apply direct pattern-based replacements for well-known DAX anti-patterns.

    Handles simple text-level transformations where the before/after is
    unambiguous and structurally safe.
    """

    strategy_name = "pattern_replacement"

    def can_apply(
        self,
        issue: AnalysisIssue,
        tokens: List[Token],
        function_db: DaxFunctionDatabase,
    ) -> bool:
        strategy = issue.rewrite_strategy or ""
        return strategy in _HANDLED_STRATEGIES

    def apply(
        self,
        dax: str,
        tokens: List[Token],
        issue: AnalysisIssue,
        function_db: DaxFunctionDatabase,
    ) -> Optional[RewriteResult]:
        strategy = issue.rewrite_strategy or ""

        for rule_strategy, pattern, replacement, explanation in _PATTERN_RULES:
            if rule_strategy != strategy:
                continue

            regex = re.compile(pattern, re.IGNORECASE)
            match = regex.search(dax)
            if not match:
                continue

            original_fragment = match.group(0)
            rewritten_fragment = regex.sub(replacement, original_fragment)
            full_rewritten = regex.sub(replacement, dax, count=1)

            if full_rewritten == dax:
                continue

            valid = self._validate_rewrite(dax, full_rewritten)
            return RewriteResult(
                strategy=self.strategy_name,
                rule_id=issue.rule_id,
                original_fragment=original_fragment,
                rewritten_fragment=rewritten_fragment,
                full_rewritten_dax=full_rewritten,
                explanation=explanation,
                confidence="high",
                estimated_improvement="Engine-optimized function replacement",
                validation_passed=valid,
            )

        return None
