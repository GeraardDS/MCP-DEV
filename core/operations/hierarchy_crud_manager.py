"""Hierarchy CRUD Manager — manage table hierarchies via TOM."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class HierarchyCrudManager:
    """CRUD operations for table hierarchies."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_hierarchies(self, table_name: str = None) -> Dict[str, Any]:
        """List hierarchies, optionally filtered by table."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        hierarchies = []
        tables = [model.Tables.Find(table_name)] if table_name else model.Tables
        for table in tables:
            if table is None:
                return {"success": False, "error": f"Table '{table_name}' not found"}
            for hier in table.Hierarchies:
                levels = []
                for level in hier.Levels:
                    levels.append({
                        "name": level.Name,
                        "ordinal": level.Ordinal,
                        "column": level.Column.Name if level.Column else None,
                    })
                hierarchies.append({
                    "table": table.Name,
                    "name": hier.Name,
                    "description": hier.Description or "",
                    "is_hidden": hier.IsHidden,
                    "levels": levels,
                })
        return {"success": True, "hierarchies": hierarchies, "count": len(hierarchies)}

    def describe_hierarchy(self, table_name: str, hierarchy_name: str) -> Dict[str, Any]:
        """Get detailed info about a hierarchy."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}
        hier = table.Hierarchies.Find(hierarchy_name)
        if not hier:
            return {"success": False, "error": f"Hierarchy '{hierarchy_name}' not found in '{table_name}'"}
        levels = []
        for level in hier.Levels:
            levels.append({
                "name": level.Name,
                "ordinal": level.Ordinal,
                "column": level.Column.Name if level.Column else None,
            })
        return {
            "success": True,
            "hierarchy": {
                "table": table.Name, "name": hier.Name, "description": hier.Description or "",
                "is_hidden": hier.IsHidden, "display_folder": hier.DisplayFolder or "", "levels": levels,
            },
        }

    def create_hierarchy(self, table_name: str, hierarchy_name: str, levels: list, **kwargs) -> Dict[str, Any]:
        """Create a new hierarchy with specified levels."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}
        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            hier = TOM.Hierarchy()
            hier.Name = hierarchy_name
            if kwargs.get("description"):
                hier.Description = kwargs["description"]
            if kwargs.get("display_folder"):
                hier.DisplayFolder = kwargs["display_folder"]
            if kwargs.get("hidden") is not None:
                hier.IsHidden = kwargs["hidden"]
            for i, level_info in enumerate(levels):
                level = TOM.Level()
                level.Name = level_info.get("name", level_info.get("column"))
                level.Ordinal = i
                col = table.Columns.Find(level_info["column"])
                if not col:
                    return {"success": False, "error": f"Column '{level_info['column']}' not found in '{table_name}'"}
                level.Column = col
                hier.Levels.Add(level)
            table.Hierarchies.Add(hier)
            model.SaveChanges()
            return {"success": True, "message": f"Hierarchy '{hierarchy_name}' created with {len(levels)} levels"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_hierarchy(self, table_name: str, hierarchy_name: str) -> Dict[str, Any]:
        """Delete a hierarchy."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}
        hier = table.Hierarchies.Find(hierarchy_name)
        if not hier:
            return {"success": False, "error": f"Hierarchy '{hierarchy_name}' not found"}
        try:
            table.Hierarchies.Remove(hier)
            model.SaveChanges()
            return {"success": True, "message": f"Hierarchy '{hierarchy_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}
