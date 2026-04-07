"""
Error handling utilities for PBIXRay MCP Server
"""

import functools
import logging
from typing import Any, Dict, Callable, Optional
from core.validation.error_response import ErrorResponse

logger = logging.getLogger(__name__)


def safe_tool_execution(fallback_error: str = "Tool not available"):
    """
    Decorator to handle common tool execution patterns with proper error handling.
    
    Args:
        fallback_error: Default error message when tool is not available
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Dict[str, Any]:
            try:
                result = func(*args, **kwargs)
                
                # Ensure result is properly formatted
                if not isinstance(result, dict):
                    return {
                        'success': True,
                        'data': result
                    }
                
                return result
                
            except ConnectionError as e:
                logger.error(f"Connection error in {func.__name__}: {e}")
                return ErrorResponse(
                    error=f'Connection error: {str(e)}',
                    error_type='connection_error',
                    suggestions=[
                        'Check Power BI Desktop connection',
                        'Verify instance is still running'
                    ]
                ).to_dict()
            except ValueError as e:
                logger.error(f"Value error in {func.__name__}: {e}")
                return ErrorResponse(
                    error=f'Invalid parameter: {str(e)}',
                    error_type='parameter_error'
                ).to_dict()
            except Exception as e:
                logger.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
                return ErrorResponse(
                    error=f'Unexpected error: {str(e)}',
                    error_type='unexpected_error',
                    context={'tool_name': func.__name__}
                ).to_dict()
        
        return wrapper
    return decorator


def require_connection(func: Callable) -> Callable:
    """
    Decorator to ensure a Power BI connection is active before executing a tool.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not hasattr(self, 'connection_manager') or not self.connection_manager.is_connected():
            return ErrorResponse(
                error='Not connected to Power BI Desktop',
                error_type='not_connected',
                suggestions=[
                    'Use detect_powerbi_desktop to find instances',
                    'Use connect_to_powerbi to establish connection'
                ]
            ).to_dict()
        
        return func(self, *args, **kwargs)
    
    return wrapper


