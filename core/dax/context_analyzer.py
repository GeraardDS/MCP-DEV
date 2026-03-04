"""
DAX Context Analyzer - Context transition detection and analysis

Detects and explains:
- Explicit CALCULATE/CALCULATETABLE context transitions
- Implicit context transitions from measure references
- Iterator function context transitions
- Performance impact assessment
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
from enum import Enum

from core.dax.dax_utilities import (
    normalize_dax,
    extract_function_body,
    extract_variables,
    get_line_column,
)
from core.config.config_manager import config as global_config

logger = logging.getLogger(__name__)

# --- Pre-compiled regex patterns ---

# Measure reference: [MeasureName]
_MEASURE_REF_RE = re.compile(r"\[([^\]]+)\]")

# Bracket expression (non-capturing, for has-measure check)
_BRACKET_EXPR_RE = re.compile(r"\[[^\]]+\]")

# Table with column: Table[Column] or 'Table Name'[Column]
_TABLE_COL_RE = re.compile(r"'?([A-Za-z0-9_\s]+)'?\[([A-Za-z0-9_\s]+)\]")

# Table name at start of body: 'TableName'[ or TableName[
_TABLE_NAME_BRACKET_RE = re.compile(r"^\s*'?([A-Za-z0-9_\s]+)'?\s*\[")

# Table name at start followed by comma or paren
_TABLE_NAME_SIMPLE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*[,)]")

# SUMMARIZE function call
_SUMMARIZE_RE = re.compile(r"\bSUMMARIZE\s*\(", re.IGNORECASE)

# Pre-compiled patterns for CALCULATE/CALCULATETABLE
_CALCULATE_PATTERNS = {
    name: re.compile(rf"\b{name}\s*\(", re.IGNORECASE) for name in ("CALCULATE", "CALCULATETABLE")
}

# Pre-compiled patterns for iterator functions
_ITERATOR_PATTERNS = {
    name: re.compile(rf"\b{name}\s*\(", re.IGNORECASE)
    for name in (
        "SUMX",
        "AVERAGEX",
        "MINX",
        "MAXX",
        "COUNTX",
        "FILTER",
        "ADDCOLUMNS",
        "SELECTCOLUMNS",
        "RANKX",
        "CONCATENATEX",
        "PRODUCTX",
        "STDEVX.S",
        "STDEVX.P",
        "VARX.S",
        "VARX.P",
    )
}


class TransitionType(Enum):
    """Type of context transition"""

    EXPLICIT_CALCULATE = "explicit_calculate"
    IMPLICIT_MEASURE = "implicit_measure"
    ITERATOR = "iterator"
    CALCULATETABLE = "calculatetable"


class PerformanceImpact(Enum):
    """Performance impact level"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ContextTransition:
    """Represents a detected context transition"""

    location: int  # Character position in DAX
    line: int  # Line number
    column: int  # Column position
    type: TransitionType
    function: str  # Function causing transition (CALCULATE, SUMX, etc.)
    measure_name: Optional[str] = None
    table_name: Optional[str] = None  # Table being iterated or referenced
    column_names: List[str] = field(default_factory=list)  # Columns involved
    row_context_vars: List[str] = field(default_factory=list)
    filter_context_before: List[str] = field(default_factory=list)
    filter_context_after: List[str] = field(default_factory=list)
    performance_impact: PerformanceImpact = PerformanceImpact.LOW
    explanation: str = ""
    nested_level: int = 0
    variables_in_scope: List[str] = field(default_factory=list)  # VAR variables available


@dataclass
class PerformanceWarning:
    """Performance warning for context transitions"""

    location: int
    severity: str  # "warning", "error"
    message: str
    suggestion: str


