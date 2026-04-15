"""Partition CRUD Manager — manage table partitions via TOM."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

try:
    from core.infrastructure.dll_paths import load_amo_assemblies, load_adomd_assembly
    if load_amo_assemblies():
        from Microsoft.AnalysisServices.Tabular import Server as AMOServer
    else:
        AMOServer = None
    if load_adomd_assembly():
        from Microsoft.AnalysisServices.AdomdClient import AdomdCommand
    else:
        AdomdCommand = None
except Exception as e:
    logger.debug(f"AMO/ADOMD assemblies not loaded: {e}")
    AMOServer = None
    AdomdCommand = None


class PartitionCrudManager:
    """CRUD operations for table partitions."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def _get_server_db_model(self):
        if AMOServer is None:
            return None, None, None, "AMO assemblies not available"
        cm = self.connection_state.connection_manager
        if cm is None:
            return None, None, None, "Not connected"
        try:
            conn = cm.get_connection()
        except Exception as e:
            return None, None, None, f"Failed to get ADOMD connection: {e}"
        if conn is None:
            return None, None, None, "ADOMD connection is None"
        server = AMOServer()
        try:
            server.Connect(conn.ConnectionString)
            db_name = None
            try:
                if AdomdCommand is not None:
                    cmd = AdomdCommand("SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS", conn)
                    reader = cmd.ExecuteReader()
                    if reader.Read():
                        db_name = str(reader.GetValue(0))
                    reader.Close()
            except Exception:
                db_name = None
            if not db_name and server.Databases.Count > 0:
                db_name = server.Databases[0].Name
            if not db_name:
                try: server.Disconnect()
                except Exception: pass
                return None, None, None, "Could not determine database name"
            db = server.Databases.GetByName(db_name)
            return server, db, db.Model, None
        except Exception as e:
            try: server.Disconnect()
            except Exception: pass
            return None, None, None, f"AMO connect failed: {e}"

    def list_partitions(self, table_name: str) -> Dict[str, Any]:
        """List all partitions for a table."""
        server, db, model, err = self._get_server_db_model()
        if err:
            return {"success": False, "error": err}
        try:
            table = model.Tables.Find(table_name)
            if not table:
                return {"success": False, "error": f"Table '{table_name}' not found"}
            partitions = []
            for partition in table.Partitions:
                partitions.append({
                    "name": partition.Name,
                    "source_type": str(partition.SourceType),
                    "mode": str(partition.Mode) if hasattr(partition, 'Mode') else None,
                    "state": str(partition.State) if hasattr(partition, 'State') else None,
                    "refreshed_time": str(partition.RefreshedTime) if hasattr(partition, 'RefreshedTime') else None,
                })
            return {"success": True, "table": table_name, "partitions": partitions, "count": len(partitions)}
        finally:
            try: server.Disconnect()
            except Exception: pass

    def describe_partition(self, table_name: str, partition_name: str) -> Dict[str, Any]:
        """Get detailed info about a partition."""
        server, db, model, err = self._get_server_db_model()
        if err:
            return {"success": False, "error": err}
        try:
            table = model.Tables.Find(table_name)
            if not table:
                return {"success": False, "error": f"Table '{table_name}' not found"}
            partition = table.Partitions.Find(partition_name)
            if not partition:
                return {"success": False, "error": f"Partition '{partition_name}' not found in '{table_name}'"}
            info = {
                "name": partition.Name,
                "source_type": str(partition.SourceType),
                "mode": str(partition.Mode) if hasattr(partition, 'Mode') else None,
                "state": str(partition.State) if hasattr(partition, 'State') else None,
                "refreshed_time": str(partition.RefreshedTime) if hasattr(partition, 'RefreshedTime') else None,
            }
            try:
                if hasattr(partition, 'Source') and hasattr(partition.Source, 'Expression'):
                    info["expression"] = partition.Source.Expression
            except Exception:
                pass
            return {"success": True, "partition": info}
        finally:
            try: server.Disconnect()
            except Exception: pass

    def update_partition_expression(self, table_name: str, partition_name: str, expression: str) -> Dict[str, Any]:
        """Update the M expression of a partition."""
        server, db, model, err = self._get_server_db_model()
        if err:
            return {"success": False, "error": err}
        try:
            table = model.Tables.Find(table_name)
            if not table:
                return {"success": False, "error": f"Table '{table_name}' not found"}
            partition = table.Partitions.Find(partition_name)
            if not partition:
                return {"success": False, "error": f"Partition '{partition_name}' not found"}
            try:
                partition.Source.Expression = expression
                model.SaveChanges()
                return {"success": True, "message": f"Updated expression for partition '{partition_name}'"}
            except Exception as e:
                return {"success": False, "error": f"Update failed: {e}"}
        finally:
            try: server.Disconnect()
            except Exception: pass

    def refresh_partition(self, table_name: str, partition_name: str) -> Dict[str, Any]:
        """Refresh a specific partition."""
        server, db, model, err = self._get_server_db_model()
        if err:
            return {"success": False, "error": err}
        try:
            table = model.Tables.Find(table_name)
            if not table:
                return {"success": False, "error": f"Table '{table_name}' not found"}
            partition = table.Partitions.Find(partition_name)
            if not partition:
                return {"success": False, "error": f"Partition '{partition_name}' not found"}
            try:
                from Microsoft.AnalysisServices.Tabular import RefreshType
                partition.RequestRefresh(RefreshType.Automatic)
                model.SaveChanges()
                return {"success": True, "message": f"Refresh requested for partition '{partition_name}'"}
            except Exception as e:
                return {"success": False, "error": f"Refresh failed: {e}"}
        finally:
            try: server.Disconnect()
            except Exception: pass
