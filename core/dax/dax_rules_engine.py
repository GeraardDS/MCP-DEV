"""
Comprehensive DAX static analysis rules engine with health scoring.

Provides rule-based static analysis of DAX expressions, detecting
performance anti-patterns, readability issues, and correctness
problems. Returns a health score (0-100) and categorized issues.

Rules:
  PERF001: SUMX/iterator containing IF/SWITCH (high)
  PERF002: Nested iterator patterns (critical)
  PERF003: FILTER(Table, ...) that could be CALCULATE (high)
  PERF004: FORMAT() usage (medium)
  PERF005: COUNTROWS(VALUES()) vs DISTINCTCOUNT (medium)
  PERF006: CROSSFILTER/USERELATIONSHIP in measures (medium)
  READ001: Unused VAR variables (low)
  READ002: Deeply nested functions >4 levels (medium)
  CORR001: Division without DIVIDE() (medium)
  CORR002: SWITCH() without default value (low)

Usage:
    engine = DaxRulesEngine()
    result = engine.analyze(dax_expression)
    print(f"Health: {result['health_score']}/100")
    for issue in result['issues']:
        print(f"[{issue['rule_id']}] {issue['severity']}: "
              f"{issue['description']}")
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from core.dax.dax_utilities import (
    extract_function_body,
    extract_variables,
    get_line_column,
    normalize_dax,
)

# ── Pre-compiled module-level patterns ────────────────────────────

# Iterator functions that create row context
_ITERATOR_NAMES = (
    "SUMX",
    "AVERAGEX",
    "COUNTX",
    "MAXX",
    "MINX",
    "PRODUCTX",
    "RANKX",
    "CONCATENATEX",
    "STDEVX\\.S",
    "STDEVX\\.P",
    "VARX\\.S",
    "VARX\\.P",
)
_ITERATOR_GROUP = "|".join(_ITERATOR_NAMES)

_ITERATOR_RE = re.compile(
    rf"\b({_ITERATOR_GROUP})\s*\(",
    re.IGNORECASE,
)

# IF or SWITCH inside iterators
_IF_SWITCH_RE = re.compile(
    r"\b(IF|SWITCH)\s*\(",
    re.IGNORECASE,
)

# FILTER function call
_FILTER_RE = re.compile(
    r"\bFILTER\s*\(",
    re.IGNORECASE,
)

# FORMAT function call
_FORMAT_RE = re.compile(
    r"\bFORMAT\s*\(",
    re.IGNORECASE,
)

# COUNTROWS(VALUES(...)) pattern
_COUNTROWS_VALUES_RE = re.compile(
    r"\bCOUNTROWS\s*\(\s*VALUES\s*\(",
    re.IGNORECASE,
)

# CROSSFILTER or USERELATIONSHIP
_CROSSFILTER_RE = re.compile(
    r"\b(CROSSFILTER|USERELATIONSHIP)\s*\(",
    re.IGNORECASE,
)

# SWITCH function call
_SWITCH_RE = re.compile(
    r"\bSWITCH\s*\(",
    re.IGNORECASE,
)

# Division operator: match a/b but not // (comments)
_DIVISION_RE = re.compile(
    r"(?<![/])/(?![/\*])",
)

# DIVIDE function call
_DIVIDE_RE = re.compile(
    r"\bDIVIDE\s*\(",
    re.IGNORECASE,
)

# Bare table name as first argument to FILTER
_BARE_TABLE_RE = re.compile(
    r"""
    ^\s*
    (?:
        '([^']+)'           # single-quoted table name
        |
        ([A-Za-z_]\w*)      # unquoted table name
    )
    \s*,                    # followed by comma
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Table-wrapping functions (FILTER's first arg is not bare)
_TABLE_WRAPPER_FUNCS = (
    "ALL",
    "ALLSELECTED",
    "ALLNOBLANKROW",
    "ALLEXCEPT",
    "VALUES",
    "DISTINCT",
    "KEEPFILTERS",
    "CALCULATETABLE",
    "FILTER",
    "TOPN",
    "SUMMARIZE",
    "SUMMARIZECOLUMNS",
    "ADDCOLUMNS",
    "SELECTCOLUMNS",
    "DATATABLE",
    "GENERATESERIES",
    "GENERATE",
    "GENERATEALL",
    "NATURALINNERJOIN",
    "NATURALLEFTOUTERJOIN",
    "CROSSJOIN",
    "UNION",
    "INTERSECT",
    "EXCEPT",
)
_TABLE_WRAPPER_RE = re.compile(
    r"\b(" + "|".join(_TABLE_WRAPPER_FUNCS) + r")\s*\(\s*$",
    re.IGNORECASE,
)

# Any function call: FunctionName(
_ANY_FUNC_CALL_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_.]*\s*\(",
)

