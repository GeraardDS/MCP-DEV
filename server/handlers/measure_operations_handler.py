"""
DEPRECATED — This handler is no longer registered.
All operations are now routed through model_operations_handler.py → 02_Model_Operations.
The core operations classes (TableOperationsHandler, etc.) are still used by the unified handler.
This file is kept for reference only.
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
        description="Unified measure CRUD: list (names only), get (with DAX), create, update, delete, rename, move.",
        handler=handle_measure_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete", "rename", "move"],
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (optional for list)"
                },
                "measure_name": {
                    "type": "string",
                    "description": "Measure name (required except list)"
                },
                "expression": {
                    "type": "string",
                    "description": "DAX expression (create, update)"
                },
                "description": {
                    "type": "string",
                    "description": "Measure description (create, update)"
                },
                "format_string": {
                    "type": "string",
                    "description": "Format string (create, update)"
                },
                "display_folder": {
                    "type": "string",
                    "description": "Display folder (create, update)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Page size (list)"
                },
                "next_token": {
                    "type": "string",
                    "description": "Pagination token (list)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New name (rename)"
                },
                "new_table": {
                    "type": "string",
                    "description": "Target table (move)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=22,  # 02 = Model Operations
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )

    registry.register(tool)
    logger.info("Registered measure_operations handler")
