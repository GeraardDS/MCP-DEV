"""
Table Operations Handler
Unified handler for all table operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.table_operations import TableOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_table_ops_handler = TableOperationsHandler()

def handle_table_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified table operations"""
    return _table_ops_handler.execute(args)

def register_table_operations_handler(registry):
    """Register table operations handler"""

    tool = ToolDefinition(
        name="02_Table_Operations",
        description="Unified table CRUD: list, describe, preview, sample_data, create, update, delete, rename, refresh.",
        handler=handle_table_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "describe", "preview", "sample_data", "create", "update", "delete", "rename", "refresh"],
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (required for all ops except list)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New name (rename)"
                },
                "description": {
                    "type": "string",
                    "description": "Table description (create, update)"
                },
                "expression": {
                    "type": "string",
                    "description": "DAX expression for calculated table (create, update)"
                },
                "hidden": {
                    "type": "boolean",
                    "description": "Hide table (create, update)"
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Max rows (default: 10, max: 1000, preview/sample_data)",
                    "default": 10
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to include (sample_data)"
                },
                "order_by": {
                    "type": "string",
                    "description": "Order by column (sample_data)"
                },
                "order_direction": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "default": "asc"
                },
                "columns_page_size": {
                    "type": "integer",
                    "description": "Page size for columns (describe)"
                },
                "measures_page_size": {
                    "type": "integer",
                    "description": "Page size for measures (describe)"
                },
                "relationships_page_size": {
                    "type": "integer",
                    "description": "Page size for relationships (describe)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Page size (list)"
                },
                "next_token": {
                    "type": "string",
                    "description": "Pagination token (list)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=20
    )

    registry.register(tool)
    logger.info("Registered table_operations handler")
