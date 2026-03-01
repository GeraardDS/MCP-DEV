"""
SE/FE profiling analysis and optimization recommendations.

Takes an SEFEResult and produces structured insights with
severity ratings and concrete optimization suggestions.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from core.performance.se_fe_profiler import SEFEResult

# ── Thresholds ────────────────────────────────────────────────────────────────

_FE_DOMINATED_RATIO = 0.70        # fe_ms / total_ms > this → FE bottleneck
_FE_DOMINATED_MIN_MS = 20.0       # only flag if total_ms > this

_SE_START_OFFSET_ABS_MS = 15.0    # se_start_offset_ms > this → expensive FE pre-work
_SE_START_OFFSET_RATIO = 0.35     # AND > this fraction of total_ms

_SE_FRAGMENTED_COUNT = 6          # se_query_count > this → many small SE queries
_SE_PARALLEL_THRESHOLD = 0.8      # se_parallelism < this (when >1 SE query)

_HIGH_MEMORY_KB = 100_000         # ~100 MB
_VERY_HIGH_MEMORY_KB = 500_000    # ~500 MB

_SLOW_QUERY_MS = 500.0            # total_ms > this → warn
_VERY_SLOW_QUERY_MS = 2_000.0     # total_ms > this → critical

_RESULT_ROWS_HIGH = 10_000        # result_rows > this → large result set warning


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SEFEInsight:
    """A single diagnostic finding with optimization guidance."""

    category: str    # Rule key, e.g. "fe_dominated", "se_fragmented"
    severity: str    # "info" | "warning" | "critical"
    title: str
    detail: str
    suggestion: str


@dataclass
class SEFEAnalysis:
    """
    Analysis result produced by analyze_se_fe().

    Attributes:
        insights: Ordered list of findings (critical first).
        diagnosis: One-line human-readable summary.
        optimization_focus: "fe" | "se" | "memory" | "none"
            Primary area to address.
        has_issues: True if any warning/critical insight found.
    """

    insights: List[SEFEInsight] = field(default_factory=list)
    diagnosis: str = "No issues detected."
    optimization_focus: str = "none"
    has_issues: bool = False

    def to_dict(self) -> dict:
        return {
            "diagnosis": self.diagnosis,
            "optimization_focus": self.optimization_focus,
            "has_issues": self.has_issues,
            "insights": [
                {
                    "category": i.category,
                    "severity": i.severity,
                    "title": i.title,
                    "detail": i.detail,
                    "suggestion": i.suggestion,
                }
                for i in self.insights
            ],
        }


# ── Rules ─────────────────────────────────────────────────────────────────────

def _rule_slow_query(result: "SEFEResult") -> List[SEFEInsight]:
    if result.total_ms >= _VERY_SLOW_QUERY_MS:
        return [SEFEInsight(
            category="slow_query",
            severity="critical",
            title=f"Very slow query ({result.total_ms:.0f} ms)",
            detail=(
                f"Total execution time is {result.total_ms:.0f} ms, "
                "exceeding the 2,000 ms critical threshold. "
                "This will cause visuals to feel unresponsive."
            ),
            suggestion=(
                "Profile the measure with Server Timings in DAX Studio. "
                "Check for FILTER on large tables, RANKX, or deeply nested "
                "CALCULATE chains."
            ),
        )]
    if result.total_ms >= _SLOW_QUERY_MS:
        return [SEFEInsight(
            category="slow_query",
            severity="warning",
            title=f"Slow query ({result.total_ms:.0f} ms)",
            detail=(
                f"Total execution time is {result.total_ms:.0f} ms. "
                "Queries above 500 ms are noticeable to end users."
            ),
            suggestion=(
                "Identify the dominant engine (FE vs SE) below and address "
                "the highest-severity finding first."
            ),
        )]
    return []


def _rule_fe_dominated(result: "SEFEResult") -> List[SEFEInsight]:
    if result.total_ms < _FE_DOMINATED_MIN_MS:
        return []
    fe_ratio = result.fe_ms / result.total_ms if result.total_ms > 0 else 0.0
    if fe_ratio < _FE_DOMINATED_RATIO:
        return []
    return [SEFEInsight(
        category="fe_dominated",
        severity="warning",
        title=f"FE-dominated ({fe_ratio:.0%} FE, {result.fe_ms:.0f} ms)",
        detail=(
            f"The Formula Engine consumed {result.fe_ms:.0f} ms "
            f"({fe_ratio:.0%} of total). "
            "FE time indicates iterator functions, context transitions, "
            "or complex filter manipulation that the SE cannot vectorise."
        ),
        suggestion=(
            "1. Replace iterators with aggregators where possible: "
            "SUMX(T, [M]) → SUM(T[col]).\n"
            "2. Use VAR to avoid repeated CALCULATE evaluation.\n"
            "3. Check for FILTER(ALL(...), ...) — prefer KEEPFILTERS.\n"
            "4. DIVIDE() is faster than IF(denominator=0, ...) in hot paths."
        ),
    )]


def _rule_se_start_offset(result: "SEFEResult") -> List[SEFEInsight]:
    """FE ran a significant time before the first SE scan was issued."""
    if result.se_start_offset_ms <= _SE_START_OFFSET_ABS_MS:
        return []
    if result.total_ms <= 0:
        return []
    ratio = result.se_start_offset_ms / result.total_ms
    if ratio < _SE_START_OFFSET_RATIO:
        return []
    return [SEFEInsight(
        category="se_start_offset",
        severity="warning",
        title=(
            f"FE pre-work before first SE scan "
            f"({result.se_start_offset_ms:.0f} ms)"
        ),
        detail=(
            f"The Formula Engine ran for {result.se_start_offset_ms:.0f} ms "
            "before sending the first query to the Storage Engine. "
            "This typically means the FE is resolving scalar contexts, "
            "materialising intermediate tables, or evaluating complex "
            "filter arguments before it can formulate an SE request."
        ),
        suggestion=(
            "1. Cache expensive sub-expressions in VAR at the top of the measure.\n"
            "2. Avoid ALLSELECTED on large tables in the filter context — it forces "
            "FE to enumerate the context before querying SE.\n"
            "3. Replace EARLIER() with VAR (EARLIER forces row-context "
            "iteration entirely in FE)."
        ),
    )]


def _rule_se_fragmented(result: "SEFEResult") -> List[SEFEInsight]:
    if result.se_query_count <= _SE_FRAGMENTED_COUNT:
        return []
    return [SEFEInsight(
        category="se_fragmented",
        severity="warning",
        title=f"Many SE queries ({result.se_query_count})",
        detail=(
            f"The measure issued {result.se_query_count} Storage Engine queries. "
            "Many small SE queries suggest the FE is iterating and issuing one "
            "SE scan per iteration step, rather than batching the work."
        ),
        suggestion=(
            "1. Replace row-context iterators with set-based aggregations.\n"
            "2. Use SUMMARIZECOLUMNS or SUMMARIZE to pre-aggregate before "
            "iterating.\n"
            "3. Check for LOOKUPVALUE / RELATED used inside iterators — "
            "move lookups outside the loop with VAR."
        ),
    )]


def _rule_dc_kind_dense(result: "SEFEResult") -> List[SEFEInsight]:
    dense_queries = [q for q in result.se_queries if q.dc_kind == "DENSE"]
    if not dense_queries:
        return []
    return [SEFEInsight(
        category="dc_kind_dense",
        severity="info",
        title=(
            f"Dense SE scan detected "
            f"({len(dense_queries)} of {result.se_query_count} queries)"
        ),
        detail=(
            "DC_KIND=DENSE means the SE scanned without an effective row filter, "
            "reading many or all rows of the underlying segment. "
            "This can be expected for aggregate queries but may indicate "
            "missing filter pushdown."
        ),
        suggestion=(
            "1. Ensure relationships are active and correctly directional so "
            "filters propagate into fact tables.\n"
            "2. If this is an unbounded aggregate, consider a pre-aggregated "
            "calculated table or aggregation table for large datasets."
        ),
    )]


def _rule_no_se_parallelism(result: "SEFEResult") -> List[SEFEInsight]:
    if result.se_query_count <= 1:
        return []
    if result.se_parallelism >= _SE_PARALLEL_THRESHOLD:
        return []
    return [SEFEInsight(
        category="no_se_parallelism",
        severity="info",
        title=(
            f"SE queries running sequentially "
            f"(parallelism {result.se_parallelism:.1f}×)"
        ),
        detail=(
            f"With {result.se_query_count} SE queries and a parallelism ratio "
            f"of {result.se_parallelism:.1f}×, the SE scans appear to be "
            "running serially. Parallel SE execution is expected when multiple "
            "independent sub-queries are issued."
        ),
        suggestion=(
            "Serial SE can be a symptom of data-dependent scans (each scan "
            "depends on the prior result). If unintended, restructure the "
            "measure to allow independent sub-expressions so the engine can "
            "schedule them in parallel."
        ),
    )]


def _rule_high_memory(result: "SEFEResult") -> List[SEFEInsight]:
    if result.peak_memory_kb <= _HIGH_MEMORY_KB:
        return []
    severity = (
        "critical"
        if result.peak_memory_kb >= _VERY_HIGH_MEMORY_KB
        else "warning"
    )
    mb = result.peak_memory_kb / 1024
    return [SEFEInsight(
        category="high_memory",
        severity=severity,
        title=f"High peak memory usage ({mb:.0f} MB)",
        detail=(
            f"The query consumed approximately {mb:.0f} MB at peak. "
            "High memory typically indicates large intermediate tables being "
            "materialised in the FE (e.g. via CROSSJOIN, SUMMARIZE on "
            "many columns, or ALLSELECTED over huge tables)."
        ),
        suggestion=(
            "1. Avoid CROSSJOIN or GENERATE on large tables.\n"
            "2. Use SUMMARIZECOLUMNS instead of ADDCOLUMNS(SUMMARIZE(...)) "
            "— SUMMARIZECOLUMNS pushes more work to the SE.\n"
            "3. Narrow the filter context before expensive aggregations "
            "with explicit FILTER conditions."
        ),
    )]


def _rule_large_result(result: "SEFEResult") -> List[SEFEInsight]:
    if result.result_rows <= _RESULT_ROWS_HIGH:
        return []
    return [SEFEInsight(
        category="large_result",
        severity="info",
        title=f"Large result set ({result.result_rows:,} rows)",
        detail=(
            f"The query returned {result.result_rows:,} rows. "
            "Large result sets increase FE serialisation time and "
            "visual render time on the client."
        ),
        suggestion=(
            "Consider whether the visual requires this level of granularity. "
            "Aggregating at a higher level or using Top N filters can "
            "significantly reduce result set size."
        ),
    )]


# ── Public API ────────────────────────────────────────────────────────────────

_RULES = [
    _rule_slow_query,
    _rule_fe_dominated,
    _rule_se_start_offset,
    _rule_se_fragmented,
    _rule_dc_kind_dense,
    _rule_no_se_parallelism,
    _rule_high_memory,
    _rule_large_result,
]

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def analyze_se_fe(result: "SEFEResult") -> SEFEAnalysis:
    """
    Analyse an SEFEResult and return structured optimization insights.

    Only meaningful when profiling_method == "trace" (full data).
    For "executor" or "basic" results, only timing-based rules fire.

    Args:
        result: SEFEResult from SEFEProfiler.profile_query().

    Returns:
        SEFEAnalysis with sorted insights and a one-line diagnosis.
    """
    all_insights: List[SEFEInsight] = []
    for rule in _RULES:
        all_insights.extend(rule(result))

    # Sort: critical → warning → info
    all_insights.sort(key=lambda i: _SEVERITY_ORDER.get(i.severity, 9))

    has_issues = any(
        i.severity in ("critical", "warning") for i in all_insights
    )

    # Determine primary optimization focus
    focus = "none"
    fe_ratio = result.fe_ms / result.total_ms if result.total_ms > 0 else 0.0
    if result.peak_memory_kb >= _HIGH_MEMORY_KB:
        focus = "memory"
    elif fe_ratio >= _FE_DOMINATED_RATIO and result.total_ms >= _FE_DOMINATED_MIN_MS:
        focus = "fe"
    elif result.se_query_count >= _SE_FRAGMENTED_COUNT:
        focus = "se"
    elif result.se_ms > result.fe_ms and result.total_ms >= _SLOW_QUERY_MS:
        focus = "se"

    # Build one-line diagnosis
    if not has_issues:
        if result.total_ms < _SLOW_QUERY_MS:
            diagnosis = (
                f"Query is fast ({result.total_ms:.0f} ms). "
                "No significant issues detected."
            )
        else:
            diagnosis = (
                f"Query took {result.total_ms:.0f} ms with no clear bottleneck."
            )
    else:
        critical = [i for i in all_insights if i.severity == "critical"]
        warnings = [i for i in all_insights if i.severity == "warning"]
        if critical:
            diagnosis = f"{critical[0].title}. {len(all_insights)} issue(s) found."
        else:
            diagnosis = f"{warnings[0].title}. {len(all_insights)} issue(s) found."

    return SEFEAnalysis(
        insights=all_insights,
        diagnosis=diagnosis,
        optimization_focus=focus,
        has_issues=has_issues,
    )
