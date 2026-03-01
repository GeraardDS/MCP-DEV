"""
CallbackDataID pattern detection for DAX measures.

Detects common DAX anti-patterns that cause CallbackDataID, which
prevents the Storage Engine from optimizing queries. When a
CallbackDataID is present, the query plan falls back to row-by-row
Formula Engine evaluation, often causing 5-50x slower performance.

Rules:
  CB001: IF/SWITCH inside iterators (critical)
  CB002: IFERROR/ISERROR in iterators (high)
  CB003: Nested iterators - Cartesian products (critical)
  CB004: FILTER on entire table (high)
  CB005: FORMAT() preventing SE optimization (medium)
  CB006: LASTDATE vs MAX for dates (medium)

Usage:
    detector = CallbackDetector()
    detections = detector.detect(dax_expression)
    for d in detections:
        print(f"[{d.rule_id}] {d.severity}: {d.description}")
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from core.dax.dax_utilities import (
    extract_function_body,
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

# Match any iterator function call: SUMX(, AVERAGEX(, etc.
_ITERATOR_RE = re.compile(
    rf"\b({_ITERATOR_GROUP})\s*\(",
    re.IGNORECASE,
)

# IF or SWITCH function call
_IF_SWITCH_RE = re.compile(
    r"\b(IF|SWITCH)\s*\(",
    re.IGNORECASE,
)

# IFERROR or ISERROR function call
_IFERROR_RE = re.compile(
    r"\b(IFERROR|ISERROR)\s*\(",
    re.IGNORECASE,
)

# FILTER function call
_FILTER_RE = re.compile(
    r"\bFILTER\s*\(",
    re.IGNORECASE,
)

# Functions that wrap a table reference (not a bare table)
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

# FORMAT function call
_FORMAT_RE = re.compile(
    r"\bFORMAT\s*\(",
    re.IGNORECASE,
)

# LASTDATE function call
_LASTDATE_RE = re.compile(
    r"\bLASTDATE\s*\(",
    re.IGNORECASE,
)

# Bare table name: starts with a letter/quote, no function call
# before it (i.e. first argument to FILTER).
# Matches: TableName  or  'Table Name'
_BARE_TABLE_RE = re.compile(
    r"""
    ^\s*                        # leading whitespace
    (?:
        '([^']+)'               # single-quoted table name
        |
        ([A-Za-z_]\w*)          # unquoted table name
    )
    \s*,                        # followed by comma (separator)
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class CallbackDetection:
    """A single CallbackDataID detection result."""

    rule_id: str  # "CB001", "CB002", etc.
    severity: str  # "critical", "high", "medium"
    description: str  # What was found
    fix_suggestion: str  # How to fix it
    line: int  # Approximate line in the expression
    match_text: str  # The matched code fragment


class _BaseRule(ABC):
    """Base class for callback detection rules."""

    rule_id: str
    severity: str

    @abstractmethod
    def check(self, dax: str) -> List[CallbackDetection]:
        """Run this rule against a DAX expression."""


class _Rule_CB001(_BaseRule):
    """IF/SWITCH inside iterator functions.

    When IF or SWITCH appears in the expression argument of an
    iterator (SUMX, AVERAGEX, COUNTX, MAXX, MINX, PRODUCTX),
    the Storage Engine cannot optimize the query and falls back
    to row-by-row Formula Engine evaluation.
    """

    rule_id = "CB001"
    severity = "critical"

    def check(self, dax: str) -> List[CallbackDetection]:
        results: List[CallbackDetection] = []

        for m in _ITERATOR_RE.finditer(dax):
            func_name = m.group(1)
            paren_pos = m.end() - 1  # position of '('
            body_start = paren_pos + 1
            body = extract_function_body(dax, body_start)

            # The expression argument is the second argument
            # (after the table). Find first top-level comma.
            expr_part = _get_expression_arg(body)
            if expr_part is None:
                continue

            for inner in _IF_SWITCH_RE.finditer(expr_part):
                inner_func = inner.group(1).upper()
                # Calculate position in the original DAX
                abs_pos = m.start()
                line, _ = get_line_column(dax, abs_pos)
                snippet = _make_snippet(dax, abs_pos, 80)
                results.append(
                    CallbackDetection(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        description=(
                            f"{inner_func}() inside {func_name}() "
                            f"forces row-by-row FE evaluation "
                            f"(CallbackDataID)"
                        ),
                        fix_suggestion=(
                            "Move conditional logic outside the "
                            "iterator, or use CALCULATE with "
                            "filters instead"
                        ),
                        line=line,
                        match_text=snippet,
                    )
                )
                break  # one detection per iterator

        return results


