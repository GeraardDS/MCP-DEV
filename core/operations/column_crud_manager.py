"""
Column CRUD Manager for MCP-PowerBi-Finvision
Provides comprehensive column management: get, create, update, delete, rename
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

AMO_AVAILABLE = False
AMOServer = None
Column = None
DataColumn = None
CalculatedColumn = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import (
        Server as AMOServer,
        Column,
        DataColumn,
        CalculatedColumn,
        DataType
    )
    AMO_AVAILABLE = True
    logger.info("AMO available for column CRUD operations")
except Exception as e:
    logger.warning(f"AMO not available for column CRUD: {e}")


# Try to load ADOMD
AdomdConnection = None
AdomdCommand = None

try:
    from core.infrastructure.dll_paths import load_adomd_assembly
    if load_adomd_assembly():
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection, AdomdCommand
except Exception:
    pass


class ColumnCRUDManager:
    """Manage column CRUD operations using TOM."""

    def __init__(self, connection):
        """Initialize with ADOMD connection."""
        self.connection = connection

    def _valid_identifier(self, s: Optional[str]) -> bool:
        """Validate identifier (column name, etc.)."""
        return bool(s) and len(str(s).strip()) > 0 and len(str(s)) <= 128 and '\0' not in str(s)

    def _get_server_db_model(self):
        """Connect and get server, database, and model objects."""
        if not AMO_AVAILABLE:
            return None, None, None

        server = AMOServer()
        try:
            server.Connect(self.connection.ConnectionString)

            # Get database name
            db_name = None
            try:
                db_query = "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS"
                cmd = AdomdCommand(db_query, self.connection)
                reader = cmd.ExecuteReader()
                if reader.Read():
                    db_name = str(reader.GetValue(0))
                reader.Close()
            except Exception:
                db_name = None

            if not db_name and server.Databases.Count > 0:
                db_name = server.Databases[0].Name

            if not db_name:
                server.Disconnect()
                return None, None, None

            db = server.Databases.GetByName(db_name)
            model = db.Model

            return server, db, model

        except Exception as e:
            try:
                server.Disconnect()
            except Exception:
                pass
            logger.error(f"Error connecting to server: {e}")
            return None, None, None

    def _parse_data_type(self, data_type_str: str):
        """Parse data type string to TOM DataType enum."""
        from Microsoft.AnalysisServices.Tabular import DataType

        type_map = {
            'String': DataType.String,
            'Int64': DataType.Int64,
            'Double': DataType.Double,
            'Decimal': DataType.Decimal,
            'Boolean': DataType.Boolean,
            'DateTime': DataType.DateTime,
            'Binary': DataType.Binary,
            'Variant': DataType.Variant,
            'Unknown': DataType.Unknown
        }

        return type_map.get(data_type_str, DataType.String)

    def get_column(self, table_name: str, column_name: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific column.

        Args:
            table_name: Name of the table
            column_name: Name of the column

        Returns:
            Result dictionary with column details
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name) or not self._valid_identifier(column_name):
            return {
                "success": False,
                "error": "Table and column names must be non-empty and <=128 chars",
                "error_type": "invalid_parameters"
            }

        server, db, model = self._get_server_db_model()
        if not model:
            return {
                "success": False,
                "error": "Could not connect to model",
                "error_type": "connection_error"
            }

        try:
            # Find table
            table = next((t for t in model.Tables if t.Name == table_name), None)
            if not table:
                return {
                    "success": False,
                    "error": f"Table '{table_name}' not found",
                    "error_type": "table_not_found"
                }

            # Find column
            column = next((c for c in table.Columns if c.Name == column_name), None)
            if not column:
                return {
                    "success": False,
                    "error": f"Column '{column_name}' not found in table '{table_name}'",
                    "error_type": "column_not_found"
                }

            # Build column info
            column_info = {
                "name": column.Name,
                "data_type": str(column.DataType),
                "description": column.Description if hasattr(column, 'Description') else None,
                "is_hidden": column.IsHidden if hasattr(column, 'IsHidden') else False,
                "display_folder": column.DisplayFolder if hasattr(column, 'DisplayFolder') else None,
                "format_string": column.FormatString if hasattr(column, 'FormatString') else None,
                "is_key": column.IsKey if hasattr(column, 'IsKey') else False,
                "sort_by_column": column.SortByColumn.Name if hasattr(column, 'SortByColumn') and column.SortByColumn else None,
            }

            # Check if calculated column
            if hasattr(column, 'Expression') and column.Expression:
                column_info["type"] = "calculated"
                column_info["expression"] = column.Expression
            else:
                column_info["type"] = "data"
                column_info["source_column"] = column.SourceColumn if hasattr(column, 'SourceColumn') else None

            return {
                "success": True,
                "table": table_name,
                "column": column_info
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error getting column: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "retrieval_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def create_column(
        self,
        table_name: str,
        column_name: str,
        data_type: str = "String",
        expression: Optional[str] = None,
        description: Optional[str] = None,
        hidden: bool = False,
        display_folder: Optional[str] = None,
        format_string: Optional[str] = None,
        source_column: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new column (data or calculated column).

        Args:
            table_name: Name of the table
            column_name: Name of the column to create
            data_type: Data type (String, Int64, Double, Decimal, Boolean, DateTime, etc.)
            expression: DAX expression for calculated column (optional)
            description: Column description (optional)
            hidden: Whether to hide the column (default: False)
            display_folder: Display folder for organization (optional)
            format_string: Format string (optional)
            source_column: Source column name for data columns (optional)

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available - cannot create columns",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name) or not self._valid_identifier(column_name):
            return {
                "success": False,
                "error": "Table and column names must be non-empty and <=128 chars",
                "error_type": "invalid_parameters"
            }

        server, db, model = self._get_server_db_model()
        if not model:
            return {
                "success": False,
                "error": "Could not connect to model",
                "error_type": "connection_error"
            }

        try:
            # Find table
            table = next((t for t in model.Tables if t.Name == table_name), None)
            if not table:
                return {
                    "success": False,
                    "error": f"Table '{table_name}' not found",
                    "error_type": "table_not_found"
                }

            # Check if column already exists
            existing_column = next((c for c in table.Columns if c.Name == column_name), None)
            if existing_column:
                return {
                    "success": False,
                    "error": f"Column '{column_name}' already exists in table '{table_name}'",
                    "error_type": "column_exists"
                }

            # Determine column type and create
            if expression:
                # Create calculated column
                from Microsoft.AnalysisServices.Tabular import CalculatedColumn
                column = CalculatedColumn()
                column.Name = column_name
                column.Expression = expression
                column_type = "calculated"
            else:
                # Create data column
                from Microsoft.AnalysisServices.Tabular import DataColumn
                column = DataColumn()
                column.Name = column_name
                if source_column:
                    column.SourceColumn = source_column
                column_type = "data"

            # Set common properties
            column.DataType = self._parse_data_type(data_type)

            if description:
                column.Description = description
            if hidden:
                column.IsHidden = hidden
            if display_folder:
                column.DisplayFolder = display_folder
            if format_string:
                column.FormatString = format_string

            # Add column to table
            table.Columns.Add(column)
            model.SaveChanges()

            logger.info(f"Created {column_type} column '{column_name}' in table '{table_name}'")

            return {
                "success": True,
                "action": "created",
                "table": table_name,
                "column": column_name,
                "column_type": column_type,
                "data_type": data_type,
                "expression": expression,
                "message": f"Successfully created {column_type} column '{column_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error creating column: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "creation_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def update_column(
        self,
        table_name: str,
        column_name: str,
        expression: Optional[str] = None,
        description: Optional[str] = None,
        hidden: Optional[bool] = None,
        display_folder: Optional[str] = None,
        format_string: Optional[str] = None,
        new_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing column.

        Args:
            table_name: Name of the table
            column_name: Current name of the column
            expression: New DAX expression for calculated column (optional)
            description: New description (optional)
            hidden: Set hidden state (optional)
            display_folder: New display folder (optional)
            format_string: New format string (optional)
            new_name: New column name (optional)

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name) or not self._valid_identifier(column_name):
            return {
                "success": False,
                "error": "Table and column names must be non-empty and <=128 chars",
                "error_type": "invalid_parameters"
            }

        server, db, model = self._get_server_db_model()
        if not model:
            return {
                "success": False,
                "error": "Could not connect to model",
                "error_type": "connection_error"
            }

        try:
            # Find table
            table = next((t for t in model.Tables if t.Name == table_name), None)
            if not table:
                return {
                    "success": False,
                    "error": f"Table '{table_name}' not found",
                    "error_type": "table_not_found"
                }

            # Find column
            column = next((c for c in table.Columns if c.Name == column_name), None)
            if not column:
                return {
                    "success": False,
                    "error": f"Column '{column_name}' not found in table '{table_name}'",
                    "error_type": "column_not_found"
                }

            updates = []

            # Update expression (calculated columns only)
            if expression is not None:
                if hasattr(column, 'Expression'):
                    column.Expression = expression
                    updates.append("expression")
                else:
                    return {
                        "success": False,
                        "error": "Column is not a calculated column - cannot set expression",
                        "error_type": "invalid_operation"
                    }

            # Update description
            if description is not None:
                column.Description = description
                updates.append("description")

            # Update hidden state
            if hidden is not None:
                column.IsHidden = hidden
                updates.append("hidden")

            # Update display folder
            if display_folder is not None:
                column.DisplayFolder = display_folder
                updates.append("display_folder")

            # Update format string
            if format_string is not None:
                column.FormatString = format_string
                updates.append("format_string")

            # Update name
            if new_name and self._valid_identifier(new_name):
                # Check if new name already exists
                if any(c.Name == new_name for c in table.Columns if c != column):
                    return {
                        "success": False,
                        "error": f"Column '{new_name}' already exists in table '{table_name}'",
                        "error_type": "name_conflict"
                    }
                column.Name = new_name
                updates.append("name")

            model.SaveChanges()

            logger.info(f"Updated column '{column_name}' in table '{table_name}': {', '.join(updates)}")

            return {
                "success": True,
                "action": "updated",
                "table": table_name,
                "column": new_name if new_name else column_name,
                "original_name": column_name if new_name else None,
                "updates": updates,
                "message": f"Successfully updated column '{column_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error updating column: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "update_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def delete_column(self, table_name: str, column_name: str) -> Dict[str, Any]:
        """
        Delete a column.

        Args:
            table_name: Name of the table
            column_name: Name of the column to delete

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name) or not self._valid_identifier(column_name):
            return {
                "success": False,
                "error": "Table and column names must be non-empty and <=128 chars",
                "error_type": "invalid_parameters"
            }

        server, db, model = self._get_server_db_model()
        if not model:
            return {
                "success": False,
                "error": "Could not connect to model",
                "error_type": "connection_error"
            }

        try:
            # Find table
            table = next((t for t in model.Tables if t.Name == table_name), None)
            if not table:
                return {
                    "success": False,
                    "error": f"Table '{table_name}' not found",
                    "error_type": "table_not_found"
                }

            # Find column
            column = next((c for c in table.Columns if c.Name == column_name), None)
            if not column:
                return {
                    "success": False,
                    "error": f"Column '{column_name}' not found in table '{table_name}'",
                    "error_type": "column_not_found"
                }

            # Remove column
            table.Columns.Remove(column)
            model.SaveChanges()

            logger.info(f"Deleted column '{column_name}' from table '{table_name}'")

            return {
                "success": True,
                "action": "deleted",
                "table": table_name,
                "column": column_name,
                "message": f"Successfully deleted column '{column_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error deleting column: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "deletion_error",
                "suggestions": [
                    "Check if column is used in relationships",
                    "Verify column is not referenced by measures or calculated columns",
                    "Ensure column is not used as a sort-by column"
                ]
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def rename_column(self, table_name: str, column_name: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a column.

        Args:
            table_name: Name of the table
            column_name: Current column name
            new_name: New column name

        Returns:
            Result dictionary with success status
        """
        return self.update_column(table_name=table_name, column_name=column_name, new_name=new_name)
