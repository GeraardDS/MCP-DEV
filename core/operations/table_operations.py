"""
Unified table operations handler
Consolidates: list_tables, describe_table + new CRUD operations

Refactored to use validation utilities for reduced code duplication.
"""
from datetime import datetime
from typing import Dict, Any
import logging
from .base_operations import BaseOperationsHandler
from core.infrastructure.connection_state import connection_state

# Import validation utilities
from core.validation import (
    get_manager_or_error,
    get_table_name,
    get_new_name,
    get_optional_int,
    apply_pagination,
    apply_describe_table_defaults,
    validate_required,
    validate_required_params,
    handle_operation_errors,
    ErrorHandler,
)

logger = logging.getLogger(__name__)


class TableOperationsHandler(BaseOperationsHandler):
    """Handles all table-related operations"""

    def __init__(self):
        super().__init__("table_operations")

        # Register all operations
        self.register_operation('list', self._list_tables)
        self.register_operation('describe', self._describe_table)
        self.register_operation('preview', self._preview_table)
        self.register_operation('sample_data', self._sample_data)
        self.register_operation('create', self._create_table)
        self.register_operation('update', self._update_table)
        self.register_operation('delete', self._delete_table)
        self.register_operation('rename', self._rename_table)
        self.register_operation('refresh', self._refresh_table)
        self.register_operation('generate_calendar', self._generate_calendar)

    def _list_tables(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all tables in the model"""
        # Get manager with connection check
        qe = get_manager_or_error('query_executor')
        if isinstance(qe, dict):  # Error response
            return qe

        result = qe.execute_info_query("TABLES")

        # Apply pagination if requested
        return apply_pagination(result, args)

    def _describe_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get comprehensive table description"""
        # Get manager with connection check
        qe = get_manager_or_error('query_executor')
        if isinstance(qe, dict):  # Error response
            return qe

        # Extract parameters with backward compatibility
        table_name = get_table_name(args)

        # Validate required parameter
        if error := validate_required(table_name, 'table_name', 'describe'):
            return error

        # Apply default pagination limits for describe_table
        args = apply_describe_table_defaults(args)

        # Check if method exists
        if not hasattr(qe, 'describe_table'):
            return {
                'success': False,
                'error': 'describe_table method not implemented in query executor'
            }

        try:
            result = qe.describe_table(table_name, args)
            return result
        except Exception as e:
            logger.error(f"Error describing table '{table_name}': {e}", exc_info=True)
            return ErrorHandler.handle_unexpected_error('describe_table', e)

    def _preview_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Preview table data (simple version).
        Delegates to sample_data for consistent implementation.
        """
        # Delegate to sample_data - preview is just sample_data without extra options
        return self._sample_data(args)

    def _sample_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get sample data from a table with optional column selection and ordering.

        This is an enhanced version of preview that supports:
        - Column selection (return only specific columns)
        - Ordering by a specific column
        - Ascending/descending order
        """
        # Get manager with connection check
        agent_policy = get_manager_or_error('agent_policy')
        if isinstance(agent_policy, dict):  # Error response
            return agent_policy

        # Extract parameters with backward compatibility
        table_name = get_table_name(args)

        # Validate required parameter
        if error := validate_required(table_name, 'table_name', 'sample_data'):
            return error

        max_rows = min(get_optional_int(args, 'max_rows', 10), 1000)  # Cap at 1000 rows
        columns = args.get('columns')  # Optional list of column names
        order_by = args.get('order_by')  # Optional column to order by
        order_direction = args.get('order_direction', 'asc').upper()  # ASC or DESC

        # Build DAX query
        if columns:
            # Select specific columns using SELECTCOLUMNS
            col_parts = []
            for col in columns:
                col_parts.append(f'"{col}", \'{table_name}\'[{col}]')
            inner_query = f"SELECTCOLUMNS('{table_name}', {', '.join(col_parts)})"
        else:
            inner_query = f"'{table_name}'"

        if order_by:
            # Add ordering
            order_col = f"'{table_name}'[{order_by}]"
            if order_direction == 'DESC':
                query = f"EVALUATE TOPN({max_rows}, {inner_query}, {order_col}, DESC)"
            else:
                query = f"EVALUATE TOPN({max_rows}, {inner_query}, {order_col}, ASC)"
        else:
            # Simple TOPN without ordering
            query = f"EVALUATE TOPN({max_rows}, {inner_query})"

        result = agent_policy.safe_run_dax(
            connection_state=connection_state,
            query=query,
            mode='auto',
            max_rows=max_rows
        )

        # Add metadata about the query
        if result.get('success'):
            result['metadata'] = {
                'table_name': table_name,
                'max_rows_requested': max_rows,
                'columns_selected': columns if columns else 'all',
                'order_by': order_by,
                'order_direction': order_direction if order_by else None
            }

        return result

    def _create_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new table"""
        # Get manager with connection check
        table_crud = get_manager_or_error('table_crud_manager')
        if isinstance(table_crud, dict):  # Error response
            return table_crud

        return table_crud.create_table(
            table_name=args.get('table_name'),
            description=args.get('description'),
            expression=args.get('expression'),
            hidden=args.get('hidden', False)
        )

    def _update_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing table"""
        # Get manager with connection check
        table_crud = get_manager_or_error('table_crud_manager')
        if isinstance(table_crud, dict):  # Error response
            return table_crud

        return table_crud.update_table(
            table_name=args.get('table_name'),
            description=args.get('description'),
            expression=args.get('expression'),
            hidden=args.get('hidden'),
            new_name=args.get('new_name')
        )

    def _delete_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a table"""
        # Get manager with connection check
        table_crud = get_manager_or_error('table_crud_manager')
        if isinstance(table_crud, dict):  # Error response
            return table_crud

        table_name = args.get('table_name')

        # Validate required parameter
        if error := validate_required(table_name, 'table_name', 'delete'):
            return error

        return table_crud.delete_table(table_name)

    def _rename_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Rename a table"""
        # Get manager with connection check
        table_crud = get_manager_or_error('table_crud_manager')
        if isinstance(table_crud, dict):  # Error response
            return table_crud

        table_name = args.get('table_name')
        new_name = get_new_name(args)

        # Validate required parameters
        if error := validate_required_params(
            (table_name, 'table_name'),
            (new_name, 'new_name'),
            operation='rename'
        ):
            return error

        return table_crud.rename_table(table_name, new_name)

    def _refresh_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh a table"""
        # Get manager with connection check
        table_crud = get_manager_or_error('table_crud_manager')
        if isinstance(table_crud, dict):  # Error response
            return table_crud

        table_name = args.get('table_name')

        # Validate required parameter
        if error := validate_required(table_name, 'table_name', 'refresh'):
            return error

        refresh_type = args.get('refresh_type', 'full')
        return table_crud.refresh_table(table_name, refresh_type=refresh_type)

    @staticmethod
    def _generate_calendar_dax(
        start_year: int,
        end_year: int,
        include_fiscal: bool = False,
        fiscal_start_month: int = 7,
    ) -> str:
        """Build DAX expression for a standard calendar calculated table."""
        base_dax = (
            f'ADDCOLUMNS(\n'
            f'    CALENDAR(DATE({start_year}, 1, 1), DATE({end_year}, 12, 31)),\n'
            f'    "Year", YEAR([Date]),\n'
            f'    "Quarter", "Q" & CEILING(MONTH([Date]) / 3, 1),\n'
            f'    "YearQuarter", YEAR([Date]) & "-Q" & CEILING(MONTH([Date]) / 3, 1),\n'
            f'    "Month", MONTH([Date]),\n'
            f'    "MonthName", FORMAT([Date], "MMMM"),\n'
            f'    "MonthShort", FORMAT([Date], "MMM"),\n'
            f'    "YearMonth", FORMAT([Date], "YYYY-MM"),\n'
            f'    "Day", DAY([Date]),\n'
            f'    "DayOfWeek", WEEKDAY([Date], 2),\n'
            f'    "DayName", FORMAT([Date], "dddd"),\n'
            f'    "WeekNumber", WEEKNUM([Date], 2),\n'
            f'    "IsWeekend", IF(WEEKDAY([Date], 2) > 5, TRUE(), FALSE()),\n'
            f'    "IsCurrentYear", IF(YEAR([Date]) = YEAR(TODAY()), TRUE(), FALSE()),\n'
            f'    "IsCurrentMonth", IF(YEAR([Date]) = YEAR(TODAY()) && MONTH([Date]) = MONTH(TODAY()), TRUE(), FALSE())'
        )

        if include_fiscal:
            base_dax += (
                f',\n'
                f'    "FiscalYear", IF(MONTH([Date]) >= {fiscal_start_month}, YEAR([Date]) + 1, YEAR([Date])),\n'
                f'    "FiscalQuarter", "FQ" & CEILING((MOD(MONTH([Date]) - {fiscal_start_month} + 12, 12) + 1) / 3, 1),\n'
                f'    "FiscalMonth", MOD(MONTH([Date]) - {fiscal_start_month} + 12, 12) + 1'
            )

        base_dax += '\n)'
        return base_dax

    def _generate_calendar(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a standard DAX calendar (date) table."""
        # Get manager with connection check
        table_crud = get_manager_or_error('table_crud_manager')
        if isinstance(table_crud, dict):  # Error response
            return table_crud

        current_year = datetime.now().year
        table_name = args.get('table_name', 'Date')
        start_year = args.get('start_year', current_year - 5)
        end_year = args.get('end_year', current_year + 2)
        include_fiscal = args.get('include_fiscal', False)
        fiscal_start_month = args.get('fiscal_start_month', 7)

        # Validate year range
        if start_year > end_year:
            return {
                'success': False,
                'error': f'start_year ({start_year}) must be <= end_year ({end_year})',
                'error_type': 'invalid_parameters',
            }

        if fiscal_start_month < 1 or fiscal_start_month > 12:
            return {
                'success': False,
                'error': f'fiscal_start_month must be 1-12, got {fiscal_start_month}',
                'error_type': 'invalid_parameters',
            }

        # Build the DAX expression
        dax_expression = self._generate_calendar_dax(
            start_year, end_year, include_fiscal, fiscal_start_month
        )

        # Create the calculated table
        result = table_crud.create_table(
            table_name=table_name,
            description=f"Calendar table ({start_year}-{end_year})"
            + (f", fiscal year starting month {fiscal_start_month}" if include_fiscal else ""),
            expression=dax_expression,
            hidden=False,
        )

        if not result.get('success'):
            return result

        # Try to mark as date table (set IsDateTable property via TOM)
        mark_result = self._mark_as_date_table(table_crud, table_name)

        result['calendar_info'] = {
            'start_year': start_year,
            'end_year': end_year,
            'include_fiscal': include_fiscal,
            'fiscal_start_month': fiscal_start_month if include_fiscal else None,
            'marked_as_date_table': mark_result.get('success', False),
        }
        if not mark_result.get('success'):
            result['calendar_info']['mark_date_table_note'] = mark_result.get('note', '')

        return result

    @staticmethod
    def _mark_as_date_table(table_crud, table_name: str) -> Dict[str, Any]:
        """Attempt to mark the table as a date table via TOM."""
        try:
            server, db, model = table_crud._get_server_db_model()
            if not model:
                return {'success': False, 'note': 'Could not connect to mark as date table'}

            try:
                table = next((t for t in model.Tables if t.Name == table_name), None)
                if not table:
                    return {'success': False, 'note': f"Table '{table_name}' not found for date table marking"}

                # Find the Date column
                date_col = next((c for c in table.Columns if c.Name == "Date"), None)
                if not date_col:
                    return {'success': False, 'note': "Date column not found in generated table"}

                # Set the Date column as the key column for the date table
                from Microsoft.AnalysisServices.Tabular import DataType, ObjectType
                table.DataCategory = "Time"
                date_col.IsKey = True

                model.SaveChanges()
                return {'success': True}

            finally:
                try:
                    server.Disconnect()
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Could not mark '{table_name}' as date table: {e}")
            return {'success': False, 'note': f'Could not mark as date table: {e}'}
