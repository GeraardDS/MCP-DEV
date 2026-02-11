"""
Measure CRUD Manager for MCP-PowerBi-Finvision
Provides measure rename and move operations
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

AMO_AVAILABLE = False
AMOServer = None
Measure = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import Server as AMOServer, Measure
    AMO_AVAILABLE = True
    logger.info("AMO available for measure CRUD operations")
except Exception as e:
    logger.warning(f"AMO not available for measure CRUD: {e}")


# Try to load ADOMD
AdomdConnection = None
AdomdCommand = None

try:
    from core.infrastructure.dll_paths import load_adomd_assembly
    if load_adomd_assembly():
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection, AdomdCommand
except Exception:
    pass


class MeasureCRUDManager:
    """Manage measure CRUD operations using TOM."""

    def __init__(self, connection):
        """Initialize with ADOMD connection."""
        self.connection = connection

    def _valid_identifier(self, s: Optional[str]) -> bool:
        """Validate identifier (measure name, etc.)."""
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

    def rename_measure(self, table_name: str, measure_name: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a measure.

        Args:
            table_name: Table containing the measure
            measure_name: Current measure name
            new_name: New measure name

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available - cannot rename measures",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(table_name) or not self._valid_identifier(measure_name) or not self._valid_identifier(new_name):
            return {
                "success": False,
                "error": "Table name, measure name, and new name must be non-empty and <=128 chars",
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

            # Find measure
            measure = next((m for m in table.Measures if m.Name == measure_name), None)
            if not measure:
                return {
                    "success": False,
                    "error": f"Measure '{measure_name}' not found in table '{table_name}'",
                    "error_type": "measure_not_found"
                }

            # Check if new name already exists
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
            error_msg = str(e)
            logger.error(f"Error renaming measure: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "rename_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def move_measure(self, source_table: str, measure_name: str, target_table: str) -> Dict[str, Any]:
        """
        Move a measure to a different table.

        Args:
            source_table: Current table containing the measure
            measure_name: Measure name to move
            target_table: Target table to move measure to

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available - cannot move measures",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(source_table) or not self._valid_identifier(measure_name) or not self._valid_identifier(target_table):
            return {
                "success": False,
                "error": "Source table, measure name, and target table must be non-empty and <=128 chars",
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

            # Check if measure with same name already exists in target table
            if any(m.Name == measure_name for m in tgt_table.Measures):
                return {
                    "success": False,
                    "error": f"Measure '{measure_name}' already exists in target table '{target_table}'",
                    "error_type": "name_conflict"
                }

            # Save measure properties
            expression = measure.Expression
            description = measure.Description if hasattr(measure, 'Description') else None
            format_string = measure.FormatString if hasattr(measure, 'FormatString') else None
            display_folder = measure.DisplayFolder if hasattr(measure, 'DisplayFolder') else None
            is_hidden = measure.IsHidden if hasattr(measure, 'IsHidden') else False

            # Remove measure from source table
            src_table.Measures.Remove(measure)

            # Create new measure in target table
            new_measure = Measure()
            new_measure.Name = measure_name
            new_measure.Expression = expression
            if description:
                new_measure.Description = description
            if format_string:
                new_measure.FormatString = format_string
            if display_folder:
                new_measure.DisplayFolder = display_folder
            new_measure.IsHidden = is_hidden

            tgt_table.Measures.Add(new_measure)
            model.SaveChanges()

            logger.info(f"Moved measure '{measure_name}' from '{source_table}' to '{target_table}'")

            return {
                "success": True,
                "action": "moved",
                "measure": measure_name,
                "source_table": source_table,
                "target_table": target_table,
                "message": f"Successfully moved measure '{measure_name}' from '{source_table}' to '{target_table}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error moving measure: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "move_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass
