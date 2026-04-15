"""
Measure CRUD Manager for MCP-PowerBi-Finvision
Provides measure rename and move operations
"""

import logging
from typing import Dict, Any, Optional, List

from core.operations.rename_cascade import cascade_measure_rename

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

            # Rename measure and cascade DAX references
            old_name = measure.Name
            measure.Name = new_name

            # Cascade: update all expressions referencing [old_name] -> [new_name]
            cascaded = cascade_measure_rename(model, old_name, new_name, table_name=table_name)

            model.SaveChanges()

            logger.info(f"Renamed measure '{old_name}' to '{new_name}' in table '{table_name}', cascaded {len(cascaded)} references")

            result = {
                "success": True,
                "action": "renamed",
                "table": table_name,
                "old_name": old_name,
                "new_name": new_name,
                "message": f"Successfully renamed measure from '{old_name}' to '{new_name}'"
            }
            if cascaded:
                result["cascaded_references"] = len(cascaded)
                result["updated_expressions"] = cascaded
            return result

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

    def batch_rename_measures(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Rename multiple measures in a single AMO connection.
        All renames + cascades happen on the same model snapshot,
        then SaveChanges() is called once at the end.

        Each item needs: table/table_name, measure/measure_name/name, new_name
        """
        if not AMO_AVAILABLE:
            return {"success": False, "error": "AMO not available", "error_type": "amo_unavailable"}

        server, db, model = self._get_server_db_model()
        if not model:
            return {"success": False, "error": "Could not connect to model", "error_type": "connection_error"}

        results = []
        errors = []
        try:
            for item in items:
                table_name = item.get('table') or item.get('table_name')
                measure_name = item.get('measure') or item.get('measure_name') or item.get('name')
                new_name = item.get('new_name')

                if not all([table_name, measure_name, new_name]):
                    r = {"success": False, "error": "Missing table, measure, or new_name", "item": item}
                    results.append(r)
                    errors.append(r)
                    continue

                table = next((t for t in model.Tables if t.Name == table_name), None)
                if not table:
                    r = {"success": False, "error": f"Table '{table_name}' not found", "item": item}
                    results.append(r)
                    errors.append(r)
                    continue

                measure = next((m for m in table.Measures if m.Name == measure_name), None)
                if not measure:
                    r = {"success": False, "error": f"Measure '{measure_name}' not found in '{table_name}'", "item": item}
                    results.append(r)
                    errors.append(r)
                    continue

                # Check conflicts across ALL tables (measure names are model-wide in DAX)
                if any(m.Name == new_name for m in table.Measures if m != measure):
                    r = {"success": False, "error": f"Measure '{new_name}' already exists in '{table_name}'", "item": item}
                    results.append(r)
                    errors.append(r)
                    continue

                old_name = measure.Name
                measure.Name = new_name
                cascaded = cascade_measure_rename(model, old_name, new_name, table_name=table_name)

                results.append({
                    "success": True,
                    "action": "renamed",
                    "table": table_name,
                    "old_name": old_name,
                    "new_name": new_name,
                    "cascaded_references": len(cascaded),
                })

            # Single SaveChanges for all renames
            if any(r.get('success') for r in results):
                model.SaveChanges()

            return {
                "success": len(errors) == 0,
                "operation": "rename",
                "total": len(items),
                "succeeded": len([r for r in results if r.get('success')]),
                "failed": len(errors),
                "results": results,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"Error in batch rename: {e}")
            return {"success": False, "error": str(e), "error_type": "batch_rename_error"}

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

            # Save all measure properties before removal
            props = {
                'expression': measure.Expression,
                'description': getattr(measure, 'Description', None) or '',
                'format_string': getattr(measure, 'FormatString', None) or '',
                'display_folder': getattr(measure, 'DisplayFolder', None) or '',
                'is_hidden': getattr(measure, 'IsHidden', False),
                'data_category': getattr(measure, 'DataCategory', None) or '',
            }

            # Preserve annotations
            annotations = {}
            try:
                for ann in measure.Annotations:
                    annotations[ann.Name] = ann.Value
            except Exception:
                pass

            # Preserve KPI
            has_kpi = hasattr(measure, 'KPI') and measure.KPI is not None
            kpi_props = {}
            if has_kpi:
                kpi = measure.KPI
                for attr in ('TargetExpression', 'StatusExpression', 'TrendExpression',
                             'TargetDescription', 'StatusDescription', 'TrendDescription',
                             'TargetFormatString', 'StatusGraphic', 'TrendGraphic'):
                    kpi_props[attr] = getattr(kpi, attr, None)

            # Preserve detail rows
            detail_rows_expr = None
            if hasattr(measure, 'DetailRowsDefinition') and measure.DetailRowsDefinition:
                drd = measure.DetailRowsDefinition
                if hasattr(drd, 'Expression'):
                    detail_rows_expr = drd.Expression

            # Remove measure from source table
            src_table.Measures.Remove(measure)

            # Create new measure in target table with ALL properties
            new_measure = Measure()
            new_measure.Name = measure_name
            new_measure.Expression = props['expression']
            new_measure.Description = props['description']
            new_measure.FormatString = props['format_string']
            new_measure.DisplayFolder = props['display_folder']
            new_measure.IsHidden = props['is_hidden']
            if props['data_category']:
                new_measure.DataCategory = props['data_category']

            tgt_table.Measures.Add(new_measure)

            # Restore annotations
            for ann_name, ann_value in annotations.items():
                try:
                    from Microsoft.AnalysisServices.Tabular import Annotation
                    ann = Annotation()
                    ann.Name = ann_name
                    ann.Value = ann_value
                    new_measure.Annotations.Add(ann)
                except Exception:
                    pass

            # Restore detail rows
            if detail_rows_expr:
                try:
                    from Microsoft.AnalysisServices.Tabular import DetailRowsDefinition
                    drd = DetailRowsDefinition()
                    drd.Expression = detail_rows_expr
                    new_measure.DetailRowsDefinition = drd
                except Exception:
                    pass

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