# RETURN keyword
_RETURN_RE = re.compile(r"\bRETURN\b", re.IGNORECASE)


# ── Data classes ──────────────────────────────────────────────────


@dataclass
class DaxIssue:
    """A single static analysis issue."""

    rule_id: str  # "PERF001", "READ001", "CORR001"
    category: str  # "performance", "readability", "correctness"
    severity: str  # "critical", "high", "medium", "low"
    description: str
    fix_suggestion: str
    line: int = 0
    match_text: str = ""


# ── Base rule ─────────────────────────────────────────────────────


class _BaseRule(ABC):
    """Base class for DAX static analysis rules."""

    rule_id: str
    category: str
    severity: str

    @abstractmethod
    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        """Run this rule against a DAX expression.

        Args:
            normalized: DAX with comments removed
            original: Original DAX expression

        Returns:
            List of detected issues
        """


# ── Performance rules ─────────────────────────────────────────────


class _PerfSumxIf(_BaseRule):
    """PERF001: IF/SWITCH inside iterator expression argument.

    When IF or SWITCH appears in the expression argument of an
    iterator, it prevents the Storage Engine from batch-processing
    and forces row-by-row Formula Engine evaluation.
    """

    rule_id = "PERF001"
    category = "performance"
    severity = "high"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        for m in _ITERATOR_RE.finditer(normalized):
            func_name = m.group(1)
            body = extract_function_body(normalized, m.end())
            expr_part = _get_expression_arg(body)
            if expr_part is None:
                continue

            for inner in _IF_SWITCH_RE.finditer(expr_part):
                inner_func = inner.group(1).upper()
                line, _ = get_line_column(normalized, m.start())
                results.append(
                    DaxIssue(
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=self.severity,
                        description=(
                            f"{inner_func}() inside "
                            f"{func_name}() forces "
                            f"row-by-row evaluation"
                        ),
                        fix_suggestion=(
                            "Use CALCULATE with filter "
                            "arguments instead of "
                            "conditional logic inside "
                            "the iterator"
                        ),
                        line=line,
                        match_text=_snippet(normalized, m.start(), 80),
                    )
                )
                break  # one detection per iterator

        return results


class _PerfNestedIterators(_BaseRule):
    """PERF002: Nested iterator patterns.

    An iterator inside another iterator creates a Cartesian
    product, potentially multiplying row counts and causing
    severe performance degradation.
    """

    rule_id = "PERF002"
    category = "performance"
    severity = "critical"

    _INNER_RE = re.compile(
        r"\b(SUMX|AVERAGEX|COUNTX|MAXX|MINX|PRODUCTX" r"|FILTER|ADDCOLUMNS|GENERATE)\s*\(",
        re.IGNORECASE,
    )

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        for m in _ITERATOR_RE.finditer(normalized):
            outer_name = m.group(1)
            body = extract_function_body(normalized, m.end())
            expr_part = _get_expression_arg(body)
            if expr_part is None:
                continue

            for inner in self._INNER_RE.finditer(expr_part):
                inner_name = inner.group(1).upper()
                line, _ = get_line_column(normalized, m.start())
                results.append(
                    DaxIssue(
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=self.severity,
                        description=(
                            f"Nested iterator: "
                            f"{inner_name}() inside "
                            f"{outer_name}() creates "
                            f"Cartesian product"
                        ),
                        fix_suggestion=(
                            "Pre-aggregate with "
                            "SUMMARIZE/ADDCOLUMNS "
                            "before iterating, or "
                            "restructure to avoid "
                            "nesting"
                        ),
                        line=line,
                        match_text=_snippet(normalized, m.start(), 80),
                    )
                )
                break  # one detection per outer iterator

        return results


