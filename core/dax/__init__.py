"""
DAX Context Analysis Module

This module provides advanced DAX context analysis capabilities:
- Context transition detection (explicit CALCULATE, implicit measures, iterators)
- Filter context visualization (text, Mermaid, HTML)
- Step-by-step context debugging
- Performance impact assessment
- VertiPaq column metrics integration
- Call tree hierarchy visualization
- Calculation group analysis
- Advanced DAX code rewriting
- Variable optimization scanning
- Visual context flow diagrams
- CallbackDataID pattern detection
- Static analysis rules engine with health scoring

Version: 4.2.0 - Added DAX static analysis rules engine
"""

from .context_analyzer import (
    DaxContextAnalyzer,
    ContextTransition,
    ContextFlowExplanation,
    PerformanceWarning,
)
from .context_visualizer import FilterContextVisualizer
from .context_debugger import DaxContextDebugger, EvaluationStep, ContextExplanation
from .vertipaq_analyzer import VertiPaqAnalyzer, ColumnMetrics, CardinalityImpact
from .call_tree_builder import CallTreeBuilder, CallTreeNode, NodeType
from .calculation_group_analyzer import (
    CalculationGroupAnalyzer,
    CalculationGroup,
    PrecedenceConflict,
    CalculationGroupIssue,
)
from .code_rewriter import (
    DaxCodeRewriter,
    VariableOptimizationScanner,
    Transformation,
)
from .visual_flow import VisualFlowDiagramGenerator, FlowStep
from .callback_detector import CallbackDetector, CallbackDetection
from .dax_rules_engine import DaxRulesEngine, DaxIssue
from .analysis_pipeline import (
    run_context_analysis,
    run_vertipaq_analysis,
    run_best_practices,
    run_call_tree,
)

__all__ = [
    # Core analyzers
    "DaxContextAnalyzer",
    "ContextTransition",
    "ContextFlowExplanation",
    "PerformanceWarning",
    "FilterContextVisualizer",
    "DaxContextDebugger",
    "EvaluationStep",
    "ContextExplanation",
    # VertiPaq integration
    "VertiPaqAnalyzer",
    "ColumnMetrics",
    "CardinalityImpact",
    # Call tree
    "CallTreeBuilder",
    "CallTreeNode",
    "NodeType",
    # Calculation groups
    "CalculationGroupAnalyzer",
    "CalculationGroup",
    "PrecedenceConflict",
    "CalculationGroupIssue",
    # Code rewriting
    "DaxCodeRewriter",
    "VariableOptimizationScanner",
    "Transformation",
    # Visual flow
    "VisualFlowDiagramGenerator",
    "FlowStep",
    # CallbackDataID detection
    "CallbackDetector",
    "CallbackDetection",
    # Static analysis rules engine
    "DaxRulesEngine",
    "DaxIssue",
    # Pipeline helpers
    "run_context_analysis",
    "run_vertipaq_analysis",
    "run_best_practices",
    "run_call_tree",
]
