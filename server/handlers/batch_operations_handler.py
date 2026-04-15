"""
Batch Operations Handler
Unified handler for batch operations on model objects
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.batch_operations import BatchOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_batch_ops_handler = BatchOperationsHandler()

def handle_batch_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle batch operations"""
    return _batch_ops_handler.execute(args)

def register_batch_operations_handler(registry):
    """Register batch operations handler"""

    tool = ToolDefinition(
        name="03_Batch_Operations",
        description="Execute batch operations on model objects with transaction support (3-5x faster than individual operations)",
        handler=handle_batch_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["measures", "tables", "columns", "relationships"],
                    "description": "Type of object to operate on (determines which batch handler to use)"
                },
                "batch_operation": {
                    "type": "string",
                    "enum": ["create", "update", "delete", "rename", "move", "move_display_folder", "activate", "deactivate", "refresh"],
                    "description": "Batch operation to perform. move_display_folder: change display folder without needing expression (measures/columns)"
                },
                "items": {
                    "type": "array",
                    "description": "List of object definitions for the operation",
                    "minItems": 1,
                    "items": {"type": "object"}
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "use_transaction": {
                            "type": "boolean",
                            "default": True,
                            "description": "Use transaction for atomic operation (all-or-nothing)"
                        },
                        "continue_on_error": {
                            "type": "boolean",
                            "default": False,
                            "description": "Continue processing remaining items on error (only with use_transaction=false)"
                        },
                        "dry_run": {
                            "type": "boolean",
                            "default": False,
                            "description": "Validate definitions without executing (test mode)"
                        }
                    }
                }
            },
            "required": ["operation", "batch_operation", "items"]
        },
        category="batch",
        sort_order=30,  # 03 = Batch & Transactions
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )

    registry.register(tool)
    logger.info("Registered batch_operations handler")
