"""Base class for rewrite strategies."""

from abc import ABC, abstractmethod
from typing import List, Optional

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from core.dax.optimizer.models import RewriteResult


class RewriteStrategy(ABC):
    """Abstract base for DAX rewrite strategies.

    Each strategy handles a set of issue types and produces
    a ``RewriteResult`` with the transformed DAX.
    """

    strategy_name: str

    @abstractmethod
    def can_apply(
        self,
        issue: AnalysisIssue,
        tokens: List[Token],
        function_db: DaxFunctionDatabase,
    ) -> bool:
        """Check if this strategy can fix the given issue."""

    @abstractmethod
    def apply(
        self,
        dax: str,
        tokens: List[Token],
        issue: AnalysisIssue,
        function_db: DaxFunctionDatabase,
    ) -> Optional[RewriteResult]:
        """Apply the rewrite. Return None if it cannot be applied."""

    def _validate_rewrite(self, original: str, rewritten: str) -> bool:
        """Validate rewritten DAX by checking structural integrity."""
        from core.dax.tokenizer import DaxLexer

        try:
            lexer = DaxLexer()
            tokens = lexer.tokenize_code(rewritten)
            if not tokens:
                return len(original.strip()) == 0
            # Check paren balance
            opens = sum(1 for t in tokens if t.type == TokenType.PAREN_OPEN)
            closes = sum(1 for t in tokens if t.type == TokenType.PAREN_CLOSE)
            if opens != closes:
                return False
            return True
        except Exception:
            return False