class _PerfFilterVsCalc(_BaseRule):
    """PERF003: FILTER on bare table that could be CALCULATE.

    FILTER(TableName, condition) materializes the entire table
    row by row. In many cases, CALCULATE with filter arguments
    is more efficient because it uses the engine's native
    filtering.
    """

    rule_id = "PERF003"
    category = "performance"
    severity = "high"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        for m in _FILTER_RE.finditer(normalized):
            body = extract_function_body(normalized, m.end())
            if not body.strip():
                continue

            bare = _BARE_TABLE_RE.match(body)
            if not bare:
                continue

            table_name = bare.group(1) or bare.group(2)

            # Exclude if preceded by a table-wrapping function
            preceding = normalized[: m.start()].rstrip()
            if _TABLE_WRAPPER_RE.search(preceding):
                continue

            line, _ = get_line_column(normalized, m.start())
            results.append(
                DaxIssue(
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=self.severity,
                    description=(
                        f"FILTER() iterates entire " f"table '{table_name}' row " f"by row"
                    ),
                    fix_suggestion=(
                        "Use CALCULATE with filter "
                        "arguments instead of "
                        "FILTER on the full table"
                    ),
                    line=line,
                    match_text=_snippet(normalized, m.start(), 80),
                )
            )

        return results


class _PerfFormat(_BaseRule):
    """PERF004: FORMAT() usage in measures.

    FORMAT() converts values to strings, which the Storage
    Engine cannot process. The query falls back to Formula
    Engine evaluation. Formatting should be done in the
    visual/report layer instead.
    """

    rule_id = "PERF004"
    category = "performance"
    severity = "medium"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        for m in _FORMAT_RE.finditer(normalized):
            line, _ = get_line_column(normalized, m.start())
            results.append(
                DaxIssue(
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=self.severity,
                    description=("FORMAT() prevents Storage " "Engine optimization"),
                    fix_suggestion=(
                        "Apply formatting in the "
                        "visual layer or use format "
                        "strings on the measure"
                    ),
                    line=line,
                    match_text=_snippet(normalized, m.start(), 60),
                )
            )

        return results


class _PerfDistinctCount(_BaseRule):
    """PERF005: COUNTROWS(VALUES()) vs DISTINCTCOUNT.

    COUNTROWS(VALUES(column)) can often be replaced with
    DISTINCTCOUNT(column), which is more readable and can
    be slightly more efficient in some cases.
    """

    rule_id = "PERF005"
    category = "performance"
    severity = "medium"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        for m in _COUNTROWS_VALUES_RE.finditer(normalized):
            line, _ = get_line_column(normalized, m.start())
            results.append(
                DaxIssue(
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=self.severity,
                    description=("COUNTROWS(VALUES()) can be " "simplified to DISTINCTCOUNT()"),
                    fix_suggestion=(
                        "Replace " "COUNTROWS(VALUES(column)) " "with DISTINCTCOUNT(column)"
                    ),
                    line=line,
                    match_text=_snippet(normalized, m.start(), 60),
                )
            )

        return results


