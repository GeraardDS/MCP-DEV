"""Model Refresh Manager — refresh model, tables, or partitions via TOM.

Field parameter tables are calculated tables; use refresh_type='calculate' to
recompute them after member edits, or 'full' to reprocess everything.
"""
import logging
from typing import Any, Dict, List, Optional

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

_REFRESH_TYPES = {
    "full": 0,
    "automatic": 2,
    "dataOnly": 3,
    "calculate": 4,
    "clearValues": 5,
    "defragment": 6,
}


def _resolve_refresh_type(refresh_type: str):
    """Resolve a refresh type string to the TOM RefreshType enum value."""
    key = (refresh_type or "automatic").strip()
    for name in _REFRESH_TYPES:
        if name.lower() == key.lower():
            key = name
            break
    if key not in _REFRESH_TYPES:
        return None, f"Invalid refresh_type '{refresh_type}'. Valid: {list(_REFRESH_TYPES.keys())}"
    try:
        from Microsoft.AnalysisServices.Tabular import RefreshType
        return getattr(RefreshType, key[0].upper() + key[1:]), None
    except Exception as e:
        return None, f"Failed to resolve RefreshType: {e}"


class ModelRefreshManager:
    """Refresh the whole model, a set of tables, or report status."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def _get_server_db_model(self):
        """Connect AMO server using the live ADOMD connection string and return (server, db, model)."""
        if AMOServer is None:
            return None, None, None, "AMO assemblies not available"

        cm = self.connection_state.connection_manager
        if cm is None:
            return None, None, None, "Not connected: no connection_manager"
        try:
            conn = cm.get_connection()
        except Exception as e:
            return None, None, None, f"Failed to obtain ADOMD connection: {e}"
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
            model = db.Model
            return server, db, model, None
        except Exception as e:
            try: server.Disconnect()
            except Exception: pass
            return None, None, None, f"AMO connect failed: {e}"

    def refresh(
        self,
        refresh_type: str = "automatic",
        tables: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Refresh the model or a specific set of tables.

        Args:
            refresh_type: full|automatic|dataOnly|calculate|clearValues|defragment
            tables: Optional list of table names. If omitted, refreshes the whole model.

        Returns:
            Dict with success, refresh_type, refreshed targets, and any errors.
        """
        server, db, model, err = self._get_server_db_model()
        if err:
            return {"success": False, "error": err}

        rtype, err = _resolve_refresh_type(refresh_type)
        if err:
            try: server.Disconnect()
            except Exception: pass
            return {"success": False, "error": err}

        refreshed: List[str] = []
        missing: List[str] = []

        try:
            if tables:
                for name in tables:
                    tbl = model.Tables.Find(name)
                    if not tbl:
                        missing.append(name)
                        continue
                    tbl.RequestRefresh(rtype)
                    refreshed.append(name)
                scope = "tables"
            else:
                model.RequestRefresh(rtype)
                refreshed = [t.Name for t in model.Tables]
                scope = "model"

            model.SaveChanges()

            result = {
                "success": True,
                "scope": scope,
                "refresh_type": refresh_type,
                "refreshed_count": len(refreshed),
                "refreshed": refreshed,
                "note": "Refresh is processed synchronously on Power BI Desktop; table data reflects the new state on return.",
            }
            if missing:
                result["missing_tables"] = missing
                result["warning"] = f"{len(missing)} table(s) not found and skipped"
            return result

        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            return {
                "success": False,
                "error": f"Refresh failed: {e}",
                "refresh_type": refresh_type,
                "refreshed_before_error": refreshed,
            }
        finally:
            try: server.Disconnect()
            except Exception: pass
