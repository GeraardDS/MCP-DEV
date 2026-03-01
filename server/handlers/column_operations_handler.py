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
        description="Unified column CRUD: list, get, statistics, distribution, create, update, delete, rename.",
        handler=handle_column_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "statistics", "distribution", "get", "create", "update", "delete", "rename"],
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (optional for list)"
                },
                "column_name": {
                    "type": "string",
                    "description": "Column name (required except list)"
                },
                "column_type": {
                    "type": "string",
                    "enum": ["all", "data", "calculated"],
                    "description": "Filter type (list)",
                    "default": "all"
                },
                "top_n": {
                    "type": "integer",
                    "description": "Top N values (distribution, default: 10)",
                    "default": 10
                },
                "page_size": {
                    "type": "integer",
                    "description": "Page size (list)"
                },
                "next_token": {
                    "type": "string",
                    "description": "Pagination token (list)"
                },
                "data_type": {
                    "type": "string",
                    "enum": ["String", "Int64", "Double", "Decimal", "Boolean", "DateTime", "Binary", "Variant"],
                    "description": "Data type (create)",
                    "default": "String"
                },
                "expression": {
                    "type": "string",
                    "description": "DAX expression for calculated column (create, update)"
                },
                "description": {
                    "type": "string",
                    "description": "Column description (create, update)"
                },
                "hidden": {
                    "type": "boolean",
                    "description": "Hide column (create, update)"
                },
                "display_folder": {
                    "type": "string",
                    "description": "Display folder path (create, update)"
                },
                "format_string": {
                    "type": "string",
                    "description": "Format string e.g. '#,0' (create, update)"
                },
                "source_column": {
                    "type": "string",
                    "description": "Source column for data columns (create)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New name (rename, update)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=21  # 02 = Model Operations
    )

    registry.register(tool)
    logger.info("Registered column_operations handler")
