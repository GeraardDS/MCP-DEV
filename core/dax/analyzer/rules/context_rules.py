"""Context transition and variable analysis rules."""

from typing import List, Set

from core.dax.tokenizer import Token, TokenType
from core.dax.knowledge import DaxFunctionDatabase
from core.dax.analyzer.models import AnalysisIssue
from .base import PythonRule

# Functions considered expensive enough to defeat short-circuit benefit.
_EXPENSIVE_FUNCS: Set[str] = {
    "CALCULATE", "CALCULATETABLE",
    "SUMX", "AVERAGEX", "COUNTX", "MAXX", "MINX", "PRODUCTX",
    "RANKX", "CONCATENATEX", "FILTER", "ADDCOLUMNS", "GENERATE",
}


class VarDefeatingShortCircuitRule(PythonRule):
    """Detect expensive VARs evaluated before IF/SWITCH (defeats short-circuit)."""

    rule_id = "PY_VAR_DEFEATING_SHORTCIRCUIT"
    category = "performance"
    severity = "high"
    title = "Expensive VARs before IF/SWITCH defeat short-circuit"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []

        # Find RETURN keyword position.
        return_idx = None
        for i, t in enumerate(tokens):
            if t.type == TokenType.KEYWORD and t.value.upper() == "RETURN":
                return_idx = i
                break

        if return_idx is None:
            return issues

        # Check if RETURN expression starts with IF or SWITCH.
        has_conditional = False
        for i in range(return_idx + 1, len(tokens)):
            t = tokens[i]
            if t.type in (TokenType.WHITESPACE, TokenType.NEWLINE):
                continue
            if t.type == TokenType.KEYWORD and t.value.upper() in ("IF", "SWITCH"):
                has_conditional = True
            elif t.type == TokenType.FUNCTION and t.value.upper() in ("IF", "SWITCH"):
                has_conditional = True
            break

        if not has_conditional:
            return issues

        # Count expensive VAR definitions before RETURN.
        expensive_count = self._count_expensive_vars(tokens, return_idx)
        if expensive_count >= 2:
            issues.append(
                self._make_issue(
                    f"{expensive_count} expensive VAR definitions "
                    f"(CALCULATE/iterators) are evaluated before the "
                    f"IF/SWITCH conditional — all branches compute even when "
                    f"only one is used, defeating short-circuit evaluation.",
                    "Move expensive computations inside IF/SWITCH branches, "
                    "or use nested IF/SWITCH so only the needed branch evaluates.",
                )
            )
        return issues

    def _count_expensive_vars(self, tokens: List[Token], return_idx: int) -> int:
        """Count VAR definitions containing expensive functions before RETURN."""
        count = 0
        i = 0
        while i < return_idx:
            t = tokens[i]
            if t.type == TokenType.KEYWORD and t.value.upper() == "VAR":
                # Collect tokens until next VAR or RETURN.
                var_body: List[Token] = []
                j = i + 1
                while j < return_idx:
                    if tokens[j].type == TokenType.KEYWORD and tokens[j].value.upper() == "VAR":
                        break
                    var_body.append(tokens[j])
                    j += 1
                # Check if body contains expensive functions.
                if self._tokens_contain_function(var_body, _EXPENSIVE_FUNCS):
                    count += 1
                i = j
            else:
                i += 1
        return count


class UnusedVarRule(PythonRule):
    """Detect VAR definitions that are never referenced."""

    rule_id = "PY_UNUSED_VAR"
    category = "maintainability"
    severity = "low"
    title = "Unused VAR definition"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []

        # Collect VAR names and their definition positions.
        var_defs: List[tuple] = []  # (name, def_index)
        for i, t in enumerate(tokens):
            if t.type == TokenType.KEYWORD and t.value.upper() == "VAR":
                # Next meaningful token should be the variable name.
                for j in range(i + 1, len(tokens)):
                    nxt = tokens[j]
                    if nxt.type in (TokenType.WHITESPACE, TokenType.NEWLINE):
                        continue
                    if nxt.type == TokenType.IDENTIFIER:
                        var_defs.append((nxt.value, j))
                    break

        # Check each VAR for usage after its definition.
        for var_name, def_idx in var_defs:
            used = False
            for k in range(def_idx + 1, len(tokens)):
                t = tokens[k]
                if t.type == TokenType.IDENTIFIER and t.value == var_name:
                    used = True
                    break
            if not used:
                issues.append(
                    self._make_issue(
                        f"Variable '{var_name}' is defined but never referenced.",
                        f"Remove the unused VAR definition to improve readability.",
                        line=tokens[def_idx].line,
                    )
                )
        return issues