class _PerfBiDiRelation(_BaseRule):
    """PERF006: CROSSFILTER/USERELATIONSHIP in measures.

    CROSSFILTER and USERELATIONSHIP modify relationship
    behavior at query time, which can indicate bidirectional
    filtering needs that may impact performance.
    """

    rule_id = "PERF006"
    category = "performance"
    severity = "medium"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        for m in _CROSSFILTER_RE.finditer(normalized):
            func_name = m.group(1).upper()
            line, _ = get_line_column(normalized, m.start())
            results.append(
                DaxIssue(
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=self.severity,
                    description=(
                        f"{func_name}() modifies " f"relationship behavior at " f"query time"
                    ),
                    fix_suggestion=(
                        "Verify this is necessary; "
                        "consider model-level "
                        "relationship changes or "
                        "bridge tables to avoid "
                        "runtime relationship "
                        "modifications"
                    ),
                    line=line,
                    match_text=_snippet(normalized, m.start(), 60),
                )
            )

        return results


# ── Readability rules ─────────────────────────────────────────────


class _ReadUnusedVars(_BaseRule):
    """READ001: VAR defined but never used in RETURN.

    Unused variables add complexity without benefit. They
    should be removed or the RETURN expression should
    reference them.
    """

    rule_id = "READ001"
    category = "readability"
    severity = "low"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        variables = extract_variables(normalized)
        if not variables:
            return results

        # Find the RETURN block
        return_match = _RETURN_RE.search(normalized)
        if not return_match:
            return results

        return_block = normalized[return_match.end() :]

        for var_name in variables:
            # Check if variable is used in RETURN block
            # Match as a whole word (VAR names are identifiers)
            pattern = re.compile(
                rf"\b{re.escape(var_name)}\b",
                re.IGNORECASE,
            )
            if not pattern.search(return_block):
                # Also check if used by other VARs after it
                used_elsewhere = False
                for other_name, other_def in variables.items():
                    if other_name == var_name:
                        continue
                    if pattern.search(other_def):
                        used_elsewhere = True
                        break

                if not used_elsewhere:
                    results.append(
                        DaxIssue(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            description=(f"Variable '{var_name}' is " f"defined but never used"),
                            fix_suggestion=(
                                f"Remove unused VAR "
                                f"'{var_name}' or use it "
                                f"in the RETURN expression"
                            ),
                            line=0,
                            match_text=f"VAR {var_name} = ...",
                        )
                    )

        return results


class _ReadDeepNesting(_BaseRule):
    """READ002: Deeply nested functions (>4 levels).

    Excessive nesting reduces readability and makes DAX
    harder to debug. Use VAR variables to break up deeply
    nested expressions.
    """

    rule_id = "READ002"
    category = "readability"
    severity = "medium"

    _MAX_DEPTH = 4

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        max_depth = 0
        max_depth_pos = 0
        depth = 0
        in_double_quote = False
        in_single_quote = False

        for i, ch in enumerate(normalized):
            if in_double_quote:
                if ch == '"':
                    nxt = normalized[i + 1] if i + 1 < len(normalized) else ""
                    if nxt == '"':
                        continue
                    in_double_quote = False
            elif in_single_quote:
                if ch == "'":
                    nxt = normalized[i + 1] if i + 1 < len(normalized) else ""
                    if nxt == "'":
                        continue
                    in_single_quote = False
            else:
                if ch == '"':
                    in_double_quote = True
                elif ch == "'":
                    in_single_quote = True
                elif ch == "(":
                    depth += 1
                    if depth > max_depth:
                        max_depth = depth
                        max_depth_pos = i
                elif ch == ")":
                    depth = max(0, depth - 1)

        if max_depth > self._MAX_DEPTH:
            line, _ = get_line_column(normalized, max_depth_pos)
            results.append(
                DaxIssue(
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=self.severity,
                    description=(
                        f"Function nesting depth of "
                        f"{max_depth} exceeds "
                        f"recommended maximum of "
                        f"{self._MAX_DEPTH}"
                    ),
                    fix_suggestion=(
                        "Use VAR variables to break "
                        "deeply nested expressions "
                        "into readable steps"
                    ),
                    line=line,
                    match_text=_snippet(normalized, max_depth_pos, 60),
                )
            )

        return results


# ── Correctness rules ─────────────────────────────────────────────