@dataclass
class ContextFlowExplanation:
    """Complete explanation of context flow in DAX expression"""

    transitions: List[ContextTransition]
    warnings: List[PerformanceWarning]
    summary: str
    complexity_score: int  # 0-100
    max_nesting_level: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "transitions": [
                {
                    "location": t.location,
                    "line": t.line,
                    "column": t.column,
                    "type": t.type.value,
                    "function": t.function,
                    "measure_name": t.measure_name,
                    "table_name": t.table_name,
                    "column_names": t.column_names,
                    "performance_impact": t.performance_impact.value,
                    "explanation": t.explanation,
                    "nested_level": t.nested_level,
                    "variables_in_scope": t.variables_in_scope,
                }
                for t in self.transitions
            ],
            "warnings": [
                {
                    "location": w.location,
                    "severity": w.severity,
                    "message": w.message,
                    "suggestion": w.suggestion,
                }
                for w in self.warnings
            ],
            "summary": self.summary,
            "complexity_score": self.complexity_score,
            "max_nesting_level": self.max_nesting_level,
        }


class DaxContextAnalyzer:
    """
    DAX Context Analyzer

    Detects and analyzes context transitions in DAX expressions:
    - CALCULATE and CALCULATETABLE (explicit transitions)
    - Measure references (implicit transitions)
    - Iterator functions with measure calls (transition in each iteration)
    """

    # Iterator functions that create row context
    ITERATOR_FUNCTIONS = {
        "SUMX",
        "AVERAGEX",
        "MINX",
        "MAXX",
        "COUNTX",
        "FILTER",
        "ADDCOLUMNS",
        "SELECTCOLUMNS",
        "RANKX",
        "CONCATENATEX",
        "PRODUCTX",
        "STDEVX.S",
        "STDEVX.P",
        "VARX.S",
        "VARX.P",
    }

    # Functions that cause explicit context transition
    CALCULATE_FUNCTIONS = {"CALCULATE", "CALCULATETABLE"}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize context analyzer

        Args:
            config: Optional configuration dict
        """
        self.config = config or {}
        self.max_expression_length = self.config.get("max_expression_length", 50000)
        self.nested_calculate_limit = self.config.get("nested_calculate_limit", 10)
        # Read truncation settings from local config or global
        self.filter_truncation_chars = self.config.get(
            "filter_truncation_chars",
            global_config.get("debug.filter_truncation_chars", 50),
        )
        self.variables = {}  # Track VAR variables

    def analyze_context_transitions(
        self,
        dax_expression: str,
        measure_name: Optional[str] = None,
        reference_index: Optional[Dict[str, Any]] = None,
    ) -> ContextFlowExplanation:
        """
        Analyze DAX expression for context transitions

        Args:
            dax_expression: DAX measure expression
            measure_name: Optional measure name for context
            reference_index: Optional index of all measures for dependency analysis

        Returns:
            ContextFlowExplanation with all detected transitions
        """
        try:
            if len(dax_expression) > self.max_expression_length:
                logger.warning(
                    f"DAX expression exceeds max length ({len(dax_expression)} > {self.max_expression_length})"
                )

            transitions: List[ContextTransition] = []
            warnings: List[PerformanceWarning] = []

            # Normalize expression (remove comments)
            normalized = self._normalize_dax(dax_expression)

            # Store for nesting level calculation
            self._last_normalized = normalized
            self._last_raw_dax = dax_expression

            # Extract variables
            self.variables = self._extract_variables(normalized)

            # Detect explicit CALCULATE transitions
            calc_transitions = self._detect_calculate_transitions(normalized)
            transitions.extend(calc_transitions)

            # Detect implicit measure call transitions
            measure_transitions = self._detect_implicit_measure_transitions(
                normalized, reference_index
            )
            transitions.extend(measure_transitions)

            # Detect iterator transitions
            iterator_transitions = self._detect_iterator_transitions(normalized, reference_index)
            transitions.extend(iterator_transitions)

            # Sort by location
            transitions.sort(key=lambda t: t.location)

            # Calculate nesting levels
            self._calculate_nesting_levels(transitions)

            # Detect performance issues
            warnings.extend(self._detect_performance_issues(transitions))

            # Calculate complexity score
            complexity = self._calculate_complexity_score(transitions)

            # Generate summary
            summary = self._generate_summary(transitions, warnings)

            max_nesting = max((t.nested_level for t in transitions), default=0)

            logger.info(
                f"Context analysis complete: {len(transitions)} transitions, "
                f"{len(warnings)} warnings, complexity={complexity}"
            )

            return ContextFlowExplanation(
                transitions=transitions,
                warnings=warnings,
                summary=summary,
                complexity_score=complexity,
                max_nesting_level=max_nesting,
            )

        except Exception as e:
            logger.error(f"Error analyzing context transitions: {e}", exc_info=True)
            return ContextFlowExplanation(
                transitions=[],
                warnings=[
                    PerformanceWarning(
                        location=0,
                        severity="error",
                        message=f"Analysis failed: {str(e)}",
                        suggestion="Check DAX syntax and try again",
                    )
                ],
                summary="Analysis failed",
                complexity_score=0,
                max_nesting_level=0,
            )

    def _normalize_dax(self, dax: str) -> str:
        """Normalize DAX expression (remove comments, extra whitespace)"""
        return normalize_dax(dax)

    def _extract_variables(self, dax: str) -> Dict[str, str]:
        """
        Extract VAR variables from DAX expression

        Returns:
            Dict mapping variable names to their definitions (truncated)
        """
        return extract_variables(dax)

    def _detect_calculate_transitions(self, dax: str) -> List[ContextTransition]:
        """Detect explicit CALCULATE/CALCULATETABLE transitions"""
        transitions = []

        for func_name in self.CALCULATE_FUNCTIONS:
            # Find all occurrences of CALCULATE/CALCULATETABLE
            compiled = _CALCULATE_PATTERNS[func_name]

            for match in compiled.finditer(dax):
                location = match.start()
                line, column = self._get_line_column(dax, location)

                # Extract filter arguments from CALCULATE
                start = match.end()
                body = self._extract_function_body(dax, start)
                filter_args = self._extract_filter_arguments(body)

                transition = ContextTransition(
                    location=location,
                    line=line,
                    column=column,
                    type=(
                        TransitionType.EXPLICIT_CALCULATE
                        if func_name == "CALCULATE"
                        else TransitionType.CALCULATETABLE
                    ),
                    function=func_name,
                    filter_context_after=filter_args,
                    explanation=f"{func_name} creates a new filter context by transitioning from row context (if any) to filter context. Any existing filter context is modified by the filter arguments.",
                    performance_impact=PerformanceImpact.LOW,
                    variables_in_scope=list(self.variables.keys()),
                )

                transitions.append(transition)

        return transitions

    def _extract_filter_arguments(self, body: str) -> List[str]:
        """Extract filter arguments from CALCULATE body"""
        # Split by comma at the top level (not inside parentheses)
        filters = []
        depth = 0
        current_arg = ""
        trunc = self.filter_truncation_chars

        for char in body:
            if char == "(":
                depth += 1
                current_arg += char
            elif char == ")":
                depth -= 1
                current_arg += char
            elif char == "," and depth == 0:
                # Top-level comma separates arguments
                arg = current_arg.strip()
                if arg and not arg.startswith("["):
                    filters.append(arg[:trunc] + "..." if len(arg) > trunc else arg)
                current_arg = ""
            else:
                current_arg += char

        # Add the last argument
        arg = current_arg.strip()
        if arg and filters:
            filters.append(arg[:trunc] + "..." if len(arg) > trunc else arg)

        return filters

    def _detect_implicit_measure_transitions(
        self,
        dax: str,
        reference_index: Optional[Dict[str, Any]],
    ) -> List[ContextTransition]:
        """Detect implicit context transitions from measure references"""
        transitions = []

        # Pattern to match measure references: [MeasureName]
        for match in _MEASURE_REF_RE.finditer(dax):
            measure_name = match.group(1)
            location = match.start()
            line, column = self._get_line_column(dax, location)

            # Check if this is likely a measure (not a column reference)
            # Heuristic: measures are typically referenced alone, not with table prefix
            context_before = dax[max(0, location - 10) : location]
            if "'" not in context_before and "[" not in context_before:
                # Likely a measure reference
                transition = ContextTransition(
                    location=location,
                    line=line,
                    column=column,
                    type=TransitionType.IMPLICIT_MEASURE,
                    function="MEASURE_REFERENCE",
                    measure_name=measure_name,
                    explanation=f"Implicit CALCULATE wrapper around measure [{measure_name}]. If in row context, this causes context transition to filter context.",
                    performance_impact=PerformanceImpact.LOW,
                    variables_in_scope=list(self.variables.keys()),
                )

                transitions.append(transition)

        return transitions

    def _detect_iterator_transitions(
        self,
        dax: str,
        reference_index: Optional[Dict[str, Any]],
    ) -> List[ContextTransition]:
        """Detect context transitions in iterator functions"""
        transitions = []

        for func_name in self.ITERATOR_FUNCTIONS:
            compiled = _ITERATOR_PATTERNS[func_name]

            for match in compiled.finditer(dax):
                location = match.start()
                line, column = self._get_line_column(dax, location)

                # Check if iterator contains measure references
                # Extract iterator body (simplified - doesn't handle nested functions perfectly)
                start = match.end()
                body = self._extract_function_body(dax, start)

                has_measure_refs = bool(_BRACKET_EXPR_RE.search(body))

                # Extract table name and columns from the first argument
                table_name, columns = self._extract_table_and_columns(body)
                row_context_vars = [table_name] if table_name else []

                if has_measure_refs:
                    transition = ContextTransition(
                        location=location,
                        line=line,
                        column=column,
                        type=TransitionType.ITERATOR,
                        function=func_name,
                        table_name=table_name,
                        column_names=columns,
                        row_context_vars=row_context_vars,
                        explanation=f"{func_name} creates row context{' over ' + table_name if table_name else ''}. Measure references inside the iterator cause context transition in EACH iteration, potentially impacting performance.",
                        performance_impact=PerformanceImpact.MEDIUM,
                        variables_in_scope=list(self.variables.keys()),
                    )

                    transitions.append(transition)

        return transitions

    def _extract_table_name(self, body: str) -> Optional[str]:
        """Extract table name from function body (first argument typically)"""
        # Try to extract table name - look for patterns like:
        # - Table[Column] -> Table
        # - 'Table Name'[Column] -> Table Name
        # - TableName -> TableName

        # First, try to match table with column: Table[Column] or 'Table'[Column]
        match = _TABLE_NAME_BRACKET_RE.search(body)
        if match:
            return match.group(1).strip()

        # Second, try to match just a table name at the start
        match = _TABLE_NAME_SIMPLE_RE.search(body)
        if match:
            table_name = match.group(1).strip()
            # Exclude DAX functions (they're usually uppercase)
            if not table_name.isupper():
                return table_name

        return None

    def _extract_table_and_columns(self, body: str) -> Tuple[Optional[str], List[str]]:
        """
        Extract table name and column names from function body

        Returns:
            Tuple of (table_name, list of column names)
        """
        table_name = None
        columns = []

        # Pattern to match table and column references:
        # - Table[Column]
        # - 'Table Name'[Column]
        # - [Column] (standalone column in same table)

        # Extract table with column: Table[Column] or 'Table'[Column]
        for match in _TABLE_COL_RE.finditer(body):
            potential_table = match.group(1).strip()
            column = match.group(2).strip()

            # If we haven't found a table yet, this is likely it
            if table_name is None and not potential_table.isupper():
                table_name = potential_table

            # Add column to list (avoid duplicates)
            if column not in columns and not column.isupper():
                columns.append(column)

        # If still no table name, try to extract from first argument
        if table_name is None:
            table_name = self._extract_table_name(body)

        return table_name, columns

    def _extract_function_body(self, dax: str, start: int) -> str:
        """Extract function body with string-literal-aware paren matching"""
        return extract_function_body(dax, start)

    def _calculate_nesting_levels(
        self,
        transitions: List[ContextTransition],
    ) -> None:
        """
        Calculate nesting level for each transition.

        For each CALCULATE/CALCULATETABLE transition, compute its scope
        (the body of that CALCULATE call) using extract_function_body.
        Then for every transition, count how many CALCULATE scopes
        contain its position. This gives accurate nesting depth even
        for sibling CALCULATEs like ``CALCULATE(X) + CALCULATE(Y)``
        where the second should have nesting=0, not 1.
        """
        # Pre-compute scope (start, end) for each CALCULATE transition
        # We need access to the normalized DAX to compute scopes.
        # Transitions store their location in the normalized DAX, and
        # analyze_context_transitions stores it in self._last_normalized.
        normalized = getattr(self, "_last_normalized", None)

        calc_types = {
            TransitionType.EXPLICIT_CALCULATE,
            TransitionType.CALCULATETABLE,
        }

        # Build list of (scope_start, scope_end) for CALCULATE transitions
        calc_scopes: list = []
        for t in transitions:
            if t.type not in calc_types:
                continue

            if normalized is None:
                # Fallback: can't compute scopes without the DAX text
                break

            # t.location points to the start of "CALCULATE(" in the DAX.
            # Find the opening paren after the function name.
            paren_pos = normalized.find("(", t.location)
            if paren_pos == -1:
                continue

            # extract_function_body expects position after the "("
            body_start = paren_pos + 1
            body = extract_function_body(normalized, body_start)
            # scope_end is body_start + len(body) (exclusive)
            scope_end = body_start + len(body)
            calc_scopes.append((body_start, scope_end))

        if calc_scopes:
            # For each transition, count how many CALCULATE scopes
            # contain its position.
            for transition in transitions:
                nesting = 0
                for scope_start, scope_end in calc_scopes:
                    if scope_start <= transition.location < scope_end:
                        nesting += 1
                transition.nested_level = nesting
        else:
            # Fallback: no scopes computed (e.g. no normalized DAX).
            # Use paren-depth tracking to determine which prior CALCULATEs
            # are still open (enclosing) at each transition's position.
            # Fixes bug where CALCULATE(X) + CALCULATE(Y) gave Y nesting=1
            # when it should be 0 (sibling, not nested).
            raw_dax = getattr(self, "_last_raw_dax", None) or ""
            for transition in transitions:
                nesting = 0
                pos = transition.location
                for prior_t in transitions:
                    if prior_t is transition:
                        break
                    if prior_t.type not in calc_types:
                        continue
                    # Track paren depth from prior CALCULATE to current pos
                    paren_start = raw_dax.find("(", prior_t.location)
                    if paren_start == -1 or paren_start >= pos:
                        continue
                    depth = 0
                    still_open = True
                    for ch in raw_dax[paren_start:pos]:
                        if ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth -= 1
                            if depth <= 0:
                                still_open = False
                                break
                    if still_open and depth > 0:
                        nesting += 1
                transition.nested_level = nesting

    def _detect_performance_issues(
        self, transitions: List[ContextTransition]
    ) -> List[PerformanceWarning]:
        """Detect performance issues from context transitions"""
        warnings = []

        # Check for excessive nesting
        max_nesting = max((t.nested_level for t in transitions), default=0)
        if max_nesting > self.nested_calculate_limit:
            warnings.append(
                PerformanceWarning(
                    location=0,
                    severity="warning",
                    message=f"Excessive CALCULATE nesting detected (depth: {max_nesting})",
                    suggestion="Consider refactoring into intermediate variables or measures",
                )
            )

        # Check for iterator + measure combinations
        iterator_with_measures = [
            t
            for t in transitions
            if t.type == TransitionType.ITERATOR
            and t.performance_impact == PerformanceImpact.MEDIUM
        ]

        if len(iterator_with_measures) > 5:
            warnings.append(
                PerformanceWarning(
                    location=0,
                    severity="warning",
                    message=f"Multiple iterators with measure references ({len(iterator_with_measures)} detected)",
                    suggestion="Each measure reference in an iterator causes context transition per row. Consider pre-calculating values or using variables.",
                )
            )

        return warnings

    def _calculate_complexity_score(self, transitions: List[ContextTransition]) -> int:
        """Calculate complexity score (0-100)"""
        if not transitions:
            return 0

        # Factors:
        # - Number of transitions (5 points each)
        # - Nesting depth (10 points per level)
        # - Iterator transitions (extra 5 points each)

        score = len(transitions) * 5

        max_nesting = max((t.nested_level for t in transitions), default=0)
        score += max_nesting * 10

        iterator_count = sum(1 for t in transitions if t.type == TransitionType.ITERATOR)
        score += iterator_count * 5

        return min(score, 100)

    def _generate_summary(
        self, transitions: List[ContextTransition], warnings: List[PerformanceWarning]
    ) -> str:
        """Generate human-readable summary"""
        if not transitions:
            return "No context transitions detected. This measure uses simple aggregations without context modifications."

        explicit = sum(1 for t in transitions if t.type == TransitionType.EXPLICIT_CALCULATE)
        implicit = sum(1 for t in transitions if t.type == TransitionType.IMPLICIT_MEASURE)
        iterators = sum(1 for t in transitions if t.type == TransitionType.ITERATOR)

        summary_parts = [f"Detected {len(transitions)} context transition(s):"]

        if explicit > 0:
            summary_parts.append(f"  • {explicit} explicit CALCULATE/CALCULATETABLE")

        if implicit > 0:
            summary_parts.append(f"  • {implicit} implicit measure references")

        if iterators > 0:
            summary_parts.append(f"  • {iterators} iterator functions with measure calls")

        if warnings:
            summary_parts.append(f"\n⚠️ {len(warnings)} performance warning(s) detected")

        return "\n".join(summary_parts)

    def _get_line_column(self, text: str, position: int) -> Tuple[int, int]:
        """Get line and column number from character position"""
        return get_line_column(text, position)

    def detect_dax_anti_patterns(self, dax_expression: str) -> Dict[str, Any]:
        """
        Detect common DAX anti-patterns using pattern matching

        Args:
            dax_expression: DAX expression to analyze

        Returns:
            Dictionary with detected patterns and recommendations
        """
        try:
            from core.research.dax_research import DaxResearchProvider

            # Use curated embedded content (disable online research to avoid formatting issues)
            research_provider = DaxResearchProvider(enable_online_research=False)
            results = research_provider.get_optimization_guidance(
                query=dax_expression,
                performance_data=None,  # No performance data needed for pattern detection
            )

            # Extract pattern-based information
            pattern_matches = results.get("pattern_matches", {})
            articles = results.get("articles", [])

            # Get pattern-based recommendations
            all_recommendations = results.get("recommendations", [])
            pattern_recommendations = all_recommendations

            return {
                "success": True,
                "patterns_detected": len(pattern_matches),
                "pattern_matches": pattern_matches,
                "articles": articles,
                "recommendations": pattern_recommendations,
            }

        except ImportError:
            logger.warning("DaxResearchProvider not available for anti-pattern detection")
            return {"success": False, "error": "Pattern detection not available"}
        except Exception as e:
            logger.error(f"Error detecting anti-patterns: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def detect_summarize_patterns(self, dax_expression: str) -> Dict[str, Any]:
        """
        Detect SUMMARIZE vs SUMMARIZECOLUMNS usage

        Returns suggestions to upgrade to SUMMARIZECOLUMNS for better performance
        """
        summarize_matches = list(_SUMMARIZE_RE.finditer(dax_expression))

        if not summarize_matches:
            return {"has_summarize": False, "recommendation": None}

        return {
            "has_summarize": True,
            "occurrences": len(summarize_matches),
            "severity": "medium",
            "recommendation": (
                f"Found {len(summarize_matches)} SUMMARIZE function(s). "
                "SUMMARIZECOLUMNS is newer and more optimized (2-10x faster). "
                "Consider converting SUMMARIZE to SUMMARIZECOLUMNS for better performance."
            ),
            "example_conversion": """