class MeasureRefWithoutVarRule(PythonRule):
    """Detect standalone measure references repeated 3+ times."""

    rule_id = "PY_MEASURE_REF_WITHOUT_VAR"
    category = "maintainability"
    severity = "medium"
    title = "Repeated measure reference — extract to VAR"
    rewrite_strategy = "variable_extraction"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []

        # Collect standalone COLUMN_REFs (not preceded by TABLE_REF/IDENTIFIER).
        standalone_refs: List[str] = []
        for i, t in enumerate(tokens):
            if t.type != TokenType.COLUMN_REF:
                continue
            # Check if preceded by a table qualifier.
            if i > 0 and tokens[i - 1].type in (
                TokenType.TABLE_REF,
                TokenType.IDENTIFIER,
            ):
                continue
            standalone_refs.append(t.value)

        # Count occurrences.
        from collections import Counter

        counts = Counter(standalone_refs)
        for ref, cnt in counts.items():
            if cnt >= 3:
                issues.append(
                    self._make_issue(
                        f"Measure reference {ref} appears {cnt} times. "
                        f"Repeated evaluation of the same measure is wasteful.",
                        f"Extract into a VAR: VAR _val = {ref}  RETURN ... _val ...",
                        rewrite_strategy=self.rewrite_strategy,
                    )
                )
        return issues


class BlankPropagationRule(PythonRule):
    """Detect ``1 - DIVIDE(...)`` or ``1 - x / y`` — BLANK propagation risk."""

    rule_id = "PY_BLANK_PROPAGATION"
    category = "correctness"
    severity = "high"
    title = "BLANK propagation risk in 1 - DIVIDE/ratio"

    def evaluate(self, tokens, function_db, context=None) -> List[AnalysisIssue]:
        issues: List[AnalysisIssue] = []

        # Scan for NUMBER(1) followed by OPERATOR(-).
        for i in range(len(tokens) - 2):
            t = tokens[i]
            if t.type != TokenType.NUMBER or t.value != "1":
                continue
            nxt = tokens[i + 1]
            if nxt.type != TokenType.OPERATOR or nxt.value != "-":
                continue
            # Look at what follows the minus.
            rest = tokens[i + 2 :]
            if not rest:
                continue
            first_after = rest[0]
            # Case 1: 1 - DIVIDE(...)
            if (
                first_after.type == TokenType.FUNCTION
                and first_after.value.upper() == "DIVIDE"
            ):
                issues.append(
                    self._make_issue(
                        "Pattern `1 - DIVIDE(a, b)` returns 1 when DIVIDE "
                        "returns BLANK (denominator is 0/BLANK), which is "
                        "almost certainly wrong.",
                        "Use `VAR _ratio = DIVIDE(a, b) "
                        "RETURN IF(ISBLANK(_ratio), BLANK(), 1 - _ratio)`.",
                    )
                )
                break
            # Case 2: 1 - [measure] / [measure] or 1 - expr / expr
            # Look for a / operator in the remaining tokens at depth 0.
            depth = 0
            for rt in rest:
                if rt.type == TokenType.PAREN_OPEN:
                    depth += 1
                elif rt.type == TokenType.PAREN_CLOSE:
                    depth -= 1
                elif (
                    rt.type == TokenType.OPERATOR
                    and rt.value == "/"
                    and depth == 0
                ):
                    issues.append(
                        self._make_issue(
                            "Pattern `1 - a / b` may produce unexpected results "
                            "when b is BLANK or 0 (BLANK propagation).",
                            "Wrap the ratio in DIVIDE with explicit BLANK "
                            "handling to avoid 1 - BLANK = 1.",
                        )
                    )
                    break
            if issues:
                break
        return issues