def validate_manager(manager_name: str, error_message: Optional[str] = None):
    """
    Decorator to validate that a required manager is available.
    
    Args:
        manager_name: Name of the manager attribute to check
        error_message: Custom error message if manager is not available
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            manager = getattr(self, manager_name, None)
            if not manager:
                return ErrorResponse(
                    error=error_message or f'{manager_name} not available',
                    error_type='manager_unavailable',
                    context={'required_manager': manager_name}
                ).to_dict()
            
            return func(self, *args, **kwargs)
        
        return wrapper
    return decorator


class ErrorHandler:
    """
    Centralized error handling for common patterns.
    """
    
    @staticmethod
    def handle_manager_unavailable(manager_name: str) -> Dict[str, Any]:
        """Standard response when a manager is not available."""
        # Map manager names to user-friendly descriptions and recovery steps
        manager_details = {
            'connection_manager': {
                'description': 'Connection Manager handles Power BI Desktop connections',
                'likely_cause': 'Server initialization incomplete or connection not established',
                'recovery_steps': [
                    '1. Try disconnecting and reconnecting',
                    '2. Restart the MCP server',
                    '3. Check if Power BI Desktop is still running'
                ]
            },
            'query_executor': {
                'description': 'Query Executor runs DAX queries and DMV queries',
                'likely_cause': 'Connection to Power BI not established or connection lost',
                'recovery_steps': [
                    '1. Run connect_to_powerbi to establish connection',
                    '2. Verify Power BI Desktop is responsive',
                    '3. Check if the model is still loaded'
                ]
            },
            'agent_policy': {
                'description': 'Agent Policy manages tool execution policies and limits',
                'likely_cause': 'Server not fully initialized',
                'recovery_steps': [
                    '1. Reconnect to Power BI Desktop',
                    '2. Restart the MCP server if issue persists'
                ]
            }
        }

        details = manager_details.get(manager_name, {
            'description': f'{manager_name} is required for this operation',
            'likely_cause': 'Component not initialized',
            'recovery_steps': ['Ensure connection is established']
        })

        return ErrorResponse(
            error=f'{manager_name} not available',
            error_type='manager_unavailable',
            suggestions=[
                'Ensure connection to Power BI Desktop is established',
                'Check if all required services are initialized'
            ],
            context={
                'required_manager': manager_name,
                'description': details['description'],
                'likely_cause': details['likely_cause'],
                'recovery_steps': details['recovery_steps']
            }
        ).to_dict()
    
    @staticmethod
    def handle_not_connected() -> Dict[str, Any]:
        """Standard response when there is no active connection."""
        return ErrorResponse(
            error='Not connected to Power BI Desktop',
            error_type='not_connected',
            suggestions=[
                'Use detect_powerbi_desktop to find instances',
                'Use connect_to_powerbi to establish connection'
            ],
            context={
                'connection_workflow': {
                    'step1': {
                        'tool': 'detect_powerbi_desktop',
                        'description': 'First detect running Power BI instances',
                        'required': False
                    },
                    'step2': {
                        'tool': 'connect_to_powerbi',
                        'description': 'Connect to a specific instance (auto-detects if model_index not provided)',
                        'required': True,
                        'note': 'This tool can auto-detect instances, so detect step is optional'
                    }
                },
                'common_causes': [
                    'No Power BI Desktop instances are running',
                    'Connection was lost or timed out',
                    'Never connected since server started'
                ],
                'troubleshooting': {
                    'if_no_instances': 'Open a .pbix file in Power BI Desktop',
                    'if_connection_lost': 'Try reconnecting with connect_to_powerbi',
                    'if_still_fails': 'Check Power BI Desktop is responsive and the model is loaded'
                }
            }
        ).to_dict()

    @staticmethod
    def handle_unknown_tool(tool_name: str) -> Dict[str, Any]:
        """Standard response for unknown tool invocations."""
        return ErrorResponse(
            error=f'Unknown tool: {tool_name}',
            error_type='unknown_tool',
            context={'tool_name': tool_name}
        ).to_dict()

    @staticmethod
    def handle_connection_error(error: Exception) -> Dict[str, Any]:
        """Standard response for connection errors."""
        error_str = str(error).lower()

        # Provide context-specific guidance based on error message
        context = {
            'error_details': str(error),
            'recovery_steps': []
        }

        if 'timeout' in error_str:
            context['likely_cause'] = 'Power BI Desktop is not responding or is busy'
            context['recovery_steps'] = [
                '1. Check if Power BI Desktop is frozen or busy',
                '2. Wait for any running operations to complete',
                '3. Try reconnecting after a few seconds',
                '4. If issue persists, restart Power BI Desktop'
            ]
        elif 'refused' in error_str or 'could not connect' in error_str:
            context['likely_cause'] = 'Power BI Desktop instance is not available'
            context['recovery_steps'] = [
                '1. Verify Power BI Desktop is still running',
                '2. Check that the model is still open',
                '3. Run detect_powerbi_desktop to find current instances',
                '4. Reconnect using connect_to_powerbi'
            ]
        elif 'authentication' in error_str or 'unauthorized' in error_str:
            context['likely_cause'] = 'Authentication or permission issue'
            context['recovery_steps'] = [
                '1. Check Windows permissions',
                '2. Verify you have access to the model',
                '3. Try running as administrator if needed'
            ]
        else:
            context['likely_cause'] = 'Unknown connection issue'
            context['recovery_steps'] = [
                '1. Verify Power BI Desktop is running',
                '2. Check network connectivity',
                '3. Try reconnecting to the instance',
                '4. Check server logs for more details'
            ]

        return ErrorResponse(
            error=f'Connection error: {str(error)}',
            error_type='connection_error',
            suggestions=[
                'Verify Power BI Desktop is running',
                'Check network connectivity',
                'Try reconnecting to the instance'
            ],
            context=context
        ).to_dict()

    @staticmethod
    def handle_connection_lost(operation_name: str = None, partial_results: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Standard response when connection is lost during an operation.

        Args:
            operation_name: Name of the operation that was interrupted
            partial_results: Any partial results from the interrupted operation

        Returns:
            Error response with reconnection guidance
        """
        context = {
            'likely_cause': 'Connection to Power BI Desktop was lost during operation',
            'recovery_steps': [
                '1. Verify Power BI Desktop is still running',
                '2. Check if the model is still open',
                '3. Use 01_Connection to reconnect',
                '4. Retry the failed operation'
            ],
            'auto_reconnect': 'The server will attempt automatic reconnection on next operation'
        }

        if operation_name:
            context['interrupted_operation'] = operation_name

        if partial_results:
            context['partial_results'] = partial_results

        return ErrorResponse(
            error='Connection lost during operation',
            error_type='connection_lost',
            suggestions=[
                'The connection to Power BI Desktop was unexpectedly closed',
                'Use 01_Connection to re-establish the connection',
                'If this happens frequently, check Power BI Desktop stability'
            ],
            context=context
        ).to_dict()

    @staticmethod
    def handle_reconnection_failed(attempts: int = 3) -> Dict[str, Any]:
        """
        Standard response when automatic reconnection fails.

        Args:
            attempts: Number of reconnection attempts made

        Returns:
            Error response with recovery guidance
        """
        return ErrorResponse(
            error=f'Failed to reconnect after {attempts} attempts',
            error_type='reconnection_failed',
            suggestions=[
                'The server attempted automatic reconnection but failed',
                'Manually reconnect using 01_Connection',
                'Verify Power BI Desktop is running with model open'
            ],
            context={
                'reconnection_attempts': attempts,
                'likely_cause': 'Power BI Desktop may have been closed or crashed',
                'recovery_steps': [
                    '1. Ensure Power BI Desktop is running',
                    '2. Ensure a .pbix file is open',
                    '3. Wait for the model to fully load',
                    '4. Use 01_Connection to verify instance availability',
                    '5. Use 01_Connection to establish new connection'
                ]
            }
        ).to_dict()
    
    @staticmethod
    def handle_validation_error(error: Exception) -> Dict[str, Any]:
        """Standard response for validation errors."""
        return ErrorResponse(
            error=f'Validation error: {str(error)}',
            error_type='validation_error'
        ).to_dict()
    
    @staticmethod
    def handle_unexpected_error(tool_name: str, error: Exception) -> Dict[str, Any]:
        """Standard response for unexpected errors with tool context."""
        import traceback

        error_str = str(error).lower()
        error_type_name = type(error).__name__

        # Provide helpful context based on error type
        context = {
            'tool_name': tool_name,
            'error_type': error_type_name,
            'error_message': str(error)
        }

        # Add specific guidance for common error patterns
        if 'keyerror' in error_type_name.lower():
            context['likely_cause'] = 'Missing required data field or parameter'
            context['suggestion'] = 'This may indicate a data structure mismatch or API change'
        elif 'attributeerror' in error_type_name.lower():
            context['likely_cause'] = 'Object method or property not available'
            context['suggestion'] = 'This may indicate an API version mismatch'
        elif 'typeerror' in error_type_name.lower():
            context['likely_cause'] = 'Incorrect data type or parameter format'
            context['suggestion'] = 'Check parameter types match expected values'
        elif 'valueerror' in error_type_name.lower():
            context['likely_cause'] = 'Invalid parameter value'
            context['suggestion'] = 'Check parameter values are within valid ranges'
        elif 'memory' in error_str or 'out of memory' in error_str:
            context['likely_cause'] = 'Insufficient memory'
            context['suggestion'] = 'Try with smaller data sets or use pagination'
            context['recovery_steps'] = [
                '1. Use limit or page_size parameters to reduce data',
                '2. Close other applications to free memory',
                '3. Consider exporting to file instead of returning large results'
            ]
        else:
            context['likely_cause'] = 'Unexpected internal error'
            context['suggestion'] = 'This is likely a bug - please report with details'

        # Add troubleshooting info
        context['troubleshooting'] = {
            'check_logs': 'Review server logs for detailed stack trace',
            'retry': 'Try the operation again - it may be a transient issue',
            'report': 'If issue persists, report as a bug with error details'
        }

        return ErrorResponse(
            error=f'Unexpected error in {tool_name}: {str(error)}',
            error_type='unexpected_error',
            suggestions=[
                'Check server logs for detailed error information',
                'Try the operation again',
                'Report persistent issues as bugs'
            ],
            context=context
        ).to_dict()

    @staticmethod
    def wrap_result(data: Any, success: bool = True) -> Dict[str, Any]:
        """Wrap raw data in standard response format."""
        if isinstance(data, dict) and 'success' in data:
            return data
        
        return {
            'success': success,
            'data': data
        }