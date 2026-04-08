"""OLS CRUD Manager — manage Object-Level Security rules via TOM."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class OlsCrudManager:
    """CRUD operations for Object-Level Security rules."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_ols_rules(self, role_name: str = None) -> Dict[str, Any]:
        """List OLS rules, optionally filtered by role."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        rules = []
        roles = [model.Roles.Find(role_name)] if role_name else model.Roles
        for role in roles:
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            for tp in role.TablePermissions:
                for cp in tp.ColumnPermissions:
                    rules.append({
                        "role": role.Name, "table": tp.Name, "column": cp.Name,
                        "metadata_permission": str(cp.MetadataPermission),
                    })
        return {"success": True, "ols_rules": rules, "count": len(rules)}

    def set_ols_rule(self, role_name: str, table_name: str, column_name: str,
                     permission: str = "None") -> Dict[str, Any]:
        """Set OLS permission on a column. permission: 'None' (block), 'Read', 'Default'."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        role = model.Roles.Find(role_name)
        if not role:
            return {"success": False, "error": f"Role '{role_name}' not found"}
        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}
        col = table.Columns.Find(column_name)
        if not col:
            return {"success": False, "error": f"Column '{column_name}' not found in '{table_name}'"}
        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            tp = role.TablePermissions.Find(table_name)
            if not tp:
                tp = TOM.TablePermission()
                tp.Table = table
                role.TablePermissions.Add(tp)
            perm_map = {
                "None": TOM.MetadataPermission.None_,
                "Read": TOM.MetadataPermission.Read,
                "Default": TOM.MetadataPermission.Default,
            }
            perm = perm_map.get(permission)
            if perm is None:
                return {"success": False, "error": f"Invalid permission: {permission}. Use: None, Read, Default"}
            cp = tp.ColumnPermissions.Find(column_name)
            if not cp:
                cp = TOM.ColumnPermission()
                cp.Column = col
                tp.ColumnPermissions.Add(cp)
            cp.MetadataPermission = perm
            model.SaveChanges()
            return {"success": True, "message": f"OLS set: {role_name}/{table_name}/{column_name} = {permission}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_ols_rule(self, role_name: str, table_name: str, column_name: str) -> Dict[str, Any]:
        """Remove OLS permission from a column."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        role = model.Roles.Find(role_name)
        if not role:
            return {"success": False, "error": f"Role '{role_name}' not found"}
        tp = role.TablePermissions.Find(table_name)
        if not tp:
            return {"success": False, "error": f"No table permission for '{table_name}' in role '{role_name}'"}
        cp = tp.ColumnPermissions.Find(column_name)
        if not cp:
            return {"success": False, "error": f"No OLS rule for '{column_name}' in '{table_name}'"}
        try:
            tp.ColumnPermissions.Remove(cp)
            model.SaveChanges()
            return {"success": True, "message": f"OLS removed: {role_name}/{table_name}/{column_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
