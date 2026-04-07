"""Variable extraction strategy — extract repeated references into VARs."""

import re
from collections import Counter
from typing import List, Optional

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from core.dax.optimizer.models import RewriteResult
from .base import RewriteStrategy


class VariableExtractionStrategy(RewriteStrategy):
    """Extract repeated measure/column references into VAR declarations.

    Handles issues with rewrite_strategy == "variable_extraction" or
    rule_id containing "MEASURE_REF".
    """

    strategy_name = "variable_extraction"

    def can_apply(
        self,
        issue: AnalysisIssue,
        tokens: List[Token],
        function_db: DaxFunctionDatabase,
    ) -> bool:
        if issue.rewrite_strategy == "variable_extraction":
            return True
        if "MEASURE_REF" in (issue.rule_id or ""):
            return True
        return False

    def apply(
        self,
        dax: str,
        tokens: List[Token],
        issue: AnalysisIssue,
        function_db: DaxFunctionDatabase,
    ) -> Optional[RewriteResult]:
        # Find standalone COLUMN_REF tokens (not preceded by a table qualifier).
        standalone_refs: List[str] = []
        for i, t in enumerate(tokens):
            if t.type != TokenType.COLUMN_REF:
                continue
            if i > 0 and tokens[i - 1].type in (
                TokenType.TABLE_REF,
                TokenType.IDENTIFIER,
            ):
                continue
            standalone_refs.append(t.value)

        counts = Counter(standalone_refs)
        # Find references repeated 2+ times.
        repeated = {ref: cnt for ref, cnt in counts.items() if cnt >= 2}
        if not repeated:
            return None

        # Pick the most-repeated reference first.
        target_ref = max(repeated, key=repeated.get)  # type: ignore[arg-type]
        var_name = self._generate_var_name(target_ref)

        rewritten = self._insert_var_and_replace(dax, target_ref, var_name)
        if rewritten is None or rewritten == dax:
            return None

        valid = self._validate_rewrite(dax, rewritten)
        return RewriteResult(
            strategy=self.strategy_name,
            rule_id=issue.rule_id,
            original_fragment=target_ref,
            rewritten_fragment=f"VAR {var_name} = {target_ref}",
            full_rewritten_dax=rewritten,
            explanation=(
                f"Extracted {repeated[target_ref]}x repeated reference "
                f"{target_ref} into VAR {var_name}."
            ),
            confidence="high",
            estimated_improvement="Avoids repeated measure evaluation",
            validation_passed=valid,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_var_name(expression: str) -> str:
        """Generate a meaningful variable name from a measure/column reference.

        [Sales Amount] -> _SalesAmount
        [Total Cost]   -> _TotalCost
        """
        clean = expression.strip("[] '\"")
        if "." in clean:
            clean = clean.split(".")[-1]
        words = re.split(r"[\s\-_]+", clean)
        camel = "".join(w.capitalize() for w in words if w)
        return f"_{camel}" if camel else "_Var"

    @staticmethod
    def _insert_var_and_replace(dax: str, target_ref: str, var_name: str) -> Optional[str]:
        """Insert a VAR declaration and replace subsequent references."""
        # Check if there is already a VAR/RETURN structure.
        has_return = bool(re.search(r"\bRETURN\b", dax, re.IGNORECASE))

        if has_return:
            # Insert VAR before the first RETURN.
            match = re.search(r"\bRETURN\b", dax, re.IGNORECASE)
            if not match:
                return None
            insert_pos = match.start()
            var_decl = f"VAR {var_name} = {target_ref}\n"
            before = dax[:insert_pos]
            after = dax[insert_pos:]
            rewritten = before + var_decl + after
        else:
            # Wrap entire expression in VAR/RETURN.
            var_decl = f"VAR {var_name} = {target_ref}\nRETURN\n"
            rewritten = var_decl + dax

        # Replace all occurrences of the reference with the variable name
        # (except the one in the VAR declaration itself).
        # Find the VAR declaration line to skip it.
        decl_pattern = f"VAR {var_name} = {re.escape(target_ref)}"
        decl_match = re.search(decl_pattern, rewritten)
        if not decl_match:
            return None

        decl_end = decl_match.end()
        before_decl = rewritten[:decl_end]
        after_decl = rewritten[decl_end:]

        # Replace target_ref in the after-decl portion.
        after_decl = after_decl.replace(target_ref, var_name)

        return before_decl + after_decl
