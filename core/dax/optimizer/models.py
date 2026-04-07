"""Dataclasses for the DAX optimizer."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RewriteResult:
    """Result of a single DAX rewrite transformation."""

    strategy: str
    rule_id: str
    original_fragment: str
    rewritten_fragment: str
    full_rewritten_dax: str
    explanation: str
    confidence: str  # "high", "medium", "low"
    estimated_improvement: str
    validation_passed: bool


@dataclass
class OptimizationResult:
    """Complete optimization result for a measure."""

    success: bool
    measure_name: Optional[str]
    original_dax: str
    analysis: Any  # UnifiedAnalysisResult
    rewrites: List[RewriteResult]
    final_dax: Optional[str]
    applied: bool
    apply_error: Optional[str]
    improvement_summary: str
