"""
Column Operations Handler
Unified handler for all column operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.column_operations import ColumnOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_column_ops_handler = ColumnOperationsHandler()

def handle_column_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified column operations"""
    return _column_ops_handler.execute(args)

def register_column_operations_handler(registry):
    """Register column operations handler"""

    tool = ToolDefinition(
        name="02_Column_Operations",
        description="Unified column CRUD: list, get, statistics, distribution, create, update, delete, rename. See input_schema for operation details.",
        handler=handle_column_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "statistics", "distribution", "get", "create", "update", "delete", "rename"],
                    "description": (
                        "Operation to perform (MUST USE ALL OPERATIONS - don't skip CRUD!):\n"
                        "• 'list' - List columns with optional filters\n"
                        "• 'get' - Get detailed column metadata\n"
                        "• 'statistics' - Get column stats (distinct/total/blank counts)\n"
                        "• 'distribution' - Get top N values with counts\n"
                        "• 'create' - CREATE new column (requires: table_name, column_name; optional: data_type, expression, description, hidden, display_folder, format_string, source_column)\n"
                        "• 'update' - UPDATE column properties (requires: table_name, column_name; optional: expression, description, hidden, display_folder, format_string, new_name)\n"
                        "• 'delete' - DELETE column (requires: table_name, column_name)\n"
                        "• 'rename' - RENAME column (requires: table_name, column_name, new_name)"
                    )
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (optional for list, required for other operations)"
                },
                "column_name": {
                    "type": "string",
                    "description": "Column name (required for: statistics, distribution, get, update, delete, rename)"
                },
                "column_type": {
                    "type": "string",
                    "enum": ["all", "data", "calculated"],
                    "description": "Filter by column type (for list operation)",
                    "default": "all"
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of top values for distribution (default: 10)",
                    "default": 10
                },
                "page_size": {
                    "type": "integer",
                    "description": "Page size for list operation"
                },
                "next_token": {
                    "type": "string",
                    "description": "Pagination token for list operation"
                },
                "data_type": {
                    "type": "string",
                    "enum": ["String", "Int64", "Double", "Decimal", "Boolean", "DateTime", "Binary", "Variant"],
                    "description": "Data type for column (required for: create)",
                    "default": "String"
                },
                "expression": {
                    "type": "string",
                    "description": "DAX expression for calculated column (optional for: create, update). If provided, creates a calculated column instead of a data column."
                },
                "description": {
                    "type": "string",
                    "description": "Column description (optional for: create, update)"
                },
                "hidden": {
                    "type": "boolean",
                    "description": "Whether to hide the column (optional for: create, update)"
                },
                "display_folder": {
                    "type": "string",
                    "description": "Display folder path (optional for: create, update)"
                },
                "format_string": {
                    "type": "string",
                    "description": "Format string like '#,0' or '$#,0.00' (optional for: create, update)"
                },
                "source_column": {
                    "type": "string",
                    "description": "Source column name for data columns (optional for: create)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New column name (required for: rename, optional for: update)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=21  # 02 = Model Operations
    )

    registry.register(tool)
    logger.info("Registered column_operations handler")
