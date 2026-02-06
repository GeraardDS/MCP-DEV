"""
Central Tool Dispatcher
Routes tool calls to appropriate handlers with error handling.
Supports both sync and async dispatch to avoid blocking the event loop.
"""
from typing import Dict, Any
import asyncio
import logging
import threading
from functools import partial
from server.registry import get_registry
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

class ToolDispatcher:
    """Dispatches tool calls to registered handlers. Thread-safe call count."""

    def __init__(self):
        self.registry = get_registry()
        self._call_count = 0
        self._count_lock = threading.Lock()

    def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch a tool call to its handler (synchronous).

        Args:
            tool_name: Name of the tool to invoke
            arguments: Tool arguments

        Returns:
            Result dictionary from the handler
        """
        with self._count_lock:
            self._call_count += 1

        try:
            # Check if tool exists
            if not self.registry.has_tool(tool_name):
                logger.warning(f"Unknown tool requested: {tool_name}")
                return {
                    'success': False,
                    'error': f'Unknown tool: {tool_name}',
                    'error_type': 'unknown_tool',
                    'available_tools': [t.name for t in self.registry.get_all_tools()[:10]]
                }

            # Get handler
            handler = self.registry.get_handler(tool_name)

            # Execute handler
            logger.debug(f"Dispatching tool: {tool_name}")
            result = handler(arguments)

            # Ensure result is a dict
            if not isinstance(result, dict):
                logger.warning(f"Handler for {tool_name} returned non-dict: {type(result)}")
                result = {'success': True, 'result': result}

            return result

        except Exception as e:
            logger.error(f"Error dispatching tool {tool_name}: {e}", exc_info=True)
            return ErrorHandler.handle_unexpected_error(tool_name, e)

    async def dispatch_async(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch a tool call without blocking the async event loop.
        Runs the synchronous handler in a thread pool executor.

        Args:
            tool_name: Name of the tool to invoke
            arguments: Tool arguments

        Returns:
            Result dictionary from the handler
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self.dispatch, tool_name, arguments))

    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics"""
        return {
            'total_calls': self._call_count,
            'registered_tools': len(self.registry.get_all_tools()),
            'categories': self.registry.list_categories()
        }
