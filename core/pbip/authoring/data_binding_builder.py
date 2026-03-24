"""
Data Binding Builder for PBIP Visual Authoring

Builds Power BI data binding structures (queryState projections) from simple
(table, field) tuples. This reverses the extraction logic in pbip_report_analyzer.py.
"""

from typing import Any, Dict, List, Optional


def build_measure_binding(
    table: str,
    measure: str,
    display_name: Optional[str] = None,
    active: bool = True,
) -> Dict[str, Any]:
    """Build a measure projection for visual queryState.

    Args:
        table: Source table/entity name (e.g., "m Measure")
        measure: Measure property name (e.g., "Net Asset Value")
        display_name: Optional display name override
        active: Whether the field is active in the visual

    Returns:
        Complete projection dict for use in queryState
    """
    projection: Dict[str, Any] = {
        "field": {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": measure,
            }
        },
        "queryRef": f"{table}.{measure}",
        "nativeQueryRef": measure,
        "active": active,
    }
    if display_name:
        projection["displayName"] = display_name
    return projection


def build_column_binding(
    table: str,
    column: str,
    display_name: Optional[str] = None,
    active: bool = True,
) -> Dict[str, Any]:
    """Build a column projection for visual queryState.

    Args:
        table: Source table/entity name (e.g., "d Date")
        column: Column property name (e.g., "Month")
        display_name: Optional display name override
        active: Whether the field is active in the visual

    Returns:
        Complete projection dict for use in queryState
    """
    projection: Dict[str, Any] = {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": column,
            }
        },
        "queryRef": f"{table}.{column}",
        "nativeQueryRef": column,
        "active": active,
    }
    if display_name:
        projection["displayName"] = display_name
    return projection


def build_hierarchy_binding(
    table: str,
    hierarchy: str,
    level: str,
    display_name: Optional[str] = None,
    active: bool = True,
) -> Dict[str, Any]:
    """Build a hierarchy level projection for visual queryState.

    Args:
        table: Source table/entity name
        hierarchy: Hierarchy name
        level: Level within the hierarchy
        display_name: Optional display name override
        active: Whether the field is active in the visual

    Returns:
        Complete projection dict for use in queryState
    """
    projection: Dict[str, Any] = {
        "field": {
            "HierarchyLevel": {
                "Expression": {
                    "Hierarchy": {
                        "Expression": {"SourceRef": {"Entity": table}},
                        "Hierarchy": hierarchy,
                    }
                },
                "Level": level,
            }
        },
        "queryRef": f"{table}.{hierarchy}.{level}",
        "nativeQueryRef": level,
        "active": active,
    }
    if display_name:
        projection["displayName"] = display_name
    return projection


def build_query_state(bindings: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Build a complete queryState from categorized bindings.

    Args:
        bindings: Dict mapping bucket names to lists of projection dicts.
                  Common buckets: "Category", "Values", "Y", "Rows", "Columns",
                  "Legend", "Series", "Size", "Tooltips", "Details"

    Returns:
        Complete queryState dict for use in visual.query
    """
    query_state: Dict[str, Any] = {}
    for bucket_name, projections in bindings.items():
        if projections:
            query_state[bucket_name] = {"projections": projections}
    return query_state


def build_filter_binding(
    table: str,
    field: str,
    field_type: str = "Column",
    values: Optional[List[Any]] = None,
    condition_type: str = "In",
) -> Dict[str, Any]:
    """Build a filter definition for page or visual level.

    Args:
        table: Source table/entity name
        field: Field name (column or measure)
        field_type: "Column" or "Measure"
        values: Filter values (for In conditions)
        condition_type: "In", "Comparison", "Between", "Not"

    Returns:
        Filter dict for use in filterConfig.filters
    """
    field_ref: Dict[str, Any] = {
        field_type: {
            "Expression": {"SourceRef": {"Entity": table}},
            "Property": field,
        }
    }

    filter_def: Dict[str, Any] = {
        "name": f"Filter_{table}_{field}".replace(" ", "_"),
        "type": "Categorical",
        "field": field_ref,
        "howCreated": "User",
    }

    if values is not None and condition_type == "In":
        filter_def["filter"] = {
            "Version": 2,
            "From": [{"Name": "t", "Entity": table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {
                                    field_type: {
                                        "Expression": {"SourceRef": {"Source": "t"}},
                                        "Property": field,
                                    }
                                }
                            ],
                            "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values],
                        }
                    }
                }
            ],
        }

    return filter_def
