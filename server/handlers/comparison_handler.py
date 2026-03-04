"""
Comparison Handler
Handles model comparison operations with workflow templates
"""
from typing import Dict, Any
import logging
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

def handle_compare_pbi_models(args: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two Power BI models - detects instances and compares them"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    connection_manager = connection_state.connection_manager
    if not connection_manager:
        return ErrorHandler.handle_manager_unavailable('connection_manager')

    # STEP 1: Detect all instances (integrated from prepare_model_comparison)
    # Note: detect_instances() returns a List[Dict], not a wrapped dictionary
    instances = connection_manager.detect_instances()

    if not instances or len(instances) < 2:
        return {
            'success': False,
            'error': 'Need at least 2 Power BI Desktop instances running for comparison',
            'detected_instances': len(instances) if instances else 0,
            'instruction': 'Please open both Power BI models in separate Desktop instances',
            'workflow': {
                'name': 'Model Comparison',
                'status': 'insufficient_instances',
                'note': 'At least 2 Power BI Desktop instances are required'
            }
        }

    # Get parameters
    old_port = args.get('old_port')
    new_port = args.get('new_port')

    # If ports not provided, return instances list and ask user to specify
    if not old_port or not new_port:
        pass  # fall through to the block below
    else:
        # Validate port values
        try:
            old_port = int(old_port)
            new_port = int(new_port)
        except (ValueError, TypeError):
            return {
                'success': False,
                'error': 'old_port and new_port must be valid integers',
                'error_type': 'invalid_input'
            }
        if not (1 <= old_port <= 65535) or not (1 <= new_port <= 65535):
            return {
                'success': False,
                'error': 'Port numbers must be between 1 and 65535',
                'error_type': 'invalid_input'
            }
        if old_port == new_port:
            return {
                'success': False,
                'error': 'old_port and new_port must be different instances',
                'error_type': 'invalid_input'
            }

    if not old_port or not new_port:
        return {
            'success': True,
            'message': 'Models detected. Please specify which is OLD and which is NEW',
            'instances': instances,
            'detected_models': len(instances),
            'instruction': 'Call this tool again with old_port and new_port parameters',
            'workflow': {
                'name': 'Model Comparison',
                'status': 'awaiting_user_input',
                'instances': [
                    {
                        'index': i,
                        'port': inst.get('port'),
                        'name': inst.get('model_name', 'Unknown'),
                        'file_path': inst.get('file_path', 'Unknown')
                    }
                    for i, inst in enumerate(instances)
                ],
                'required_input': 'old_port and new_port parameters'
            }
        }

    # STEP 2: Compare models using orchestrator
    try:
        from core.comparison.model_comparison_orchestrator import ModelComparisonOrchestrator
        orchestrator = ModelComparisonOrchestrator()

        result = orchestrator.compare_models(old_port, new_port)

        # Add workflow completion status
        if result.get('success'):
            result['workflow'] = {
                'name': 'Model Comparison',
                'status': 'completed',
                'summary': f'Compared models (old: {old_port}, new: {new_port})',
                'next_recommendations': [
                    {
                        'action': 'Document comparison results',
                        'tool': 'generate_model_documentation_word',
                        'description': 'Create a Word document with comparison findings'
                    }
                ]
            }

        return result

    except ImportError as e:
        logger.error(f"Import error in model comparison: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Model comparison module not available: {str(e)}',
            'error_type': 'import_error',
            'workflow': {
                'name': 'Model Comparison',
                'status': 'error',
                'error': 'Comparison feature not available'
            }
        }
    except Exception as e:
        logger.error(f"Error comparing models: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error comparing models: {str(e)}',
            'workflow': {
                'name': 'Model Comparison',
                'status': 'error',
                'error': str(e)
            }
        }


# Note: register_comparison_handlers() was removed — handle_compare_pbi_models is
# used by analysis_handler.py (06_Analysis_Operations.compare).
