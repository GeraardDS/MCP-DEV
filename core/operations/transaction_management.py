"""
Transaction management handler

NOTE: This is an operation-tracking system, NOT true ACID transactions.
Begin/commit/rollback only update in-memory status flags — they do NOT
undo or atomically apply model changes. Model writes via TOM are applied
immediately when the individual operation handlers execute. The transaction
record tracks which operations were performed within a logical group, but
rollback does not reverse those operations.

For true transactional model changes, use the Tabular Editor CLI or the
TOM BeginUpdate/EndUpdate pattern via C# scripting.
"""
from typing import Dict, Any
import logging
import threading
from .base_operations import BaseOperationsHandler
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler
import uuid
import time

logger = logging.getLogger(__name__)

# Simple in-memory transaction tracker (would be persisted in production)
_active_transactions: Dict[str, Dict[str, Any]] = {}
_transaction_lock = threading.RLock()

# Transaction timeout: auto-expire stale transactions
_TRANSACTION_TIMEOUT_SECONDS = 3600  # 1 hour

class TransactionManagementHandler(BaseOperationsHandler):
    """Handles transaction management operations"""

    def __init__(self):
        super().__init__("manage_transactions")

        # Register all operations
        self.register_operation('begin', self._begin_transaction)
        self.register_operation('commit', self._commit_transaction)
        self.register_operation('rollback', self._rollback_transaction)
        self.register_operation('status', self._get_status)
        self.register_operation('list_active', self._list_active)

    def _cleanup_expired_transactions(self) -> int:
        """Remove transactions that have exceeded the timeout. Must be called with lock held."""
        now = time.time()
        expired = [
            tid for tid, txn in _active_transactions.items()
            if txn['status'] == 'active' and (now - txn['started_at']) > _TRANSACTION_TIMEOUT_SECONDS
        ]
        for tid in expired:
            _active_transactions[tid]['status'] = 'expired'
            del _active_transactions[tid]
            logger.warning(f"Transaction {tid} expired after {_TRANSACTION_TIMEOUT_SECONDS}s")
        return len(expired)

    def _begin_transaction(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Begin a new transaction"""
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        # Generate transaction ID
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"

        with _transaction_lock:
            # Cleanup expired transactions first
            self._cleanup_expired_transactions()

            # Create transaction record
            _active_transactions[transaction_id] = {
                'id': transaction_id,
                'status': 'active',
                'started_at': time.time(),
                'operations': [],
                'connection_name': args.get('connection_name', 'default')
            }

        logger.info(f"Started transaction: {transaction_id}")

        return {
            'success': True,
            'transaction_id': transaction_id,
            'status': 'active',
            'message': f'Transaction {transaction_id} started. Use this ID for commit/rollback operations.'
        }

    def _commit_transaction(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Commit a transaction"""
        transaction_id = args.get('transaction_id')

        if not transaction_id:
            return {
                'success': False,
                'error': 'transaction_id parameter is required for operation: commit'
            }

        with _transaction_lock:
            if transaction_id not in _active_transactions:
                return {
                    'success': False,
                    'error': f'Transaction not found: {transaction_id}',
                    'suggestion': 'Use list_active operation to see active transactions'
                }

            transaction = _active_transactions[transaction_id]

            if transaction['status'] != 'active':
                return {
                    'success': False,
                    'error': f'Transaction is not active (status: {transaction["status"]})'
                }

            # Mark as committed
            transaction['status'] = 'committed'
            transaction['committed_at'] = time.time()
            operations_count = len(transaction['operations'])

            # Clean up after commit
            del _active_transactions[transaction_id]

        logger.info(f"Committed transaction: {transaction_id}")

        return {
            'success': True,
            'transaction_id': transaction_id,
            'status': 'committed',
            'message': f'Transaction {transaction_id} committed successfully',
            'operations_count': operations_count
        }

    def _rollback_transaction(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mark a transaction as rolled back.

        WARNING: This only updates the tracking record's status. It does NOT
        reverse any model changes that were made during the transaction.
        Model writes via TOM are applied immediately and cannot be undone here.
        """
        transaction_id = args.get('transaction_id')

        if not transaction_id:
            return {
                'success': False,
                'error': 'transaction_id parameter is required for operation: rollback'
            }

        with _transaction_lock:
            if transaction_id not in _active_transactions:
                return {
                    'success': False,
                    'error': f'Transaction not found: {transaction_id}'
                }

            transaction = _active_transactions[transaction_id]

            if transaction['status'] != 'active':
                return {
                    'success': False,
                    'error': f'Transaction is not active (status: {transaction["status"]})'
                }

            # Mark as rolled back
            transaction['status'] = 'rolled_back'
            transaction['rolled_back_at'] = time.time()
            operations_count = len(transaction['operations'])

            # Clean up after rollback
            del _active_transactions[transaction_id]

        logger.info(f"Rolled back transaction: {transaction_id}")

        return {
            'success': True,
            'transaction_id': transaction_id,
            'status': 'rolled_back',
            'message': f'Transaction {transaction_id} marked as rolled back (tracking only — model changes are NOT reversed)',
            'operations_count': operations_count
        }

    def _get_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get transaction status"""
        transaction_id = args.get('transaction_id')

        if not transaction_id:
            return {
                'success': False,
                'error': 'transaction_id parameter is required for operation: status'
            }

        with _transaction_lock:
            if transaction_id not in _active_transactions:
                return {
                    'success': False,
                    'error': f'Transaction not found: {transaction_id}',
                    'note': 'Transaction may have been committed or rolled back'
                }

            transaction = _active_transactions[transaction_id]

            return {
                'success': True,
                'transaction': {
                    'id': transaction['id'],
                    'status': transaction['status'],
                    'started_at': transaction['started_at'],
                    'operations_count': len(transaction['operations']),
                    'duration_seconds': round(time.time() - transaction['started_at'], 2)
                }
            }

    def _list_active(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all active transactions"""
        with _transaction_lock:
            # Cleanup expired first
            self._cleanup_expired_transactions()

            active_txns = []
            for txn_id, txn in _active_transactions.items():
                active_txns.append({
                    'id': txn['id'],
                    'status': txn['status'],
                    'started_at': txn['started_at'],
                    'operations_count': len(txn['operations']),
                    'duration_seconds': round(time.time() - txn['started_at'], 2)
                })

        return {
            'success': True,
            'active_transaction_count': len(active_txns),
            'transactions': active_txns
        }