-- BEFORE (SUMMARIZE):
SUMMARIZE(
    Sales,
    Sales[ProductID],
    "Total", SUM(Sales[Amount])
)

-- AFTER (SUMMARIZECOLUMNS):
SUMMARIZECOLUMNS(
    Sales[ProductID],
    "Total", [Total Sales]
)
""",
        }

    def format_dax_with_annotations(
        self, dax_expression: str, transitions: List[ContextTransition]
    ) -> str:
        """
        Format DAX code with inline visual annotations showing where context transitions occur

        Args:
            dax_expression: Original DAX expression
            transitions: List of detected context transitions

        Returns:
            Formatted DAX code with inline annotations
        """
        if not transitions:
            return dax_expression

        # Split DAX into lines
        lines = dax_expression.split("\n")

        # Group transitions by line number
        transitions_by_line = {}
        for i, transition in enumerate(transitions, 1):
            line_num = transition.line
            if line_num not in transitions_by_line:
                transitions_by_line[line_num] = []

            # Create annotation emoji based on type
            if transition.type == TransitionType.ITERATOR:
                emoji = "🔄"
                type_label = "Iterator"
            elif transition.type == TransitionType.IMPLICIT_MEASURE:
                emoji = "📊"
                type_label = "Measure Ref"
            else:
                emoji = "⚡"
                type_label = "CALCULATE"

            # Create impact indicator
            if transition.performance_impact == PerformanceImpact.HIGH:
                impact = "🔴"
            elif transition.performance_impact == PerformanceImpact.MEDIUM:
                impact = "🟡"
            else:
                impact = "🟢"

            transitions_by_line[line_num].append(
                {
                    "number": i,
                    "emoji": emoji,
                    "type": type_label,
                    "impact": impact,
                    "function": transition.function,
                    "explanation": (
                        transition.explanation[:80] + "..."
                        if len(transition.explanation) > 80
                        else transition.explanation
                    ),
                }
            )

        # Build annotated code
        annotated_lines = []
        for line_num, line_text in enumerate(lines, 1):
            annotated_lines.append(line_text)

            # Add annotations for this line
            if line_num in transitions_by_line:
                for trans_info in transitions_by_line[line_num]:
                    annotation = f"    {trans_info['emoji']} {trans_info['impact']} Transition #{trans_info['number']} ({trans_info['type']}): {trans_info['function']}"
                    annotated_lines.append(annotation)

        return "\n".join(annotated_lines)

    def explain_context_flow(self, dax_expression: str) -> str:
        """
        Generate step-by-step explanation of context flow

        Args:
            dax_expression: DAX expression

        Returns:
            Human-readable explanation
        """
        analysis = self.analyze_context_transitions(dax_expression)

        explanation_parts = [analysis.summary, ""]

        if analysis.transitions:
            explanation_parts.append("Context Flow Details:")
            explanation_parts.append("=" * 50)

            for i, transition in enumerate(analysis.transitions, 1):
                explanation_parts.append(f"\n{i}. Line {transition.line}, Col {transition.column}:")
                explanation_parts.append(f"   Function: {transition.function}")
                explanation_parts.append(f"   Type: {transition.type.value}")
                explanation_parts.append(f"   {transition.explanation}")

                if transition.performance_impact != PerformanceImpact.LOW:
                    explanation_parts.append(
                        f"   ⚠️ Performance Impact: {transition.performance_impact.value.upper()}"
                    )

        if analysis.warnings:
            explanation_parts.append("\nPerformance Warnings:")
            explanation_parts.append("=" * 50)

            for warning in analysis.warnings:
                explanation_parts.append(f"\n⚠️ {warning.message}")
                explanation_parts.append(f"   💡 Suggestion: {warning.suggestion}")

        return "\n".join(explanation_parts)
