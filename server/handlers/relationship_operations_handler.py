"""
Relationship Operations Handler
Unified handler for all relationship operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.relationship_operations import RelationshipOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_relationship_ops_handler = RelationshipOperationsHandler()

def handle_relationship_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified relationship operations"""
    return _relationship_ops_handler.execute(args)

def register_relationship_operations_handler(registry):
    """Register relationship operations handler"""

    tool = ToolDefinition(
        name="02_Relationship_Operations",
        description="Unified relationship CRUD: list, get, find, create, update, delete, activate, deactivate.",
        handler=handle_relationship_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "get", "find", "create", "update", "delete", "activate", "deactivate"],
                },
                "relationship_name": {
                    "type": "string",
                    "description": "Relationship name (get, update, delete, activate, deactivate)"
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (find)"
                },
                "from_table": {
                    "type": "string",
                    "description": "Source table (create)"
                },
                "from_column": {
                    "type": "string",
                    "description": "Source column (create)"
                },
                "to_table": {
                    "type": "string",
                    "description": "Target table (create)"
                },
                "to_column": {
                    "type": "string",
                    "description": "Target column (create)"
                },
                "name": {
                    "type": "string",
                    "description": "Relationship name (create, auto-generated if omitted)"
                },
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
                "is_active": {
                    "type": "boolean",
                    "description": "Active state (create, update)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New name (update)"
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Active only (list)",
                    "default": False
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
        sort_order=23,  # 02 = Model Operations
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )

    registry.register(tool)
    logger.info("Registered relationship_operations handler")