class _Rule_CB002(_BaseRule):
    """IFERROR/ISERROR in iterator functions.

    Error-handling functions inside iterators force step-by-step
    FE execution, preventing SE batch processing.
    """

    rule_id = "CB002"
    severity = "high"

    def check(self, dax: str) -> List[CallbackDetection]:
        results: List[CallbackDetection] = []

        for m in _ITERATOR_RE.finditer(dax):
            func_name = m.group(1)
            paren_pos = m.end() - 1
            body_start = paren_pos + 1
            body = extract_function_body(dax, body_start)

            expr_part = _get_expression_arg(body)
            if expr_part is None:
                continue

            for inner in _IFERROR_RE.finditer(expr_part):
                inner_func = inner.group(1).upper()
                abs_pos = m.start()
                line, _ = get_line_column(dax, abs_pos)
                snippet = _make_snippet(dax, abs_pos, 80)
                results.append(
                    CallbackDetection(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        description=(
                            f"{inner_func}() inside {func_name}() "
                            f"forces step-by-step FE execution"
                        ),
                        fix_suggestion=(
                            "Use DIVIDE() instead of division "
                            "with IFERROR, or handle errors "
                            "outside the iterator"
                        ),
                        line=line,
                        match_text=snippet,
                    )
                )
                break

        return results


class _Rule_CB003(_BaseRule):
    """Nested iterators creating Cartesian products.

    An iterator inside another iterator (e.g. SUMX inside SUMX,
    FILTER inside SUMX) creates a Cartesian product that can
    explode row counts and cause severe performance degradation.
    """

    rule_id = "CB003"
    severity = "critical"

    # Inner iterators to look for (includes FILTER)
    _INNER_ITER_RE = re.compile(
        r"\b(SUMX|AVERAGEX|COUNTX|MAXX|MINX|PRODUCTX" r"|FILTER|ADDCOLUMNS|GENERATE)\s*\(",
        re.IGNORECASE,
    )

    def check(self, dax: str) -> List[CallbackDetection]:
        results: List[CallbackDetection] = []

        for m in _ITERATOR_RE.finditer(dax):
            outer_name = m.group(1)
            paren_pos = m.end() - 1
            body_start = paren_pos + 1
            body = extract_function_body(dax, body_start)

            expr_part = _get_expression_arg(body)
            if expr_part is None:
                continue

            for inner in self._INNER_ITER_RE.finditer(expr_part):
                inner_name = inner.group(1).upper()
                abs_pos = m.start()
                line, _ = get_line_column(dax, abs_pos)
                snippet = _make_snippet(dax, abs_pos, 80)
                results.append(
                    CallbackDetection(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        description=(
                            f"Nested iterator: {inner_name}() "
                            f"inside {outer_name}() creates "
                            f"Cartesian product"
                        ),
                        fix_suggestion=(
                            "Consider SUMMARIZE or ADDCOLUMNS " "to pre-aggregate before iterating"
                        ),
                        line=line,
                        match_text=snippet,
                    )
                )
                break

        return results


class _Rule_CB004(_BaseRule):
    """FILTER on entire table vs column filter.

    FILTER(TableName, ...) where TableName is a bare table
    reference (not wrapped in ALL, VALUES, etc.) materializes
    the entire table in memory row by row.
    """

    rule_id = "CB004"
    severity = "high"

    def check(self, dax: str) -> List[CallbackDetection]:
        results: List[CallbackDetection] = []

        for m in _FILTER_RE.finditer(dax):
            paren_pos = m.end() - 1
            body_start = paren_pos + 1
            body = extract_function_body(dax, body_start)

            if not body.strip():
                continue

            # Check if first argument is a bare table name
            bare_match = _BARE_TABLE_RE.match(body)
            if not bare_match:
                continue

            table_name = bare_match.group(1) or bare_match.group(2)

            # Check the text before the table name to ensure
            # it's not wrapped in a function like ALL(), VALUES()
            preceding = dax[: m.start()].rstrip()
            if _TABLE_WRAPPER_RE.search(preceding):
                continue

            abs_pos = m.start()
            line, _ = get_line_column(dax, abs_pos)
            snippet = _make_snippet(dax, abs_pos, 80)
            results.append(
                CallbackDetection(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    description=(f"FILTER() iterates entire table " f"'{table_name}' row by row"),
                    fix_suggestion=(
                        "Use CALCULATE with filter arguments "
                        "instead of FILTER on the entire table"
                    ),
                    line=line,
                    match_text=snippet,
                )
            )

        return results


