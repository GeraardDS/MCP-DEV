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
                    "enum": ["create", "update", "delete", "rename", "move", "activate", "deactivate", "refresh"],
                    "description": "Batch operation to perform (available operations depend on object type)"
                },
                "items": {
                    "type": "array",
                    "description": "List of object definitions for the operation",
                    "minItems": 1
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
            "required": ["operation", "batch_operation", "items"],
            "examples": [
                {
                    "_description": "Batch create multiple measures (transactional)",
                    "operation": "measures",
                    "batch_operation": "create",
                    "items": [
                        {"table_name": "Sales", "measure_name": "Total Sales", "expression": "SUM(Sales[Amount])"},
                        {"table_name": "Sales", "measure_name": "Avg Sales", "expression": "AVERAGE(Sales[Amount])"},
                        {"table_name": "Sales", "measure_name": "Sales Count", "expression": "COUNTROWS(Sales)"}
                    ],
                    "options": {"use_transaction": True}
                },
                {
                    "_description": "Batch delete measures with dry-run first",
                    "operation": "measures",
                    "batch_operation": "delete",
                    "items": [
                        {"table_name": "Sales", "measure_name": "Old Metric 1"},
                        {"table_name": "Sales", "measure_name": "Old Metric 2"}
                    ],
                    "options": {"dry_run": True}
                },
                {
                    "_description": "Batch rename columns",
                    "operation": "columns",
                    "batch_operation": "rename",
                    "items": [
                        {"table_name": "Customer", "column_name": "CustID", "new_name": "CustomerID"},
                        {"table_name": "Customer", "column_name": "CustName", "new_name": "CustomerName"},
                        {"table_name": "Product", "column_name": "ProdID", "new_name": "ProductID"}
                    ]
                },
                {
                    "_description": "Batch update measure formatting",
                    "operation": "measures",
                    "batch_operation": "update",
                    "items": [
                        {"table_name": "Sales", "measure_name": "Total Sales", "format_string": "$#,0"},
                        {"table_name": "Sales", "measure_name": "Profit Margin", "format_string": "0.0%"}
                    ]
                },
                {
                    "_description": "Batch move measures to dedicated table",
                    "operation": "measures",
                    "batch_operation": "move",
                    "items": [
                        {"table_name": "Sales", "measure_name": "Total Sales", "new_table": "_Measures"},
                        {"table_name": "Sales", "measure_name": "Profit Margin", "new_table": "_Measures"}
                    ]
                },
                {
                    "_description": "Batch create relationships",
                    "operation": "relationships",
                    "batch_operation": "create",
                    "items": [
                        {"from_table": "Sales", "from_column": "CustomerID", "to_table": "Customer", "to_column": "CustomerID"},
                        {"from_table": "Sales", "from_column": "ProductID", "to_table": "Product", "to_column": "ProductID"}
                    ]
                },
                {
                    "_description": "Batch deactivate relationships",
                    "operation": "relationships",
                    "batch_operation": "deactivate",
                    "items": [
                        {"relationship_name": "Sales-Date-ShipDate"},
                        {"relationship_name": "Sales-Date-DueDate"}
                    ]
                },
                {
                    "_description": "Continue on error mode (non-transactional)",
                    "operation": "measures",
                    "batch_operation": "create",
                    "items": [
                        {"table_name": "Sales", "measure_name": "Good Measure", "expression": "SUM(Sales[Amount])"},
                        {"table_name": "Sales", "measure_name": "Might Fail", "expression": "SUM(NonExistent[Column])"}
                    ],
                    "options": {"use_transaction": False, "continue_on_error": True}
                }
            ]
        },
        category="batch",
        sort_order=30  # 03 = Batch & Transactions
    )

    registry.register(tool)
    logger.info("Registered batch_operations handler")
