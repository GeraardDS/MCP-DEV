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

def handle_reconnect(args: Dict[str, Any]) -> Dict[str, Any]:
    """Re-acquire the ADOMD/TOM connection in-place.

    Use when PBI Desktop's msmdsrv port has changed (process restart, reopen,
    crash+relaunch) or the live connection is stale. Cheaper than
    12_Autonomous_Workflow reload because PBI Desktop is NOT restarted — only
    the connection objects and manager singletons are rebuilt.

    Returns old_port vs new_port + a trivial DMV health check.
    """
    try:
        cm = connection_state.connection_manager
        if not cm:
            return ErrorHandler.handle_manager_unavailable('connection_manager')

        prev_info = connection_state.get_pbip_info() or {}
        prev_file = prev_info.get('file_full_path')
        prev_port = None
        try:
            prev_conn = cm.get_connection()
            prev_cs = getattr(prev_conn, 'ConnectionString', '') if prev_conn else ''
            if 'localhost:' in prev_cs:
                prev_port = prev_cs.split('localhost:')[1].split(';')[0].strip()
        except Exception:
            pass

        instances = cm.detect_instances()
        if not instances:
            return {'success': False, 'error': 'No Power BI Desktop instances detected', 'error_type': 'no_instances'}

        # Prefer the instance whose file_full_path matches the previous session
        target_index = int(args.get('model_index', 0))
        if prev_file:
            for i, inst in enumerate(instances):
                if inst.get('file_full_path') == prev_file:
                    target_index = i
                    break

        result = cm.connect(target_index)
        if not result.get('success'):
            return result

        connection_state.set_connection_manager(cm)
        connection_state.initialize_managers(force_reinit=True)

        # Refresh PBIP info
        try:
            inst = instances[target_index]
            pbip_folder = inst.get('pbip_folder_path')
            file_path = inst.get('file_full_path')
            file_type = inst.get('file_type')
            if pbip_folder or file_path:
                connection_state.set_pbip_info(
                    pbip_folder_path=pbip_folder,
                    file_full_path=file_path,
                    file_type=file_type,
                    source='auto-detected',
                )
        except Exception as pbip_err:
            logger.warning(f"reconnect: failed to refresh pbip info (non-critical): {pbip_err}")

        # Health check via a trivial DMV
        health_ok = False
        health_error = None
        try:
            qe = connection_state.query_executor
            if qe and hasattr(qe, 'execute_info_query'):
                probe = qe.execute_info_query('CATALOGS', top_n=1)
                health_ok = bool(probe.get('success'))
                if not health_ok:
                    health_error = probe.get('error')
        except Exception as he:
            health_error = str(he)

        new_port = None
        try:
            cs = result.get('connection_string', '')
            if 'localhost:' in cs:
                new_port = cs.split('localhost:')[1].split(';')[0].strip()
        except Exception:
            pass

        return {
            'success': True,
            'reconnected': True,
            'port_changed': bool(prev_port and new_port and prev_port != new_port),
            'previous_port': prev_port,
            'new_port': new_port,
            'file': prev_file,
            'model_index': target_index,
            'health_ok': health_ok,
            'health_error': health_error,
            'pbip_info': connection_state.get_pbip_info(),
        }
    except Exception as e:
        logger.error(f"Error reconnecting: {e}", exc_info=True)
        return ErrorHandler.handle_unexpected_error('reconnect', e)


def handle_connection(args: Dict[str, Any]) -> Dict[str, Any]:
    """Unified connection handler"""
    operation = args.get('operation', 'detect')
    if operation == 'detect':
        return handle_detect_powerbi_desktop(args)
    elif operation == 'connect':
        return handle_connect_to_powerbi(args)
    elif operation == 'reconnect':
        return handle_reconnect(args)
    else:
        return {'success': False, 'error': f'Unknown operation: {operation}. Valid: detect, connect, reconnect'}


def register_connection_handlers(registry):
    """Register connection handlers"""
    tool = ToolDefinition(
        name="01_Connection",
        description="Detect running Power BI Desktop instances (detect), connect to one (connect), or reacquire an in-place connection after a port change / PBI restart (reconnect — cheaper than 12_Autonomous_Workflow reload).",
        handler=handle_connection,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["detect", "connect", "reconnect"],
                    "default": "detect"
                },
                "model_index": {
                    "type": "integer",
                    "description": "Index of the model to connect to (default: 0, connect only)"
                }
            },
            "required": []
        },
        category="core",
        sort_order=10,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    registry.register(tool)
    logger.info("Registered connection handler")
