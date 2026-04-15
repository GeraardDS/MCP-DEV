"""RLS Role CRUD Manager — create/update/delete security roles, table filters, and members via TOM."""
import logging
from typing import Any, Dict, List, Optional

from core.operations.amo_helpers import get_server_db_model, safe_disconnect

logger = logging.getLogger(__name__)

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    if load_amo_assemblies():
        from Microsoft.AnalysisServices.Tabular import (
            ModelRole, ModelPermission, TablePermission, ModelRoleMember,
            ExternalModelRoleMember, WindowsModelRoleMember,
        )
    else:
        ModelRole = None
        ModelPermission = None
        TablePermission = None
        ModelRoleMember = None
        ExternalModelRoleMember = None
        WindowsModelRoleMember = None
except Exception as e:
    logger.debug(f"AMO not loaded: {e}")
    ModelRole = None
    ModelPermission = None
    TablePermission = None
    ModelRoleMember = None
    ExternalModelRoleMember = None
    WindowsModelRoleMember = None


_PERMISSION_MAP = {
    "none": "None",
    "read": "Read",
    "readrefresh": "ReadRefresh",
    "refresh": "Refresh",
    "administrator": "Administrator",
}


def _resolve_permission(value: str):
    """Parse permission string to ModelPermission enum."""
    if ModelPermission is None:
        return None
    key = (value or "read").strip().lower()
    name = _PERMISSION_MAP.get(key, "Read")
    return getattr(ModelPermission, name)


