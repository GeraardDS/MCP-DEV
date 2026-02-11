"""
Transaction Management Handler
Handles ACID transactions for atomic model changes
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.operations.transaction_management import TransactionManagementHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_transaction_mgmt_handler = TransactionManagementHandler()

def handle_manage_transactions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle transaction management operations"""
    return _transaction_mgmt_handler.execute(args)

def register_transaction_management_handler(registry):
    """Register transaction management handler"""

    tool = ToolDefinition(
        name="03_Manage_Transactions",
        description="Manage ACID transactions for atomic model changes with rollback support",
        handler=handle_manage_transactions,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["begin", "commit", "rollback", "status", "list_active"],
                    "description": "Transaction operation to perform"
                },
                "transaction_id": {
                    "type": "string",
                    "description": "Transaction ID (required for: commit, rollback, status)"
                },
                "connection_name": {
                    "type": "string",
                    "description": "Connection name (optional for: begin)"
                }
            },
            "required": ["operation"]
        },
        category="batch",
        sort_order=31  # 03 = Batch & Transactions
    )

    registry.register(tool)
    logger.info("Registered manage_transactions handler")