class _CorrDivision(_BaseRule):
    """CORR001: Division without DIVIDE() wrapper.

    The / operator returns an error when dividing by zero.
    DIVIDE(a, b) handles division by zero gracefully by
    returning BLANK() by default.
    """

    rule_id = "CORR001"
    category = "correctness"
    severity = "medium"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        # Skip if the expression already uses DIVIDE
        if _DIVIDE_RE.search(normalized):
            return results

        divisions = list(_DIVISION_RE.finditer(normalized))
        if not divisions:
            return results

        # Report the first occurrence only to avoid noise
        m = divisions[0]
        line, _ = get_line_column(normalized, m.start())
        results.append(
            DaxIssue(
                rule_id=self.rule_id,
                category=self.category,
                severity=self.severity,
                description=(
                    "Division operator '/' used "
                    "without DIVIDE() wrapper "
                    f"({len(divisions)} occurrence(s))"
                ),
                fix_suggestion=(
                    "Use DIVIDE(numerator, " "denominator) to handle " "division-by-zero safely"
                ),
                line=line,
                match_text=_snippet(normalized, max(0, m.start() - 10), 40),
            )
        )

        return results


class _CorrSwitchDefault(_BaseRule):
    """CORR002: SWITCH() without a default value.

    SWITCH(expression, value1, result1, ...) without a
    trailing default argument returns BLANK() for unmatched
    values, which may cause unexpected results.
    """

    rule_id = "CORR002"
    category = "correctness"
    severity = "low"

    def check(self, normalized: str, original: str) -> List[DaxIssue]:
        results: List[DaxIssue] = []

        for m in _SWITCH_RE.finditer(normalized):
            body = extract_function_body(normalized, m.end())
            # Count top-level arguments (commas at depth 0)
            arg_count = _count_top_level_args(body)

            # SWITCH(expr, val1, res1) = 3 args (no default)
            # SWITCH(expr, val1, res1, default) = 4 args
            # SWITCH(expr, val1, res1, val2, res2) = 5 args
            # Pattern: 1 + 2*N args = no default
            #          1 + 2*N + 1 args = has default
            # So if (arg_count - 1) is even, no default
            if arg_count >= 3 and (arg_count - 1) % 2 == 0:
                line, _ = get_line_column(normalized, m.start())
                results.append(
                    DaxIssue(
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=self.severity,
                        description=("SWITCH() has no default " "value for unmatched cases"),
                        fix_suggestion=(
                            "Add a default value as "
                            "the last SWITCH argument "
                            "to handle unmatched cases "
                            "explicitly"
                        ),
                        line=line,
                        match_text=_snippet(normalized, m.start(), 60),
                    )
                )

        return results


# ── Helper functions ──────────────────────────────────────────────


def _get_expression_arg(body: str):
    """Extract the expression argument from an iterator body.

    Iterator functions: SUMX(table, expression). Returns the
    text after the first top-level comma.

    Args:
        body: Function body text (content between parens)

    Returns:
        Expression argument text, or None if no comma found
    """
    depth = 0
    in_double_quote = False
    in_single_quote = False

    for i, ch in enumerate(body):
        if in_double_quote:
            if ch == '"':
                if i + 1 < len(body) and body[i + 1] == '"':
                    continue
                in_double_quote = False
        elif in_single_quote:
            if ch == "'":
                if i + 1 < len(body) and body[i + 1] == "'":
                    continue
                in_single_quote = False
        else:
            if ch == '"':
                in_double_quote = True
            elif ch == "'":
                in_single_quote = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                return body[i + 1 :]

    return None


def _count_top_level_args(body: str) -> int:
    """Count top-level arguments in a function body.

    Args:
        body: Function body (content between parens)

    Returns:
        Number of arguments (commas + 1)
    """
    if not body.strip():
        return 0

    count = 1
    depth = 0
    in_double_quote = False
    in_single_quote = False

    for i, ch in enumerate(body):
        if in_double_quote:
            if ch == '"':
                if i + 1 < len(body) and body[i + 1] == '"':
                    continue
                in_double_quote = False
        elif in_single_quote:
            if ch == "'":
                if i + 1 < len(body) and body[i + 1] == "'":
                    continue
                in_single_quote = False
        else:
            if ch == '"':
                in_double_quote = True
            elif ch == "'":
                in_single_quote = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                count += 1

    return count


