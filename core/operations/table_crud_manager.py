"""
Table CRUD Manager for MCP-PowerBi-Finvision
Provides comprehensive table management: create, update, delete, rename, refresh
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

AMO_AVAILABLE = False
AMOServer = None
Table = None
Partition = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import Server as AMOServer, Table, Partition, PartitionSourceType
    AMO_AVAILABLE = True
    logger.info("AMO available for table CRUD operations")
except Exception as e:
    logger.warning(f"AMO not available for table CRUD: {e}")


# Try to load ADOMD
AdomdConnection = None
AdomdCommand = None

try:
    from core.infrastructure.dll_paths import load_adomd_assembly
    if load_adomd_assembly():
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection, AdomdCommand
except Exception:
    pass


class TableCRUDManager:
    """Manage table CRUD operations using TOM."""

    def __init__(self, connection):
        """Initialize with ADOMD connection."""
        self.connection = connection

    def _valid_identifier(self, s: Optional[str]) -> bool:
        """Validate identifier (table name, etc.)."""
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

    def create_table(
        self,
        table_name: str,
        description: Optional[str] = None,
        expression: Optional[str] = None,
        hidden: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new table (calculated table).

        Args:
            table_name: Name of the table to create
            description: Optional table description
            expression: DAX expression for calculated table (required for calculated tables)
            hidden: Whether to hide the table (default: False)

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available - cannot create tables",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name):
            return {
                "success": False,
                "error": "Table name must be non-empty and <=128 chars",
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
            # Check if table already exists
            existing_table = next((t for t in model.Tables if t.Name == table_name), None)
            if existing_table:
                return {
                    "success": False,
                    "error": f"Table '{table_name}' already exists",
                    "error_type": "table_exists"
                }

            # Create new table
            table = Table()
            table.Name = table_name

            if description:
                table.Description = description

            if hidden:
                table.IsHidden = hidden

            # Add partition (required for all tables)
            # Import necessary type
            from Microsoft.AnalysisServices.Tabular import Partition, PartitionSourceType

            partition = Partition()
            partition.Name = table_name

            if expression:
                # Set as calculated table
                from Microsoft.AnalysisServices.Tabular import CalculatedPartitionSource
                calc_source = CalculatedPartitionSource()
                calc_source.Expression = expression
                partition.Source = calc_source
            else:
                # For regular tables, create an M partition with empty source
                # This allows the table structure to exist, columns can be added later
                from Microsoft.AnalysisServices.Tabular import MPartitionSource
                m_source = MPartitionSource()
                m_source.Expression = ""  # Empty M expression
                partition.Source = m_source

            table.Partitions.Add(partition)

            model.Tables.Add(table)
            model.SaveChanges()

            logger.info(f"Created table '{table_name}'")

            return {
                "success": True,
                "action": "created",
                "table": table_name,
                "description": description,
                "expression": expression,
                "hidden": hidden,
                "message": f"Successfully created table '{table_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error creating table: {error_msg}")
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

    def update_table(
        self,
        table_name: str,
        description: Optional[str] = None,
        expression: Optional[str] = None,
        hidden: Optional[bool] = None,
        new_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing table.

        Args:
            table_name: Current name of the table
            description: New description (optional)
            expression: New DAX expression for calculated table (optional)
            hidden: Set hidden state (optional)
            new_name: New table name (optional)

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name):
            return {
                "success": False,
                "error": "Table name must be non-empty and <=128 chars",
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

            updates = []

            # Update description
            if description is not None:
                table.Description = description
                updates.append("description")

            # Update hidden state
            if hidden is not None:
                table.IsHidden = hidden
                updates.append("hidden")

            # Update expression (for calculated tables)
            if expression is not None:
                if table.Partitions.Count > 0:
                    from Microsoft.AnalysisServices.Tabular import CalculatedPartitionSource
                    partition = table.Partitions[0]
                    if hasattr(partition.Source, 'Expression'):
                        partition.Source.Expression = expression
                        updates.append("expression")
                    else:
                        return {
                            "success": False,
                            "error": "Table is not a calculated table",
                            "error_type": "invalid_operation"
                        }

            # Update name
            if new_name and self._valid_identifier(new_name):
                # Check if new name already exists
                if any(t.Name == new_name for t in model.Tables if t != table):
                    return {
                        "success": False,
                        "error": f"Table '{new_name}' already exists",
                        "error_type": "name_conflict"
                    }
                table.Name = new_name
                updates.append("name")

            model.SaveChanges()

            logger.info(f"Updated table '{table_name}': {', '.join(updates)}")

            return {
                "success": True,
                "action": "updated",
                "table": new_name if new_name else table_name,
                "original_name": table_name if new_name else None,
                "updates": updates,
                "message": f"Successfully updated table '{table_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error updating table: {error_msg}")
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

    def delete_table(self, table_name: str) -> Dict[str, Any]:
        """
        Delete a table.

        Args:
            table_name: Name of the table to delete

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name):
            return {
                "success": False,
                "error": "Table name must be non-empty and <=128 chars",
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

            # Remove table
            model.Tables.Remove(table)
            model.SaveChanges()

            logger.info(f"Deleted table '{table_name}'")

            return {
                "success": True,
                "action": "deleted",
                "table": table_name,
                "message": f"Successfully deleted table '{table_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error deleting table: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "deletion_error",
                "suggestions": [
                    "Check if table is referenced by relationships",
                    "Verify no measures or columns are being used elsewhere",
                    "Ensure table is not a required system table"
                ]
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def rename_table(self, table_name: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a table.

        Args:
            table_name: Current table name
            new_name: New table name

        Returns:
            Result dictionary with success status
        """
        return self.update_table(table_name=table_name, new_name=new_name)

    def refresh_table(self, table_name: str) -> Dict[str, Any]:
        """
        Refresh a table's data.

        Args:
            table_name: Name of the table to refresh

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name):
            return {
                "success": False,
                "error": "Table name must be non-empty and <=128 chars",
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

            # Request refresh
            from Microsoft.AnalysisServices.Tabular import RefreshType
            table.RequestRefresh(RefreshType.Full)
            model.SaveChanges()

            logger.info(f"Requested refresh for table '{table_name}'")

            return {
                "success": True,
                "action": "refresh_requested",
                "table": table_name,
                "message": f"Successfully requested refresh for table '{table_name}'",
                "note": "Refresh is asynchronous - check table status for completion"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error refreshing table: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "refresh_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass
