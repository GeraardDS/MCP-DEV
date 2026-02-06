"""
Handler Factory for unified operation handlers.

This factory reduces handler boilerplate by ~70% across 7 handler files.
Eliminates ~420 lines of duplicated handler registration code.
"""
import logging
from typing import Any, Callable, Dict, List, Optional, Type

from server.registry import ToolDefinition

logger = logging.getLogger(__name__)


def create_unified_handler(
    operation_name: str,
    operations_class: Type,
    tool_definition: Dict[str, Any]
) -> tuple[Callable, Callable]:
    """
    Factory to create unified operation handler boilerplate.

    This creates:
    1. A handler function that routes to the operations class
    2. A registration function that registers the tool with the registry

    Args:
        operation_name: Name of the operation (e.g., 'measure_operations')
        operations_class: The operations handler class to instantiate
        tool_definition: Dictionary with tool definition parameters

    Returns:
        Tuple of (handler_function, registration_function)

    Usage:
        from core.operations.measure_operations import MeasureOperationsHandler

        handle_measure_operations, register_measure_operations = create_unified_handler(
            operation_name='measure_operations',
            operations_class=MeasureOperationsHandler,
            tool_definition={
                'name': 'measure_operations',
                'description': '...',
                'input_schema': {...},
                'category': 'metadata',
                'sort_order': 12
            }
        )
    """
    # Create singleton instance of the operations handler
    handler_instance = operations_class()

    def handle_operation(args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle unified operations"""
        return handler_instance.execute(args)

    def register_operation(registry) -> None:
        """Register the operation handler with the registry"""
        tool = ToolDefinition(
            name=tool_definition['name'],
            description=tool_definition['description'],
            handler=handle_operation,
            input_schema=tool_definition['input_schema'],
            category=tool_definition.get('category', 'operations'),
            sort_order=tool_definition.get('sort_order', 100)
        )
        registry.register(tool)
        logger.info(f"Registered {operation_name} handler")

    return handle_operation, register_operation


class UnifiedHandlerBuilder:
    """
    Builder pattern for creating unified handlers with fluent interface.

    Usage:
        handler, register = (UnifiedHandlerBuilder('measure_operations')
            .with_class(MeasureOperationsHandler)
            .with_description('Unified measure operations...')
            .with_schema({...})
            .with_category('metadata')
            .with_sort_order(12)
            .build())
    """

    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self._operations_class = None
        self._description = ''
        self._input_schema = {}
        self._category = 'operations'
        self._sort_order = 100

    def with_class(self, operations_class: Type) -> 'UnifiedHandlerBuilder':
        """Set the operations handler class."""
        self._operations_class = operations_class
        return self

    def with_description(self, description: str) -> 'UnifiedHandlerBuilder':
        """Set the tool description."""
        self._description = description
        return self

    def with_schema(self, input_schema: Dict[str, Any]) -> 'UnifiedHandlerBuilder':
        """Set the input schema."""
        self._input_schema = input_schema
        return self

    def with_category(self, category: str) -> 'UnifiedHandlerBuilder':
        """Set the tool category."""
        self._category = category
        return self

    def with_sort_order(self, sort_order: int) -> 'UnifiedHandlerBuilder':
        """Set the sort order."""
        self._sort_order = sort_order
        return self

    def build(self) -> tuple[Callable, Callable]:
        """Build and return the handler and registration functions."""
        if not self._operations_class:
            raise ValueError("Operations class is required")

        return create_unified_handler(
            operation_name=self.operation_name,
            operations_class=self._operations_class,
            tool_definition={
                'name': self.operation_name,
                'description': self._description,
                'input_schema': self._input_schema,
                'category': self._category,
                'sort_order': self._sort_order
            }
        )


def create_simple_handler(
    tool_name: str,
    handler_func: Callable,
    description: str,
    input_schema: Dict[str, Any],
    category: str = 'operations',
    sort_order: int = 100
) -> Callable:
    """
    Create a simple registration function for non-unified handlers.

    This is useful for handlers that don't use the unified operations pattern
    but still want to reduce boilerplate.

    Args:
        tool_name: Name of the tool
        handler_func: The handler function
        description: Tool description
        input_schema: Tool input schema
        category: Tool category
        sort_order: Sort order

    Returns:
        Registration function

    Usage:
        def my_handler(args):
            ...

        register_my_handler = create_simple_handler(
            tool_name='my_tool',
            handler_func=my_handler,
            description='...',
            input_schema={...}
        )

        # Later in registration
        register_my_handler(registry)
    """
    def register(registry) -> None:
        tool = ToolDefinition(
            name=tool_name,
            description=description,
            handler=handler_func,
            input_schema=input_schema,
            category=category,
            sort_order=sort_order
        )
        registry.register(tool)
        logger.info(f"Registered {tool_name} handler")

    return register


def create_handler_module(
    operation_name: str,
    operations_class: Type,
    description: str,
    input_schema: Dict[str, Any],
    category: str = 'metadata',
    sort_order: int = 100
) -> Dict[str, Any]:
    """
    Create a complete handler module as a dictionary.

    This returns everything needed for a handler module in a dictionary format.

    Args:
        operation_name: Name of the operation
        operations_class: The operations handler class
        description: Tool description
        input_schema: Tool input schema
        category: Tool category
        sort_order: Sort order

    Returns:
        Dictionary with 'handler', 'register', and 'instance' keys

    Usage:
        module = create_handler_module(
            operation_name='measure_operations',
            operations_class=MeasureOperationsHandler,
            description='...',
            input_schema={...}
        )

        handle_measure_operations = module['handler']
        register_measure_operations_handler = module['register']
    """
    handler_instance = operations_class()

    def handle_operation(args: Dict[str, Any]) -> Dict[str, Any]:
        return handler_instance.execute(args)

    def register_operation(registry) -> None:
        tool = ToolDefinition(
            name=operation_name,
            description=description,
            handler=handle_operation,
            input_schema=input_schema,
            category=category,
            sort_order=sort_order
        )
        registry.register(tool)
        logger.info(f"Registered {operation_name} handler")

    return {
        'handler': handle_operation,
        'register': register_operation,
        'instance': handler_instance
    }


# Pre-built schema templates for common patterns
COMMON_SCHEMAS = {
    'pagination': {
        "page_size": {
            "type": "integer",
            "description": "Page size for list operations"
        },
        "next_token": {
            "type": "string",
            "description": "Pagination token for continuing from previous results"
        }
    },
    'table_name': {
        "table_name": {
            "type": "string",
            "description": "Table name (required for most operations)"
        }
    },
    'crud_common': {
        "description": {
            "type": "string",
            "description": "Description text"
        },
        "hidden": {
            "type": "boolean",
            "description": "Whether to hide from client tools"
        },
        "display_folder": {
            "type": "string",
            "description": "Display folder path"
        }
    },
    'new_name': {
        "new_name": {
            "type": "string",
            "description": "New name for rename operations"
        }
    }
}


def build_input_schema(
    operation_enum: list,
    required: Optional[List[str]] = None,
    **additional_properties
) -> Dict[str, Any]:
    """
    Helper to build input schemas with common patterns.

    Args:
        operation_enum: List of valid operation names
        required: List of required properties
        **additional_properties: Additional properties to include

    Returns:
        Complete input schema dictionary
    """
    schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": operation_enum,
                "description": f"Operation to perform: {', '.join(operation_enum)}"
            },
            **additional_properties
        },
        "required": required or ["operation"]
    }
    return schema


def merge_schemas(*schemas: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge multiple schema property dictionaries.

    Usage:
        properties = merge_schemas(
            COMMON_SCHEMAS['pagination'],
            COMMON_SCHEMAS['table_name'],
            {'my_property': {...}}
        )
    """
    result = {}
    for schema in schemas:
        result.update(schema)
    return result
