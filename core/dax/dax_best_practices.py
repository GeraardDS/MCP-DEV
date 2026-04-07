"""
Comprehensive DAX Best Practices and Analysis Module

This module consolidates all DAX best practices, standardized checks, optimizations,
and anti-pattern detection into a single, reusable component.

Integrates with:
- DAX Intelligence Tool (Tool 03)
- Context analysis
- VertiPaq analysis
- Online research (SQLBI, DAX Patterns, Microsoft Learn)

Features:
- 15+ anti-pattern checks
- Performance optimization suggestions
- Code quality assessments
- Security best practices
- Maintainability guidelines
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class IssueSeverity(Enum):
    """Severity levels for DAX issues"""

    CRITICAL = "critical"  # Major performance or correctness issues
    HIGH = "high"  # Significant performance impact
    MEDIUM = "medium"  # Moderate impact
    LOW = "low"  # Minor improvements
    INFO = "info"  # Informational/best practice


class IssueCategory(Enum):
    """Categories for DAX issues"""

    PERFORMANCE = "performance"
    ANTI_PATTERN = "anti_pattern"
    MAINTAINABILITY = "maintainability"
    BEST_PRACTICE = "best_practice"
    SECURITY = "security"
    CORRECTNESS = "correctness"


@dataclass
class DaxIssue:
    """Represents a single DAX issue or recommendation"""

    title: str
    description: str
    severity: IssueSeverity
    category: IssueCategory
    code_example_before: Optional[str] = None
    code_example_after: Optional[str] = None
    estimated_improvement: Optional[str] = None
    article_reference: Optional[Dict[str, str]] = None
    location: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "category": self.category.value,
            "code_example_before": self.code_example_before,
            "code_example_after": self.code_example_after,
            "estimated_improvement": self.estimated_improvement,
            "article_reference": self.article_reference,
            "location": self.location,
        }


class DaxBestPracticesAnalyzer:
    """
    Comprehensive DAX analyzer with all best practices and checks.

    This is the central module called by DAX Intelligence (Tool 03) for complete analysis.
    """

    def __init__(self):
        """Initialize the analyzer with all check definitions"""
        self.checks = self._initialize_checks()
        self.articles_referenced: Set[str] = set()

    def analyze(
        self,
        dax_expression: str,
        context_analysis: Optional[Dict[str, Any]] = None,
        vertipaq_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run comprehensive DAX analysis with all checks.

        Args:
            dax_expression: DAX code to analyze
            context_analysis: Optional context transition analysis results
            vertipaq_analysis: Optional VertiPaq metrics

        Returns:
            Complete analysis results with issues, recommendations, and referenced articles
        """
        # Try unified analyzer first (new engine)
        try:
            from core.dax.analyzer.unified_analyzer import DaxUnifiedAnalyzer
            from core.dax.analyzer.models import AnalysisContext

            ctx = AnalysisContext(vertipaq_data=vertipaq_analysis)
            result = DaxUnifiedAnalyzer().analyze(dax_expression, ctx)
            return result.to_best_practices_format()
        except Exception as e:
            logger.warning("Unified analyzer fallback: %s", e)

        # Original implementation follows
        issues: List[DaxIssue] = []

        # Run all pattern-based checks
        for check_name, check_func in self.checks.items():
            try:
                check_issues = check_func(dax_expression)
                if check_issues:
                    issues.extend(check_issues)
            except Exception as e:
                logger.warning(f"Check {check_name} failed: {e}")

        # Add context-based issues
        if context_analysis:
            context_issues = self._analyze_context_results(dax_expression, context_analysis)
            issues.extend(context_issues)

        # Add VertiPaq-based issues
        if vertipaq_analysis and vertipaq_analysis.get("success"):
            vertipaq_issues = self._analyze_vertipaq_results(dax_expression, vertipaq_analysis)
            issues.extend(vertipaq_issues)

        # Sort by severity (critical first)
        severity_order = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.HIGH: 1,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 3,
            IssueSeverity.INFO: 4,
        }
        issues.sort(key=lambda x: severity_order[x.severity])

        # Calculate metrics
        critical_count = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
        high_count = sum(1 for i in issues if i.severity == IssueSeverity.HIGH)
        medium_count = sum(1 for i in issues if i.severity == IssueSeverity.MEDIUM)

        # Generate summary
        summary = self._generate_summary(issues, dax_expression)

        # Get referenced articles
        articles = self._get_referenced_articles()

        return {
            "success": True,
            "total_issues": len(issues),
            "critical_issues": critical_count,
            "high_issues": high_count,
            "medium_issues": medium_count,
            "issues": [issue.to_dict() for issue in issues],
            "summary": summary,
            "articles_referenced": articles,
            "overall_score": self._calculate_score(issues),
            "complexity_level": self._assess_complexity(dax_expression, context_analysis),
        }

    def _initialize_checks(self) -> Dict[str, callable]:
        """Initialize all check functions"""
        return {
            "sumx_filter": self._check_sumx_filter,
            "countrows_filter": self._check_countrows_filter,
            "filter_all": self._check_filter_all,
            "nested_calculate": self._check_nested_calculate,
            "related_in_iterator": self._check_related_in_iterator,
            "divide_optimization": self._check_divide_optimization,
            "values_in_calculate": self._check_values_in_calculate,
            "measure_in_filter": self._check_measure_in_filter,
            "unnecessary_iterators": self._check_unnecessary_iterators,
            "multiple_measure_refs": self._check_multiple_measure_refs,
            "variable_usage": self._check_variable_usage,
            "error_handling": self._check_error_handling,
            "naming_conventions": self._check_naming_conventions,
            "blank_vs_zero": self._check_blank_vs_zero,
            "calculate_filter_boolean": self._check_calculate_filter_boolean,
            "iferror_iserror": self._check_iferror_iserror,
            "addcolumns_in_measure": self._check_addcolumns,
            "if_iterator": self._check_if_in_iterator,
            "filter_bare_table": self._check_filter_bare_table,
            "selectedvalue_over_hasonevalue": self._check_selectedvalue_over_hasonevalue,
            "keepfilters_opportunity": self._check_keepfilters_opportunity,
            "var_defeating_shortcircuit": self._check_var_defeating_shortcircuit,
            "count_vs_countrows": self._check_count_vs_countrows,
            "all_table_vs_column": self._check_all_table_vs_column,
            "addcolumns_summarize": self._check_addcolumns_summarize,
            "divide_in_iterator": self._check_divide_in_iterator,
            "summarize_inline_expressions": self._check_summarize_inline_expressions,
            "if_switch_fusion_break": self._check_if_switch_fusion_break,
        }

    # =============================================================================
    # PERFORMANCE ANTI-PATTERNS
    # =============================================================================

    def _check_sumx_filter(self, dax: str) -> List[DaxIssue]:
        """Check for SUMX(FILTER(...)) anti-pattern"""
        issues = []
        pattern = r"(SUMX|AVERAGEX|MINX|MAXX)\s*\(\s*FILTER\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_sumx_filter")
            issues.append(
                DaxIssue(
                    title="SUMX(FILTER()) Anti-Pattern Detected",
                    description=(
                        "Using SUMX(FILTER(...)) forces row-by-row evaluation in the Formula Engine, "
                        "preventing query fusion and parallelization. This can be 5-10x slower than "
                        "using CALCULATE."
                    ),
                    severity=IssueSeverity.CRITICAL,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before=f"{match.group(1)}(FILTER(Table, condition), Table[Column])",
                    code_example_after=f"CALCULATE({match.group(1).replace('X', '')}(Table[Column]), condition)",
                    estimated_improvement="5-10x faster",
                    article_reference={
                        "title": "Avoid FILTER as filter argument (Microsoft Learn)",
                        "url": "https://learn.microsoft.com/en-us/power-bi/guidance/dax-avoid-avoid-filter-as-filter-argument",
                        "source": "Microsoft Learn",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_countrows_filter(self, dax: str) -> List[DaxIssue]:
        """Check for COUNTROWS(FILTER(...)) anti-pattern"""
        issues = []
        pattern = r"COUNTROWS\s*\(\s*FILTER\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_countrows_filter")
            issues.append(
                DaxIssue(
                    title="COUNTROWS(FILTER()) Anti-Pattern",
                    description=(
                        "COUNTROWS(FILTER(...)) prevents xVelocity compression and parallelization. "
                        "Replace with CALCULATE for significant performance gains."
                    ),
                    severity=IssueSeverity.CRITICAL,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before="COUNTROWS(FILTER(Table, Table[Column] > 100))",
                    code_example_after="CALCULATE(COUNTROWS(Table), Table[Column] > 100)",
                    estimated_improvement="5-10x faster",
                    article_reference={
                        "title": "COUNTROWS Best Practices (Microsoft Learn)",
                        "url": "https://learn.microsoft.com/en-us/dax/best-practices/dax-countrows",
                        "source": "Microsoft Learn",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_filter_all(self, dax: str) -> List[DaxIssue]:
        """Check for FILTER(ALL(...)) anti-pattern"""
        issues = []
        pattern = r"FILTER\s*\(\s*(ALL|ALLSELECTED)\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_filter_all")
            issues.append(
                DaxIssue(
                    title="FILTER(ALL()) Forces Formula Engine Evaluation",
                    description=(
                        "FILTER(ALL(...)) cannot be pushed to the Storage Engine and materializes "
                        "the entire table in memory. Use CALCULATE with filter arguments instead."
                    ),
                    severity=IssueSeverity.HIGH,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before=f"FILTER({match.group(1)}(Table), condition)",
                    code_example_after="CALCULATE(VALUES(Table), condition)",
                    estimated_improvement="3-5x faster",
                    article_reference={
                        "title": "Dynamic Segmentation Pattern (DAX Patterns)",
                        "url": "https://www.daxpatterns.com/dynamic-segmentation/",
                        "source": "DAX Patterns",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_nested_calculate(self, dax: str) -> List[DaxIssue]:
        """Check for nested CALCULATE functions"""
        issues = []
        pattern = r"CALCULATE\s*\([^)]*CALCULATE\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_context_transition")
            issues.append(
                DaxIssue(
                    title="Nested CALCULATE Detected",
                    description=(
                        "Nested CALCULATE functions cause multiple context transitions, "
                        "adding overhead and potentially causing unexpected results. "
                        "Consolidate filters into a single CALCULATE."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before="CALCULATE(CALCULATE([Measure], Filter1), Filter2)",
                    code_example_after="CALCULATE([Measure], Filter1, Filter2)",
                    estimated_improvement="2-3x faster",
                    article_reference={
                        "title": "Understanding Context Transition",
                        "url": "https://www.sqlbi.com/articles/understanding-context-transition/",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_related_in_iterator(self, dax: str) -> List[DaxIssue]:
        """Check for RELATED in iterator functions"""
        issues = []
        pattern = r"(SUMX|AVERAGEX|COUNTX|FILTER)\s*\([^)]*RELATED\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_related_iterators")
            issues.append(
                DaxIssue(
                    title="RELATED in Iterator Function",
                    description=(
                        "Using RELATED inside iterators causes row-by-row relationship traversal. "
                        "Consider denormalizing data or using table expansion before iteration."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before="SUMX(Sales, Sales[Qty] * RELATED(Product[Price]))",
                    code_example_after="-- Denormalize: Add Price column to Sales table\nSUM(Sales, Sales[Qty] * Sales[Price])",
                    estimated_improvement="2-4x faster for large tables",
                    article_reference={
                        "title": "Avoiding RELATED in Iterators",
                        "url": "https://www.sqlbi.com/articles/avoiding-related-in-iterators/",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_divide_optimization(self, dax: str) -> List[DaxIssue]:
        """Check for manual division with zero checks instead of DIVIDE"""
        issues = []
        # Pattern: IF(denominator = 0, alternate, numerator / denominator)
        pattern = r"IF\s*\([^=]+\s*=\s*0\s*,\s*[^,]+\s*,\s*[^/]+\s*/\s*[^)]+\)"

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_divide")
            issues.append(
                DaxIssue(
                    title="Manual Division with Zero Check",
                    description=(
                        "Manual IF checks for division by zero are less efficient than the DIVIDE function, "
                        "which is optimized by the Storage Engine."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before="IF([Denominator] = 0, 0, [Numerator] / [Denominator])",
                    code_example_after="DIVIDE([Numerator], [Denominator], 0)",
                    estimated_improvement="2-3x faster",
                    article_reference={
                        "title": "DIVIDE Function Reference (DAX.Guide)",
                        "url": "https://dax.guide/divide/",
                        "source": "DAX.Guide",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_values_in_calculate(self, dax: str) -> List[DaxIssue]:
        """Check for VALUES in CALCULATE filter arguments"""
        issues = []
        pattern = r"CALCULATE\s*\([^)]*,\s*VALUES\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_values_optimize")
            issues.append(
                DaxIssue(
                    title="VALUES in CALCULATE Filter",
                    description=(
                        "Using VALUES in CALCULATE filter arguments may cause unnecessary context transitions. "
                        "Consider using direct column references instead."
                    ),
                    severity=IssueSeverity.LOW,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before="CALCULATE([Sales], VALUES(Product[Category]))",
                    code_example_after="CALCULATE([Sales], Product[Category])",
                    estimated_improvement="Minor performance gain",
                    article_reference={
                        "title": "Optimizing VALUES Performance",
                        "url": "https://www.sqlbi.com/articles/optimizing-values-performance/",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_measure_in_filter(self, dax: str) -> List[DaxIssue]:
        """Check for measures in FILTER predicates"""
        issues = []
        # Pattern: FILTER with measure reference (using [] notation)
        pattern = r"FILTER\s*\([^)]*,\s*\[[^\]]+\]\s*[><!=]"

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_measure_filter")
            issues.append(
                DaxIssue(
                    title="Measure in FILTER Predicate",
                    description=(
                        "Using measures in FILTER predicates causes row-by-row context transitions, "
                        "blocking Storage Engine optimization. Pre-calculate the measure or use column references."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before="FILTER(Products, [Total Sales] > 1000)",
                    code_example_after="VAR Threshold = 1000\nRETURN FILTER(Products, Products[Sales] > Threshold)",
                    estimated_improvement="3-5x faster",
                    article_reference={
                        "title": "Static Segmentation Pattern (DAX Patterns)",
                        "url": "https://www.daxpatterns.com/static-segmentation/",
                        "source": "DAX Patterns",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_unnecessary_iterators(self, dax: str) -> List[DaxIssue]:
        """Check for iterator functions that could be simple aggregations"""
        issues = []
        # Pattern: SUMX(Table, Table[Column]) - direct column reference without calculation
        pattern = r"(SUMX|AVERAGEX)\s*\(([^,]+),\s*\2\[([^\]]+)\]\s*\)"

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            issues.append(
                DaxIssue(
                    title="Unnecessary Iterator Function",
                    description=(
                        "Using an iterator function for simple column aggregation adds overhead. "
                        "Direct aggregation functions are faster."
                    ),
                    severity=IssueSeverity.LOW,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before=f"{match.group(1)}({match.group(2)}, {match.group(2)}[{match.group(3)}])",
                    code_example_after=f"{match.group(1).replace('X', '')}({match.group(2)}[{match.group(3)}])",
                    estimated_improvement="Minor performance gain",
                    location=f"Position {match.start()}",
                )
            )

        return issues

    # =============================================================================
    # MAINTAINABILITY AND BEST PRACTICES
    # =============================================================================

    def _check_multiple_measure_refs(self, dax: str) -> List[DaxIssue]:
        """Check for multiple measure references without variables"""
        issues = []
        # Count measure references (words in brackets)
        measure_refs = re.findall(r"\[[^\]]+\]", dax)

        # Check if same measure is referenced multiple times
        measure_counts = {}
        for ref in measure_refs:
            measure_counts[ref] = measure_counts.get(ref, 0) + 1

        repeated_measures = [m for m, count in measure_counts.items() if count > 2]

        if repeated_measures and "VAR" not in dax.upper():
            self.articles_referenced.add("sqlbi_variables")
            issues.append(
                DaxIssue(
                    title="Repeated Measure References Without Variables",
                    description=(
                        f"The following measures are referenced multiple times: {', '.join(repeated_measures)}. "
                        "Use variables to cache results and avoid repeated calculations."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.MAINTAINABILITY,
                    code_example_before=f"{repeated_measures[0]} + {repeated_measures[0]} + {repeated_measures[0]}",
                    code_example_after=f"VAR Result = {repeated_measures[0]}\nRETURN Result + Result + Result",
                    estimated_improvement="Reduces calculation overhead",
                )
            )

        return issues

    def _check_variable_usage(self, dax: str) -> List[DaxIssue]:
        """Check for proper variable usage"""
        issues = []

        # Check if VAR is used
        has_vars = "VAR" in dax.upper()
        has_return = "RETURN" in dax.upper()

        # Complex expression without variables (heuristic: length > 200 and multiple operations)
        if len(dax) > 200 and not has_vars:
            operation_count = dax.count("+") + dax.count("-") + dax.count("*") + dax.count("/")
            if operation_count > 3:
                self.articles_referenced.add("sqlbi_variables")
                issues.append(
                    DaxIssue(
                        title="Complex Expression Without Variables",
                        description=(
                            "This is a complex expression without variables. "
                            "Variables improve readability, maintainability, and can reduce calculation overhead."
                        ),
                        severity=IssueSeverity.INFO,
                        category=IssueCategory.MAINTAINABILITY,
                        code_example_after="VAR Step1 = [First Calculation]\nVAR Step2 = [Second Calculation]\nRETURN Step1 + Step2",
                        estimated_improvement="Better maintainability",
                    )
                )

        # VAR without RETURN
        if has_vars and not has_return:
            issues.append(
                DaxIssue(
                    title="VAR Without RETURN",
                    description="Variables are declared but RETURN is missing. This will cause a syntax error.",
                    severity=IssueSeverity.CRITICAL,
                    category=IssueCategory.CORRECTNESS,
                )
            )

        return issues

    def _check_error_handling(self, dax: str) -> List[DaxIssue]:
        """Check for proper error handling"""
        issues = []

        # Check for IFERROR usage (good practice)
        has_iferror = "IFERROR" in dax.upper()
        has_division = "/" in dax
        has_divide = "DIVIDE" in dax.upper()

        # Division without DIVIDE or IFERROR
        if has_division and not (has_divide or has_iferror):
            issues.append(
                DaxIssue(
                    title="Division Without Error Handling",
                    description=(
                        "Division operator (/) without error handling can cause errors. "
                        "Use DIVIDE function or wrap in IFERROR."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.BEST_PRACTICE,
                    code_example_after="DIVIDE([Numerator], [Denominator], 0) -- or IFERROR([Numerator]/[Denominator], 0)",
                )
            )

        return issues

    def _check_naming_conventions(self, dax: str) -> List[DaxIssue]:
        """Check for naming convention best practices"""
        issues = []

        # Check for single-letter variable names (V1, V2, etc.)
        pattern = r"\bVAR\s+([A-Z]|V\d+)\s*="
        matches = list(re.finditer(pattern, dax))

        if matches:
            issues.append(
                DaxIssue(
                    title="Non-Descriptive Variable Names",
                    description=(
                        f"Found {len(matches)} variables with non-descriptive names (V1, V2, A, B, etc.). "
                        "Use descriptive names to improve code readability."
                    ),
                    severity=IssueSeverity.INFO,
                    category=IssueCategory.MAINTAINABILITY,
                    code_example_before="VAR V1 = SUM(Sales[Amount])\nVAR V2 = SUM(Sales[Quantity])",
                    code_example_after="VAR TotalAmount = SUM(Sales[Amount])\nVAR TotalQuantity = SUM(Sales[Quantity])",
                )
            )

        return issues

    def _check_blank_vs_zero(self, dax: str) -> List[DaxIssue]:
        """Check for proper handling of BLANK vs 0"""
        issues = []

        # Check for = 0 comparisons (should consider using ISBLANK)
        if "= 0" in dax or "=0" in dax:
            issues.append(
                DaxIssue(
                    title="Consider BLANK vs Zero Distinction",
                    description=(
                        "Comparing to zero without checking for BLANK. "
                        "In DAX, BLANK and 0 are different. Consider if ISBLANK is more appropriate."
                    ),
                    severity=IssueSeverity.INFO,
                    category=IssueCategory.BEST_PRACTICE,
                    code_example_after="IF(ISBLANK([Value]), ..., IF([Value] = 0, ..., ...))",
                )
            )

        return issues

    def _check_calculate_filter_boolean(self, dax: str) -> List[DaxIssue]:
        """Check for boolean expressions vs FILTER in CALCULATE"""
        issues = []

        # Check if CALCULATE uses FILTER with simple conditions
        pattern = r"CALCULATE\s*\([^)]*,\s*FILTER\s*\([^,]+,\s*[^,]+\s*[<>=!]+\s*[^)]+\)"

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("microsoft_dax_optimization")
            issues.append(
                DaxIssue(
                    title="FILTER with Simple Boolean in CALCULATE",
                    description=(
                        "Using FILTER for simple boolean conditions in CALCULATE is less efficient. "
                        "Use boolean expressions directly as filter arguments."
                    ),
                    severity=IssueSeverity.LOW,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before='CALCULATE([Sales], FILTER(Product, Product[Category] = "Electronics"))',
                    code_example_after='CALCULATE([Sales], Product[Category] = "Electronics")',
                    estimated_improvement="Minor performance gain",
                    article_reference={
                        "title": "DAX: Avoid FILTER as filter argument",
                        "url": "https://learn.microsoft.com/en-us/power-bi/guidance/dax-avoid-avoid-filter-as-filter-argument",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_iferror_iserror(self, dax: str) -> List[DaxIssue]:
        """Check for IFERROR/ISERROR usage"""
        issues = []
        pattern = r"\b(IFERROR|ISERROR)\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("iferror_iserror")
            issues.append(
                DaxIssue(
                    title="Avoid IFERROR/ISERROR Functions",
                    description=(
                        f"{match.group(1)} forces Power BI to enter step-by-step execution for each row, "
                        "significantly impacting performance. Use IF with logical tests or built-in error handling instead."
                    ),
                    severity=IssueSeverity.HIGH,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before=f"{match.group(1)}([Value]/[Divisor], 0)",
                    code_example_after="DIVIDE([Value], [Divisor], 0)  -- or use IF with logical test",
                    estimated_improvement="Avoids step-by-step execution overhead",
                    article_reference={
                        "title": "Appropriate use of error functions in DAX",
                        "url": "https://learn.microsoft.com/en-us/dax/best-practices/dax-error-functions",
                        "source": "Microsoft Learn",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_addcolumns(self, dax: str) -> List[DaxIssue]:
        """Check for ADDCOLUMNS in measure expressions"""
        issues = []
        pattern = r"\bADDCOLUMNS\s*\("

        matches = list(re.finditer(pattern, dax, re.IGNORECASE))
        if matches:
            self.articles_referenced.add("addcolumns_in_measure")
            issues.append(
                DaxIssue(
                    title="ADDCOLUMNS in Measure Creates Nested Iterations",
                    description=(
                        "Using ADDCOLUMNS inside measures creates nested iterations because measures "
                        "are calculated iteratively by default. This negatively affects report performance."
                    ),
                    severity=IssueSeverity.HIGH,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before='ADDCOLUMNS(Table, "NewCol", [Measure])',
                    code_example_after="-- Use variables or separate measures instead\nVAR Result = [Measure]\nRETURN Result",
                    estimated_improvement="Eliminates nested iteration overhead",
                    location=f"Found {len(matches)} occurrence{'s' if len(matches) > 1 else ''}",
                )
            )

        return issues

    def _check_if_in_iterator(self, dax: str) -> List[DaxIssue]:
        """Check for IF conditions inside iterator functions"""
        issues = []
        pattern = r"(SUMX|AVERAGEX|COUNTX|MINX|MAXX)\s*\([^,]+,\s*IF\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            issues.append(
                DaxIssue(
                    title="IF Condition Inside Iterator Function",
                    description=(
                        "IF conditions in iterators are expensive. When the condition only references "
                        "columns of the iterated table, move the filter to CALCULATE instead."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before=f"{match.group(1)}(Table, IF(condition, calculation, 0))",
                    code_example_after=f"CALCULATE({match.group(1).replace('X', '')}(Table[Column]), KEEPFILTERS(condition))",
                    estimated_improvement="Reduces iteration overhead",
                    article_reference={
                        "title": "SUMX with IF predicate optimization",
                        "url": "https://kb.daxoptimizer.com/d/101600",
                        "source": "DAX Optimizer",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    # =============================================================================
    # EXTENDED PERFORMANCE CHECKS (v10)
    # =============================================================================

    def _check_filter_bare_table(self, dax: str) -> List[DaxIssue]:
        """Check for FILTER(BareTable, ...) — 117x performance difference."""
        issues = []
        pattern = (
            r"FILTER\s*\(\s*"
            r"(?!ALL\b|VALUES\b|DISTINCT\b|ALLSELECTED\b|KEEPFILTERS\b|"
            r"CALCULATETABLE\b|TOPN\b|SUMMARIZE\b|ADDCOLUMNS\b|SELECTCOLUMNS\b|"
            r"GENERATE\b|UNION\b|INTERSECT\b|EXCEPT\b|FILTER\b|DATATABLE\b|"
            r"GENERATESERIES\b)"
            r"(?:'[^']+'\s*,|[A-Za-z_]\w*\s*,)"
        )

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_filter_columns")
            issues.append(
                DaxIssue(
                    title="FILTER on Bare Table Reference (Critical Performance Impact)",
                    description=(
                        "FILTER(Table, condition) iterates the entire expanded table including all "
                        "related tables via relationships. This can be 10-117x slower than using a "
                        "Boolean filter expression directly in CALCULATE."
                    ),
                    severity=IssueSeverity.CRITICAL,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before="CALCULATE([Sales], FILTER(Sales, Sales[Amount] > 100))",
                    code_example_after="CALCULATE([Sales], Sales[Amount] > 100)",
                    estimated_improvement="10-100x faster (filters expanded table including all related tables)",
                    article_reference={
                        "title": "Filter columns, not tables in DAX (SQLBI)",
                        "url": "https://www.sqlbi.com/articles/filter-columns-not-tables-in-dax/",
                        "source": "SQLBI",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_selectedvalue_over_hasonevalue(self, dax: str) -> List[DaxIssue]:
        """Check for IF(HASONEVALUE(...), VALUES(...)) pattern."""
        issues = []
        pattern = r"IF\s*\(\s*HASONEVALUE\s*\([^)]+\)\s*,\s*VALUES\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("ms_selectedvalue")
            issues.append(
                DaxIssue(
                    title="Use SELECTEDVALUE Instead of IF(HASONEVALUE(), VALUES())",
                    description=(
                        "The IF(HASONEVALUE(Col), VALUES(Col)) pattern can be simplified to "
                        "SELECTEDVALUE(Col), which is more readable and slightly more efficient."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.BEST_PRACTICE,
                    code_example_before="IF(HASONEVALUE(Table[Col]), VALUES(Table[Col]))",
                    code_example_after="SELECTEDVALUE(Table[Col])",
                    article_reference={
                        "title": "Use SELECTEDVALUE instead of VALUES (Microsoft Learn)",
                        "url": "https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue",
                        "source": "Microsoft Learn",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_keepfilters_opportunity(self, dax: str) -> List[DaxIssue]:
        """Check for FILTER(VALUES(...), ...) that could use KEEPFILTERS."""
        issues = []
        pattern = r"FILTER\s*\(\s*VALUES\s*\(\s*[^)]+\)\s*,"

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_keepfilters")
            issues.append(
                DaxIssue(
                    title="FILTER(VALUES()) Can Be Replaced with KEEPFILTERS",
                    description=(
                        "FILTER(VALUES(Col), predicate) iterates all visible values. "
                        "KEEPFILTERS(predicate) achieves the same result more efficiently by "
                        "intersecting with the existing filter context."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before='CALCULATE([M], FILTER(VALUES(Table[Col]), Table[Col] = "X"))',
                    code_example_after='CALCULATE([M], KEEPFILTERS(Table[Col] = "X"))',
                    article_reference={
                        "title": "Using KEEPFILTERS in DAX (SQLBI)",
                        "url": "https://www.sqlbi.com/articles/using-keepfilters-in-dax/",
                        "source": "SQLBI",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_var_defeating_shortcircuit(self, dax: str) -> List[DaxIssue]:
        """Check for VARs with expensive operations before IF/SWITCH."""
        issues = []
        # Look for VAR ... = CALCULATE/SUMX/... followed by IF or SWITCH
        expensive_ops = r"(CALCULATE|SUMX|AVERAGEX|COUNTX|MAXX|MINX)"
        var_pattern = re.compile(
            rf"\bVAR\s+\w+\s*=\s*{expensive_ops}\s*\(",
            re.IGNORECASE,
        )

        var_matches = list(var_pattern.finditer(dax))
        if len(var_matches) >= 2:
            # Check if IF or SWITCH follows the VAR block
            if_switch = re.search(r"\b(IF|SWITCH)\s*\(", dax, re.IGNORECASE)
            if if_switch and if_switch.start() > var_matches[-1].start():
                self.articles_referenced.add("sqlbi_var_shortcircuit")
                issues.append(
                    DaxIssue(
                        title="VARs May Defeat Short-Circuit Evaluation",
                        description=(
                            "Multiple VAR definitions with expensive operations (CALCULATE, SUMX, etc.) "
                            "before IF/SWITCH forces eager evaluation of all branches. If only one branch "
                            "is used, ~50% of computation is wasted."
                        ),
                        severity=IssueSeverity.HIGH,
                        category=IssueCategory.PERFORMANCE,
                        code_example_before=(
                            "VAR _sales = CALCULATE([Sales], ...)\n"
                            "VAR _salesLY = CALCULATE([Sales LY], ...)\n"
                            "RETURN IF(condition, _sales, _salesLY)"
                        ),
                        code_example_after=(
                            "IF(condition,\n"
                            "    CALCULATE([Sales], ...),\n"
                            "    CALCULATE([Sales LY], ...)\n"
                            ")"
                        ),
                        estimated_improvement="50% faster when one branch is unused",
                        article_reference={
                            "title": "Optimizing IF and SWITCH using variables (SQLBI)",
                            "url": "https://www.sqlbi.com/articles/optimizing-if-and-switch-expressions-using-variables/",
                            "source": "SQLBI",
                        },
                        location=f"Found {len(var_matches)} expensive VARs before IF/SWITCH",
                    )
                )

        return issues

    def _check_count_vs_countrows(self, dax: str) -> List[DaxIssue]:
        """Check for COUNT(Column) that should be COUNTROWS(Table)."""
        issues = []
        pattern = r"\bCOUNT\s*\(\s*[^)]*\["

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            # Exclude COUNTROWS, COUNTA, COUNTAX, COUNTBLANK, COUNTX
            prefix = dax[max(0, match.start() - 5) : match.start()]
            if re.search(r"(ROWS|A|AX|BLANK|X)\s*$", prefix, re.IGNORECASE):
                continue
            issues.append(
                DaxIssue(
                    title="COUNT(Column) Can Be Simplified to COUNTROWS",
                    description=(
                        "COUNT(Table[Column]) counts non-blank values in a column. "
                        "If you're counting rows, COUNTROWS(Table) is clearer and marginally faster."
                    ),
                    severity=IssueSeverity.LOW,
                    category=IssueCategory.BEST_PRACTICE,
                    code_example_before="COUNT(Sales[OrderID])",
                    code_example_after="COUNTROWS(Sales)",
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_all_table_vs_column(self, dax: str) -> List[DaxIssue]:
        """Check for ALL(Table) that should specify columns."""
        issues = []
        pattern = r"\bALL\s*\(\s*(?:\'[^\']+\'|[A-Za-z_]\w*)\s*\)"

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            # Only flag if the expression also references specific columns from that table
            table_match = re.search(
                r"ALL\s*\(\s*(?:'([^']+)'|([A-Za-z_]\w*))\s*\)", match.group(), re.IGNORECASE
            )
            if table_match:
                table_name = table_match.group(1) or table_match.group(2)
                # Check if any column from this table is referenced in the expression
                col_ref = re.search(
                    rf"(?:'{re.escape(table_name)}'|{re.escape(table_name)})\s*\[\w+\]",
                    dax,
                    re.IGNORECASE,
                )
                if col_ref:
                    issues.append(
                        DaxIssue(
                            title="ALL(Table) Removes All Filters — Consider ALL(Table[Col])",
                            description=(
                                f"ALL({table_name}) removes filters from ALL columns in the table. "
                                "If you only need to remove specific column filters, use "
                                "ALL(Table[Col1], Table[Col2]) to preserve other filter context."
                            ),
                            severity=IssueSeverity.MEDIUM,
                            category=IssueCategory.PERFORMANCE,
                            code_example_before=f"CALCULATE([M], ALL({table_name}))",
                            code_example_after=f"CALCULATE([M], ALL({table_name}[Region], {table_name}[Category]))",
                            location=f"Position {match.start()}",
                        )
                    )

        return issues

    def _check_addcolumns_summarize(self, dax: str) -> List[DaxIssue]:
        """Check for ADDCOLUMNS(SUMMARIZE(...)) that should use SUMMARIZECOLUMNS."""
        issues = []
        pattern = r"\bADDCOLUMNS\s*\(\s*SUMMARIZE\s*\("

        for match in re.finditer(pattern, dax, re.IGNORECASE):
            self.articles_referenced.add("sqlbi_summarizecolumns")
            issues.append(
                DaxIssue(
                    title="ADDCOLUMNS(SUMMARIZE()) Should Use SUMMARIZECOLUMNS",
                    description=(
                        "ADDCOLUMNS(SUMMARIZE(Table, Cols), ...) can be replaced with "
                        "SUMMARIZECOLUMNS(Cols, ...) which produces optimal query plans "
                        "and is significantly faster."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.PERFORMANCE,
                    code_example_before='ADDCOLUMNS(SUMMARIZE(Sales, Sales[Product]), "Total", [Total Sales])',
                    code_example_after='SUMMARIZECOLUMNS(Sales[Product], "Total", [Total Sales])',
                    estimated_improvement="2-5x faster — SUMMARIZECOLUMNS produces optimal query plans",
                    article_reference={
                        "title": "Introducing SUMMARIZECOLUMNS (SQLBI)",
                        "url": "https://www.sqlbi.com/articles/introducing-summarizecolumns/",
                        "source": "SQLBI",
                    },
                    location=f"Position {match.start()}",
                )
            )

        return issues

    def _check_divide_in_iterator(self, dax: str) -> List[DaxIssue]:
        """Check for DIVIDE() inside iterator body."""
        issues = []
        iterator_pattern = r"\b(SUMX|AVERAGEX|COUNTX|MAXX|MINX)\s*\("

        for match in re.finditer(iterator_pattern, dax, re.IGNORECASE):
            # Get the full body after the iterator opening
            rest = dax[match.end() :]
            # Simple check: look for DIVIDE in the next ~500 chars (within the iterator)
            if re.search(r"\bDIVIDE\s*\(", rest[:500], re.IGNORECASE):
                self.articles_referenced.add("sqlbi_divide_performance")
                issues.append(
                    DaxIssue(
                        title="DIVIDE() in Iterator Creates CallbackDataID",
                        description=(
                            "DIVIDE() inside an iterator always creates CallbackDataID in SE queries "
                            "because the division-by-zero check requires FE row-by-row evaluation. "
                            "The / operator can execute entirely in SE when zero denominators are pre-filtered."
                        ),
                        severity=IssueSeverity.HIGH,
                        category=IssueCategory.PERFORMANCE,
                        code_example_before="SUMX(Sales, DIVIDE(Sales[Revenue], Sales[Cost]))",
                        code_example_after="CALCULATE(SUMX(Sales, Sales[Revenue] / Sales[Cost]), Sales[Cost] <> 0)",
                        estimated_improvement="DIVIDE always creates CallbackDataID. / operator can execute in SE.",
                        article_reference={
                            "title": "DIVIDE performance (SQLBI)",
                            "url": "https://www.sqlbi.com/articles/divide-performance/",
                            "source": "SQLBI",
                        },
                        location=f"Position {match.start()}",
                    )
                )

        return issues

    def _check_summarize_inline_expressions(self, dax: str) -> List[DaxIssue]:
        """Check for SUMMARIZE with inline expressions (deprecated, can produce wrong results).

        SUMMARIZE(Table, Col, "Name", <expr>) with inline expressions is deprecated.
        Only SUMMARIZE(Table, Col1, Col2, ...) for grouping is safe.
        Skip if preceded by ADDCOLUMNS( (already covered by addcolumns_summarize check).
        """
        issues = []
        # Match SUMMARIZE( ... , "StringLiteral" , ... ) indicating inline expressions
        # Look for SUMMARIZE followed by args that include a quoted string (name for column)
        pattern = r"\bSUMMARIZE\s*\("
        for match in re.finditer(pattern, dax, re.IGNORECASE):
            # Check if preceded by ADDCOLUMNS( — if so, skip (covered elsewhere)
            prefix = dax[max(0, match.start() - 30) : match.start()].strip()
            if re.search(r"\bADDCOLUMNS\s*\(\s*$", prefix, re.IGNORECASE):
                continue

            # Look for string literal args after the SUMMARIZE( opening
            rest = dax[match.end() :]
            # Check first ~500 chars for a pattern like: , "Name", <expr>
            snippet = rest[:500]
            if re.search(r',\s*"[^"]+"\s*,', snippet):
                self.articles_referenced.add("sqlbi_summarizecolumns")
                issues.append(
                    DaxIssue(
                        title="SUMMARIZE with Inline Expressions (Deprecated)",
                        description=(
                            'SUMMARIZE(Table, GroupCol, "Name", <expr>) with inline '
                            "expressions is deprecated and can produce incorrect results. "
                            'Use ADDCOLUMNS(SUMMARIZE(Table, GroupCol), "Name", <expr>) '
                            'or SUMMARIZECOLUMNS(GroupCol, "Name", <expr>) instead.'
                        ),
                        severity=IssueSeverity.HIGH,
                        category=IssueCategory.CORRECTNESS,
                        code_example_before=(
                            'SUMMARIZE(Sales, Sales[Product], "Total", SUM(Sales[Amount]))'
                        ),
                        code_example_after=(
                            "ADDCOLUMNS(\n"
                            "    SUMMARIZE(Sales, Sales[Product]),\n"
                            '    "Total", SUM(Sales[Amount])\n'
                            ")"
                        ),
                        estimated_improvement=(
                            "Correctness fix — inline SUMMARIZE expressions can silently "
                            "return wrong results"
                        ),
                        article_reference={
                            "title": "Introducing SUMMARIZECOLUMNS (SQLBI)",
                            "url": "https://www.sqlbi.com/articles/introducing-summarizecolumns/",
                            "source": "SQLBI",
                        },
                        location=f"Position {match.start()}",
                    )
                )

        return issues

    def _check_if_switch_fusion_break(self, dax: str) -> List[DaxIssue]:
        """Check for IF/SWITCH branches that break vertical fusion.

        IF/SWITCH returning different measures in branches breaks vertical fusion,
        potentially causing billions of FE combinations. Time intelligence functions
        in branches also break fusion.
        """
        issues = []
        # Measure reference pattern: [MeasureName] not preceded by table name
        _MEASURE_REF_RE = re.compile(r"(?<!\w\[)\[([^\]]+)\]")
        # Time intelligence functions that break fusion
        _TIME_INTEL_RE = re.compile(
            r"\b(DATESYTD|DATEADD|TOTALYTD|TOTALQTD|TOTALMTD|"
            r"SAMEPERIODLASTYEAR|DATESBETWEEN|DATESINPERIOD|"
            r"PARALLELPERIOD|PREVIOUSMONTH|PREVIOUSQUARTER|PREVIOUSYEAR|"
            r"NEXTMONTH|NEXTQUARTER|NEXTYEAR)\s*\(",
            re.IGNORECASE,
        )

        # Check IF branches
        if_pattern = r"\bIF\s*\("
        for match in re.finditer(if_pattern, dax, re.IGNORECASE):
            body = dax[match.end() : match.end() + 1000]

            # Check for time intelligence in IF body
            ti_funcs = set(m.group(1).upper() for m in _TIME_INTEL_RE.finditer(body))
            if ti_funcs:
                self.articles_referenced.add("sqlbi_fusion_optimization")
                issues.append(
                    DaxIssue(
                        title="IF with Time Intelligence Breaks Vertical Fusion",
                        description=(
                            f"IF branch contains time intelligence functions "
                            f"({', '.join(sorted(ti_funcs))}). This breaks vertical "
                            f"fusion and forces the FE to evaluate each combination "
                            f"separately, potentially causing exponential query explosion. "
                            f"Pre-compute both branches with VAR to enable fusion."
                        ),
                        severity=IssueSeverity.HIGH,
                        category=IssueCategory.PERFORMANCE,
                        code_example_before="IF([ShowYTD], TOTALYTD([Sales], D[Date]), [Sales])",
                        code_example_after=(
                            "VAR _ytd = TOTALYTD([Sales], D[Date])\n"
                            "VAR _current = [Sales]\n"
                            "RETURN IF([ShowYTD], _ytd, _current)"
                        ),
                        estimated_improvement=(
                            "Can reduce SE queries from thousands to dozens by enabling "
                            "vertical fusion"
                        ),
                        article_reference={
                            "title": "Optimizing fusion for DAX measures (SQLBI)",
                            "url": "https://www.sqlbi.com/articles/optimizing-fusion-for-dax-measures/",
                            "source": "SQLBI",
                        },
                        location=f"Position {match.start()}",
                    )
                )
                continue

            # Check for 2+ different measure references (not simple IF(cond, 1, 0))
            measures = set(_MEASURE_REF_RE.findall(body))
            if len(measures) >= 2:
                self.articles_referenced.add("sqlbi_fusion_optimization")
                issues.append(
                    DaxIssue(
                        title="IF with Different Measures Breaks Vertical Fusion",
                        description=(
                            f"IF branch references {len(measures)} different measures "
                            f"({', '.join('[' + m + ']' for m in sorted(measures))}). "
                            f"Different measures in IF branches break vertical fusion. "
                            f"Pre-compute both branches with VAR to enable fusion."
                        ),
                        severity=IssueSeverity.MEDIUM,
                        category=IssueCategory.PERFORMANCE,
                        code_example_before="IF([Condition], [MeasureA], [MeasureB])",
                        code_example_after=(
                            "VAR _a = [MeasureA]\n"
                            "VAR _b = [MeasureB]\n"
                            "RETURN IF([Condition], _a, _b)"
                        ),
                        estimated_improvement=(
                            "Enables vertical fusion — can significantly reduce SE queries"
                        ),
                        location=f"Position {match.start()}",
                    )
                )

        # Check SWITCH branches
        switch_pattern = r"\bSWITCH\s*\("
        for match in re.finditer(switch_pattern, dax, re.IGNORECASE):
            body = dax[match.end() : match.end() + 1500]

            ti_funcs = set(m.group(1).upper() for m in _TIME_INTEL_RE.finditer(body))
            if ti_funcs:
                self.articles_referenced.add("sqlbi_fusion_optimization")
                issues.append(
                    DaxIssue(
                        title="SWITCH with Time Intelligence Breaks Vertical Fusion",
                        description=(
                            f"SWITCH branch contains time intelligence functions "
                            f"({', '.join(sorted(ti_funcs))}). This breaks vertical "
                            f"fusion. Pre-compute all branches with VAR."
                        ),
                        severity=IssueSeverity.HIGH,
                        category=IssueCategory.PERFORMANCE,
                        code_example_before=(
                            "SWITCH(TRUE(), [IsYTD], TOTALYTD([Sales], D[Date]), [Sales])"
                        ),
                        code_example_after=(
                            "VAR _ytd = TOTALYTD([Sales], D[Date])\n"
                            "VAR _current = [Sales]\n"
                            "RETURN SWITCH(TRUE(), [IsYTD], _ytd, _current)"
                        ),
                        estimated_improvement=("Can reduce SE queries from thousands to dozens"),
                        location=f"Position {match.start()}",
                    )
                )
                continue

            measures = set(_MEASURE_REF_RE.findall(body))
            if len(measures) >= 2:
                self.articles_referenced.add("sqlbi_fusion_optimization")
                issues.append(
                    DaxIssue(
                        title="SWITCH with Different Measures Breaks Vertical Fusion",
                        description=(
                            f"SWITCH references {len(measures)} different measures. "
                            f"Pre-compute all branches with VAR to enable fusion."
                        ),
                        severity=IssueSeverity.MEDIUM,
                        category=IssueCategory.PERFORMANCE,
                        code_example_before=(
                            "SWITCH([Selection], 1, [MeasureA], 2, [MeasureB], [MeasureC])"
                        ),
                        code_example_after=(
                            "VAR _a = [MeasureA]\nVAR _b = [MeasureB]\nVAR _c = [MeasureC]\n"
                            "RETURN SWITCH([Selection], 1, _a, 2, _b, _c)"
                        ),
                        estimated_improvement="Enables vertical fusion",
                        location=f"Position {match.start()}",
                    )
                )

        return issues

    # =============================================================================
    # CONTEXT AND VERTIPAQ ANALYSIS
    # =============================================================================

    def _analyze_context_results(
        self, dax: str, context_analysis: Dict[str, Any]
    ) -> List[DaxIssue]:
        """Generate issues based on context transition analysis"""
        issues = []

        complexity_score = context_analysis.get("complexity_score", 0)
        max_nesting = context_analysis.get("max_nesting_level", 0)

        if complexity_score > 15:
            issues.append(
                DaxIssue(
                    title="High Complexity Score",
                    description=(
                        f"This measure has a complexity score of {complexity_score}. "
                        "High complexity can lead to performance issues and maintenance challenges."
                    ),
                    severity=IssueSeverity.HIGH,
                    category=IssueCategory.MAINTAINABILITY,
                )
            )

        if max_nesting > 3:
            issues.append(
                DaxIssue(
                    title="Deep Nesting Level",
                    description=(
                        f"This measure has {max_nesting} levels of nesting. "
                        "Deep nesting makes code harder to understand and maintain."
                    ),
                    severity=IssueSeverity.MEDIUM,
                    category=IssueCategory.MAINTAINABILITY,
                )
            )

        return issues

    def _analyze_vertipaq_results(
        self, dax: str, vertipaq_analysis: Dict[str, Any]
    ) -> List[DaxIssue]:
        """Generate issues based on VertiPaq metrics"""
        issues = []

        high_cardinality_cols = vertipaq_analysis.get("high_cardinality_columns", [])
        optimizations = vertipaq_analysis.get("optimizations", [])

        if high_cardinality_cols:
            for col in high_cardinality_cols:
                issues.append(
                    DaxIssue(
                        title=f"High Cardinality Column: {col}",
                        description=(
                            f"Column {col} has high cardinality and is used in this measure. "
                            "This can significantly impact performance, especially in iterators."
                        ),
                        severity=IssueSeverity.HIGH,
                        category=IssueCategory.PERFORMANCE,
                    )
                )

        for opt in optimizations:
            severity = (
                IssueSeverity.HIGH if opt.get("severity") == "critical" else IssueSeverity.MEDIUM
            )
            issues.append(
                DaxIssue(
                    title=opt.get("issue", "Optimization Opportunity"),
                    description=opt.get("recommendation", ""),
                    severity=severity,
                    category=IssueCategory.PERFORMANCE,
                )
            )

        return issues

    # =============================================================================
    # SUMMARY AND SCORING
    # =============================================================================

    def _generate_summary(self, issues: List[DaxIssue], dax: str) -> str:
        """Generate a human-readable summary"""
        if not issues:
            return "✅ Excellent! No major issues found. The DAX follows best practices."

        critical = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
        high = sum(1 for i in issues if i.severity == IssueSeverity.HIGH)
        medium = sum(1 for i in issues if i.severity == IssueSeverity.MEDIUM)

        summary_parts = []

        if critical > 0:
            summary_parts.append(f"🔴 {critical} CRITICAL issue{'s' if critical > 1 else ''}")
        if high > 0:
            summary_parts.append(f"🟠 {high} HIGH priority issue{'s' if high > 1 else ''}")
        if medium > 0:
            summary_parts.append(f"🟡 {medium} MEDIUM priority issue{'s' if medium > 1 else ''}")

        return f"Found {len(issues)} total issue{'s' if len(issues) > 1 else ''}: " + ", ".join(
            summary_parts
        )

    def _calculate_score(self, issues: List[DaxIssue]) -> int:
        """Calculate an overall quality score (0-100)"""
        if not issues:
            return 100

        # Deduct points based on severity
        deductions = {
            IssueSeverity.CRITICAL: 20,
            IssueSeverity.HIGH: 10,
            IssueSeverity.MEDIUM: 5,
            IssueSeverity.LOW: 2,
            IssueSeverity.INFO: 1,
        }

        total_deduction = sum(deductions[issue.severity] for issue in issues)
        score = max(0, 100 - total_deduction)

        return score

    def _assess_complexity(self, dax: str, context_analysis: Optional[Dict[str, Any]]) -> str:
        """Assess overall complexity level"""
        factors = []

        # Length
        if len(dax) > 500:
            factors.append("length")

        # Nesting
        if context_analysis:
            nesting = context_analysis.get("max_nesting_level", 0)
            if nesting > 3:
                factors.append("deep_nesting")

        # Function count
        function_count = len(re.findall(r"\b[A-Z]+\s*\(", dax))
        if function_count > 10:
            factors.append("many_functions")

        if len(factors) >= 2:
            return "high"
        elif len(factors) == 1:
            return "medium"
        else:
            return "low"

    def _get_referenced_articles(self) -> List[Dict[str, str]]:
        """Get list of all articles referenced during analysis"""
        article_map = {
            "sqlbi_sumx_filter": {
                "title": "Avoid FILTER as filter argument",
                "url": "https://learn.microsoft.com/en-us/power-bi/guidance/dax-avoid-avoid-filter-as-filter-argument",
                "source": "Microsoft Learn",
            },
            "sqlbi_countrows_filter": {
                "title": "COUNTROWS Best Practices",
                "url": "https://learn.microsoft.com/en-us/dax/best-practices/dax-countrows",
                "source": "Microsoft Learn",
            },
            "sqlbi_filter_all": {
                "title": "Dynamic Segmentation Pattern",
                "url": "https://www.daxpatterns.com/dynamic-segmentation/",
                "source": "DAX Patterns",
            },
            "sqlbi_context_transition": {
                "title": "Understanding Context Transition",
                "url": "https://www.sqlbi.com/articles/understanding-context-transition/",
                "source": "SQLBI",
            },
            "sqlbi_related_iterators": {
                "title": "RELATED Function Reference",
                "url": "https://dax.guide/related/",
                "source": "DAX.Guide",
            },
            "sqlbi_divide": {
                "title": "DIVIDE Function Reference",
                "url": "https://dax.guide/divide/",
                "source": "DAX.Guide",
            },
            "sqlbi_values_optimize": {
                "title": "VALUES Function Reference",
                "url": "https://dax.guide/values/",
                "source": "DAX.Guide",
            },
            "sqlbi_measure_filter": {
                "title": "Static Segmentation Pattern",
                "url": "https://www.daxpatterns.com/static-segmentation/",
                "source": "DAX Patterns",
            },
            "sqlbi_variables": {
                "title": "Use variables to improve your DAX formulas",
                "url": "https://learn.microsoft.com/en-us/dax/best-practices/dax-variables",
                "source": "Microsoft Learn",
            },
            "microsoft_dax_optimization": {
                "title": "Power BI Performance Best Practices",
                "url": "https://learn.microsoft.com/en-us/power-bi/guidance/power-bi-optimization",
                "source": "Microsoft Learn",
            },
            "dax_guide_sumx": {
                "title": "SUMX Function - When to use",
                "url": "https://dax.guide/sumx/#when-to-use-sumx",
                "source": "DAX.Guide",
            },
            "dax_patterns_time_intel": {
                "title": "Standard Time-Related Calculations",
                "url": "https://www.daxpatterns.com/standard-time-related-calculations/",
                "source": "DAX Patterns",
            },
            "sqlbi_filter_columns": {
                "title": "Filter columns, not tables in DAX",
                "url": "https://www.sqlbi.com/articles/filter-columns-not-tables-in-dax/",
                "source": "SQLBI",
            },
            "ms_selectedvalue": {
                "title": "Use SELECTEDVALUE instead of VALUES",
                "url": "https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue",
                "source": "Microsoft Learn",
            },
            "sqlbi_keepfilters": {
                "title": "Using KEEPFILTERS in DAX",
                "url": "https://www.sqlbi.com/articles/using-keepfilters-in-dax/",
                "source": "SQLBI",
            },
            "sqlbi_var_shortcircuit": {
                "title": "Optimizing IF and SWITCH using variables",
                "url": "https://www.sqlbi.com/articles/optimizing-if-and-switch-expressions-using-variables/",
                "source": "SQLBI",
            },
            "sqlbi_summarizecolumns": {
                "title": "Introducing SUMMARIZECOLUMNS",
                "url": "https://www.sqlbi.com/articles/introducing-summarizecolumns/",
                "source": "SQLBI",
            },
            "sqlbi_divide_performance": {
                "title": "DIVIDE performance",
                "url": "https://www.sqlbi.com/articles/divide-performance/",
                "source": "SQLBI",
            },
        }

        return [article_map[ref] for ref in self.articles_referenced if ref in article_map]