def _snippet(dax: str, pos: int, max_len: int) -> str:
    """Extract a code snippet around a position.

    Args:
        dax: Full DAX expression
        pos: Character position to start from
        max_len: Maximum snippet length

    Returns:
        Truncated code fragment with ellipsis if needed
    """
    end = min(pos + max_len, len(dax))
    snippet = dax[pos:end].replace("\n", " ").strip()
    if end < len(dax):
        snippet += "..."
    return snippet


# ── Severity deductions for health score ──────────────────────────

_SEVERITY_DEDUCTIONS = {
    "critical": 20,
    "high": 10,
    "medium": 5,
    "low": 2,
}


# ── Main engine class ────────────────────────────────────────────


class DaxRulesEngine:
    """DAX static analysis with health scoring.

    Analyzes DAX expressions against a comprehensive set of
    rules covering performance, readability, and correctness.
    Returns a health score (0-100) and categorized issues.

    Usage:
        engine = DaxRulesEngine()
        result = engine.analyze(dax_expression)
    """

    def __init__(self) -> None:
        self._rules: list = self._build_rules()

    def analyze(self, dax_expression: str) -> dict:
        """Analyze DAX and return issues + health score.

        Args:
            dax_expression: Raw DAX expression

        Returns:
            Dict with health_score, issues, issue_count,
            and by_category breakdown
        """
        normalized = normalize_dax(dax_expression)
        issues: List[DaxIssue] = []

        for rule in self._rules:
            issues.extend(rule.check(normalized, dax_expression))

        # Sort by severity priority, then by line
        severity_order = {
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 3,
        }
        issues.sort(
            key=lambda i: (
                severity_order.get(i.severity, 99),
                i.line,
            )
        )

        score = self._calculate_health_score(issues)

        return {
            "health_score": score,
            "issues": [self._issue_to_dict(i) for i in issues],
            "issue_count": len(issues),
            "by_category": self._group_by_category(issues),
        }

    def _calculate_health_score(self, issues: List[DaxIssue]) -> int:
        """Calculate health score 0-100.

        Deductions: critical=-20, high=-10, medium=-5,
        low=-2. Floored at 0.
        """
        score = 100
        for issue in issues:
            deduction = _SEVERITY_DEDUCTIONS.get(issue.severity, 0)
            score -= deduction
        return max(0, score)

    def _issue_to_dict(self, issue: DaxIssue) -> dict:
        """Convert DaxIssue to a serializable dict."""
        return {
            "rule_id": issue.rule_id,
            "category": issue.category,
            "severity": issue.severity,
            "description": issue.description,
            "fix_suggestion": issue.fix_suggestion,
            "line": issue.line,
            "match_text": issue.match_text,
        }

    def _group_by_category(self, issues: List[DaxIssue]) -> dict:
        """Group issue counts by category."""
        groups: dict = {}
        for issue in issues:
            cat = issue.category
            if cat not in groups:
                groups[cat] = 0
            groups[cat] += 1
        return groups

    def _build_rules(self) -> list:
        """Build the comprehensive rule set."""
        return [
            # Performance rules
            _PerfSumxIf(),  # PERF001
            _PerfNestedIterators(),  # PERF002
            _PerfFilterVsCalc(),  # PERF003
            _PerfFormat(),  # PERF004
            _PerfDistinctCount(),  # PERF005
            _PerfBiDiRelation(),  # PERF006
            # Readability rules
            _ReadUnusedVars(),  # READ001
            _ReadDeepNesting(),  # READ002
            # Correctness rules
            _CorrDivision(),  # CORR001
            _CorrSwitchDefault(),  # CORR002
        ]
