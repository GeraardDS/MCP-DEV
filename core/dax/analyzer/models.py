"""Dataclasses for the unified DAX analyzer.

Data contracts used by the entire analysis + optimization system.
Includes backward-compatible format converters so old facades
(DaxBestPracticesAnalyzer, DaxRulesEngine, CallbackDetector) can
consume results without changing handler code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Severity ordering: critical first, info last.
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Health-score deductions per severity level.
_SEVERITY_DEDUCTIONS = {"critical": 20, "high": 10, "medium": 5, "low": 2, "info": 1}


@dataclass
class AnalysisContext:
    """Optional enrichment data for tiered analysis.

    Tier 1 (static) needs nothing. Tier 2 adds VertiPaq / model metadata.
    Tier 3 adds live trace data.
    """

    vertipaq_data: Optional[Dict[str, Any]] = None
    table_row_counts: Optional[Dict[str, int]] = None
    model_relationships: Optional[List[Dict]] = None
    calculation_groups: Optional[List[Dict]] = None
    trace_data: Optional[Dict[str, Any]] = None
    measure_name: Optional[str] = None
    table_name: Optional[str] = None


@dataclass
class AnalysisIssue:
    """A single analysis finding produced by the unified engine."""

    rule_id: str
    category: str  # performance | correctness | maintainability
    severity: str  # critical | high | medium | low | info
    title: str
    description: str
    fix_suggestion: str
    source: str  # static | vertipaq | trace

    # Optional detail fields
    location: Optional[str] = None
    code_before: Optional[str] = None
    code_after: Optional[str] = None
    estimated_improvement: Optional[str] = None
    rewrite_strategy: Optional[str] = None
    references: Optional[List[Dict]] = None
    confidence: str = "high"
    vertipaq_detail: Optional[str] = None
    trace_detail: Optional[str] = None
    match_text: Optional[str] = None
    line: int = 0

    # ------------------------------------------------------------------
    # Legacy conversion
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Convert to the legacy dict format used by best-practices results."""
        d: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "fix_suggestion": self.fix_suggestion,
            "source": self.source,
            "confidence": self.confidence,
            "line": self.line,
        }

        if self.location is not None:
            d["location"] = self.location
        if self.code_before is not None:
            d["code_example_before"] = self.code_before
        if self.code_after is not None:
            d["code_example_after"] = self.code_after
        if self.estimated_improvement is not None:
            d["estimated_improvement"] = self.estimated_improvement
        if self.rewrite_strategy is not None:
            d["rewrite_strategy"] = self.rewrite_strategy
        if self.references:
            # Legacy format uses singular "article_reference" with first ref.
            d["article_reference"] = self.references[0]
        if self.vertipaq_detail is not None:
            d["vertipaq_detail"] = self.vertipaq_detail
        if self.trace_detail is not None:
            d["trace_detail"] = self.trace_detail
        if self.match_text is not None:
            d["match_text"] = self.match_text

        return d


@dataclass
class RewriteCandidate:
    """An issue that has an automated rewrite strategy attached."""

    issue: AnalysisIssue
    strategy_name: str
    estimated_confidence: str = "medium"


@dataclass
class UnifiedAnalysisResult:
    """Complete analysis output from the unified DAX engine."""

    success: bool
    issues: List[AnalysisIssue]
    health_score: int  # 0-100
    tier_used: int  # 1, 2, or 3
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    rewrite_candidates: List[RewriteCandidate] = field(default_factory=list)
    summary: str = ""
    tokens: Optional[Any] = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_issues(
        cls,
        issues: List[AnalysisIssue],
        tier_used: int = 1,
        tokens: Optional[Any] = None,
    ) -> "UnifiedAnalysisResult":
        """Build a result from a flat list of issues.

        - Sorts by severity (critical first).
        - Computes health_score with per-severity deductions.
        - Extracts rewrite candidates from issues that carry a strategy.
        """
        sorted_issues = sorted(
            issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99)
        )

        # Severity counts
        counts: Dict[str, int] = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }
        for issue in sorted_issues:
            if issue.severity in counts:
                counts[issue.severity] += 1

        # Health score
        score = 100
        for sev, cnt in counts.items():
            score -= _SEVERITY_DEDUCTIONS.get(sev, 0) * cnt
        score = max(0, score)

        # Rewrite candidates
        rewrite_candidates = [
            RewriteCandidate(
                issue=issue,
                strategy_name=issue.rewrite_strategy,  # type: ignore[arg-type]
                estimated_confidence="medium",
            )
            for issue in sorted_issues
            if issue.rewrite_strategy
        ]

        total = len(sorted_issues)
        summary = f"{total} issues found (score: {score}/100)"

        return cls(
            success=True,
            issues=sorted_issues,
            health_score=score,
            tier_used=tier_used,
            total_issues=total,
            critical_issues=counts["critical"],
            high_issues=counts["high"],
            medium_issues=counts["medium"],
            rewrite_candidates=rewrite_candidates,
            summary=summary,
            tokens=tokens,
        )

    # ------------------------------------------------------------------
    # Backward-compatible format converters
    # ------------------------------------------------------------------

    def to_best_practices_format(self) -> Dict[str, Any]:
        """Return a dict matching DaxBestPracticesAnalyzer.analyze() output."""
        # Deduplicate article references across all issues.
        seen_urls: set = set()
        articles: List[Dict] = []
        for issue in self.issues:
            if issue.references:
                for ref in issue.references:
                    url = ref.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        articles.append(ref)

        # Complexity heuristic: severity-weighted.
        if self.critical_issues > 0 or self.total_issues >= 5:
            complexity = "complex"
        elif self.high_issues > 0 or self.total_issues >= 2:
            complexity = "moderate"
        else:
            complexity = "simple"

        return {
            "success": True,
            "total_issues": self.total_issues,
            "critical_issues": self.critical_issues,
            "high_issues": self.high_issues,
            "medium_issues": self.medium_issues,
            "issues": [issue.to_dict() for issue in self.issues],
            "summary": self.summary,
            "articles_referenced": articles,
            "overall_score": self.health_score,
            "complexity_level": complexity,
        }

    def to_rules_engine_format(self) -> Dict[str, Any]:
        """Return a dict matching DaxRulesEngine.analyze() output."""
        categories: Dict[str, int] = {}
        engine_issues: List[Dict[str, Any]] = []

        for issue in self.issues:
            # Map category names to rules-engine categories.
            cat = issue.category
            if cat == "maintainability":
                cat = "readability"
            categories[cat] = categories.get(cat, 0) + 1

            engine_issues.append(
                {
                    "rule_id": issue.rule_id,
                    "category": issue.category,
                    "severity": issue.severity,
                    "description": issue.description,
                    "fix_suggestion": issue.fix_suggestion,
                    "line": issue.line,
                    "match_text": issue.match_text,
                }
            )

        return {
            "health_score": self.health_score,
            "issues": engine_issues,
            "issue_count": self.total_issues,
            "categories": categories,
        }

    def to_callback_format(self) -> Dict[str, Any]:
        """Return a dict matching CallbackDetector.detect_dict() output."""
        detections: List[Dict[str, Any]] = []
        for issue in self.issues:
            if issue.rule_id.startswith("CB"):
                detections.append(
                    {
                        "rule_id": issue.rule_id,
                        "severity": issue.severity,
                        "description": issue.description,
                        "location": issue.location,
                        "fix_suggestion": issue.fix_suggestion,
                    }
                )

        return {
            "success": True,
            "total_detections": len(detections),
            "detections": detections,
        }
