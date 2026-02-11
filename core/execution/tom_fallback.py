"""TOM/AMO fallback methods for when DMV queries are blocked."""
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

AMO_AVAILABLE = False
try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import Server as AMOServer
    AMO_AVAILABLE = True
except Exception as e:
    logger.warning(f"AMO/TOM not available: {e}")


class TomFallback:
    """Fallback methods using TOM/AMO when DMV queries fail."""

    @staticmethod
    def connect_amo_server_db(connection, get_db_name_callback) -> Tuple[Any, Any]:
        if not AMO_AVAILABLE:
            return None, None
        try:
            srv = AMOServer()
            conn_str = getattr(connection, "ConnectionString", None)
            if not conn_str:
                return None, None
            srv.Connect(conn_str)
            db_name = get_db_name_callback()
            db = None
            if db_name and hasattr(srv, "Databases"):
                try:
                    db = srv.Databases.GetByName(db_name)
                except Exception:
                    db = srv.Databases[0] if srv.Databases.Count > 0 else None
            else:
                db = srv.Databases[0] if srv.Databases.Count > 0 else None
            if not db:
                try:
                    srv.Disconnect()
                except Exception:
                    pass
                return None, None
            return srv, db
        except Exception as e:
            logger.debug(f"connect_amo_server_db failed: {e}")
            return None, None

    @staticmethod
    def enumerate_m_expressions(connection, get_db_name_callback, limit: Optional[int] = None) -> Dict[str, Any]:
        server, db = TomFallback.connect_amo_server_db(connection, get_db_name_callback)
        if not server or not db:
            return {"success": False, "error": "AMO/TOM unavailable", "error_type": "amo_not_available"}
        try:
            rows: List[Dict[str, Any]] = []
            model = db.Model
            exprs = getattr(model, "Expressions", None)
            if exprs:
                for exp in exprs:
                    rows.append({"Name": getattr(exp, "Name", ""), "Expression": getattr(exp, "Expression", ""), "Kind": "M"})
                    if limit and len(rows) >= limit:
                        break
            return {"success": True, "rows": rows, "row_count": len(rows), "method": "TOM"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                server.Disconnect()
            except Exception:
                pass
