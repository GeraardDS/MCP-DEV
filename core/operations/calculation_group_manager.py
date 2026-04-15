"""
Calculation Group Manager for PBIXRay MCP Server
Manage calculation groups and calculation items
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

AMO_AVAILABLE = True  # Determined lazily per-connection


def _read_calc_item_format_string(item):
    """Read the format string expression across TOM versions."""
    try:
        fsd = getattr(item, "FormatStringDefinition", None)
        if fsd is not None:
            expr = getattr(fsd, "Expression", None)
            if expr:
                return str(expr)
    except Exception:
        pass
    try:
        if hasattr(item, "FormatStringExpression"):
            v = item.FormatStringExpression
            return str(v) if v else None
    except Exception:
        pass
    return None


def _set_calc_item_format_string(item, expression: str, Tabular) -> bool:
    """Set the calculation item's format string expression across TOM versions.

    Newer TOM exposes FormatStringDefinition (a complex object with .Expression);
    older TOM exposes FormatStringExpression as a flat string. Try the modern
    path first, then fall back. Returns True on success, False if neither works.
    """
    try:
        FSDef = getattr(Tabular, "FormatStringDefinition", None)
        if FSDef is not None:
            fsd = FSDef()
            fsd.Expression = expression
            item.FormatStringDefinition = fsd
            return True
    except Exception:
        pass
    try:
        if hasattr(item, "FormatStringExpression"):
            item.FormatStringExpression = expression
            return True
    except Exception:
        pass
    return False


class CalculationGroupManager:
    """Manage calculation groups and items."""

    def __init__(self, connection):
        """Initialize with ADOMD connection."""
        self.connection = connection

    def _connect_amo_server_db(self):
        """Open a TOM Server using the ADOMD connection string and return (server, db, TabularModule) or (None, None, None)."""
        try:
            from core.infrastructure.dll_paths import load_amo_assemblies
            load_amo_assemblies()
            import Microsoft.AnalysisServices.Tabular as Tabular  # type: ignore
            server = Tabular.Server()
            conn_str = getattr(self.connection, 'ConnectionString', None)
            if not conn_str:
                return None, None, None
            server.Connect(conn_str)
            db = server.Databases[0] if server.Databases.Count > 0 else None
            if not db:
                try:
                    server.Disconnect()
                except Exception:
                    pass
                return None, None, None
            return server, db, Tabular
        except Exception as _e:
            logger.warning(f"AMO not available for calc groups: {_e}")
            return None, None, None

    def _list_calculation_groups_via_dax(self) -> Dict[str, Any]:
        """List calculation groups using DAX queries (fallback when AMO unavailable)."""
        try:
            import Microsoft.AnalysisServices.AdomdClient as Adomd  # type: ignore

            # Query to get all tables that are calculation groups
            tables_query = """
            EVALUATE
            SELECTCOLUMNS(
                FILTER(
                    INFO.TABLES(),
                    [TABLE_TYPE] = "CALCULATION_GROUP"
                ),
                "TableName", [Name],
                "Description", [Description]
            )
            """

            calc_groups = []

            # Execute the query to get calculation group tables
            cmd = Adomd.AdomdCommand(tables_query, self.connection)
            reader = cmd.ExecuteReader()

            cg_tables = []
            while reader.Read():
                cg_tables.append({
                    'table_name': str(reader[0]) if reader[0] is not None else '',
                    'description': str(reader[1]) if reader[1] is not None else None
                })
            reader.Close()

            # For each calculation group table, get its items
            for cg_table in cg_tables:
                table_name = cg_table['table_name']

                # Query calculation items using EVALUATE on the calculation group table
                try:
                    items_query = f"""
                    EVALUATE
                    SELECTCOLUMNS(
                        '{table_name}',
                        "Name", [{table_name}]
                    )
                    """

                    cmd_items = Adomd.AdomdCommand(items_query, self.connection)
                    reader_items = cmd_items.ExecuteReader()

                    items = []
                    ordinal = 0
                    while reader_items.Read():
                        item_name = str(reader_items[0]) if reader_items[0] is not None else ''
                        items.append({
                            'name': item_name,
                            'expression': None,  # Not available via DAX query
                            'ordinal': ordinal,
                            'format_string_expression': None
                        })
                        ordinal += 1
                    reader_items.Close()

                    calc_groups.append({
                        'name': table_name,
                        'table': table_name,
                        'precedence': 0,  # Not available via DAX query
                        'description': cg_table['description'],
                        'items': items,
                        'item_count': len(items)
                    })

                except Exception as item_error:
                    logger.warning(f"Could not query items for calculation group '{table_name}': {item_error}")
                    # Add the calc group without items
                    calc_groups.append({
                        'name': table_name,
                        'table': table_name,
                        'precedence': 0,
                        'description': cg_table['description'],
                        'items': [],
                        'item_count': 0
                    })

            return {
                'success': True,
                'calculation_groups': calc_groups,
                'total_groups': len(calc_groups),
                'method': 'dax_dmv',
                'note': 'Limited information available via DAX queries. For full details (expressions, precedence), AMO connection is required.'
            }

        except Exception as e:
            logger.error(f"Error listing calculation groups via DAX: {e}")
            return {'success': False, 'error': f'Failed to list calculation groups via DAX: {str(e)}'}

    def list_calculation_groups(self) -> Dict[str, Any]:
        """List all calculation groups and their items."""
        # Try DAX-based approach first (works without AMO)
        dax_result = self._list_calculation_groups_via_dax()
        if dax_result.get('success'):
            return dax_result

        # Fall back to AMO if DAX approach fails
        server, db, Tabular = self._connect_amo_server_db()
        if not server or not db or not Tabular:
            # Both methods failed
            return {
                'success': False,
                'error': 'Unable to list calculation groups. AMO not available and DAX query failed.',
                'dax_error': dax_result.get('error')
            }
        try:
            model = db.Model

            calc_groups = []

            for table in model.Tables:
                if hasattr(table, 'CalculationGroup') and table.CalculationGroup is not None:
                    calc_group = table.CalculationGroup

                    items = []
                    for item in calc_group.CalculationItems:
                        items.append({
                            'name': item.Name,
                            'expression': item.Expression,
                            'ordinal': item.Ordinal if hasattr(item, 'Ordinal') else None,
                            'format_string_expression': _read_calc_item_format_string(item)
                        })

                    calc_groups.append({
                        'name': calc_group.Name if hasattr(calc_group, 'Name') else table.Name,
                        'table': table.Name,
                        'precedence': calc_group.Precedence if hasattr(calc_group, 'Precedence') else 0,
                        'description': calc_group.Description if hasattr(calc_group, 'Description') else None,
                        'items': items,
                        'item_count': len(items)
                    })

            return {
                'success': True,
                'calculation_groups': calc_groups,
                'total_groups': len(calc_groups)
            }

        except Exception as e:
            logger.error(f"Error listing calculation groups: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def create_calculation_group(
        self,
        name: str,
        items: List[Dict[str, Any]],
        description: Optional[str] = None,
        precedence: int = 0
    ) -> Dict[str, Any]:
        """
        Create a calculation group with items.

        Args:
            name: Name of the calculation group
            items: List of calculation items with 'name' and 'expression'
            description: Optional description
            precedence: Precedence level (default 0)

        Returns:
            Result dictionary
        """
        server, db, Tabular = self._connect_amo_server_db()
        if not server or not db or not Tabular:
            return {'success': False, 'error': 'AMO not available for calculation groups'}

        if not items:
            return {
                'success': False,
                'error': 'At least one calculation item is required'
            }

        try:
            model = db.Model

            # Check if table already exists
            existing_table = next((t for t in model.Tables if t.Name == name), None)
            if existing_table:
                return {
                    'success': False,
                    'error': f"Table '{name}' already exists. Use a different name."
                }

            # Create table for calculation group
            table = Tabular.Table()
            table.Name = name
            
            # Mark table as CalculationGroup type if supported
            try:
                if hasattr(Tabular, 'TableType') and hasattr(table, 'TableType'):
                    table.TableType = Tabular.TableType.CalculationGroup
            except Exception:
                pass

            # Create calculation group
            calc_group = Tabular.CalculationGroup()
            if description:
                calc_group.Description = description
            if hasattr(calc_group, 'Precedence'):
                calc_group.Precedence = precedence

            # Create the mandatory calculation group column (string type)
            # Must be added to table.Columns, not calc_group.Columns
            try:
                cg_col = Tabular.CalculationGroupColumn()
                cg_col.Name = name
                table.Columns.Add(cg_col)
            except Exception:
                # Older TOM fallback: use DataColumn with String type
                try:
                    data_col = Tabular.DataColumn()
                    data_col.Name = name
                    try:
                        data_col.DataType = Tabular.DataType.String
                    except Exception:
                        pass
                    table.Columns.Add(data_col)
                except Exception as inner_e:
                    return {
                        'success': False,
                        'error': 'Failed to create calculation group column',
                        'details': str(inner_e)
                    }

            # Add calculation items
            for idx, item_data in enumerate(items):
                item = Tabular.CalculationItem()
                item.Name = item_data.get('name')
                item.Expression = item_data.get('expression')

                if 'ordinal' in item_data and hasattr(item, 'Ordinal'):
                    item.Ordinal = item_data['ordinal']
                elif hasattr(item, 'Ordinal'):
                    item.Ordinal = idx

                if 'format_string_expression' in item_data and item_data['format_string_expression']:
                    _set_calc_item_format_string(item, item_data['format_string_expression'], Tabular)

                calc_group.CalculationItems.Add(item)

            table.CalculationGroup = calc_group
            
            # CRITICAL: TOM requires calculation group tables to have a partition with CalculationGroup source
            # This partition must exist before SaveChanges() validation
            try:
                part = Tabular.Partition()
                part.Name = f"{name}_Partition"
                
                # Calculation groups require a CalculationGroupSource (not M or Query source)
                try:
                    cg_source = Tabular.CalculationGroupSource()
                    part.Source = cg_source
                    logger.info(f"Created CalculationGroupSource partition for '{name}'")
                except Exception as cg_error:
                    # Fallback for older TOM: try creating without explicit source type
                    logger.warning(f"CalculationGroupSource not available: {cg_error}")
                    # Some TOM versions auto-create partition source for calc groups
                    pass
                
                # Set DataView to Full if available (required for some TOM versions)
                if hasattr(part, 'DataView'):
                    try:
                        if hasattr(Tabular, 'DataViewType'):
                            part.DataView = Tabular.DataViewType.Full
                        else:
                            part.DataView = 0  # numeric: 0 = Full
                    except Exception as dv_error:
                        logger.debug(f"DataView setting failed: {dv_error}")
                
                # Add the partition to the table BEFORE adding table to model
                table.Partitions.Add(part)
                logger.info(f"Added CalculationGroup partition to table '{name}'")
                
            except Exception as part_error:
                logger.warning(f"Failed to create partition for calculation group: {part_error}")
                # Continue - SaveChanges will provide specific error if partition is critical
            
            # Add table to model
            model.Tables.Add(table)

            # Save changes - this will validate the complete structure
            try:
                model.SaveChanges()
                logger.info(f"Created calculation group '{name}' with {len(items)} items")
            except Exception as save_error:
                # Provide helpful error message about common issues
                error_msg = str(save_error)
                suggestions = [
                    'Verify calculation item expressions are valid DAX',
                    'Ensure calculation group name is unique',
                    'Check that model compatibility level supports calculation groups (1470+)'
                ]
                
                if 'partition' in error_msg.lower() or 'dataview' in error_msg.lower():
                    suggestions.insert(0, 'Partition validation failed - this TOM version may have specific DataView requirements')
                
                return {
                    'success': False,
                    'error': error_msg,
                    'suggestions': suggestions
                }

            return {
                'success': True,
                'action': 'created',
                'calculation_group': name,
                'items_count': len(items),
                'message': f"Successfully created calculation group '{name}' with {len(items)} items"
            }

        except Exception as e:
            logger.error(f"Error creating calculation group: {e}")
            return {
                'success': False,
                'error': str(e),
                'suggestions': [
                    'Verify calculation item expressions are valid DAX',
                    'Ensure calculation group name is unique',
                    'Check that model compatibility level supports calculation groups (1470+)',
                    'Verify TOM libraries are up to date'
                ]
            }
        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def delete_calculation_group(self, name: str) -> Dict[str, Any]:
        """Delete a calculation group."""
        server, db, Tabular = self._connect_amo_server_db()
        if not server or not db or not Tabular:
            return {'success': False, 'error': 'AMO not available'}
        try:
            model = db.Model

            # Find table with calculation group
            table = next((t for t in model.Tables if t.Name == name and hasattr(t, 'CalculationGroup') and t.CalculationGroup is not None), None)

            if not table:
                return {
                    'success': False,
                    'error': f"Calculation group '{name}' not found"
                }

            # Remove table (which contains calculation group)
            model.Tables.Remove(table)
            model.SaveChanges()

            logger.info(f"Deleted calculation group '{name}'")

            return {
                'success': True,
                'action': 'deleted',
                'calculation_group': name,
                'message': f"Successfully deleted calculation group '{name}'"
            }

        except Exception as e:
            logger.error(f"Error deleting calculation group: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    def _find_calc_group_table(self, model, group_name: str):
        """Find a table hosting a calculation group by table name."""
        for t in model.Tables:
            try:
                if t.Name == group_name and getattr(t, "CalculationGroup", None) is not None:
                    return t
            except Exception:
                continue
        return None

    def add_calculation_item(
        self,
        group_name: str,
        item_name: str,
        expression: str,
        ordinal: Optional[int] = None,
        format_string_expression: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a new item to an existing calculation group."""
        if not item_name or expression is None:
            return {"success": False, "error": "item_name and expression are required"}
        server, db, Tabular = self._connect_amo_server_db()
        if not server or not db or not Tabular:
            return {"success": False, "error": "AMO not available"}
        try:
            model = db.Model
            table = self._find_calc_group_table(model, group_name)
            if table is None:
                return {"success": False, "error": f"Calculation group '{group_name}' not found"}
            cg = table.CalculationGroup
            existing = next((i for i in cg.CalculationItems if i.Name == item_name), None)
            if existing is not None:
                return {"success": False, "error": f"Item '{item_name}' already exists in '{group_name}'"}
            item = Tabular.CalculationItem()
            item.Name = item_name
            item.Expression = expression
            if ordinal is not None and hasattr(item, "Ordinal"):
                item.Ordinal = ordinal
            if format_string_expression is not None:
                if not _set_calc_item_format_string(item, format_string_expression, Tabular):
                    return {"success": False, "error": "TOM does not expose FormatStringExpression / FormatStringDefinition on this CalculationItem; cannot set format_string_expression"}
            if description:
                item.Description = description
            cg.CalculationItems.Add(item)
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Added item '{item_name}' to '{group_name}'",
                "group": group_name,
                "item": item_name,
            }
        except Exception as e:
            logger.error(f"add_calculation_item failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            try: server.Disconnect()
            except Exception: pass

    def update_calculation_item(
        self,
        group_name: str,
        item_name: str,
        new_name: Optional[str] = None,
        expression: Optional[str] = None,
        ordinal: Optional[int] = None,
        format_string_expression: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing calculation item. Any field can be renamed or edited."""
        server, db, Tabular = self._connect_amo_server_db()
        if not server or not db or not Tabular:
            return {"success": False, "error": "AMO not available"}
        try:
            model = db.Model
            table = self._find_calc_group_table(model, group_name)
            if table is None:
                return {"success": False, "error": f"Calculation group '{group_name}' not found"}
            cg = table.CalculationGroup
            item = next((i for i in cg.CalculationItems if i.Name == item_name), None)
            if item is None:
                return {"success": False, "error": f"Item '{item_name}' not found in '{group_name}'"}
            updates = []
            if new_name and new_name != item_name:
                try:
                    item.RequestRename(new_name)
                except Exception:
                    item.Name = new_name
                updates.append(f"renamed to '{new_name}'")
            if expression is not None:
                item.Expression = expression
                updates.append("expression")
            if ordinal is not None and hasattr(item, "Ordinal"):
                item.Ordinal = ordinal
                updates.append(f"ordinal={ordinal}")
            if format_string_expression is not None:
                if _set_calc_item_format_string(item, format_string_expression, Tabular):
                    updates.append("format_string_expression")
                else:
                    return {"success": False, "error": "TOM does not expose FormatStringExpression / FormatStringDefinition on this CalculationItem; cannot set format_string_expression"}
            if description is not None:
                item.Description = description
                updates.append("description")
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Updated item '{item_name}' in '{group_name}': {', '.join(updates) or 'no changes'}",
                "group": group_name,
                "item": new_name or item_name,
            }
        except Exception as e:
            logger.error(f"update_calculation_item failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            try: server.Disconnect()
            except Exception: pass

    def delete_calculation_item(self, group_name: str, item_name: str) -> Dict[str, Any]:
        """Delete a calculation item from a calculation group."""
        server, db, Tabular = self._connect_amo_server_db()
        if not server or not db or not Tabular:
            return {"success": False, "error": "AMO not available"}
        try:
            model = db.Model
            table = self._find_calc_group_table(model, group_name)
            if table is None:
                return {"success": False, "error": f"Calculation group '{group_name}' not found"}
            cg = table.CalculationGroup
            item = next((i for i in cg.CalculationItems if i.Name == item_name), None)
            if item is None:
                return {"success": False, "error": f"Item '{item_name}' not found in '{group_name}'"}
            cg.CalculationItems.Remove(item)
            model.SaveChanges()
            return {
                "success": True,
                "message": f"Deleted item '{item_name}' from '{group_name}'",
            }
        except Exception as e:
            logger.error(f"delete_calculation_item failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            try: server.Disconnect()
            except Exception: pass
