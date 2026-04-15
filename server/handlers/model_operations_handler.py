"""
Model Operations Handler
Unified CRUD for tables, columns, measures, relationships, calculation groups,
partitions, hierarchies, perspectives, cultures, named expressions, and OLS rules.
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
from core.operations.partition_crud_manager import PartitionCrudManager
from core.operations.hierarchy_crud_manager import HierarchyCrudManager
from core.operations.perspective_crud_manager import PerspectiveCrudManager
from core.operations.culture_crud_manager import CultureCrudManager
from core.operations.named_expression_crud_manager import NamedExpressionCrudManager
from core.operations.ols_crud_manager import OlsCrudManager
from core.operations.model_refresh_manager import ModelRefreshManager

logger = logging.getLogger(__name__)

# Reuse existing singleton handlers
_handlers = {
    "table": TableOperationsHandler(),
    "column": ColumnOperationsHandler(),
    "measure": MeasureOperationsHandler(),
    "relationship": RelationshipOperationsHandler(),
    "calculation_group": CalculationGroupOperationsHandler(),
    "partition": PartitionCrudManager(),
    "hierarchy": HierarchyCrudManager(),
    "perspective": PerspectiveCrudManager(),
    "culture": CultureCrudManager(),
    "named_expression": NamedExpressionCrudManager(),
    "ols_rule": OlsCrudManager(),
    "model": ModelRefreshManager(),
}

# Valid operations per object_type (for error messages)
_valid_operations = {
    "table": ["list", "describe", "sample_data", "create", "update", "delete", "rename", "refresh", "generate_calendar"],
    "column": ["list", "get", "statistics", "distribution", "create", "update", "delete", "rename"],
    "measure": ["list", "get", "create", "update", "delete", "rename", "move"],
    "relationship": ["list", "get", "find", "create", "update", "delete", "activate", "deactivate"],
    "calculation_group": ["list", "create", "delete", "list_items"],
    "partition": ["list", "describe", "refresh"],
    "hierarchy": ["list", "describe", "create", "delete"],
    "perspective": ["list", "describe", "create", "delete"],
    "culture": ["list", "describe", "create", "delete", "set_translation"],
    "named_expression": ["list", "describe", "create", "update", "delete"],
    "ols_rule": ["list", "set", "remove"],
    "model": ["refresh"],
}


def _dispatch_new_type(manager, object_type: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch operations for new TOM object types."""
    operation = args.get("operation", "list")
    dispatch_map = {
        "partition": {
            "list": lambda: manager.list_partitions(args.get("table_name")),
            "describe": lambda: manager.describe_partition(args.get("table_name"), args.get("partition_name")),
            "refresh": lambda: manager.refresh_partition(args.get("table_name"), args.get("partition_name")),
        },
        "hierarchy": {
            "list": lambda: manager.list_hierarchies(args.get("table_name")),
            "describe": lambda: manager.describe_hierarchy(args.get("table_name"), args.get("hierarchy_name")),
            "create": lambda: manager.create_hierarchy(
                args.get("table_name"), args.get("hierarchy_name"), args.get("levels", []),
                description=args.get("description"), display_folder=args.get("display_folder"),
                hidden=args.get("hidden")),
            "delete": lambda: manager.delete_hierarchy(args.get("table_name"), args.get("hierarchy_name")),
        },
        "perspective": {
            "list": lambda: manager.list_perspectives(),
            "describe": lambda: manager.describe_perspective(args.get("perspective_name")),
            "create": lambda: manager.create_perspective(args.get("perspective_name"), description=args.get("description")),
            "delete": lambda: manager.delete_perspective(args.get("perspective_name")),
        },
        "culture": {
            "list": lambda: manager.list_cultures(),
            "describe": lambda: manager.describe_culture(args.get("culture_name")),
            "create": lambda: manager.create_culture(args.get("culture_name")),
            "delete": lambda: manager.delete_culture(args.get("culture_name")),
            "set_translation": lambda: manager.set_translation(
                args.get("culture_name"), args.get("object_type_target"), args.get("name"),
                args.get("property_name"), args.get("value"), table_name=args.get("table_name")),
        },
        "named_expression": {
            "list": lambda: manager.list_expressions(),
            "describe": lambda: manager.describe_expression(args.get("expression_name")),
            "create": lambda: manager.create_expression(
                args.get("expression_name"), args.get("expression"), description=args.get("description")),
            "update": lambda: manager.update_expression(
                args.get("expression_name"), args.get("expression"), description=args.get("description")),
            "delete": lambda: manager.delete_expression(args.get("expression_name")),
        },
        "ols_rule": {
            "list": lambda: manager.list_ols_rules(args.get("role_name")),
            "set": lambda: manager.set_ols_rule(
                args.get("role_name"), args.get("table_name"), args.get("column_name"),
                args.get("permission", "None")),
            "remove": lambda: manager.remove_ols_rule(
                args.get("role_name"), args.get("table_name"), args.get("column_name")),
        },
        "model": {
            "refresh": lambda: manager.refresh(
                refresh_type=args.get("refresh_type", "automatic"),
                tables=args.get("tables"),
            ),
        },
    }
    ops = dispatch_map.get(object_type, {})
    handler_fn = ops.get(operation)
    if not handler_fn:
        return {
            "success": False,
            "error": f"Unknown operation '{operation}' for {object_type}",
            "valid_operations": list(ops.keys()),
        }
    return handler_fn()


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

    # New TOM types don't have execute() — dispatch directly
    if object_type in ("partition", "hierarchy", "perspective", "culture", "named_expression", "ols_rule", "model"):
        return _dispatch_new_type(handler, object_type, args)

    # Existing types use the execute() pattern
    return handler.execute(args)


