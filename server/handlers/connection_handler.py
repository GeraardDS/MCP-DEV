"""
Connection Handler
Simplified - just the 2 essential connection tools
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

def handle_detect_powerbi_desktop(args: Dict[str, Any]) -> Dict[str, Any]:
    """Detect running Power BI Desktop instances"""
    try:
        connection_manager = connection_state.connection_manager
        if not connection_manager:
            return ErrorHandler.handle_manager_unavailable('connection_manager')

        instances = connection_manager.detect_instances()
        return {
            'success': True,
            'instances': instances,
            'count': len(instances)
        }
    except Exception as e:
        logger.error(f"Error detecting instances: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('detect_powerbi_desktop', e)

def handle_connect_to_powerbi(args: Dict[str, Any]) -> Dict[str, Any]:
    """Connect to Power BI Desktop instance"""
    try:
        connection_manager = connection_state.connection_manager
        if not connection_manager:
            return ErrorHandler.handle_manager_unavailable('connection_manager')

        model_index = args.get('model_index', 0)

        # Auto-detect if not connected
        instances = connection_manager.detect_instances()
        if not instances:
            return {
                'success': False,
                'error': 'No Power BI Desktop instances detected',
                'error_type': 'no_instances'
            }

        # Connect
        result = connection_manager.connect(model_index)
        if result.get('success'):
            # Initialize managers
            connection_state.set_connection_manager(connection_manager)
            connection_state.initialize_managers()

            # Store PBIP/PBIX file information for visual debugger integration
            try:
                if model_index < len(instances):
                    instance = instances[model_index]
                    pbip_folder = instance.get('pbip_folder_path')
                    file_path = instance.get('file_full_path')
                    file_type = instance.get('file_type')

                    if pbip_folder or file_path:
                        connection_state.set_pbip_info(
                            pbip_folder_path=pbip_folder,
                            file_full_path=file_path,
                            file_type=file_type,
                            source='auto-detected'
                        )
                        result['pbip_info'] = connection_state.get_pbip_info()
                        if pbip_folder:
                            logger.info(f"PBIP folder auto-detected: {pbip_folder}")
            except Exception as pbip_error:
                logger.warning(f"Failed to store PBIP info (non-critical): {pbip_error}")

            # PERFORMANCE: Pre-warm table mapping cache to eliminate first-request latency
            try:
                qe = connection_state.query_executor
                if qe and hasattr(qe, '_ensure_table_mappings'):
                    logger.info("Pre-warming table mapping cache...")
                    qe._ensure_table_mappings()
                    logger.info("Table mapping cache pre-warmed successfully")
            except Exception as cache_error:
                logger.warning(f"Failed to pre-warm cache (non-critical): {cache_error}")
                # Don't fail connection if cache pre-warming fails

        return result

    except Exception as e:
        logger.error(f"Error connecting: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('connect_to_powerbi', e)

def register_connection_handlers(registry):
    """Register connection handlers"""
    tools = [
        ToolDefinition(
            name="01_Detect_PBI_Instances",
            description="[01_Connection] Detect running Power BI Desktop instances",
            handler=handle_detect_powerbi_desktop,
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            category="core",
            sort_order=10
        ),
        ToolDefinition(
            name="01_Connect_To_Instance",
            description="[01_Connection] Connect to Power BI Desktop (auto-detect or specify model_index)",
            handler=handle_connect_to_powerbi,
            input_schema={
                "type": "object",
                "properties": {
                    "model_index": {"type": "integer", "description": "Index of the model to connect to (default: 0)"}
                },
                "required": []
            },
            category="core",
            sort_order=11
        ),
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} connection handlers")
