"""
Relationship CRUD Manager for MCP-PowerBi-Finvision
Provides comprehensive relationship management: create, update, delete, activate, deactivate
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

AMO_AVAILABLE = False
AMOServer = None
SingleColumnRelationship = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import (
        Server as AMOServer,
        SingleColumnRelationship,
        RelationshipEndCardinality,
        CrossFilteringBehavior
    )
    AMO_AVAILABLE = True
    logger.info("AMO available for relationship CRUD operations")
except Exception as e:
    logger.warning(f"AMO not available for relationship CRUD: {e}")


# Try to load ADOMD
AdomdConnection = None
AdomdCommand = None

try:
    from core.infrastructure.dll_paths import load_adomd_assembly
    if load_adomd_assembly():
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection, AdomdCommand
except Exception:
    pass


class RelationshipCRUDManager:
    """Manage relationship CRUD operations using TOM."""

    def __init__(self, connection):
        """Initialize with ADOMD connection."""
        self.connection = connection

    def _valid_identifier(self, s: Optional[str]) -> bool:
        """Validate identifier (table name, column name, etc.)."""
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

    def _parse_cardinality(self, cardinality_str: str):
        """Parse cardinality string to TOM enum."""
        from Microsoft.AnalysisServices.Tabular import RelationshipEndCardinality

        cardinality_map = {
            'One': RelationshipEndCardinality.One,
            'Many': RelationshipEndCardinality.Many
        }

        return cardinality_map.get(cardinality_str, RelationshipEndCardinality.Many)

    def _parse_cross_filtering(self, cross_filtering_str: str):
        """Parse cross filtering behavior string to TOM enum."""
        from Microsoft.AnalysisServices.Tabular import CrossFilteringBehavior

        cf_map = {
            'OneDirection': CrossFilteringBehavior.OneDirection,
            'BothDirections': CrossFilteringBehavior.BothDirections,
            'Automatic': CrossFilteringBehavior.Automatic
        }

        return cf_map.get(cross_filtering_str, CrossFilteringBehavior.OneDirection)

    def create_relationship(
        self,
        from_table: str,
        from_column: str,
        to_table: str,
        to_column: str,
        name: Optional[str] = None,
        from_cardinality: str = "Many",
        to_cardinality: str = "One",
        cross_filtering_behavior: str = "OneDirection",
        is_active: bool = True
    ) -> Dict[str, Any]:
        """
        Create a new relationship between tables.

        Args:
            from_table: Source table name
            from_column: Source column name
            to_table: Target table name
            to_column: Target column name
            name: Relationship name (optional, auto-generated if not provided)
            from_cardinality: Source cardinality (Many, One)
            to_cardinality: Target cardinality (Many, One)
            cross_filtering_behavior: OneDirection, BothDirections, Automatic
            is_active: Whether relationship is active (default: True)

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available - cannot create relationships",
                "error_type": "amo_unavailable"
            }

        if not all([self._valid_identifier(x) for x in [from_table, from_column, to_table, to_column]]):
            return {
                "success": False,
                "error": "Table and column names must be non-empty and <=128 chars",
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
            # Find tables
            from_table_obj = next((t for t in model.Tables if t.Name == from_table), None)
            to_table_obj = next((t for t in model.Tables if t.Name == to_table), None)

            if not from_table_obj:
                return {
                    "success": False,
                    "error": f"Source table '{from_table}' not found",
                    "error_type": "table_not_found"
                }

            if not to_table_obj:
                return {
                    "success": False,
                    "error": f"Target table '{to_table}' not found",
                    "error_type": "table_not_found"
                }

            # Find columns
            from_column_obj = next((c for c in from_table_obj.Columns if c.Name == from_column), None)
            to_column_obj = next((c for c in to_table_obj.Columns if c.Name == to_column), None)

            if not from_column_obj:
                return {
                    "success": False,
                    "error": f"Source column '{from_column}' not found in table '{from_table}'",
                    "error_type": "column_not_found"
                }

            if not to_column_obj:
                return {
                    "success": False,
                    "error": f"Target column '{to_column}' not found in table '{to_table}'",
                    "error_type": "column_not_found"
                }

            # Create relationship
            from Microsoft.AnalysisServices.Tabular import SingleColumnRelationship
            relationship = SingleColumnRelationship()

            # Set name (auto-generate if not provided)
            if name and self._valid_identifier(name):
                relationship.Name = name
            else:
                # Auto-generate name
                relationship.Name = f"{from_table}_{from_column}_to_{to_table}_{to_column}"

            # Set columns
            relationship.FromColumn = from_column_obj
            relationship.ToColumn = to_column_obj

            # Set cardinality
            relationship.FromCardinality = self._parse_cardinality(from_cardinality)
            relationship.ToCardinality = self._parse_cardinality(to_cardinality)

            # Set cross filtering behavior
            relationship.CrossFilteringBehavior = self._parse_cross_filtering(cross_filtering_behavior)

            # Set active state
            relationship.IsActive = is_active

            # Add to model
            model.Relationships.Add(relationship)
            model.SaveChanges()

            logger.info(f"Created relationship from {from_table}[{from_column}] to {to_table}[{to_column}]")

            return {
                "success": True,
                "action": "created",
                "name": relationship.Name,
                "from_table": from_table,
                "from_column": from_column,
                "to_table": to_table,
                "to_column": to_column,
                "from_cardinality": from_cardinality,
                "to_cardinality": to_cardinality,
                "cross_filtering_behavior": cross_filtering_behavior,
                "is_active": is_active,
                "message": f"Successfully created relationship '{relationship.Name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error creating relationship: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "creation_error",
                "suggestions": [
                    "Verify column data types are compatible",
                    "Check if relationship already exists between these columns",
                    "Ensure no circular dependencies in relationships"
                ]
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def update_relationship(
        self,
        relationship_name: str,
        cross_filtering_behavior: Optional[str] = None,
        is_active: Optional[bool] = None,
        new_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing relationship.

        Args:
            relationship_name: Current relationship name
            cross_filtering_behavior: New cross filtering behavior (optional)
            is_active: New active state (optional)
            new_name: New relationship name (optional)

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(relationship_name):
            return {
                "success": False,
                "error": "Relationship name must be non-empty and <=128 chars",
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
            # Find relationship
            relationship = next((r for r in model.Relationships if r.Name == relationship_name), None)
            if not relationship:
                return {
                    "success": False,
                    "error": f"Relationship '{relationship_name}' not found",
                    "error_type": "relationship_not_found"
                }

            updates = []

            # Update cross filtering behavior
            if cross_filtering_behavior is not None:
                relationship.CrossFilteringBehavior = self._parse_cross_filtering(cross_filtering_behavior)
                updates.append("cross_filtering_behavior")

            # Update active state
            if is_active is not None:
                relationship.IsActive = is_active
                updates.append("is_active")

            # Update name
            if new_name and self._valid_identifier(new_name):
                # Check if new name already exists
                if any(r.Name == new_name for r in model.Relationships if r != relationship):
                    return {
                        "success": False,
                        "error": f"Relationship '{new_name}' already exists",
                        "error_type": "name_conflict"
                    }
                relationship.Name = new_name
                updates.append("name")

            model.SaveChanges()

            logger.info(f"Updated relationship '{relationship_name}': {', '.join(updates)}")

            return {
                "success": True,
                "action": "updated",
                "name": new_name if new_name else relationship_name,
                "original_name": relationship_name if new_name else None,
                "updates": updates,
                "message": f"Successfully updated relationship '{relationship_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error updating relationship: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "update_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def delete_relationship(self, relationship_name: str) -> Dict[str, Any]:
        """
        Delete a relationship.

        Args:
            relationship_name: Name of the relationship to delete

        Returns:
            Result dictionary with success status
        """
        if not AMO_AVAILABLE:
            return {
                "success": False,
                "error": "AMO not available",
                "error_type": "amo_unavailable"
            }

        if not self._valid_identifier(relationship_name):
            return {
                "success": False,
                "error": "Relationship name must be non-empty and <=128 chars",
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
            # Find relationship
            relationship = next((r for r in model.Relationships if r.Name == relationship_name), None)
            if not relationship:
                return {
                    "success": False,
                    "error": f"Relationship '{relationship_name}' not found",
                    "error_type": "relationship_not_found"
                }

            # Remove relationship
            model.Relationships.Remove(relationship)
            model.SaveChanges()

            logger.info(f"Deleted relationship '{relationship_name}'")

            return {
                "success": True,
                "action": "deleted",
                "name": relationship_name,
                "message": f"Successfully deleted relationship '{relationship_name}'"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error deleting relationship: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "deletion_error"
            }

        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def activate_relationship(self, relationship_name: str) -> Dict[str, Any]:
        """
        Activate a relationship.

        Args:
            relationship_name: Name of the relationship to activate

        Returns:
            Result dictionary with success status
        """
        return self.update_relationship(relationship_name=relationship_name, is_active=True)

    def deactivate_relationship(self, relationship_name: str) -> Dict[str, Any]:
        """
        Deactivate a relationship.

        Args:
            relationship_name: Name of the relationship to deactivate

        Returns:
            Result dictionary with success status
        """
        return self.update_relationship(relationship_name=relationship_name, is_active=False)

    def rename_relationship(self, relationship_name: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a relationship.

        Args:
            relationship_name: Current relationship name
            new_name: New relationship name

        Returns:
            Result dictionary with success status
        """
        return self.update_relationship(relationship_name=relationship_name, new_name=new_name)
