"""Shared AMO/TOM helpers for CRUD managers.

Centralizes the server/db/model acquisition pattern so every CRUD manager
doesn't re-implement the same ~30 lines of boilerplate.
"""
import logging
from typing import Any, Optional, Tuple

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


def get_server_db_model(connection_state) -> Tuple[Any, Any, Any, Optional[str]]:
    """Acquire an AMO server + database + model from the active connection.

    Returns (server, db, model, error). On error, (None, None, None, message).
    Caller is responsible for server.Disconnect() in a finally block.
    """
    if AMOServer is None:
        return None, None, None, "AMO assemblies not available"
    cm = connection_state.connection_manager
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


def safe_disconnect(server) -> None:
    """Disconnect an AMO server silently."""
    try:
        server.Disconnect()
    except Exception:
        pass