def register_model_operations_handler(registry):
    """Register unified model operations handler"""
    tool = ToolDefinition(
        name="02_Model_Operations",
        description="Unified CRUD for tables, columns, measures, relationships, calculation groups, partitions, hierarchies, perspectives, cultures, named expressions, and OLS rules. Specify object_type + operation.",
        handler=handle_model_operations,
        input_schema={
            "type": "object",
            "properties": {
                "object_type": {
                    "type": "string",
                    "enum": ["table", "column", "measure", "relationship", "calculation_group",
                             "partition", "hierarchy", "perspective", "culture", "named_expression", "ols_rule", "model"],
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
                # Partition-specific
                "partition_name": {"type": "string", "description": "Partition name"},
                # Hierarchy-specific
                "hierarchy_name": {"type": "string", "description": "Hierarchy name"},
                "levels": {
                    "type": "array",
                    "description": "Hierarchy levels (create)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "column": {"type": "string"}
                        }
                    }
                },
                # Perspective-specific
                "perspective_name": {"type": "string", "description": "Perspective name"},
                # Culture-specific
                "culture_name": {"type": "string", "description": "Culture name (e.g. 'fr-FR')"},
                "object_type_target": {
                    "type": "string",
                    "enum": ["table", "column", "measure", "hierarchy"],
                    "description": "Target object type (set_translation)"
                },
                "property_name": {
                    "type": "string",
                    "enum": ["caption", "description", "display_folder"],
                    "description": "Property to translate (set_translation)"
                },
                "value": {"type": "string", "description": "Translation value"},
                # Named expression-specific
                "expression_name": {"type": "string", "description": "Named expression name"},
                # OLS-specific
                "role_name": {"type": "string", "description": "Security role name"},
                "permission": {
                    "type": "string",
                    "enum": ["None", "Read", "Default"],
                    "description": "OLS permission level"
                },
                # Refresh-specific (object_type=model or table/partition refresh)
                "refresh_type": {
                    "type": "string",
                    "enum": ["full", "automatic", "dataOnly", "calculate", "clearValues", "defragment"],
                    "description": "Refresh type (model/table refresh). 'automatic' picks the minimal required refresh; 'calculate' recomputes calculated tables/columns (use for field parameters); 'full' reprocesses everything.",
                    "default": "automatic"
                },
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Table names to refresh (object_type=model, operation=refresh). Omit to refresh entire model."
                },
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
