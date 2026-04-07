"""
DEPRECATED — This handler is no longer registered.
All operations are now routed through model_operations_handler.py → 02_Model_Operations.
The core operations classes (TableOperationsHandler, etc.) are still used by the unified handler.
This file is kept for reference only.
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
        description="Unified table CRUD: list, describe, sample_data, create, update, delete, refresh, generate_calendar.",
        handler=handle_table_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "describe", "sample_data", "create", "update", "delete", "refresh", "generate_calendar"],
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (required for most ops except list; default 'Date' for generate_calendar)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New name (update)"
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
                    "description": "Max rows (default: 10, max: 1000, sample_data)",
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
                },
                "start_year": {
                    "type": "integer",
                    "description": "Start year for calendar (generate_calendar, default: current year - 5)"
                },
                "end_year": {
                    "type": "integer",
                    "description": "End year for calendar (generate_calendar, default: current year + 2)"
                },
                "include_fiscal": {
                    "type": "boolean",
                    "description": "Include fiscal year columns (generate_calendar, default: false)"
                },
                "fiscal_start_month": {
                    "type": "integer",
                    "description": "Fiscal year start month 1-12 (generate_calendar, default: 7 for July)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=20,
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )

    registry.register(tool)
    logger.info("Registered table_operations handler")
