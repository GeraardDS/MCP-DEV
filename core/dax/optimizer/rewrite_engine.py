"""DAX Rewrite Engine — generates optimized DAX from analysis issues."""

import logging
import re
from typing import List, Optional

from core.dax.tokenizer import DaxLexer, Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from core.dax.optimizer.models import RewriteResult
from core.dax.optimizer.strategies import load_strategies

logger = logging.getLogger(__name__)


class DaxRewriteEngine:
    """Generates optimized DAX rewrites based on analysis issues.

    Loads all registered rewrite strategies and matches them to issues
    that carry a ``rewrite_strategy`` field. Each strategy produces a
    ``RewriteResult`` with the transformed DAX and metadata.
    """

    def __init__(self, function_db: Optional[DaxFunctionDatabase] = None) -> None:
        self._function_db = function_db or DaxFunctionDatabase.get()
        self._lexer = DaxLexer(function_names=self._function_db.get_function_names())
        self._strategies = load_strategies()

    def rewrite(
        self,
        dax: str,
        tokens: List[Token],
        issues: List[AnalysisIssue],
    ) -> List[RewriteResult]:
        """Generate rewrites for fixable issues.

        Iterates through issues that have a ``rewrite_strategy`` set,
        finds the first matching strategy, and produces a ``RewriteResult``.
        """
        results: List[RewriteResult] = []
        for issue in issues:
            if not issue.rewrite_strategy:
                continue
            for strategy in self._strategies:
                if strategy.can_apply(issue, tokens, self._function_db):
                    try:
                        result = strategy.apply(dax, tokens, issue, self._function_db)
                        if result:
                            results.append(result)
                            break
                    except Exception as e:
                        logger.warning("Strategy %s failed: %s", strategy.strategy_name, e)
        return results

    def apply_rewrites(self, dax: str, rewrites: List[RewriteResult]) -> str:
        """Apply rewrites to produce final DAX.

        Applies validated rewrites sequentially — each builds on the
        previous result's ``full_rewritten_dax``.
        """
        if not rewrites:
            return dax
        current = dax
        for rw in rewrites:
            if rw.validation_passed and rw.full_rewritten_dax:
                current = rw.full_rewritten_dax
        return current

    @staticmethod
    def generate_variable_name(expression: str) -> str:
        """Generate a meaningful variable name from a DAX expression.

        [Sales Amount]    -> _SalesAmount
        [Total Cost]      -> _TotalCost
        SUM(Sales[Qty])   -> _TotalQty
        Budget            -> _Budget
        """
        # Strip brackets and quotes.
        clean = expression.strip("[] '\"")
        # Remove table prefix if present.
        if "." in clean:
            clean = clean.split(".")[-1]
        # CamelCase the words.
        words = re.split(r"[\s\-_]+", clean)
        camel = "".join(w.capitalize() for w in words if w)
        return f"_{camel}" if camel else "_Var"