class _Rule_CB005(_BaseRule):
    """FORMAT() preventing SE optimization.

    FORMAT() converts values to strings, which the Storage
    Engine cannot process. The entire expression containing
    FORMAT() is handled by the Formula Engine.
    """

    rule_id = "CB005"
    severity = "medium"

    def check(self, dax: str) -> List[CallbackDetection]:
        results: List[CallbackDetection] = []

        for m in _FORMAT_RE.finditer(dax):
            abs_pos = m.start()
            line, _ = get_line_column(dax, abs_pos)
            snippet = _make_snippet(dax, abs_pos, 60)
            results.append(
                CallbackDetection(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    description=("FORMAT() prevents Storage Engine " "optimization"),
                    fix_suggestion=(
                        "Use format strings in the visual "
                        "layer, or apply FORMAT only in "
                        "final display measures"
                    ),
                    line=line,
                    match_text=snippet,
                )
            )

        return results


class _Rule_CB006(_BaseRule):
    """LASTDATE vs MAX for dates.

    LASTDATE() is a table function that returns a single-row
    table, which prevents SE optimization. MAX() returns a
    scalar and is better optimized.
    """

    rule_id = "CB006"
    severity = "medium"

    def check(self, dax: str) -> List[CallbackDetection]:
        results: List[CallbackDetection] = []

        for m in _LASTDATE_RE.finditer(dax):
            abs_pos = m.start()
            line, _ = get_line_column(dax, abs_pos)
            snippet = _make_snippet(dax, abs_pos, 60)
            results.append(
                CallbackDetection(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    description=("LASTDATE() returns a table, " "preventing SE optimization"),
                    fix_suggestion=(
                        "Consider using MAX() instead of "
                        "LASTDATE() for better SE "
                        "optimization"
                    ),
                    line=line,
                    match_text=snippet,
                )
            )

        return results


# ── Helper functions ──────────────────────────────────────────────


def _get_expression_arg(body: str) -> Optional[str]:
    """Extract the expression argument from an iterator body.

    Iterator functions have the form: SUMX(table, expression).
    This returns the text after the first top-level comma,
    which is the expression argument.

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


def _make_snippet(dax: str, pos: int, max_len: int) -> str:
    """Extract a code snippet around a position.

    Args:
        dax: Full DAX expression
        pos: Character position to center around
        max_len: Maximum snippet length

    Returns:
        Truncated code fragment with ellipsis if needed
    """
    end = min(pos + max_len, len(dax))
    snippet = dax[pos:end].replace("\n", " ").strip()
    if end < len(dax):
        snippet += "..."
    return snippet


# ── Main detector class ──────────────────────────────────────────


class CallbackDetector:
    """Detect DAX patterns that cause CallbackDataID.

    CallbackDataID appears in VertiPaq SE query plans when the
    Storage Engine cannot fully process a query and must call
    back to the Formula Engine for row-by-row evaluation. This
    is one of the most common causes of slow DAX measures.

    Usage:
        detector = CallbackDetector()
        detections = detector.detect(dax_expression)
    """

    def __init__(self) -> None:
        self._rules: List[_BaseRule] = self._build_rules()

    def detect(self, dax_expression: str) -> List[CallbackDetection]:
        """Analyze DAX expression for CallbackDataID patterns.

        Args:
            dax_expression: Raw or normalized DAX expression

        Returns:
            List of CallbackDetection results sorted by line
        """
        # Normalize to remove comments before analysis
        normalized = normalize_dax(dax_expression)

        results: List[CallbackDetection] = []
        for rule in self._rules:
            results.extend(rule.check(normalized))

        # Sort by line number, then by rule_id
        results.sort(key=lambda d: (d.line, d.rule_id))
        return results

    def detect_dict(self, dax_expression: str) -> dict:
        """Analyze and return results as a dictionary.

        Convenience method for JSON serialization in handlers.

        Args:
            dax_expression: Raw or normalized DAX expression

        Returns:
            Dict with detections list and summary counts
        """
        detections = self.detect(dax_expression)

        critical = sum(1 for d in detections if d.severity == "critical")
        high = sum(1 for d in detections if d.severity == "high")
        medium = sum(1 for d in detections if d.severity == "medium")

        return {
            "callback_detections": [
                {
                    "rule_id": d.rule_id,
                    "severity": d.severity,
                    "description": d.description,
                    "fix_suggestion": d.fix_suggestion,
                    "line": d.line,
                    "match_text": d.match_text,
                }
                for d in detections
            ],
            "summary": {
                "total": len(detections),
                "critical": critical,
                "high": high,
                "medium": medium,
            },
        }

    def _build_rules(self) -> List[_BaseRule]:
        """Build the ordered rule set."""
        return [
            _Rule_CB001(),
            _Rule_CB002(),
            _Rule_CB003(),
            _Rule_CB004(),
            _Rule_CB005(),
            _Rule_CB006(),
        ]
