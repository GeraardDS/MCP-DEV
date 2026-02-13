"""
Role Operations Handler
Unified handler for all RLS/OLS role operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.role_operations import RoleOperationsHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_role_ops_handler = RoleOperationsHandler()

def handle_role_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified role operations"""
    return _role_ops_handler.execute(args)

def register_role_operations_handler(registry):
    """Register role operations handler"""

    tool = ToolDefinition(
        name="02_Role_Operations",
        description="RLS/OLS security role operations: list roles with permissions.",
        handler=handle_role_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list"],
                    "description": (
                        "Operation to perform:\n"
                        "• 'list' - List all security roles (RLS/OLS)\n"
                        "Note: Additional operations (create, update, delete, rename, create_permission, etc.) will be available when implemented."
                    )
                },
                "role_name": {
                    "type": "string",
                    "description": "Role name (required for most operations)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New role name (required for: rename)"
                },
                "definition": {
                    "type": "object",
                    "description": "Role definition (required for: create, update)"
                },
                "permission": {
                    "type": "object",
                    "description": "Permission definition (required for: create_permission, update_permission)",
                    "properties": {
                        "table_name": {"type": "string"},
                        "filter_expression": {"type": "string"}
                    }
                },
                "table_name": {
                    "type": "string",
                    "description": "Table name (required for: delete_permission, test_role)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=25  # 02 = Model Operations
    )

    registry.register(tool)
    logger.info("Registered role_operations handler")
