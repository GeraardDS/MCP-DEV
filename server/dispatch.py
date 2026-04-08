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
from core.config.config_manager import config

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

            # Security gates (read-only mode + destructive confirmation)
            read_only = config.get('security.read_only_mode', False)
            confirm_destructive = config.get('security.confirm_destructive', False)

            if read_only or confirm_destructive:
                tool_def = self.registry.get_tool_def(tool_name)
                annotations = tool_def.annotations or {}

                # Read-only mode enforcement
                if read_only and not annotations.get('readOnlyHint', False):
                    logger.warning(
                        f"Read-only mode: blocked tool '{tool_name}'"
                    )
                    return {
                        'success': False,
                        'error': f'Tool "{tool_name}" blocked: server is in read-only mode',
                        'error_type': 'read_only_mode'
                    }

                # Confirmation gate for destructive operations
                if (
                    confirm_destructive
                    and annotations.get('destructiveHint')
                    and not arguments.get('confirmed', False)
                ):
                    logger.info(
                        f"Confirmation gate: blocked '{tool_name}' "
                        f"(operation={arguments.get('operation', 'N/A')})"
                    )
                    return {
                        'success': False,
                        'error_type': 'confirmation_required',
                        'message': (
                            f'Tool "{tool_name}" is destructive. '
                            f'Re-call with confirmed=true to proceed.'
                        ),
                        'tool': tool_name,
                        'operation': arguments.get('operation', 'unknown'),
                        'args_received': {
                            k: v for k, v in arguments.items()
                            if k != 'confirmed'
                        },
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