class RlsRoleCrudManager:
    """CRUD for model roles, table permissions (filters), and role members."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def create_role(
        self,
        role_name: str,
        model_permission: str = "Read",
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new role."""
        if ModelRole is None:
            return {"success": False, "error": "AMO not available"}
        if not role_name:
            return {"success": False, "error": "role_name is required"}
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            if model.Roles.Find(role_name) is not None:
                return {"success": False, "error": f"Role '{role_name}' already exists"}
            role = ModelRole()
            role.Name = role_name
            role.ModelPermission = _resolve_permission(model_permission)
            if description:
                role.Description = description
            model.Roles.Add(role)
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Created role '{role_name}'",
                "role": role_name,
                "model_permission": model_permission,
            }
        except Exception as e:
            return {"success": False, "error": f"create_role failed: {e}"}
        finally:
            safe_disconnect(server)

    def update_role(
        self,
        role_name: str,
        new_name: Optional[str] = None,
        model_permission: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rename and/or update permission/description."""
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            role = model.Roles.Find(role_name)
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            updates = []
            if new_name and new_name != role_name:
                role.RequestRename(new_name)
                updates.append(f"renamed to '{new_name}'")
            if model_permission is not None:
                role.ModelPermission = _resolve_permission(model_permission)
                updates.append(f"permission={model_permission}")
            if description is not None:
                role.Description = description
                updates.append("description")
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Updated role '{role_name}': {', '.join(updates) or 'no changes'}",
                "role": new_name or role_name,
            }
        except Exception as e:
            return {"success": False, "error": f"update_role failed: {e}"}
        finally:
            safe_disconnect(server)

    def delete_role(self, role_name: str) -> Dict[str, Any]:
        """Delete a role and all its table permissions + members."""
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            role = model.Roles.Find(role_name)
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            model.Roles.Remove(role)
            model.SaveChanges()
            return {"success": True, "message": f"Deleted role '{role_name}'"}
        except Exception as e:
            return {"success": False, "error": f"delete_role failed: {e}"}
        finally:
            safe_disconnect(server)

    def set_table_filter(
        self,
        role_name: str,
        table_name: str,
        filter_expression: str,
    ) -> Dict[str, Any]:
        """Set or update a table's RLS filter expression on a role.

        Passing an empty filter_expression is not allowed — use clear_table_filter instead.
        """
        if TablePermission is None:
            return {"success": False, "error": "AMO not available"}
        if not filter_expression:
            return {"success": False, "error": "filter_expression is required; use clear_table_filter to remove"}
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            role = model.Roles.Find(role_name)
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            table = model.Tables.Find(table_name)
            if table is None:
                return {"success": False, "error": f"Table '{table_name}' not found"}
            perm = role.TablePermissions.Find(table_name)
            created = False
            if perm is None:
                perm = TablePermission()
                perm.Table = table
                role.TablePermissions.Add(perm)
                created = True
            perm.FilterExpression = filter_expression
            model.SaveChanges()
            return {
                "success": True,
                "message": f"{'Created' if created else 'Updated'} filter on '{table_name}' for role '{role_name}'",
                "role": role_name,
                "table": table_name,
                "filter_expression": filter_expression,
            }
        except Exception as e:
            return {"success": False, "error": f"set_table_filter failed: {e}"}
        finally:
            safe_disconnect(server)

    def clear_table_filter(self, role_name: str, table_name: str) -> Dict[str, Any]:
        """Remove a role's RLS filter on a table (drops the TablePermission)."""
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            role = model.Roles.Find(role_name)
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            perm = role.TablePermissions.Find(table_name)
            if perm is None:
                return {"success": False, "error": f"No permission for '{table_name}' on role '{role_name}'"}
            role.TablePermissions.Remove(perm)
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Cleared filter on '{table_name}' for role '{role_name}'",
            }
        except Exception as e:
            return {"success": False, "error": f"clear_table_filter failed: {e}"}
        finally:
            safe_disconnect(server)

    def add_member(
        self,
        role_name: str,
        member_identifier: str,
        member_type: str = "external",
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a member to a role.

        member_type: 'external' (default — UPN or AAD object ID) or 'windows' (domain\\user).
        """
        if ModelRoleMember is None:
            return {"success": False, "error": "AMO not available"}
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            role = model.Roles.Find(role_name)
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            mtype = (member_type or "external").strip().lower()
            if mtype == "windows":
                member = WindowsModelRoleMember()
            else:
                member = ExternalModelRoleMember()
                if tenant_id:
                    member.IdentityProvider = "AzureAD"
                    member.TenantId = tenant_id
            member.MemberName = member_identifier
            role.Members.Add(member)
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Added {mtype} member '{member_identifier}' to '{role_name}'",
            }
        except Exception as e:
            return {"success": False, "error": f"add_member failed: {e}"}
        finally:
            safe_disconnect(server)

    def remove_member(self, role_name: str, member_identifier: str) -> Dict[str, Any]:
        """Remove a member from a role by MemberName match."""
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            role = model.Roles.Find(role_name)
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            target = None
            for m in role.Members:
                if str(m.MemberName) == member_identifier:
                    target = m
                    break
            if target is None:
                return {"success": False, "error": f"Member '{member_identifier}' not found on role '{role_name}'"}
            role.Members.Remove(target)
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Removed member '{member_identifier}' from '{role_name}'",
            }
        except Exception as e:
            return {"success": False, "error": f"remove_member failed: {e}"}
        finally:
            safe_disconnect(server)

    def list_members(self, role_name: str) -> Dict[str, Any]:
        """List all members on a role."""
        server, db, model, err = get_server_db_model(self.connection_state)
        if err:
            return {"success": False, "error": err}
        try:
            role = model.Roles.Find(role_name)
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            members: List[Dict[str, Any]] = []
            for m in role.Members:
                entry = {
                    "name": str(m.MemberName),
                    "member_type": m.GetType().Name,
                }
                try:
                    if hasattr(m, "IdentityProvider"):
                        entry["identity_provider"] = str(m.IdentityProvider) if m.IdentityProvider else None
                except Exception:
                    pass
                members.append(entry)
            return {
                "success": True,
                "role": role_name,
                "members": members,
                "count": len(members),
            }
        except Exception as e:
            return {"success": False, "error": f"list_members failed: {e}"}
        finally:
            safe_disconnect(server)
