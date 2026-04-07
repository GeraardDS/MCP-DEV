"""Tests for TransactionManagementHandler — in-memory transaction tracking.

Covers:
- begin creates transaction
- commit removes transaction
- rollback removes transaction
- status returns correct state
- list_active returns only active
- expired transactions are cleaned up
"""

import time
import pytest
from unittest.mock import patch, MagicMock
from core.operations.transaction_management import (
    TransactionManagementHandler,
    _active_transactions,
    _transaction_lock,
)


@pytest.fixture(autouse=True)
def clean_transactions():
    """Ensure no leftover transactions between tests."""
    with _transaction_lock:
        _active_transactions.clear()
    yield
    with _transaction_lock:
        _active_transactions.clear()


@pytest.fixture
def handler():
    return TransactionManagementHandler()


@pytest.fixture
def mock_connected():
    """Mock connection_state.is_connected() to return True."""
    with patch(
        "core.operations.transaction_management.connection_state"
    ) as mock_cs:
        mock_cs.is_connected.return_value = True
        yield mock_cs


# ---------------------------------------------------------------------------
# Begin
# ---------------------------------------------------------------------------

class TestBeginTransaction:

    def test_begin_creates_transaction(self, handler, mock_connected):
        result = handler._begin_transaction({})
        assert result["success"] is True
        assert "transaction_id" in result
        assert result["status"] == "active"

    def test_begin_generates_unique_ids(self, handler, mock_connected):
        r1 = handler._begin_transaction({})
        r2 = handler._begin_transaction({})
        assert r1["transaction_id"] != r2["transaction_id"]

    def test_begin_requires_connection(self, handler):
        with patch(
            "core.operations.transaction_management.connection_state"
        ) as mock_cs:
            mock_cs.is_connected.return_value = False
            result = handler._begin_transaction({})
            assert result["success"] is False


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

class TestCommitTransaction:

    def test_commit_removes_transaction(self, handler, mock_connected):
        begin = handler._begin_transaction({})
        txn_id = begin["transaction_id"]

        result = handler._commit_transaction({"transaction_id": txn_id})
        assert result["success"] is True
        assert result["status"] == "committed"

        # Transaction should be removed from active list
        with _transaction_lock:
            assert txn_id not in _active_transactions

    def test_commit_missing_id_fails(self, handler, mock_connected):
        result = handler._commit_transaction({})
        assert result["success"] is False
        assert "required" in result["error"].lower()

    def test_commit_unknown_id_fails(self, handler, mock_connected):
        result = handler._commit_transaction({"transaction_id": "txn_nonexistent"})
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_double_commit_fails(self, handler, mock_connected):
        begin = handler._begin_transaction({})
        txn_id = begin["transaction_id"]
        handler._commit_transaction({"transaction_id": txn_id})
        result = handler._commit_transaction({"transaction_id": txn_id})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

class TestRollbackTransaction:

    def test_rollback_removes_transaction(self, handler, mock_connected):
        begin = handler._begin_transaction({})
        txn_id = begin["transaction_id"]

        result = handler._rollback_transaction({"transaction_id": txn_id})
        assert result["success"] is True
        assert result["status"] == "rolled_back"

        with _transaction_lock:
            assert txn_id not in _active_transactions

    def test_rollback_missing_id_fails(self, handler, mock_connected):
        result = handler._rollback_transaction({})
        assert result["success"] is False

    def test_rollback_unknown_id_fails(self, handler, mock_connected):
        result = handler._rollback_transaction({"transaction_id": "txn_ghost"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestGetStatus:

    def test_status_returns_active(self, handler, mock_connected):
        begin = handler._begin_transaction({})
        txn_id = begin["transaction_id"]

        result = handler._get_status({"transaction_id": txn_id})
        assert result["success"] is True
        assert result["transaction"]["status"] == "active"

    def test_status_after_commit_not_found(self, handler, mock_connected):
        begin = handler._begin_transaction({})
        txn_id = begin["transaction_id"]
        handler._commit_transaction({"transaction_id": txn_id})

        result = handler._get_status({"transaction_id": txn_id})
        assert result["success"] is False

    def test_status_missing_id_fails(self, handler, mock_connected):
        result = handler._get_status({})
        assert result["success"] is False

    def test_status_includes_duration(self, handler, mock_connected):
        begin = handler._begin_transaction({})
        txn_id = begin["transaction_id"]
        result = handler._get_status({"transaction_id": txn_id})
        assert "duration_seconds" in result["transaction"]


# ---------------------------------------------------------------------------
# List Active
# ---------------------------------------------------------------------------

class TestListActive:

    def test_list_empty_when_none(self, handler, mock_connected):
        result = handler._list_active({})
        assert result["success"] is True
        assert result["active_transaction_count"] == 0

    def test_list_returns_active_only(self, handler, mock_connected):
        handler._begin_transaction({})
        b2 = handler._begin_transaction({})
        handler._commit_transaction({"transaction_id": b2["transaction_id"]})

        result = handler._list_active({})
        assert result["active_transaction_count"] == 1

    def test_list_returns_multiple(self, handler, mock_connected):
        handler._begin_transaction({})
        handler._begin_transaction({})
        handler._begin_transaction({})

        result = handler._list_active({})
        assert result["active_transaction_count"] == 3


# ---------------------------------------------------------------------------
# Expiration
# ---------------------------------------------------------------------------

class TestExpiration:

    def test_expired_transaction_cleaned(self, handler, mock_connected):
        begin = handler._begin_transaction({})
        txn_id = begin["transaction_id"]

        # Manually set started_at to the past
        with _transaction_lock:
            _active_transactions[txn_id]["started_at"] = time.time() - 7200

        # Trigger cleanup
        result = handler._list_active({})
        assert result["active_transaction_count"] == 0
