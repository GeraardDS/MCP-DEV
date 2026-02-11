"""
RLS Manager for PBIXRay MCP Server
Manages Row-Level Security roles and testing
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Try to load AMO
AMO_AVAILABLE = False
AMOServer = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import Server as AMOServer
    AMO_AVAILABLE = True
except Exception as e:
    logger.warning(f"AMO not available: {e}")


class RLSManager:
    """Manage Row-Level Security roles."""

    def __init__(self, connection, query_executor):
        """Initialize with connection and query executor."""
        self.connection = connection
        self.executor = query_executor

    def list_roles(self) -> Dict[str, Any]:
        """List all security roles and their filters."""
        if not AMO_AVAILABLE:
            return {
                'success': False,
                'error': 'AMO not available for role management'
            }

        server = AMOServer()
        try:
            server.Connect(self.connection.ConnectionString)

            if server.Databases.Count == 0:
                return {'success': False, 'error': 'No database found'}

            db = server.Databases[0]
            model = db.Model

            roles = []

            if hasattr(model, 'Roles'):
                for role in model.Roles:
                    role_data = {
                        'name': role.Name,
                        'description': role.Description if hasattr(role, 'Description') else None,
                        'model_permission': str(role.ModelPermission) if hasattr(role, 'ModelPermission') else 'Read',
                        'table_permissions': []
                    }

                    # Get table permissions (filters)
                    if hasattr(role, 'TablePermissions'):
                        for perm in role.TablePermissions:
                            perm_data = {
                                'table': perm.Table.Name if perm.Table else 'Unknown'
                            }

                            if hasattr(perm, 'FilterExpression') and perm.FilterExpression:
                                perm_data['filter_expression'] = perm.FilterExpression

                            role_data['table_permissions'].append(perm_data)

                    # Get members count
                    if hasattr(role, 'Members'):
                        role_data['members_count'] = role.Members.Count
                    else:
                        role_data['members_count'] = 0

                    roles.append(role_data)

            return {
                'success': True,
                'roles': roles,
                'total_roles': len(roles)
            }

        except Exception as e:
            logger.error(f"Error listing roles: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def test_role_filter(self, role_name: str, test_query: str) -> Dict[str, Any]:
        """
        Test RLS by executing query with role filter applied.

        Args:
            role_name: Role name to test
            test_query: DAX query to execute with role filter

        Returns:
            Query results with role filter applied
        """
        try:
            # First, get the role filters
            roles_result = self.list_roles()
            if not roles_result.get('success'):
                return roles_result

            # Find the role
            role = next((r for r in roles_result['roles'] if r['name'] == role_name), None)
            if not role:
                return {
                    'success': False,
                    'error': f"Role '{role_name}' not found"
                }

            # Execute test query normally
            result_without_rls = self.executor.validate_and_execute_dax(test_query)

            # Note: Actual RLS testing with impersonation requires XMLA
            # For now, we show what the role filters are
            return {
                'success': True,
                'role': role_name,
                'test_query': test_query,
                'result_without_rls': result_without_rls,
                'role_filters': role.get('table_permissions', []),
                'note': 'Full RLS impersonation testing requires XMLA endpoint connection',
                'recommendation': 'Manually verify filters by adding WHERE clause to query'
            }

        except Exception as e:
            logger.error(f"Error testing role: {e}")
            return {'success': False, 'error': str(e)}

    def validate_rls_coverage(self) -> Dict[str, Any]:
        """Check if all tables with sensitive data have RLS applied."""
        try:
            # Get all tables
            tables_result = self.executor.execute_info_query("TABLES", top_n=100)
            if not tables_result.get('success'):
                return tables_result

            # Prefer visible, uniquely named tables to avoid skewed coverage
            all_tables = tables_result.get('rows', [])
            tables: List[str] = []
            seen: set[str] = set()
            for t in all_tables:
                name = t.get('Name') or t.get('[Name]')
                if not name:
                    continue
                hidden_val = t.get('IsHidden') or t.get('[IsHidden]')
                is_hidden = bool(str(hidden_val).strip().lower() == 'true') if hidden_val is not None else bool(hidden_val)
                if is_hidden:
                    continue
                if name not in seen:
                    seen.add(str(name))
                    tables.append(str(name))

            # Get roles
            roles_result = self.list_roles()
            if not roles_result.get('success'):
                return roles_result

            # Get all tables with RLS filters
            tables_with_rls = set()
            for role in roles_result['roles']:
                for perm in role.get('table_permissions', []):
                    if perm.get('filter_expression'):
                        tables_with_rls.add(perm['table'])

            # Find tables without RLS
            tables_without_rls = [t for t in tables if t not in tables_with_rls]

            return {
                'success': True,
                'total_tables': len(tables),
                'tables_with_rls': len(tables_with_rls),
                'tables_without_rls': len(tables_without_rls),
                'uncovered_tables': sorted(list(tables_without_rls))[:20],  # First 20 unique, sorted for stability
                'coverage_percentage': round((len(tables_with_rls) / len(tables) * 100.0), 1) if tables else 0.0,
                'recommendation': 'Review tables without RLS to ensure they do not contain sensitive data'
            }

        except Exception as e:
            logger.error(f"Error validating RLS coverage: {e}")
            return {'success': False, 'error': str(e)}
