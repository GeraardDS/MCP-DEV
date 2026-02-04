"""
Bulk Operations Manager for PBIXRay MCP Server
Handles batch operations for measures and other objects
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class BulkOperationsManager:
    """Handle bulk operations on measures and other objects."""

    def __init__(self, dax_injector):
        """Initialize with DAX injector."""
        self.dax_injector = dax_injector
        self._connection_manager = None

    def set_connection_manager(self, connection_manager):
        """
        Set reference to connection manager for reconnection support.

        Args:
            connection_manager: ConnectionManager instance
        """
        self._connection_manager = connection_manager
        # Also set on DAX injector for its internal use
        if self.dax_injector and hasattr(self.dax_injector, 'set_connection_manager'):
            self.dax_injector.set_connection_manager(connection_manager)
        logger.debug("Bulk operations manager linked to connection manager")

    def _check_connection(self) -> Dict[str, Any]:
        """
        Check if connection is alive, attempt reconnection if needed.

        Returns:
            Dict with 'connected' (bool) and optional 'error' (str)
        """
        if not self._connection_manager:
            # No connection manager, assume connected (fallback behavior)
            return {'connected': True}

        result = self._connection_manager.ensure_connected(max_retries=3)
        if result.get('connected'):
            if result.get('reconnected'):
                logger.info("Bulk operations: Connection was restored")
            return {'connected': True, 'reconnected': result.get('reconnected', False)}

        return {
            'connected': False,
            'error': result.get('error', 'Connection lost')
        }

    def bulk_create_measures(self, measures: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create multiple measures in batch.

        Args:
            measures: List of measure definitions with:
                - table: Table name
                - measure: Measure name
                - expression: DAX expression
                - display_folder: Optional folder
                - description: Optional description
                - format_string: Optional format

        Returns:
            Batch operation results
        """
        if not measures:
            return {
                'success': False,
                'error': 'No measures provided'
            }

        # Check connection before starting batch
        conn_check = self._check_connection()
        if not conn_check.get('connected'):
            return {
                'success': False,
                'error': conn_check.get('error', 'Connection lost'),
                'error_type': 'connection_lost',
                'suggestions': [
                    'Connection to Power BI Desktop was lost before batch could start',
                    'Ensure Power BI Desktop is running',
                    'Try reconnecting using 01_Connect_To_Instance'
                ]
            }

        results = []
        success_count = 0
        error_count = 0
        connection_lost = False
        reconnection_count = 0

        for idx, measure_def in enumerate(measures):
            # Check connection every 5 items to detect loss early (balance performance vs reliability)
            if idx > 0 and idx % 5 == 0:
                conn_check = self._check_connection()
                if not conn_check.get('connected'):
                    connection_lost = True
                    # Mark remaining items as skipped
                    for remaining_idx in range(idx, len(measures)):
                        remaining_def = measures[remaining_idx]
                        remaining_measure = remaining_def.get('measure') or remaining_def.get('measure_name') or f'item_{remaining_idx}'
                        results.append({
                            'index': remaining_idx,
                            'measure': remaining_measure,
                            'success': False,
                            'error': 'Skipped: connection lost',
                            'skipped': True
                        })
                        error_count += 1
                    break
                elif conn_check.get('reconnected'):
                    reconnection_count += 1

            try:
                # Accept both 'table'/'table_name' and 'measure'/'measure_name' field names
                table = measure_def.get('table') or measure_def.get('table_name')
                measure = measure_def.get('measure') or measure_def.get('measure_name')
                expression = measure_def.get('expression')

                if not all([table, measure, expression]):
                    results.append({
                        'index': idx,
                        'measure': measure,
                        'success': False,
                        'error': 'Missing required fields (table/table_name, measure/measure_name, expression)'
                    })
                    error_count += 1
                    continue

                # Create measure
                result = self.dax_injector.upsert_measure(
                    table_name=table,
                    measure_name=measure,
                    dax_expression=expression,
                    display_folder=measure_def.get('display_folder'),
                    description=measure_def.get('description'),
                    format_string=measure_def.get('format_string')
                )

                if result.get('success'):
                    success_count += 1
                    results.append({
                        'index': idx,
                        'measure': measure,
                        'table': table,
                        'success': True,
                        'action': result.get('action', 'created')
                    })
                else:
                    error_count += 1
                    error_type = result.get('error_type', '')

                    # Check if this was a connection loss
                    if error_type == 'connection_lost':
                        connection_lost = True
                        results.append({
                            'index': idx,
                            'measure': measure,
                            'table': table,
                            'success': False,
                            'error': 'Connection lost during operation'
                        })
                        # Mark remaining items as skipped
                        for remaining_idx in range(idx + 1, len(measures)):
                            remaining_measure = measures[remaining_idx].get('measure') or measures[remaining_idx].get('measure_name') or f'item_{remaining_idx}'
                            results.append({
                                'index': remaining_idx,
                                'measure': remaining_measure,
                                'success': False,
                                'error': 'Skipped: connection lost',
                                'skipped': True
                            })
                            error_count += 1
                        break
                    else:
                        results.append({
                            'index': idx,
                            'measure': measure,
                            'table': table,
                            'success': False,
                            'error': result.get('error', 'Unknown error')
                        })

            except Exception as e:
                error_count += 1
                error_str = str(e).lower()

                # Check if exception indicates connection loss
                if any(x in error_str for x in ['connection', 'closed', 'disconnected', 'timeout']):
                    connection_lost = True
                    results.append({
                        'index': idx,
                        'success': False,
                        'error': f'Connection error: {str(e)}'
                    })
                    # Mark remaining items as skipped
                    for remaining_idx in range(idx + 1, len(measures)):
                        remaining_measure = measures[remaining_idx].get('measure') or measures[remaining_idx].get('measure_name') or f'item_{remaining_idx}'
                        results.append({
                            'index': remaining_idx,
                            'measure': remaining_measure,
                            'success': False,
                            'error': 'Skipped: connection lost',
                            'skipped': True
                        })
                        error_count += 1
                    break
                else:
                    results.append({
                        'index': idx,
                        'success': False,
                        'error': str(e)
                    })

        response = {
            'success': error_count == 0,
            'total_measures': len(measures),
            'success_count': success_count,
            'error_count': error_count,
            'results': results,
            'summary': f"Created {success_count}/{len(measures)} measures successfully"
        }

        if connection_lost:
            response['connection_lost'] = True
            response['warning'] = 'Batch operation was interrupted due to connection loss'

        if reconnection_count > 0:
            response['reconnections'] = reconnection_count

        return response

    def bulk_update_display_folders(
        self,
        table: str,
        measures: List[str],
        display_folder: str
    ) -> Dict[str, Any]:
        """
        Update display folder for multiple measures.

        Args:
            table: Table name
            measures: List of measure names
            display_folder: New display folder

        Returns:
            Batch operation results
        """
        # Check connection before starting batch
        conn_check = self._check_connection()
        if not conn_check.get('connected'):
            return {
                'success': False,
                'error': conn_check.get('error', 'Connection lost'),
                'error_type': 'connection_lost'
            }

        results = []
        success_count = 0
        error_count = 0
        connection_lost = False

        for idx, measure in enumerate(measures):
            # Check connection every 5 items
            if idx > 0 and idx % 5 == 0:
                conn_check = self._check_connection()
                if not conn_check.get('connected'):
                    connection_lost = True
                    # Mark remaining items as skipped
                    for remaining_idx in range(idx, len(measures)):
                        results.append({
                            'measure': measures[remaining_idx],
                            'success': False,
                            'error': 'Skipped: connection lost',
                            'skipped': True
                        })
                        error_count += 1
                    break

            try:
                result = self.dax_injector.upsert_measure(
                    table_name=table,
                    measure_name=measure,
                    dax_expression="",  # Will preserve existing
                    display_folder=display_folder
                )

                if result.get('success'):
                    success_count += 1
                    results.append({
                        'measure': measure,
                        'success': True
                    })
                else:
                    error_count += 1
                    if result.get('error_type') == 'connection_lost':
                        connection_lost = True
                        results.append({
                            'measure': measure,
                            'success': False,
                            'error': 'Connection lost'
                        })
                        # Mark remaining items as skipped
                        for remaining_idx in range(idx + 1, len(measures)):
                            results.append({
                                'measure': measures[remaining_idx],
                                'success': False,
                                'error': 'Skipped: connection lost',
                                'skipped': True
                            })
                            error_count += 1
                        break
                    else:
                        results.append({
                            'measure': measure,
                            'success': False,
                            'error': result.get('error')
                        })

            except Exception as e:
                error_count += 1
                results.append({
                    'measure': measure,
                    'success': False,
                    'error': str(e)
                })

        response = {
            'success': error_count == 0,
            'total_measures': len(measures),
            'success_count': success_count,
            'error_count': error_count,
            'display_folder': display_folder,
            'results': results
        }

        if connection_lost:
            response['connection_lost'] = True
            response['warning'] = 'Batch operation was interrupted due to connection loss'

        return response

    def bulk_delete_measures(
        self,
        measures: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Delete multiple measures.

        Args:
            measures: List of dicts with 'table' and 'measure'

        Returns:
            Batch operation results
        """
        # Check connection before starting batch
        conn_check = self._check_connection()
        if not conn_check.get('connected'):
            return {
                'success': False,
                'error': conn_check.get('error', 'Connection lost'),
                'error_type': 'connection_lost'
            }

        results = []
        success_count = 0
        error_count = 0
        connection_lost = False

        for idx, measure_def in enumerate(measures):
            # Check connection every 5 items
            if idx > 0 and idx % 5 == 0:
                conn_check = self._check_connection()
                if not conn_check.get('connected'):
                    connection_lost = True
                    # Mark remaining items as skipped
                    for remaining_idx in range(idx, len(measures)):
                        remaining_def = measures[remaining_idx]
                        results.append({
                            'table': remaining_def.get('table'),
                            'measure': remaining_def.get('measure'),
                            'success': False,
                            'error': 'Skipped: connection lost',
                            'skipped': True
                        })
                        error_count += 1
                    break

            # Accept both 'table'/'table_name' and 'measure'/'measure_name' field names
            table = measure_def.get('table') or measure_def.get('table_name')
            measure = measure_def.get('measure') or measure_def.get('measure_name')

            if not table or not measure:
                error_count += 1
                results.append({
                    'table': table,
                    'measure': measure,
                    'success': False,
                    'error': 'Missing table/table_name or measure/measure_name'
                })
                continue

            try:
                result = self.dax_injector.delete_measure(table, measure)

                if result.get('success'):
                    success_count += 1
                    results.append({
                        'table': table,
                        'measure': measure,
                        'success': True
                    })
                else:
                    error_count += 1
                    if result.get('error_type') == 'connection_lost':
                        connection_lost = True
                        results.append({
                            'table': table,
                            'measure': measure,
                            'success': False,
                            'error': 'Connection lost'
                        })
                        # Mark remaining items as skipped
                        for remaining_idx in range(idx + 1, len(measures)):
                            remaining_def = measures[remaining_idx]
                            results.append({
                                'table': remaining_def.get('table'),
                                'measure': remaining_def.get('measure'),
                                'success': False,
                                'error': 'Skipped: connection lost',
                                'skipped': True
                            })
                            error_count += 1
                        break
                    else:
                        results.append({
                            'table': table,
                            'measure': measure,
                            'success': False,
                            'error': result.get('error')
                        })

            except Exception as e:
                error_count += 1
                results.append({
                    'table': table,
                    'measure': measure,
                    'success': False,
                    'error': str(e)
                })

        response = {
            'success': error_count == 0,
            'total_measures': len(measures),
            'success_count': success_count,
            'error_count': error_count,
            'results': results
        }

        if connection_lost:
            response['connection_lost'] = True
            response['warning'] = 'Batch operation was interrupted due to connection loss'

        return response

    def import_measures_from_json(self, json_data: str) -> Dict[str, Any]:
        """
        Import measures from JSON string.

        Expected format:
        [
            {
                "table": "Sales",
                "measure": "Total Sales",
                "expression": "SUM(Sales[Amount])",
                "display_folder": "Sales KPIs",
                "format_string": "#,##0.00"
            },
            ...
        ]

        Args:
            json_data: JSON string with measure definitions

        Returns:
            Import results
        """
        try:
            measures = json.loads(json_data)

            if not isinstance(measures, list):
                return {
                    'success': False,
                    'error': 'JSON must be an array of measure definitions'
                }

            return self.bulk_create_measures(measures)

        except json.JSONDecodeError as e:
            return {
                'success': False,
                'error': f"Invalid JSON: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error importing measures: {e}")
            return {
                'success': False,
                'error': str(e)
            }
