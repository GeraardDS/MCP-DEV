"""JSON-based DAX rule engine -- loads rules from JSON and evaluates against token streams."""

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.dax.tokenizer import DaxLexer, Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue

logger = logging.getLogger(__name__)

# Iterator functions whose second argument is the "expression" argument.
_STANDARD_ITERATORS: Set[str] = {
    "SUMX",
    "AVERAGEX",
    "MINX",
    "MAXX",
    "COUNTX",
    "RANKX",
    "PRODUCTX",
    "ADDCOLUMNS",
    "SELECTCOLUMNS",
    "GENERATE",
    "GENERATEALL",
}

# Non-descriptive variable name pattern: single char or char + single digit.
_NONDESCRIPTIVE_VAR_RE = re.compile(r"^_?[A-Za-z]\d?$")


class JsonRuleEngine:
    """Load DAX analysis rules from JSON config files and evaluate them against tokens.

    Rules are grouped into JSON files under ``core/dax/knowledge/rules/``.
    Each file is a JSON array of rule objects with a ``pattern_type`` field that
    determines which evaluator method handles the rule.
    """

    def __init__(self, rules_dir: Optional[Path] = None) -> None:
        self._rules: List[Dict[str, Any]] = []
        self._db = DaxFunctionDatabase.get()
        self._lexer = DaxLexer(function_names=self._db.get_function_names())

        if rules_dir is None:
            rules_dir = Path(__file__).resolve().parent.parent / "knowledge" / "rules"

        self._load_rules(rules_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rule_count(self) -> int:
        """Total number of loaded rules."""
        return len(self._rules)

    def evaluate(
        self,
        tokens: List[Token],
        dax: str,
        context: Optional[Any] = None,
    ) -> List[AnalysisIssue]:
        """Run all rules against *tokens* and return found issues."""
        issues: List[AnalysisIssue] = []

        for rule in self._rules:
            ptype = rule.get("pattern_type", "")
            evaluator = self._EVALUATORS.get(ptype)
            if evaluator is None:
                continue
            try:
                found = evaluator(self, rule, tokens, dax)
                issues.extend(found)
            except Exception:
                logger.debug("Rule %s raised an exception", rule.get("rule_id"), exc_info=True)

        return issues

    # ------------------------------------------------------------------
    # Rule loading
    # ------------------------------------------------------------------

    def _load_rules(self, rules_dir: Path) -> None:
        """Load all ``*.json`` files in *rules_dir*."""
        if not rules_dir.is_dir():
            logger.warning("Rules directory not found: %s", rules_dir)
            return

        for path in sorted(rules_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._rules.extend(data)
                    logger.debug("Loaded %d rules from %s", len(data), path.name)
            except Exception:
                logger.warning("Failed to load rules from %s", path, exc_info=True)

    # ------------------------------------------------------------------
    # Issue factory
    # ------------------------------------------------------------------

    def _make_issue(
        self,
        rule: Dict[str, Any],
        *,
        location: Optional[str] = None,
        match_text: Optional[str] = None,
        line: int = 0,
    ) -> AnalysisIssue:
        """Create an ``AnalysisIssue`` from a rule dict."""
        return AnalysisIssue(
            rule_id=rule["rule_id"],
            category=rule.get("category", "performance"),
            severity=rule.get("severity", "medium"),
            title=rule.get("title", rule["rule_id"]),
            description=rule.get("description", ""),
            fix_suggestion=rule.get("fix_suggestion", ""),
            source="static",
            location=location,
            estimated_improvement=rule.get("estimated_improvement"),
            rewrite_strategy=rule.get("rewrite_strategy"),
            references=rule.get("references"),
            match_text=match_text,
            line=line,
        )

    # ------------------------------------------------------------------
    # Pattern-type evaluators
    # ------------------------------------------------------------------

    def _eval_function_nesting(
        self, rule: Dict, tokens: List[Token], dax: str
    ) -> List[AnalysisIssue]:
        """Detect outer(inner(...)) nesting patterns."""
        match = rule.get("match", {})
        outer_names: Set[str] = {n.upper() for n in match.get("outer", [])}
        inner_name: str = match.get("inner", "").upper()
        position: str = match.get("position", "first_arg")

        if not outer_names or not inner_name:
            return []

        issues: List[AnalysisIssue] = []

        for i, tok in enumerate(tokens):
            if tok.type != TokenType.FUNCTION:
                continue
            if tok.value.upper() not in outer_names:
                continue

            args = self._lexer.extract_function_args(tokens, i)
            if not args:
                continue

            # Determine which args to check based on position.
            args_to_check: List[List[Token]]
            if position == "first_arg":
                args_to_check = [args[0]]
            elif position == "any_arg":
                args_to_check = args
            else:
                args_to_check = [args[0]]

            for arg_tokens in args_to_check:
                for at in arg_tokens:
                    if at.type == TokenType.FUNCTION and at.value.upper() == inner_name:
                        issues.append(
                            self._make_issue(
                                rule,
                                location=f"{tok.value}({inner_name}(...))",
                                match_text=dax[tok.start : at.end] if at.end <= len(dax) else None,
                                line=tok.line,
                            )
                        )
                        break  # One match per arg group is enough.

        return issues

    def _eval_function_in_context(
        self, rule: Dict, tokens: List[Token], dax: str
    ) -> List[AnalysisIssue]:
        """Detect target functions inside iterator expression args."""
        match = rule.get("match", {})
        context_fns: Set[str] = {n.upper() for n in match.get("context_functions", [])}
        targets: Set[str] = {n.upper() for n in match.get("target", [])}

        if not context_fns or not targets:
            return []

        issues: List[AnalysisIssue] = []

        for i, tok in enumerate(tokens):
            if tok.type != TokenType.FUNCTION:
                continue
            if tok.value.upper() not in context_fns:
                continue

            args = self._lexer.extract_function_args(tokens, i)
            if len(args) < 2:
                continue

            # Expression arg is the 2nd argument for standard iterators.
            expr_arg = args[1]

            for at in expr_arg:
                if at.type == TokenType.FUNCTION and at.value.upper() in targets:
                    issues.append(
                        self._make_issue(
                            rule,
                            location=f"{at.value} inside {tok.value} expression",
                            match_text=at.value,
                            line=at.line,
                        )
                    )
                    break  # One match per iterator.

        return issues

    def _eval_function_usage(
        self, rule: Dict, tokens: List[Token], dax: str
    ) -> List[AnalysisIssue]:
        """Detect usage of specific functions anywhere in the expression."""
        match = rule.get("match", {})
        target_fns: Set[str] = {n.upper() for n in match.get("functions", [])}

        if not target_fns:
            return []

        issues: List[AnalysisIssue] = []
        seen: Set[str] = set()

        for tok in tokens:
            if tok.type != TokenType.FUNCTION:
                continue
            upper = tok.value.upper()
            if upper in target_fns and upper not in seen:
                seen.add(upper)
                issues.append(
                    self._make_issue(
                        rule,
                        location=tok.value,
                        match_text=tok.value,
                        line=tok.line,
                    )
                )

        return issues

    def _eval_missing_function(
        self, rule: Dict, tokens: List[Token], dax: str
    ) -> List[AnalysisIssue]:
        """Detect division operator without DIVIDE function."""
        match = rule.get("match", {})
        operator = match.get("operator", "/")
        missing_fn = match.get("missing", "DIVIDE").upper()

        has_operator = False
        has_function = False
        op_token: Optional[Token] = None

        for tok in tokens:
            if tok.type == TokenType.OPERATOR and tok.value == operator:
                has_operator = True
                if op_token is None:
                    op_token = tok
            if tok.type == TokenType.FUNCTION and tok.value.upper() == missing_fn:
                has_function = True

        if has_operator and not has_function and op_token is not None:
            return [
                self._make_issue(
                    rule,
                    location=f"operator '{operator}'",
                    match_text=operator,
                    line=op_token.line,
                )
            ]

        return []

    def _eval_bare_table_arg(
        self, rule: Dict, tokens: List[Token], dax: str
    ) -> List[AnalysisIssue]:
        """Detect FILTER with a bare table reference as first argument."""
        issues: List[AnalysisIssue] = []

        for i, tok in enumerate(tokens):
            if tok.type != TokenType.FUNCTION:
                continue
            if tok.value.upper() != "FILTER":
                continue

            args = self._lexer.extract_function_args(tokens, i)
            if not args:
                continue

            first_arg = args[0]
            # A bare table arg is a single IDENTIFIER or TABLE_REF token
            # (not wrapped in a function like ALL, VALUES, etc.).
            non_trivial = [
                t for t in first_arg if t.type not in (TokenType.WHITESPACE, TokenType.NEWLINE)
            ]
            if len(non_trivial) == 1 and non_trivial[0].type in (
                TokenType.IDENTIFIER,
                TokenType.TABLE_REF,
            ):
                issues.append(
                    self._make_issue(
                        rule,
                        location=f"FILTER({non_trivial[0].value}, ...)",
                        match_text=non_trivial[0].value,
                        line=tok.line,
                    )
                )

        return issues

    def _eval_repeated_reference(
        self, rule: Dict, tokens: List[Token], dax: str
    ) -> List[AnalysisIssue]:
        """Detect the same column/measure reference appearing >= threshold times."""
        match = rule.get("match", {})
        threshold: int = match.get("threshold", 3)

        # Check if VARs are used at all — if VAR + RETURN present, the user
        # may already be capturing references.
        has_var = any(t.type == TokenType.KEYWORD and t.value.upper() == "VAR" for t in tokens)

        counter: Counter = Counter()
        first_occurrence: Dict[str, Token] = {}

        for tok in tokens:
            if tok.type in (TokenType.COLUMN_REF, TokenType.QUALIFIED_REF):
                key = tok.value
                counter[key] += 1
                if key not in first_occurrence:
                    first_occurrence[key] = tok

        issues: List[AnalysisIssue] = []
        for ref, count in counter.items():
            if count >= threshold:
                ftok = first_occurrence[ref]
                issues.append(
                    self._make_issue(
                        rule,
                        location=f"{ref} referenced {count} times",
                        match_text=ref,
                        line=ftok.line,
                    )
                )

        return issues

    def _eval_nesting_depth(self, rule: Dict, tokens: List[Token], dax: str) -> List[AnalysisIssue]:
        """Detect function nesting deeper than max_depth."""
        match = rule.get("match", {})
        target_fn: str = match.get("function", "*").upper()
        max_depth: int = match.get("max_depth", 5)

        # Build a map of function-call start indexes to their paren indexes.
        pmap = self._lexer.build_paren_map(tokens)

        # Track nesting: walk tokens, maintaining a stack of open function parens.
        func_stack: List[int] = []  # Indexes into tokens of PAREN_OPEN for functions.
        # Set of paren-open indexes that belong to function calls.
        func_paren_opens: Set[int] = set()
        for i, tok in enumerate(tokens):
            if tok.type == TokenType.FUNCTION:
                # Find the next PAREN_OPEN.
                for j in range(i + 1, len(tokens)):
                    if tokens[j].type == TokenType.PAREN_OPEN:
                        func_paren_opens.add(j)
                        break

        issues: List[AnalysisIssue] = []
        reported_depths: Set[int] = set()

        for i, tok in enumerate(tokens):
            if tok.type == TokenType.PAREN_OPEN and i in func_paren_opens:
                func_stack.append(i)
                depth = len(func_stack)
                if depth > max_depth and depth not in reported_depths:
                    reported_depths.add(depth)
                    # Find the function name for this paren.
                    fn_name = "unknown"
                    for j in range(i - 1, -1, -1):
                        if tokens[j].type == TokenType.FUNCTION:
                            fn_name = tokens[j].value
                            break
                    if target_fn == "*" or fn_name.upper() == target_fn:
                        issues.append(
                            self._make_issue(
                                rule,
                                location=f"nesting depth {depth} at {fn_name}",
                                match_text=fn_name,
                                line=tok.line,
                            )
                        )
            elif tok.type == TokenType.PAREN_CLOSE:
                # Pop if the matching open was a function paren.
                if func_stack:
                    open_idx = func_stack[-1]
                    if pmap.get(open_idx) == i:
                        func_stack.pop()

        return issues

    def _eval_unused_var(self, rule: Dict, tokens: List[Token], dax: str) -> List[AnalysisIssue]:
        """Detect VAR definitions whose names are never referenced afterward."""
        issues: List[AnalysisIssue] = []

        # Collect all VAR definitions: (name, token_index, token).
        var_defs: List[tuple] = []
        for i, tok in enumerate(tokens):
            if tok.type == TokenType.KEYWORD and tok.value.upper() == "VAR":
                # Next non-whitespace token should be the variable name.
                for j in range(i + 1, len(tokens)):
                    nt = tokens[j]
                    if nt.type in (TokenType.WHITESPACE, TokenType.NEWLINE):
                        continue
                    if nt.type == TokenType.IDENTIFIER:
                        var_defs.append((nt.value, j, nt))
                    break

        if not var_defs:
            return []

        # For each VAR, check if its name appears as an IDENTIFIER anywhere
        # after its definition (but not as the definition itself).
        for var_name, def_idx, var_tok in var_defs:
            upper_name = var_name.upper()
            used = False
            for j in range(def_idx + 1, len(tokens)):
                t = tokens[j]
                if t.type == TokenType.IDENTIFIER and t.value.upper() == upper_name:
                    used = True
                    break
            if not used:
                issues.append(
                    self._make_issue(
                        rule,
                        location=f"VAR {var_name}",
                        match_text=var_name,
                        line=var_tok.line,
                    )
                )

        return issues

    def _eval_switch_without_default(
        self, rule: Dict, tokens: List[Token], dax: str
    ) -> List[AnalysisIssue]:
        """Detect SWITCH calls without a default/else branch.

        SWITCH(expr, val1, res1, val2, res2) has an even number of args after
        the expression. SWITCH(expr, val1, res1, val2, res2, default) has an odd
        number (the extra one is the default).

        So: total args = 1 (expr) + pairs + optional_default.
        If (total_args - 1) is even -> no default.
        If (total_args - 1) is odd  -> has default.
        """
        issues: List[AnalysisIssue] = []

        for i, tok in enumerate(tokens):
            if tok.type not in (TokenType.FUNCTION, TokenType.KEYWORD):
                continue
            if tok.value.upper() != "SWITCH":
                continue

            args = self._lexer.extract_function_args(tokens, i)
            if len(args) < 3:
                # SWITCH needs at least expr + one value/result pair.
                continue

            # args[0] = expression, then pairs of (value, result), optional default.
            remaining = len(args) - 1  # After the expression arg.
            if remaining % 2 == 0:
                # Even = all pairs, no default.
                issues.append(
                    self._make_issue(
                        rule,
                        location="SWITCH without default",
                        match_text="SWITCH",
                        line=tok.line,
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # Evaluator dispatch table
    # ------------------------------------------------------------------

    _EVALUATORS = {
        "function_nesting": _eval_function_nesting,
        "function_in_context": _eval_function_in_context,
        "function_usage": _eval_function_usage,
        "missing_function": _eval_missing_function,
        "bare_table_arg": _eval_bare_table_arg,
        "repeated_reference": _eval_repeated_reference,
        "nesting_depth": _eval_nesting_depth,
        "unused_var": _eval_unused_var,
        "switch_without_default": _eval_switch_without_default,
        # "pattern" type rules are descriptive-only (documentation),
        # they need custom Python logic to evaluate and are not handled
        # by the generic engine. They can be handled by future Tier 2/3
        # evaluators or Python callback rules.
    }
