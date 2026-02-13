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
                    "description": (
                        "Operation to perform (MUST USE ALL OPERATIONS - don't skip CRUD!):\n"
                        "• 'list' - List all tables\n"
                        "• 'describe' - Get table details with columns/measures/relationships\n"
                        "• 'preview' - Show sample data rows (alias for sample_data with defaults)\n"
                        "• 'sample_data' - Get sample data with optional column selection and ordering\n"
                        "• 'create' - CREATE new table (requires: table_name; optional: description, expression, hidden)\n"
                        "• 'update' - UPDATE table properties (requires: table_name; optional: description, expression, hidden, new_name)\n"
                        "• 'delete' - DELETE table (requires: table_name)\n"
                        "• 'rename' - RENAME table (requires: table_name, new_name)\n"
                        "• 'refresh' - REFRESH table data (requires: table_name)"
                    )
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (required for: describe, preview, sample_data, create, update, delete, rename, refresh)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New table name (required for: rename operation)"
                },
                "description": {
                    "type": "string",
                    "description": "Table description (optional for: create, update)"
                },
                "expression": {
                    "type": "string",
                    "description": "DAX expression for calculated table (optional for: create, update). Example: 'TOPN(100, Customer, [Revenue], DESC)'"
                },
                "hidden": {
                    "type": "boolean",
                    "description": "Hide table from client tools (optional for: create, update)"
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return (default: 10, max: 1000, for preview/sample_data operations)",
                    "default": 10
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of column names to include in sample_data (optional, default: all columns)"
                },
                "order_by": {
                    "type": "string",
                    "description": "Column name to order by (for sample_data operation)"
                },
                "order_direction": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Order direction: 'asc' or 'desc' (default: 'asc', for sample_data operation)",
                    "default": "asc"
                },
                "columns_page_size": {
                    "type": "integer",
                    "description": "Page size for columns in describe operation"
                },
                "measures_page_size": {
                    "type": "integer",
                    "description": "Page size for measures in describe operation"
                },
                "relationships_page_size": {
                    "type": "integer",
                    "description": "Page size for relationships in describe operation"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Page size for list operation"
                },
                "next_token": {
                    "type": "string",
                    "description": "Pagination token for list operation"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=20
    )

    registry.register(tool)
    logger.info("Registered table_operations handler")
