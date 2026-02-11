"""
Measure Operations Handler
Unified handler for all measure operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.measure_operations import MeasureOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_measure_ops_handler = MeasureOperationsHandler()

def handle_measure_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified measure operations"""
    return _measure_ops_handler.execute(args)

def register_measure_operations_handler(registry):
    """Register measure operations handler"""

    tool = ToolDefinition(
        name="02_Measure_Operations",
        description="Unified measure CRUD: list (names only), get (with DAX), create, update, delete, rename, move. Use 'get' to see DAX expressions.",
        handler=handle_measure_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete", "rename", "move"],
                    "description": (
                        "Operation to perform (MUST USE ALL OPERATIONS - don't skip CRUD!):\n"
                        "• 'list' - List measure names (returns NAMES only, no DAX)\n"
                        "• 'get' - Get measure details WITH DAX expression\n"
                        "• 'create' - CREATE new measure (requires: table_name, measure_name, expression; optional: description, format_string, display_folder)\n"
                        "• 'update' - UPDATE measure properties (requires: table_name, measure_name; optional: expression, description, format_string, display_folder)\n"
                        "• 'delete' - DELETE measure (requires: table_name, measure_name)\n"
                        "• 'rename' - RENAME measure (requires: table_name, measure_name, new_name)\n"
                        "• 'move' - MOVE measure to different table (requires: table_name, measure_name, new_table)"
                    )
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (optional for list, required for other operations)"
                },
                "measure_name": {
                    "type": "string",
                    "description": "Measure name (required for: get, update, delete, rename, move)"
                },
                "expression": {
                    "type": "string",
                    "description": "DAX expression (required for: create, update)"
                },
                "description": {
                    "type": "string",
                    "description": "Measure description (optional for: create, update)"
                },
                "format_string": {
                    "type": "string",
                    "description": "Format string (optional for: create, update)"
                },
                "display_folder": {
                    "type": "string",
                    "description": "Display folder (optional for: create, update)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Page size for list operation"
                },
                "next_token": {
                    "type": "string",
                    "description": "Pagination token for list operation"
                },
                "new_name": {
                    "type": "string",
                    "description": "New measure name (required for: rename)"
                },
                "new_table": {
                    "type": "string",
                    "description": "Target table for move operation (required for: move)"
                }
            },
            "required": ["operation"],
            "examples": [
                {
                    "_description": "List all measures in the model",
                    "operation": "list"
                },
                {
                    "_description": "List measures in a specific table",
                    "operation": "list",
                    "table_name": "Sales"
                },
                {
                    "_description": "Get measure details with DAX expression",
                    "operation": "get",
                    "table_name": "Sales",
                    "measure_name": "Total Revenue"
                },
                {
                    "_description": "Create a new measure with formatting",
                    "operation": "create",
                    "table_name": "Sales",
                    "measure_name": "Profit Margin",
                    "expression": "DIVIDE([Gross Profit], [Total Revenue])",
                    "format_string": "0.0%",
                    "display_folder": "Profitability"
                },
                {
                    "_description": "Create simple sum measure",
                    "operation": "create",
                    "table_name": "Sales",
                    "measure_name": "Total Sales",
                    "expression": "SUM(Sales[Amount])",
                    "format_string": "$#,0"
                },
                {
                    "_description": "Update measure expression",
                    "operation": "update",
                    "table_name": "Sales",
                    "measure_name": "Total Revenue",
                    "expression": "SUMX(Sales, Sales[Quantity] * Sales[UnitPrice])"
                },
                {
                    "_description": "Update measure format and folder",
                    "operation": "update",
                    "table_name": "Sales",
                    "measure_name": "Total Revenue",
                    "format_string": "$#,0.00",
                    "display_folder": "Revenue Metrics"
                },
                {
                    "_description": "Delete obsolete measure",
                    "operation": "delete",
                    "table_name": "Sales",
                    "measure_name": "Old Metric"
                },
                {
                    "_description": "Rename measure",
                    "operation": "rename",
                    "table_name": "Sales",
                    "measure_name": "Rev",
                    "new_name": "Total Revenue"
                },
                {
                    "_description": "Move measure to dedicated measures table",
                    "operation": "move",
                    "table_name": "Sales",
                    "measure_name": "Total Revenue",
                    "new_table": "_Measures"
                }
            ]
        },
        category="model",
        sort_order=22  # 02 = Model Operations
    )

    registry.register(tool)
    logger.info("Registered measure_operations handler")
