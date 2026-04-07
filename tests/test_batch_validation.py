"""Tests for batch dry_run validation in BatchOperationsHandler.

Covers:
- dry_run with valid items returns success
- dry_run with missing name returns error
- dry_run with missing expression returns error
- dry_run with missing table returns error
- dry_run for delete operations
- Edge cases: empty items, mixed valid/invalid
"""

import pytest
from unittest.mock import patch
from core.operations.batch_operations import BatchOperationsHandler


@pytest.fixture
def handler():
    return BatchOperationsHandler()


@pytest.fixture
def mock_connected():
    """Mock connection_state.is_connected() to return True."""
    with patch(
        "core.operations.batch_operations.connection_state"
    ) as mock_cs:
        mock_cs.is_connected.return_value = True
        yield mock_cs


# ---------------------------------------------------------------------------
# Valid dry runs
# ---------------------------------------------------------------------------

class TestDryRunValid:

    def test_create_valid_items_succeed(self, handler, mock_connected):
        args = {
            "batch_operation": "create",
            "items": [
                {"name": "Sales YTD", "expression": "TOTALYTD([Sales], 'Date'[Date])", "table": "Measures"},
                {"name": "Cost YTD", "expression": "TOTALYTD([Cost], 'Date'[Date])", "table": "Measures"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["item_count"] == 2

    def test_update_valid_items_succeed(self, handler, mock_connected):
        args = {
            "batch_operation": "update",
            "items": [
                {"name": "Sales", "expression": "SUM('Sales'[Amount])", "table": "Measures"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is True

    def test_delete_valid_items_succeed(self, handler, mock_connected):
        args = {
            "batch_operation": "delete",
            "items": [
                {"name": "Deprecated Measure"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------

class TestDryRunValidationFailures:

    def test_missing_name_fails(self, handler, mock_connected):
        args = {
            "batch_operation": "create",
            "items": [
                {"expression": "SUM(x)", "table": "Measures"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is False
        assert result["dry_run"] is True
        errors = result["validation_errors"]
        assert len(errors) == 1
        assert any("name" in e for e in errors[0]["errors"])

    def test_missing_expression_fails(self, handler, mock_connected):
        args = {
            "batch_operation": "create",
            "items": [
                {"name": "Sales", "table": "Measures"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is False
        errors = result["validation_errors"]
        assert any("expression" in e for e in errors[0]["errors"])

    def test_missing_table_fails(self, handler, mock_connected):
        args = {
            "batch_operation": "create",
            "items": [
                {"name": "Sales", "expression": "SUM(x)"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is False
        errors = result["validation_errors"]
        assert any("table" in e for e in errors[0]["errors"])

    def test_delete_missing_name_fails(self, handler, mock_connected):
        args = {
            "batch_operation": "delete",
            "items": [
                {"table": "Measures"},  # No name
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is False

    def test_mixed_valid_invalid_reports_only_invalid(self, handler, mock_connected):
        args = {
            "batch_operation": "create",
            "items": [
                {"name": "Good", "expression": "SUM(x)", "table": "T"},
                {"expression": "SUM(y)", "table": "T"},  # Missing name
                {"name": "AlsoGood", "expression": "SUM(z)", "table": "T"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is False
        assert len(result["validation_errors"]) == 1
        assert result["validation_errors"][0]["index"] == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestDryRunEdgeCases:

    def test_empty_items_fails(self, handler, mock_connected):
        args = {
            "batch_operation": "create",
            "items": [],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is False

    def test_no_batch_operation_fails(self, handler, mock_connected):
        args = {
            "items": [{"name": "X", "expression": "1", "table": "T"}],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is False

    def test_table_name_alias_accepted(self, handler, mock_connected):
        """Both 'table' and 'table_name' should satisfy the table requirement."""
        args = {
            "batch_operation": "create",
            "items": [
                {"name": "Sales", "expression": "SUM(x)", "table_name": "Measures"},
            ],
            "options": {"dry_run": True},
        }
        result = handler._batch_measures(args)
        assert result["success"] is True

    def test_not_connected_fails(self, handler):
        with patch(
            "core.operations.batch_operations.connection_state"
        ) as mock_cs:
            mock_cs.is_connected.return_value = False
            args = {
                "batch_operation": "create",
                "items": [{"name": "X", "expression": "1", "table": "T"}],
                "options": {"dry_run": True},
            }
            result = handler._batch_measures(args)
            assert result["success"] is False
