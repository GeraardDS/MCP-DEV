"""
TMDL Operations Handler
Unified handler for all TMDL operations
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

def handle_tmdl_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified TMDL operations"""
    operation = args.get('operation')

    if not operation:
        return {
            'success': False,
            'error': 'operation parameter is required'
        }

    # Route to appropriate handler based on operation
    if operation == 'export':
        return _handle_export(args)
    elif operation == 'find_replace':
        return _handle_find_replace(args)
    elif operation == 'bulk_rename':
        return _handle_bulk_rename(args)
    elif operation == 'generate_script':
        return _handle_generate_script(args)
    elif operation == 'migrate_measures':
        return _handle_migrate_measures(args)
    else:
        return {
            'success': False,
            'error': f'Unknown operation: {operation}'
        }

def _handle_export(args: Dict[str, Any]) -> Dict[str, Any]:
    """Export TMDL definition"""
    if not connection_state.is_connected():
        return ErrorHandler.handle_not_connected()

    model_exporter = connection_state.model_exporter
    if not model_exporter:
        return ErrorHandler.handle_manager_unavailable('model_exporter')

    output_dir = args.get('output_dir')
    return model_exporter.export_tmdl(output_dir)

def _handle_find_replace(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find and replace in TMDL with regex support"""
    tmdl_path = args.get('tmdl_path')
    pattern = args.get('pattern')
    replacement = args.get('replacement')
    dry_run = args.get('dry_run', True)
    regex = args.get('regex', False)
    case_sensitive = args.get('case_sensitive', True)
    target = args.get('target', 'all')

    if not tmdl_path:
        return {
            'success': False,
            'error': 'tmdl_path parameter is required for find_replace operation'
        }

    if not pattern or replacement is None:
        return {
            'success': False,
            'error': 'pattern and replacement parameters are required for find_replace operation'
        }

    try:
        from core.tmdl import TmdlBulkEditor
        editor = TmdlBulkEditor()

        result = editor.replace_in_measures(
            tmdl_path=tmdl_path,
            find=pattern,
            replace=replacement,
            regex=regex,
            case_sensitive=case_sensitive,
            dry_run=dry_run,
            target=target
        )

        return result.to_dict()

    except ImportError as ie:
        logger.error(f"Import error: {ie}", exc_info=True)
        return {
            'success': False,
            'error': 'TmdlBulkEditor not available. This is an internal error.',
            'error_type': 'import_error'
        }
    except FileNotFoundError as fnf:
        return {
            'success': False,
            'error': f'TMDL path not found: {str(fnf)}'
        }
    except Exception as e:
        logger.error(f"Error in TMDL find/replace: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error in TMDL find/replace: {str(e)}'
        }

def _handle_bulk_rename(args: Dict[str, Any]) -> Dict[str, Any]:
    """Bulk rename with reference updates"""
    tmdl_path = args.get('tmdl_path')
    renames = args.get('renames', [])
    dry_run = args.get('dry_run', True)
    update_references = args.get('update_references', True)

    if not tmdl_path:
        return {
            'success': False,
            'error': 'tmdl_path parameter is required for bulk_rename operation'
        }

    if not renames:
        return {
            'success': False,
            'error': 'renames parameter required for bulk_rename operation (array of rename operations with "object_type", "old_name" and "new_name")'
        }

    # Validate and normalize rename operations
    normalized_renames = []
    for i, rename in enumerate(renames):
        if not isinstance(rename, dict):
            return {
                'success': False,
                'error': f'Rename operation {i+1} must be a dictionary'
            }

        # Ensure required fields exist
        if 'old_name' not in rename or 'new_name' not in rename:
            return {
                'success': False,
                'error': f'Rename operation {i+1} must have "old_name" and "new_name" fields'
            }

        # Add object_type if missing (default to measure)
        normalized_rename = {
            'object_type': rename.get('object_type', 'measure'),
            'old_name': rename['old_name'],
            'new_name': rename['new_name']
        }

        # Add optional table_name for measures and columns
        if 'table_name' in rename:
            normalized_rename['table_name'] = rename['table_name']

        normalized_renames.append(normalized_rename)

    try:
        from core.tmdl import TmdlBulkEditor
        editor = TmdlBulkEditor()

        result = editor.bulk_rename(
            tmdl_path=tmdl_path,
            renames=normalized_renames,
            update_references=update_references,
            dry_run=dry_run
        )

        return result.to_dict()

    except ImportError as ie:
        logger.error(f"Import error: {ie}", exc_info=True)
        return {
            'success': False,
            'error': 'TmdlBulkEditor not available. This is an internal error.',
            'error_type': 'import_error'
        }
    except FileNotFoundError as fnf:
        return {
            'success': False,
            'error': f'TMDL path not found: {str(fnf)}'
        }
    except Exception as e:
        logger.error(f"Error in TMDL bulk rename: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error in TMDL bulk rename: {str(e)}'
        }

def _handle_generate_script(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate TMDL script from definition"""
    definition = args.get('definition')
    object_type = args.get('object_type', 'table')  # table, measure, relationship, calc_group

    if not definition:
        return {
            'success': False,
            'error': 'definition parameter is required for generate_script operation (object definition as dict)'
        }

    try:
        from core.tmdl import TmdlScriptGenerator
        generator = TmdlScriptGenerator()

        # Use the unified method that handles all object types
        script = generator.generate_from_definition(object_type, definition)

        return {
            'success': True,
            'script': script
        }

    except ImportError as ie:
        logger.error(f"Import error: {ie}", exc_info=True)
        return {
            'success': False,
            'error': 'TmdlScriptGenerator not available. This is an internal error.',
            'error_type': 'import_error'
        }
    except Exception as e:
        logger.error(f"Error generating TMDL script: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error generating TMDL script: {str(e)}'
        }

def _handle_migrate_measures(args: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate measures between TMDL files with display folder filtering"""
    source_path = args.get('source_path')
    target_path = args.get('target_path')
    display_folder_filter = args.get('display_folder_filter')
    replace_target = args.get('replace_target', False)
    skip_duplicates = args.get('skip_duplicates', True)
    dry_run = args.get('dry_run', True)

    if not source_path:
        return {
            'success': False,
            'error': 'source_path parameter is required for migrate_measures operation'
        }

    if not target_path:
        return {
            'success': False,
            'error': 'target_path parameter is required for migrate_measures operation'
        }

    try:
        from core.tmdl import TmdlMeasureMigrator
        migrator = TmdlMeasureMigrator()

        result = migrator.migrate_measures(
            source_path=source_path,
            target_path=target_path,
            display_folder_filter=display_folder_filter,
            replace_target=replace_target,
            skip_duplicates=skip_duplicates,
            dry_run=dry_run
        )

        return result.to_dict()

    except ImportError as ie:
        logger.error(f"Import error: {ie}", exc_info=True)
        return {
            'success': False,
            'error': 'TmdlMeasureMigrator not available. This is an internal error.',
            'error_type': 'import_error'
        }
    except FileNotFoundError as fnf:
        return {
            'success': False,
            'error': f'Source file not found: {str(fnf)}'
        }
    except Exception as e:
        logger.error(f"Error in measure migration: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error in measure migration: {str(e)}'
        }

def register_tmdl_operations_handler(registry):
    """Register unified TMDL operations handler"""

    tool = ToolDefinition(
        name="02_TMDL_Operations",
        description="TMDL automation: export, find/replace, bulk rename, script generation, measure migration.",
        handler=handle_tmdl_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["export", "find_replace", "bulk_rename", "generate_script", "migrate_measures"],
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory"
                },
                "tmdl_path": {
                    "type": "string",
                    "description": "TMDL export folder"
                },
                "pattern": {
                    "type": "string",
                    "description": "Find pattern"
                },
                "replacement": {
                    "type": "string",
                    "description": "Replacement text"
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview only (default: true)"
                },
                "regex": {
                    "type": "boolean",
                    "description": "Use regex (default: false)"
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Case sensitive (default: true)"
                },
                "target": {
                    "type": "string",
                    "description": "Target objects (default: 'all')"
                },
                "renames": {
                    "type": "array",
                    "description": "Rename operations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string"},
                            "old_name": {"type": "string"},
                            "new_name": {"type": "string"},
                            "table_name": {"type": "string"}
                        },
                        "required": ["old_name", "new_name"]
                    }
                },
                "update_references": {
                    "type": "boolean",
                    "description": "Update refs when renaming (default: true)"
                },
                "definition": {
                    "type": "object",
                    "description": "Object definition"
                },
                "object_type": {
                    "type": "string",
                    "enum": ["table", "measure", "relationship", "calc_group"],
                    "description": "Object type (default: 'table')"
                },
                "source_path": {
                    "type": "string",
                    "description": "Source TMDL file"
                },
                "target_path": {
                    "type": "string",
                    "description": "Target TMDL file"
                },
                "display_folder_filter": {
                    "type": "string",
                    "description": "Folder prefix filter"
                },
                "replace_target": {
                    "type": "boolean",
                    "description": "Replace target entirely (default: false)"
                },
                "skip_duplicates": {
                    "type": "boolean",
                    "description": "Skip existing measures (default: true)"
                }
            },
            "required": ["operation"]
        },
        category="model",
        sort_order=26  # 02 = Model Operations
    )

    registry.register(tool)
    logger.info("Registered tmdl_operations handler")
