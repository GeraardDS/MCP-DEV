"""Python-based structural analysis rules for DAX."""

from .base import PythonRule
from .iterator_rules import (
    NestedIteratorRule,
    IfSwitchInIteratorRule,
    DivideInIteratorRule,
    UnnecessaryIteratorRule,
    RelatedInIteratorRule,
)
from .calculate_rules import (
    NestedCalculateRule,
    FilterTableNotColumnRule,
    KeepfiltersOpportunityRule,
    AllTableVsColumnRule,
)
from .filter_rules import (
    FilterBareTableRule,
    FilterAllMaterializationRule,
    IntersectVsTreatasRule,
    AddcolumnsSummarizeRule,
)
from .context_rules import (
    VarDefeatingShortCircuitRule,
    UnusedVarRule,
    MeasureRefWithoutVarRule,
    BlankPropagationRule,
)
from .model_rules import (
    DirectMeasureReferenceRule,
    SemiAdditivePatternRule,
)


def load_python_rules() -> list:
    """Instantiate and return all Python rules."""
    return [
        # Iterator rules
        NestedIteratorRule(),
        IfSwitchInIteratorRule(),
        DivideInIteratorRule(),
        UnnecessaryIteratorRule(),
        RelatedInIteratorRule(),
        # Calculate rules
        NestedCalculateRule(),
        FilterTableNotColumnRule(),
        KeepfiltersOpportunityRule(),
        AllTableVsColumnRule(),
        # Filter rules
        FilterBareTableRule(),
        FilterAllMaterializationRule(),
        IntersectVsTreatasRule(),
        AddcolumnsSummarizeRule(),
        # Context rules
        VarDefeatingShortCircuitRule(),
        UnusedVarRule(),
        MeasureRefWithoutVarRule(),
        BlankPropagationRule(),
        # Model rules
        DirectMeasureReferenceRule(),
        SemiAdditivePatternRule(),
    ]
