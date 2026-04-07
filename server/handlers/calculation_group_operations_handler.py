"""
Calculation Group Operations Handler
Unified handler for all calculation group operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.calculation_group_operations import CalculationGroupOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_calc_group_ops_handler = CalculationGroupOperationsHandler()

def handle_calculation_group_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified calculation group operations"""
    return _calc_group_ops_handler.execute(args)

def register_calculation_group_operations_handler(registry):
    """Register calculation group operations handler"""

    tool = ToolDefinition(
        name="02_Calculation_Group_Operations",
        description="Unified calculation group CRUD: list, list_items, create, delete.",
        handler=handle_calculation_group_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "create", "delete", "list_items"],
                },
                "group_name": {
                    "type": "string",
                    "description": "Group name (required except list)"
                },
                "items": {
                    "type": "array",
                    "description": "Calculation items (create)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "expression": {"type": "string"},
                            "ordinal": {"type": "integer"}
                        }
                    }
                },
                "description": {
                    "type": "string",
                    "description": "Group description (create)"
                },
                "precedence": {
                    "type": "integer",
                    "description": "Precedence value (create)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=24,  # 02 = Model Operations
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )

    registry.register(tool)
    logger.info("Registered calculation_group_operations handler")
