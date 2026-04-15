"""
Unified batch operations handler
Handles batch create/update/delete operations for all object types
"""
from typing import Dict, Any, List
import logging
from .base_operations import BaseOperationsHandler
from core.infrastructure.connection_state import connection_state
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

class BatchOperationsHandler(BaseOperationsHandler):
    """Handles batch operations for model objects"""

    def __init__(self):
        super().__init__("batch_operations")

        # Register batch operations by object type
        self.register_operation('measures', self._batch_measures)
        self.register_operation('tables', self._batch_tables)
        self.register_operation('columns', self._batch_columns)
        self.register_operation('relationships', self._batch_relationships)

    def _batch_measures(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Batch operations for measures"""
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        operation = args.get('batch_operation')  # create, update, delete, etc.
        items = args.get('items', []) or args.get('measures', [])
        options = args.get('options', {})

        if not operation:
            return {
                'success': False,
                'error': 'batch_operation parameter is required (create, update, delete, etc.)'
            }

        if not items:
            return {
                'success': False,
                'error': 'items parameter is required (array of measure definitions)'
            }

        # Get options
        use_transaction = options.get('use_transaction', True)
        continue_on_error = options.get('continue_on_error', False)
        dry_run = options.get('dry_run', False)

        if dry_run:
            # Validate definitions before executing
            validation_errors = []
            for idx, item in enumerate(items):
                item_errors = []
                item_name = item.get('measure') or item.get('measure_name') or item.get('name') or f'item[{idx}]'
                has_table = item.get('table') or item.get('table_name')
                if operation == 'create':
                    if not item_name or item_name == f'item[{idx}]':
                        item_errors.append('missing required field: name/measure/measure_name')
                    if not item.get('expression'):
                        item_errors.append('missing required field: expression')
                    if not has_table:
                        item_errors.append('missing required field: table or table_name')
                elif operation == 'update':
                    if not item_name or item_name == f'item[{idx}]':
                        item_errors.append('missing required field: name/measure/measure_name')
                    if not has_table:
                        item_errors.append('missing required field: table or table_name')
                elif operation == 'delete':
                    if not item_name or item_name == f'item[{idx}]':
                        item_errors.append('missing required field: name/measure/measure_name')
                elif operation == 'rename':
                    if not item_name or item_name == f'item[{idx}]':
                        item_errors.append('missing required field: name/measure/measure_name')
                    if not item.get('new_name'):
                        item_errors.append('missing required field: new_name')
                    if not has_table:
                        item_errors.append('missing required field: table or table_name')
                elif operation == 'move_display_folder':
                    if not item_name or item_name == f'item[{idx}]':
                        item_errors.append('missing required field: name/measure/measure_name')
                    if not has_table:
                        item_errors.append('missing required field: table or table_name')
                    if 'display_folder' not in item:
                        item_errors.append('missing required field: display_folder')
                elif operation == 'move':
                    if not item_name or item_name == f'item[{idx}]':
                        item_errors.append('missing required field: name/measure/measure_name')
                    if not has_table:
                        item_errors.append('missing required field: table or table_name')
                    if not item.get('new_table') and not item.get('target_table'):
                        item_errors.append('missing required field: new_table or target_table')
                if item_errors:
                    validation_errors.append({
                        'index': idx,
                        'item': item_name,
                        'errors': item_errors
                    })

            if validation_errors:
                return {
                    'success': False,
                    'dry_run': True,
                    'message': f'Validation failed for {len(validation_errors)} of {len(items)} item(s)',
                    'item_count': len(items),
                    'validation_errors': validation_errors
                }

            return {
                'success': True,
                'dry_run': True,
                'message': f'Validated {len(items)} measure(s) for {operation} operation',
                'item_count': len(items),
                'would_execute': f'{operation} on {len(items)} measures'
            }

        # Route to appropriate batch operation based on operation type
        if operation in ['create', 'update']:
            # Use existing bulk_create_measures functionality
            bulk_ops = connection_state.bulk_operations
            if not bulk_ops:
                return ErrorHandler.handle_manager_unavailable('bulk_operations')

            return bulk_ops.bulk_create_measures(items)

        elif operation == 'delete':
            # Use existing bulk_delete_measures functionality
            bulk_ops = connection_state.bulk_operations
            if not bulk_ops:
                return ErrorHandler.handle_manager_unavailable('bulk_operations')

            return bulk_ops.bulk_delete_measures(items)

        elif operation == 'rename':
            measure_crud = connection_state.measure_crud_manager
            if not measure_crud:
                return ErrorHandler.handle_manager_unavailable('measure_crud_manager')

            # Use batch method: single AMO connection, all cascades see each other's changes
            return measure_crud.batch_rename_measures(items)

        elif operation == 'move_display_folder':
            bulk_ops = connection_state.bulk_operations
            if not bulk_ops:
                return ErrorHandler.handle_manager_unavailable('bulk_operations')

            # Each item needs: table/table_name, measure/measure_name/name, display_folder
            return self._batch_item_loop(items, lambda item: bulk_ops.dax_injector.upsert_measure(
                table_name=item.get('table') or item.get('table_name'),
                measure_name=item.get('measure') or item.get('measure_name') or item.get('name'),
                dax_expression="",  # Empty = preserve existing
                display_folder=item.get('display_folder', ''),
            ), operation)

        elif operation == 'move':
            measure_crud = connection_state.measure_crud_manager
            if not measure_crud:
                return ErrorHandler.handle_manager_unavailable('measure_crud_manager')

            return self._batch_item_loop(items, lambda item: measure_crud.move_measure(
                source_table=item.get('table') or item.get('table_name'),
                measure_name=item.get('measure') or item.get('measure_name') or item.get('name'),
                target_table=item.get('new_table') or item.get('target_table'),
            ), operation)

        else:
            return {
                'success': False,
                'error': f'Unknown batch operation: {operation}',
                'supported_operations': ['create', 'update', 'delete', 'rename', 'move', 'move_display_folder']
            }

    def _batch_item_loop(self, items, fn, operation):
        """Generic loop: call fn(item) for each item, collect results."""
        results = []
        errors = []
        for item in items:
            try:
                result = fn(item)
                results.append(result)
                if not result.get('success'):
                    errors.append(result)
            except Exception as e:
                error_result = {'success': False, 'error': str(e), 'item': item}
                results.append(error_result)
                errors.append(error_result)
        return {
            'success': len(errors) == 0,
            'operation': operation,
            'total': len(items),
            'succeeded': len([r for r in results if r.get('success')]),
            'failed': len(errors),
            'results': results,
            'errors': errors if errors else None,
        }

    def _batch_tables(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Batch operations for tables"""
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        table_crud = connection_state.table_crud_manager
        if not table_crud:
            return ErrorHandler.handle_manager_unavailable('table_crud_manager')

        operation = args.get('batch_operation')
        items = args.get('items', [])
        options = args.get('options', {})

        if not operation:
            return {
                'success': False,
                'error': 'batch_operation parameter is required'
            }

        if not items:
            return {
                'success': False,
                'error': 'items parameter is required'
            }

        dry_run = options.get('dry_run', False)
        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'message': f'Validated {len(items)} table(s) for {operation} operation',
                'item_count': len(items)
            }

        # Process each table
        results = []
        errors = []
        for item in items:
            try:
                if operation == 'create':
                    result = table_crud.create_table(
                        table_name=item.get('table_name') or item.get('name'),
                        description=item.get('description'),
                        expression=item.get('expression'),
                        hidden=item.get('hidden', False)
                    )
                elif operation == 'update':
                    result = table_crud.update_table(
                        table_name=item.get('table_name') or item.get('name'),
                        description=item.get('description'),
                        expression=item.get('expression'),
                        hidden=item.get('hidden'),
                        new_name=item.get('new_name')
                    )
                elif operation == 'delete':
                    result = table_crud.delete_table(
                        table_name=item.get('table_name') or item.get('name')
                    )
                elif operation == 'rename':
                    result = table_crud.rename_table(
                        table_name=item.get('table_name') or item.get('name'),
                        new_name=item.get('new_name')
                    )
                elif operation == 'refresh':
                    result = table_crud.refresh_table(
                        table_name=item.get('table_name') or item.get('name')
                    )
                else:
                    result = {
                        'success': False,
                        'error': f'Unknown operation: {operation}'
                    }

                results.append(result)
                if not result.get('success'):
                    errors.append(result)
            except Exception as e:
                error_result = {'success': False, 'error': str(e), 'item': item}
                results.append(error_result)
                errors.append(error_result)

        return {
            'success': len(errors) == 0,
            'operation': operation,
            'total': len(items),
            'succeeded': len([r for r in results if r.get('success')]),
            'failed': len(errors),
            'results': results,
            'errors': errors if errors else None
        }

    def _batch_columns(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Batch operations for columns"""
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        column_crud = connection_state.column_crud_manager
        if not column_crud:
            return ErrorHandler.handle_manager_unavailable('column_crud_manager')

        operation = args.get('batch_operation')
        items = args.get('items', [])
        options = args.get('options', {})

        if not operation:
            return {
                'success': False,
                'error': 'batch_operation parameter is required'
            }

        if not items:
            return {
                'success': False,
                'error': 'items parameter is required'
            }

        dry_run = options.get('dry_run', False)
        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'message': f'Validated {len(items)} column(s) for {operation} operation',
                'item_count': len(items)
            }

        # Process each column
        results = []
        errors = []
        for item in items:
            try:
                if operation == 'create':
                    result = column_crud.create_column(
                        table_name=item.get('table_name'),
                        column_name=item.get('column_name') or item.get('name'),
                        data_type=item.get('data_type', 'String'),
                        expression=item.get('expression'),
                        description=item.get('description'),
                        hidden=item.get('hidden', False),
                        display_folder=item.get('display_folder'),
                        format_string=item.get('format_string'),
                        source_column=item.get('source_column')
                    )
                elif operation == 'update':
                    result = column_crud.update_column(
                        table_name=item.get('table_name'),
                        column_name=item.get('column_name') or item.get('name'),
                        expression=item.get('expression'),
                        description=item.get('description'),
                        hidden=item.get('hidden'),
                        display_folder=item.get('display_folder'),
                        format_string=item.get('format_string'),
                        new_name=item.get('new_name')
                    )
                elif operation == 'delete':
                    result = column_crud.delete_column(
                        table_name=item.get('table_name'),
                        column_name=item.get('column_name') or item.get('name')
                    )
                elif operation == 'rename':
                    result = column_crud.rename_column(
                        table_name=item.get('table_name'),
                        column_name=item.get('column_name') or item.get('name'),
                        new_name=item.get('new_name')
                    )
                elif operation == 'move_display_folder':
                    result = column_crud.update_column(
                        table_name=item.get('table_name'),
                        column_name=item.get('column_name') or item.get('name'),
                        display_folder=item.get('display_folder', ''),
                    )
                else:
                    result = {
                        'success': False,
                        'error': f'Unknown operation: {operation}'
                    }

                results.append(result)
                if not result.get('success'):
                    errors.append(result)
            except Exception as e:
                error_result = {'success': False, 'error': str(e), 'item': item}
                results.append(error_result)
                errors.append(error_result)

        return {
            'success': len(errors) == 0,
            'operation': operation,
            'total': len(items),
            'succeeded': len([r for r in results if r.get('success')]),
            'failed': len(errors),
            'results': results,
            'errors': errors if errors else None
        }

    def _batch_relationships(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Batch operations for relationships"""
        if not connection_state.is_connected():
            return ErrorHandler.handle_not_connected()

        rel_crud = connection_state.relationship_crud_manager
        if not rel_crud:
            return ErrorHandler.handle_manager_unavailable('relationship_crud_manager')

        operation = args.get('batch_operation')
        items = args.get('items', [])
        options = args.get('options', {})

        if not operation:
            return {
                'success': False,
                'error': 'batch_operation parameter is required'
            }

        if not items:
            return {
                'success': False,
                'error': 'items parameter is required'
            }

        dry_run = options.get('dry_run', False)
        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'message': f'Validated {len(items)} relationship(s) for {operation} operation',
                'item_count': len(items)
            }

        # Process each relationship
        results = []
        errors = []
        for item in items:
            try:
                if operation == 'create':
                    result = rel_crud.create_relationship(
                        from_table=item.get('from_table'),
                        from_column=item.get('from_column'),
                        to_table=item.get('to_table'),
                        to_column=item.get('to_column'),
                        name=item.get('name'),
                        from_cardinality=item.get('from_cardinality', 'Many'),
                        to_cardinality=item.get('to_cardinality', 'One'),
                        cross_filtering_behavior=item.get('cross_filtering_behavior', 'OneDirection'),
                        is_active=item.get('is_active', True)
                    )
                elif operation == 'update':
                    result = rel_crud.update_relationship(
                        relationship_name=item.get('relationship_name') or item.get('name'),
                        cross_filtering_behavior=item.get('cross_filtering_behavior'),
                        is_active=item.get('is_active'),
                        new_name=item.get('new_name')
                    )
                elif operation == 'delete':
                    result = rel_crud.delete_relationship(
                        relationship_name=item.get('relationship_name') or item.get('name')
                    )
                elif operation == 'activate':
                    result = rel_crud.activate_relationship(
                        relationship_name=item.get('relationship_name') or item.get('name')
                    )
                elif operation == 'deactivate':
                    result = rel_crud.deactivate_relationship(
                        relationship_name=item.get('relationship_name') or item.get('name')
                    )
                else:
                    result = {
                        'success': False,
                        'error': f'Unknown operation: {operation}'
                    }

                results.append(result)
                if not result.get('success'):
                    errors.append(result)
            except Exception as e:
                error_result = {'success': False, 'error': str(e), 'item': item}
                results.append(error_result)
                errors.append(error_result)

        return {
            'success': len(errors) == 0,
            'operation': operation,
            'total': len(items),
            'succeeded': len([r for r in results if r.get('success')]),
            'failed': len(errors),
            'results': results,
            'errors': errors if errors else None
        }
