"""Perspective CRUD Manager — manage model perspectives via TOM."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class PerspectiveCrudManager:
    """CRUD operations for model perspectives."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_perspectives(self) -> Dict[str, Any]:
        """List all perspectives in the model."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        perspectives = []
        for persp in model.Perspectives:
            table_count = sum(1 for _ in persp.PerspectiveTables)
            perspectives.append({
                "name": persp.Name,
                "description": persp.Description or "",
                "table_count": table_count,
            })
        return {"success": True, "perspectives": perspectives, "count": len(perspectives)}

    def describe_perspective(self, perspective_name: str) -> Dict[str, Any]:
        """Get detailed info about a perspective."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        persp = model.Perspectives.Find(perspective_name)
        if not persp:
            return {"success": False, "error": f"Perspective '{perspective_name}' not found"}
        tables = []
        for pt in persp.PerspectiveTables:
            columns = [pc.Name for pc in pt.PerspectiveColumns]
            measures = [pm.Name for pm in pt.PerspectiveMeasures]
            hierarchies = [ph.Name for ph in pt.PerspectiveHierarchies]
            tables.append({"table": pt.Name, "columns": columns, "measures": measures, "hierarchies": hierarchies})
        return {"success": True, "perspective": {"name": persp.Name, "description": persp.Description or "", "tables": tables}}

    def create_perspective(self, perspective_name: str, **kwargs) -> Dict[str, Any]:
        """Create a new perspective."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            persp = TOM.Perspective()
            persp.Name = perspective_name
            if kwargs.get("description"):
                persp.Description = kwargs["description"]
            model.Perspectives.Add(persp)
            model.SaveChanges()
            return {"success": True, "message": f"Perspective '{perspective_name}' created"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_perspective(self, perspective_name: str) -> Dict[str, Any]:
        """Delete a perspective."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        persp = model.Perspectives.Find(perspective_name)
        if not persp:
            return {"success": False, "error": f"Perspective '{perspective_name}' not found"}
        try:
            model.Perspectives.Remove(persp)
            model.SaveChanges()
            return {"success": True, "message": f"Perspective '{perspective_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}
