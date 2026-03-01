"""
DAX Injector for PBIXRay MCP Server

Provides live DAX measure injection and modification capabilities.
"""

import logging
from typing import Dict, Any, Optional, Tuple

from core.dax.dax_utilities import validate_dax_identifier

logger = logging.getLogger(__name__)

# Try to load AMO
AMO_AVAILABLE = False
AMOServer = None
Measure = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import Server as AMOServer, Measure
    AMO_AVAILABLE = True
    logger.info("AMO available for DAX injection")
except Exception as e:
    logger.warning(f"AMO not available for DAX injection: {e}")


# Try to load ADOMD for database queries
AdomdConnection = None
AdomdCommand = None

try:
    from core.infrastructure.dll_paths import load_adomd_assembly
    if load_adomd_assembly():
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection, AdomdCommand
except Exception:
    pass


class DAXInjector:
    """
    DAX measure injection and modification service.

    Allows creating and updating DAX measures in live Power BI Desktop models.
    """

    def __init__(self, connection):
        """
        Initialize DAX injector.

        Args:
            connection: Active ADOMD connection
        """
        self.connection = connection
        self._connection_manager = None  # Optional reference for reconnection support

    def set_connection_manager(self, connection_manager):
        """
        Set reference to connection manager for reconnection support.

        Args:
            connection_manager: ConnectionManager instance
        """
        self._connection_manager = connection_manager
        logger.debug("DAX injector linked to connection manager for reconnection support")

    def _verify_connection(self) -> Dict[str, Any]:
        """
        Verify connection is alive, attempt reconnection if needed.

        Returns:
            Dict with 'success' (bool) and optional 'error' (str)
        """
        try:
            # Check if ADOMD connection is open
            if self.connection and hasattr(self.connection, 'State'):
                state = self.connection.State.ToString()
                if state == 'Open':
                    return {'success': True}

            # Connection not open - try reconnection if manager available
            if self._connection_manager:
                logger.warning("DAX Injector: Connection not open, attempting reconnection...")
                result = self._connection_manager.ensure_connected(max_retries=3)
                if result.get('connected'):
                    # Update our connection reference
                    self.connection = self._connection_manager.get_connection()
                    logger.info("DAX Injector: Reconnection successful")
                    return {'success': True, 'reconnected': True}
                else:
                    return {
                        'success': False,
                        'error': result.get('error', 'Connection lost and reconnection failed')
                    }

            return {
                'success': False,
                'error': 'Connection not open and no connection manager for reconnection'
            }

        except Exception as e:
            logger.error(f"Error verifying connection: {e}")
            return {'success': False, 'error': str(e)}

    def _get_database_name(
        self, server
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Get database name via DMV query with AMO fallback.

        Tries a DMV catalog query first, then falls back to the
        first database exposed by AMO (typical for PBI Desktop).

        Args:
            server: Connected AMO Server instance

        Returns:
            Tuple of (db_name, error_dict). On success,
            error_dict is None. On failure, db_name is empty
            and error_dict contains the error response.
        """
        db_name = None
        try:
            db_query = (
                "SELECT [CATALOG_NAME] "
                "FROM $SYSTEM.DBSCHEMA_CATALOGS"
            )
            cmd = AdomdCommand(db_query, self.connection)
            reader = cmd.ExecuteReader()
            if reader.Read():
                db_name = str(reader.GetValue(0))
            reader.Close()
        except Exception:
            db_name = None

        if not db_name:
            try:
                if server.Databases.Count > 0:
                    db_name = server.Databases[0].Name
            except Exception:
                pass

        if not db_name:
            return "", {
                "success": False,
                "error": "Could not determine database name",
                "error_type": "database_error",
            }

        return db_name, None

    def upsert_measure(
        self,
        table_name: str,
        measure_name: str,
        dax_expression: str,
        display_folder: Optional[str] = None,
        description: Optional[str] = None,
        format_string: Optional[str] = None,
        data_category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create or update a DAX measure.

        Args:
            table_name: Name of the table to add measure to
            measure_name: Name of the measure
            dax_expression: DAX expression for the measure
            display_folder: Optional display folder for organization
            description: Optional measure description
            format_string: Optional format string (e.g., "#,##0.00")
            data_category: Optional data category (e.g., "ImageUrl" for SVG visuals)

        Returns:
            Result dictionary with success status and details
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available - cannot inject measures",
                "error_type": "amo_unavailable"
            }

        # Verify connection before AMO operations
        conn_check = self._verify_connection()
        if not conn_check.get('success'):
            return {
                "success": False,
                "error": conn_check.get('error', 'Connection lost'),
                "error_type": "connection_lost",
                "suggestions": [
                    "The connection to Power BI Desktop was lost",
                    "Ensure Power BI Desktop is still running",
                    "Try reconnecting using 01_Connect_To_Instance"
                ]
            }

        # Validate identifiers
        if not validate_dax_identifier(table_name):
            return {
                "success": False,
                "error": f"Invalid table name: '{table_name}'",
                "error_type": "invalid_parameters",
            }
        if not validate_dax_identifier(measure_name):
            return {
                "success": False,
                "error": f"Invalid measure name: '{measure_name}'",
                "error_type": "invalid_parameters",
            }

        server = AMOServer()

        try:
            # Connect to server
            server.Connect(self.connection.ConnectionString)

            db_name, db_error = self._get_database_name(server)
            if db_error:
                return db_error

            # Get database and model
            db = server.Databases.GetByName(db_name)
            model = db.Model

            # Find table
            table = next((t for t in model.Tables if t.Name == table_name), None)

            if not table:
                available_tables = [t.Name for t in model.Tables]
                return {
                    "success": False,
                    "error": f"Table '{table_name}' not found",
                    "error_type": "table_not_found",
                    "available_tables": available_tables[:10]  # Show first 10
                }

            # Find or create measure
            measure = next((m for m in table.Measures if m.Name == measure_name), None)

            if measure:
                # Update existing measure
                if dax_expression:
                    measure.Expression = dax_expression

                if display_folder is not None:
                    measure.DisplayFolder = display_folder

                if description is not None:
                    measure.Description = description

                if format_string is not None:
                    measure.FormatString = format_string

                if data_category is not None:
                    measure.DataCategory = data_category

                action = "updated"
                logger.info(f"Updated measure '{measure_name}' in table '{table_name}'")

            else:
                # Create new measure (requires an expression)
                if not dax_expression:
                    return {
                        "success": False,
                        "error": "Expression is required when creating a new measure",
                        "error_type": "invalid_parameters"
                    }
                measure = Measure()
                measure.Name = measure_name
                measure.Expression = dax_expression

                if display_folder:
                    measure.DisplayFolder = display_folder

                if description:
                    measure.Description = description

                if format_string:
                    measure.FormatString = format_string

                if data_category:
                    measure.DataCategory = data_category

                table.Measures.Add(measure)
                action = "created"
                logger.info(f"Created measure '{measure_name}' in table '{table_name}'")

            # Save changes
            model.SaveChanges()

            return {
                "success": True,
                "action": action,
                "table": table_name,
                "measure": measure_name,
                "expression": dax_expression,
                "display_folder": display_folder,
                "description": description,
                "format_string": format_string,
                "data_category": data_category,
                "message": f"Successfully {action} measure '{measure_name}' in table '{table_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error upserting measure: {error_msg}")

            # Provide helpful suggestions based on error
            suggestions = []

            if "syntax" in error_msg.lower() or "expression" in error_msg.lower():
                suggestions.extend([
                    "Check DAX syntax - ensure expression is valid",
                    "Verify all referenced columns and measures exist",
                    "Test the DAX expression separately first"
                ])

            if "table" in error_msg.lower():
                suggestions.append(f"Verify table '{table_name}' exists in the model")

            if "duplicate" in error_msg.lower() or "already exists" in error_msg.lower():
                suggestions.append("Measure name may conflict with existing object")

            if not suggestions:
                suggestions.extend([
                    "Verify all table and column references exist",
                    "Check DAX expression syntax",
                    "Ensure model is in a valid state"
                ])

            return {
                "success": False,
                "error": error_msg,
                "error_type": "injection_error",
                "suggestions": suggestions
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def delete_measure(self, table_name: str, measure_name: str) -> Dict[str, Any]:
        """
        Delete a DAX measure.

        Args:
            table_name: Name of the table containing the measure
            measure_name: Name of the measure to delete

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        # Verify connection before AMO operations
        conn_check = self._verify_connection()
        if not conn_check.get('success'):
            return {
                "success": False,
                "error": conn_check.get('error', 'Connection lost'),
                "error_type": "connection_lost"
            }

        # Validate identifiers early
        if not validate_dax_identifier(table_name):
            return {
                "success": False,
                "error": f"Invalid table name: '{table_name}'",
                "error_type": "invalid_parameters",
            }
        if not validate_dax_identifier(measure_name):
            return {
                "success": False,
                "error": f"Invalid measure name: '{measure_name}'",
                "error_type": "invalid_parameters",
            }

        server = AMOServer()

        try:
            server.Connect(self.connection.ConnectionString)

            db_name, db_error = self._get_database_name(server)
            if db_error:
                return db_error

            # Get database and model
            db = server.Databases.GetByName(db_name)
            model = db.Model

            # Find table
            table = next((t for t in model.Tables if t.Name == table_name), None)

            if not table:
                return {
                    "success": False,
                    "error": f"Table '{table_name}' not found"
                }

            # Find measure
            measure = next((m for m in table.Measures if m.Name == measure_name), None)

            if not measure:
                return {
                    "success": False,
                    "error": f"Measure '{measure_name}' not found in table '{table_name}'"
                }

            # Remove measure
            table.Measures.Remove(measure)
            model.SaveChanges()

            logger.info(f"Deleted measure '{measure_name}' from table '{table_name}'")

            return {
                "success": True,
                "action": "deleted",
                "table": table_name,
                "measure": measure_name,
                "message": f"Successfully deleted measure '{measure_name}'"
            }

        except Exception as e:
            logger.error(f"Error deleting measure: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "deletion_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def rename_measure(self, table_name: str, measure_name: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a DAX measure.

        Args:
            table_name: Name of the table containing the measure
            measure_name: Current name of the measure
            new_name: New name for the measure

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        # Verify connection before AMO operations
        conn_check = self._verify_connection()
        if not conn_check.get('success'):
            return {
                "success": False,
                "error": conn_check.get('error', 'Connection lost'),
                "error_type": "connection_lost"
            }

        for name_label, name_val in [
            ("table", table_name),
            ("measure", measure_name),
            ("new measure", new_name),
        ]:
            if not validate_dax_identifier(name_val):
                return {
                    "success": False,
                    "error": f"Invalid {name_label} name: "
                             f"'{name_val}'",
                    "error_type": "invalid_parameters",
                }

        server = AMOServer()

        try:
            server.Connect(self.connection.ConnectionString)

            db_name, db_error = self._get_database_name(server)
            if db_error:
                return db_error

            # Get database and model
            db = server.Databases.GetByName(db_name)
            model = db.Model

            # Find table
            table = next(
                (t for t in model.Tables if t.Name == table_name),
                None,
            )
            if not table:
                return {
                    "success": False,
                    "error": f"Table '{table_name}' not found"
                }

            # Find measure
            measure = next((m for m in table.Measures if m.Name == measure_name), None)
            if not measure:
                return {
                    "success": False,
                    "error": f"Measure '{measure_name}' not found in table '{table_name}'"
                }

            # Check if new name already exists in the table
            if any(m.Name == new_name for m in table.Measures if m != measure):
                return {
                    "success": False,
                    "error": f"Measure '{new_name}' already exists in table '{table_name}'",
                    "error_type": "name_conflict"
                }

            # Rename measure
            old_name = measure.Name
            measure.Name = new_name
            model.SaveChanges()

            logger.info(f"Renamed measure '{old_name}' to '{new_name}' in table '{table_name}'")

            return {
                "success": True,
                "action": "renamed",
                "table": table_name,
                "old_name": old_name,
                "new_name": new_name,
                "message": f"Successfully renamed measure from '{old_name}' to '{new_name}'"
            }

        except Exception as e:
            logger.error(f"Error renaming measure: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "rename_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def move_measure(self, source_table: str, measure_name: str, target_table: str) -> Dict[str, Any]:
        """
        Move a DAX measure from one table to another.

        Args:
            source_table: Name of the table containing the measure
            measure_name: Name of the measure to move
            target_table: Name of the destination table

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        # Verify connection before AMO operations
        conn_check = self._verify_connection()
        if not conn_check.get('success'):
            return {
                "success": False,
                "error": conn_check.get('error', 'Connection lost'),
                "error_type": "connection_lost"
            }

        for name_label, name_val in [
            ("source table", source_table),
            ("measure", measure_name),
            ("target table", target_table),
        ]:
            if not validate_dax_identifier(name_val):
                return {
                    "success": False,
                    "error": f"Invalid {name_label} name: "
                             f"'{name_val}'",
                    "error_type": "invalid_parameters",
                }

        if source_table == target_table:
            return {
                "success": False,
                "error": "Source and target tables must be different",
                "error_type": "invalid_parameters"
            }

        server = AMOServer()

        try:
            server.Connect(self.connection.ConnectionString)

            db_name, db_error = self._get_database_name(server)
            if db_error:
                return db_error

            # Get database and model
            db = server.Databases.GetByName(db_name)
            model = db.Model

            # Find source table
            src_table = next((t for t in model.Tables if t.Name == source_table), None)
            if not src_table:
                return {
                    "success": False,
                    "error": f"Source table '{source_table}' not found",
                    "error_type": "table_not_found"
                }

            # Find target table
            tgt_table = next((t for t in model.Tables if t.Name == target_table), None)
            if not tgt_table:
                return {
                    "success": False,
                    "error": f"Target table '{target_table}' not found",
                    "error_type": "table_not_found"
                }

            # Find measure
            measure = next((m for m in src_table.Measures if m.Name == measure_name), None)
            if not measure:
                return {
                    "success": False,
                    "error": f"Measure '{measure_name}' not found in table '{source_table}'",
                    "error_type": "measure_not_found"
                }

            # Check if measure with same name exists in target table
            if any(m.Name == measure_name for m in tgt_table.Measures):
                return {
                    "success": False,
                    "error": f"Measure '{measure_name}' already exists in target table '{target_table}'",
                    "error_type": "name_conflict"
                }

            # Move measure (remove from source, add to target)
            # Note: We need to create a new measure object with same properties
            new_measure = Measure()
            new_measure.Name = measure.Name
            new_measure.Expression = measure.Expression

            # Copy optional properties
            if hasattr(measure, 'Description') and measure.Description:
                new_measure.Description = measure.Description
            if hasattr(measure, 'DisplayFolder') and measure.DisplayFolder:
                new_measure.DisplayFolder = measure.DisplayFolder
            if hasattr(measure, 'FormatString') and measure.FormatString:
                new_measure.FormatString = measure.FormatString
            if hasattr(measure, 'DataCategory') and measure.DataCategory:
                new_measure.DataCategory = measure.DataCategory

            # Remove from source and add to target
            src_table.Measures.Remove(measure)
            tgt_table.Measures.Add(new_measure)
            model.SaveChanges()

            logger.info(f"Moved measure '{measure_name}' from table '{source_table}' to '{target_table}'")

            return {
                "success": True,
                "action": "moved",
                "measure": measure_name,
                "source_table": source_table,
                "target_table": target_table,
                "message": f"Successfully moved measure '{measure_name}' from '{source_table}' to '{target_table}'"
            }

        except Exception as e:
            logger.error(f"Error moving measure: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "move_error",
                "suggestions": [
                    "Verify both source and target tables exist",
                    "Check that measure references are valid in target table context",
                    "Ensure no name conflicts in target table"
                ]
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass
