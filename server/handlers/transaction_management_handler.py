"""
INTERNAL HELPER — Not a registered MCP tool.
Provides helper functions consumed by active handlers.

Used by batch_operations_handler for transaction support.
Transaction tracking is in-memory only (not true ACID).
"""
from typing import Dict, Any
import logging
from core.operations.transaction_management import TransactionManagementHandler

logger = logging.getLogger(__name__)

# Create singleton instance
_transaction_mgmt_handler = TransactionManagementHandler()

def handle_manage_transactions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle transaction management operations"""
    return _transaction_mgmt_handler.execute(args)
