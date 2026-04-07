"""
Model Operations Handler
Unified CRUD for tables, columns, measures, relationships, and calculation groups.
Replaces 5 separate handlers with a single object_type + operation dispatcher.
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.table_operations import TableOperationsHandler
from core.operations.column_operations import ColumnOperationsHandler
from core.operations.measure_operations import MeasureOperationsHandler
from core.operations.relationship_operations import RelationshipOperationsHandler
from core.operations.calculation_group_operations import CalculationGroupOperationsHandler

logger = logging.getLogger(__name__)

# Reuse existing singleton handlers
_handlers = {
    "table": TableOperationsHandler(),
    "column": ColumnOperationsHandler(),
    "measure": MeasureOperationsHandler(),
    "relationship": RelationshipOperationsHandler(),
    "calculation_group": CalculationGroupOperationsHandler(),
}

# Valid operations per object_type (for error messages)
_valid_operations = {
    "table": ["list", "describe", "sample_data", "create", "update", "delete", "refresh", "generate_calendar"],
    "column": ["list", "get", "statistics", "distribution", "create", "update", "delete"],
    "measure": ["list", "get", "create", "update", "delete", "rename", "move"],
    "relationship": ["list", "get", "find", "create", "update", "delete", "activate", "deactivate"],
    "calculation_group": ["list", "create", "delete", "list_items"],
}


def handle_model_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Unified model CRUD dispatcher"""
    object_type = args.get("object_type")
    if not object_type:
        return {
            "success": False,
            "error": "object_type is required",
            "valid_types": list(_handlers.keys()),
        }

    handler = _handlers.get(object_type)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown object_type: {object_type}",
            "valid_types": list(_handlers.keys()),
        }

    operation = args.get("operation")
    valid_ops = _valid_operations.get(object_type, [])
    if operation and operation not in valid_ops:
        return {
            "success": False,
            "error": f"Invalid operation '{operation}' for {object_type}",
            "valid_operations": valid_ops,
        }

    # Delegate to the existing handler — it already knows how to dispatch operations
    return handler.execute(args)


def register_model_operations_handler(registry):
    """Register unified model operations handler"""
    tool = ToolDefinition(
        name="02_Model_Operations",
        description="Unified CRUD for tables, columns, measures, relationships, and calculation groups. Specify object_type + operation.",
        handler=handle_model_operations,
        input_schema={
            "type": "object",
            "properties": {
                "object_type": {
                    "type": "string",
                    "enum": ["table", "column", "measure", "relationship", "calculation_group"],
                    "description": "Type of model object to operate on"
                },
                "operation": {
                    "type": "string",
                    "description": "Operation to perform (valid values depend on object_type)"
                },
                # Shared identifiers
                "table_name": {"type": "string", "description": "Table name"},
                "column_name": {"type": "string", "description": "Column name"},
                "measure_name": {"type": "string", "description": "Measure name"},
                "relationship_name": {"type": "string", "description": "Relationship name"},
                "group_name": {"type": "string", "description": "Calculation group name"},
                "name": {"type": "string", "description": "Object name (relationship create, auto-generated if omitted)"},
                "new_name": {"type": "string", "description": "New name (rename/update)"},
                # Shared properties
                "expression": {"type": "string", "description": "DAX expression"},
                "description": {"type": "string", "description": "Object description"},
                "format_string": {"type": "string", "description": "Format string"},
                "display_folder": {"type": "string", "description": "Display folder path"},
                "hidden": {"type": "boolean", "description": "Hide object"},
                # Table-specific
                "max_rows": {"type": "integer", "description": "Max rows for sample_data (default 10, max 1000)", "default": 10},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Columns to include (sample_data)"},
                "order_by": {"type": "string", "description": "Order by column (sample_data)"},
                "order_direction": {"type": "string", "enum": ["asc", "desc"], "default": "asc"},
                "columns_page_size": {"type": "integer", "description": "Page size for columns (table describe)"},
                "measures_page_size": {"type": "integer", "description": "Page size for measures (table describe)"},
                "relationships_page_size": {"type": "integer", "description": "Page size for relationships (table describe)"},
                "start_year": {"type": "integer", "description": "Start year (generate_calendar, default: current year - 5)"},
                "end_year": {"type": "integer", "description": "End year (generate_calendar, default: current year + 2)"},
                "include_fiscal": {"type": "boolean", "description": "Include fiscal year columns (generate_calendar, default: false)"},
                "fiscal_start_month": {"type": "integer", "description": "Fiscal year start month 1-12 (generate_calendar, default: 7)"},
                # Column-specific
                "column_type": {
                    "type": "string",
                    "enum": ["all", "data", "calculated"],
                    "description": "Filter type (column list)",
                    "default": "all"
                },
                "data_type": {
                    "type": "string",
                    "enum": ["String", "Int64", "Double", "Decimal", "Boolean", "DateTime", "Binary", "Variant"],
                    "description": "Data type (column create)",
                    "default": "String"
                },
                "source_column": {"type": "string", "description": "Source column for data columns (column create)"},
                "top_n": {"type": "integer", "description": "Top N values (column statistics/distribution, default: 10)", "default": 10},
                # Measure-specific
                "new_table": {"type": "string", "description": "Target table (measure move)"},
                # Relationship-specific
                "from_table": {"type": "string", "description": "Source table (relationship create)"},
                "from_column": {"type": "string", "description": "Source column (relationship create)"},
                "to_table": {"type": "string", "description": "Target table (relationship create)"},
                "to_column": {"type": "string", "description": "Target column (relationship create)"},
                "from_cardinality": {
                    "type": "string",
                    "enum": ["One", "Many"],
                    "default": "Many"
                },
                "to_cardinality": {
                    "type": "string",
                    "enum": ["One", "Many"],
                    "default": "One"
                },
                "cross_filtering_behavior": {
                    "type": "string",
                    "enum": ["OneDirection", "BothDirections", "Automatic"],
                    "default": "OneDirection"
                },
                "is_active": {"type": "boolean", "description": "Relationship active state"},
                "active_only": {"type": "boolean", "description": "Filter active relationships only (relationship list)", "default": False},
                # Calculation group-specific
                "items": {
                    "type": "array",
                    "description": "Calculation items (calc group create)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "expression": {"type": "string"},
                            "ordinal": {"type": "integer"}
                        }
                    }
                },
                "precedence": {"type": "integer", "description": "Calculation group precedence"},
                # Pagination (shared)
                "page_size": {"type": "integer", "description": "Page size for list operations"},
                "next_token": {"type": "string", "description": "Pagination token"},
            },
            "required": ["object_type"]
        },
        category="model",
        sort_order=20,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    registry.register(tool)
    logger.info("Registered unified model_operations handler")
