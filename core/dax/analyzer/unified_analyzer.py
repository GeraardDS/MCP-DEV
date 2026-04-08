"""Unified DAX Analyzer — single entry point for all static analysis."""

import logging
from typing import List, Optional, Tuple

from core.dax.tokenizer import DaxLexer, Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import (
    AnalysisContext,
    AnalysisIssue,
    UnifiedAnalysisResult,
)
from core.dax.analyzer.rule_engine import JsonRuleEngine
from core.dax.analyzer.rules import load_python_rules

logger = logging.getLogger(__name__)


class DaxUnifiedAnalyzer:
    """Single entry point for all DAX static analysis.

    Combines JSON rules and Python rules, evaluated against
    tokenized DAX using the function knowledge base.
    """

    def __init__(self):
        self._function_db = DaxFunctionDatabase.get()
        self._lexer = DaxLexer(function_names=self._function_db.get_function_names())
        self._json_engine = JsonRuleEngine()
        self._python_rules = load_python_rules()

    def analyze(
        self,
        dax_expression: str,
        context: Optional[AnalysisContext] = None,
    ) -> UnifiedAnalysisResult:
        """Run ALL rules against tokenized DAX at highest available tier."""
        tokens = self._lexer.tokenize_code(dax_expression)

        issues: List[AnalysisIssue] = []

        # JSON rules
        try:
            json_issues = self._json_engine.evaluate(tokens, dax_expression, context)
            issues.extend(json_issues)
        except Exception as e:
            logger.warning("JSON rule engine error: %s", e)

        # Python rules
        for rule in self._python_rules:
            try:
                rule_issues = rule.evaluate(tokens, self._function_db, context)
                issues.extend(rule_issues)
            except Exception as e:
                logger.warning("Python rule %s error: %s", rule.rule_id, e)

        # Deduplicate by rule_id + location (same issue from JSON and Python)
        seen = set()
        unique_issues = []
        for issue in issues:
            key = (issue.rule_id, issue.location or "", issue.line)
            if key not in seen:
                seen.add(key)
                unique_issues.append(issue)

        # Suppress known false positives based on expression context
        unique_issues = self._suppress_false_positives(unique_issues, dax_expression)

        tier = 1
        if context and context.trace_data:
            tier = 3
        elif context and context.vertipaq_data:
            tier = 2

        return UnifiedAnalysisResult.from_issues(unique_issues, tier_used=tier, tokens=tokens)

    @staticmethod
    def _suppress_false_positives(
        issues: list, dax: str
    ) -> list:
        """Downgrade or annotate issues that are structurally necessary."""
        has_xirr = "XIRR" in dax.upper()
        has_extended_cols = "[@" in dax

        result = []
        for issue in issues:
            # IFERROR + XIRR: no alternative exists
            if issue.rule_id in ("CORR_IFERROR_USAGE", "PERF_IFERROR") and has_xirr:
                issue.severity = "info"
                issue.description += " [Suppressed: IFERROR on XIRR is unavoidable]"
                result.append(issue)
                continue

            # CALCULATETABLE(FILTER()) on extended columns: can't use boolean filter
            if issue.rule_id == "PERF_CALCULATETABLE_FILTER" and has_extended_cols:
                issue.severity = "info"
                issue.description += " [Suppressed: FILTER on extended column [@col] required]"
                result.append(issue)
                continue

            result.append(issue)
        return result

    def analyze_batch(
        self,
        measures: List[Tuple[str, str]],
        context: Optional[AnalysisContext] = None,
    ) -> List[UnifiedAnalysisResult]:
        """Analyze multiple measures. Each tuple is (name, dax_expression)."""
        results = []
        for name, dax in measures:
            ctx = context or AnalysisContext()
            ctx.measure_name = name
            results.append(self.analyze(dax, ctx))
        return results
