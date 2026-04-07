"""Interactive Model Explorer for Power BI models.

Generates a comprehensive, interactive HTML application for exploring:
- Table dependencies and usage
- Measure dependencies (forward and reverse)
- Interactive relationship graph visualization
- Column usage across measures and relationships
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .utils import ensure_dir, now_iso, safe_filename

logger = logging.getLogger(__name__)


class InteractiveDependencyExplorer:
    """Generates interactive HTML explorer for Power BI model dependencies."""

    def __init__(self, connection_state):
        """Initialize explorer with connection state.

        Args:
            connection_state: Active connection state with query executor and managers
        """
        self.connection_state = connection_state
        self.query_executor = connection_state.query_executor
        self.dependency_analyzer = connection_state.dependency_analyzer

        # Validate that query executor is available
        if not self.query_executor:
            raise ValueError("Query executor is not initialized. Ensure connection is established and managers are initialized.")

    def collect_all_model_data(
        self, include_hidden: bool = True, dependency_depth: int = 5
    ) -> Dict[str, Any]:
        """Collect all model data needed for the explorer.

        Args:
            include_hidden: Include hidden objects in analysis (default: True)
            dependency_depth: Maximum depth for dependency tree analysis

        Returns:
            Dictionary with all model data and metadata

        Raises:
            TypeError: If parameter types are invalid
            ValueError: If parameter values are out of valid range
        """
        # Input validation
        if not isinstance(include_hidden, bool):
            raise TypeError(f"include_hidden must be boolean, got {type(include_hidden).__name__}")

        if not isinstance(dependency_depth, int):
            raise TypeError(f"dependency_depth must be integer, got {type(dependency_depth).__name__}")

        if dependency_depth < 1:
            raise ValueError(f"dependency_depth must be >= 1, got {dependency_depth}")

        if dependency_depth > 10:
            logger.warning(
                f"dependency_depth={dependency_depth} > 10 may cause performance issues "
                f"and long execution times. Consider using a smaller value."
            )

        try:
            logger.info("Collecting model data for interactive explorer")

            # Fetch raw data from Power BI
            logger.debug("Fetching TABLES data...")
            tables_result = self.query_executor.execute_info_query("TABLES", top_n=5000)
            logger.debug(f"TABLES result: success={tables_result.get('success')}, rows={len(tables_result.get('rows', []))}")

            logger.debug("Fetching COLUMNS data...")
            columns_result = self.query_executor.execute_info_query("COLUMNS", top_n=5000)
            logger.debug(f"COLUMNS result: success={columns_result.get('success')}, rows={len(columns_result.get('rows', []))}")

            logger.debug("Fetching MEASURES data...")
            measures_result = self.query_executor.execute_info_query("MEASURES", top_n=5000)
            logger.debug(f"MEASURES result: success={measures_result.get('success')}, rows={len(measures_result.get('rows', []))}")

            logger.debug("Fetching RELATIONSHIPS data...")
            relationships_result = self.query_executor.execute_info_query("RELATIONSHIPS", top_n=5000)
            logger.debug(f"RELATIONSHIPS result: success={relationships_result.get('success')}, rows={len(relationships_result.get('rows', []))}")

            if not all(
                [
                    tables_result.get("success"),
                    columns_result.get("success"),
                    measures_result.get("success"),
                ]
            ):
                error_details = []
                if not tables_result.get("success"):
                    error_details.append(f"TABLES: {tables_result.get('error', 'Unknown error')}")
                if not columns_result.get("success"):
                    error_details.append(f"COLUMNS: {columns_result.get('error', 'Unknown error')}")
                if not measures_result.get("success"):
                    error_details.append(f"MEASURES: {measures_result.get('error', 'Unknown error')}")

                error_message = "Failed to fetch model metadata: " + "; ".join(error_details)
                logger.error(error_message)
                return {
                    "success": False,
                    "error": error_message,
                }

            tables_raw = tables_result.get("rows", [])
            columns_raw = columns_result.get("rows", [])
            measures_raw = measures_result.get("rows", [])
            relationships_raw = relationships_result.get("rows", [])

            logger.info(f"Fetched raw data: {len(tables_raw)} tables, {len(columns_raw)} columns, {len(measures_raw)} measures, {len(relationships_raw)} relationships")

            # Fetch row counts via TOM
            logger.debug("Fetching row counts via TOM...")
            row_counts = self.query_executor.get_table_row_counts()
            logger.info(f"Fetched row counts for {len(row_counts)} tables")

            # Log sample data for debugging
            if tables_raw and len(tables_raw) > 0:
                logger.debug(f"Sample table row keys: {list(tables_raw[0].keys())}")
                logger.debug(f"Sample table row: {tables_raw[0]}")
            if columns_raw and len(columns_raw) > 0:
                logger.debug(f"Sample column row keys: {list(columns_raw[0].keys())}")
                logger.debug(f"Sample column row: {columns_raw[0]}")
            if measures_raw and len(measures_raw) > 0:
                logger.debug(f"Sample measure row keys: {list(measures_raw[0].keys())}")
            if relationships_raw and len(relationships_raw) > 0:
                logger.debug(f"Sample relationship row keys: {list(relationships_raw[0].keys())}")
                logger.debug(f"Sample relationship row: {relationships_raw[0]}")

            # Check if we got any data at all
            if len(tables_raw) == 0 and len(measures_raw) == 0:
                logger.warning("No tables or measures found in the model. This could indicate:")
                logger.warning("  1. The model is empty")
                logger.warning("  2. All objects are hidden (try include_hidden=True)")
                logger.warning("  3. There's a connection issue")

                # Return a more informative error
                return {
                    "success": False,
                    "error": "No tables or measures found in the Power BI model. The model may be empty, or all objects are hidden. Try setting include_hidden=True to see hidden objects.",
                    "raw_counts": {
                        "tables": len(tables_raw),
                        "columns": len(columns_raw),
                        "measures": len(measures_raw),
                        "relationships": len(relationships_raw),
                    }
                }

            # Filter hidden objects if requested
            if not include_hidden:
                tables_before = len(tables_raw)
                columns_before = len(columns_raw)
                measures_before = len(measures_raw)

                tables_raw = [t for t in tables_raw if not self._get_field(t, "IsHidden")]
                columns_raw = [c for c in columns_raw if not self._get_field(c, "IsHidden")]
                measures_raw = [m for m in measures_raw if not self._get_field(m, "IsHidden")]

                logger.info(f"After filtering hidden objects: {len(tables_raw)}/{tables_before} tables, {len(columns_raw)}/{columns_before} columns, {len(measures_raw)}/{measures_before} measures")

                # Check if filtering removed everything
                if len(tables_raw) == 0 and tables_before > 0:
                    logger.warning(f"All {tables_before} tables were filtered out because they are hidden. Use include_hidden=True to see them.")
                if len(measures_raw) == 0 and measures_before > 0:
                    logger.warning(f"All {measures_before} measures were filtered out because they are hidden. Use include_hidden=True to see them.")

            # Build processed data structures
            logger.debug("Building table view data...")
            tables_data = self.build_table_view_data(
                tables_raw, columns_raw, measures_raw, relationships_raw, dependency_depth, row_counts
            )
            logger.debug(f"Built table view data: {len(tables_data)} tables")

            logger.debug("Building measure view data...")
            measures_data = self.build_measure_view_data(
                measures_raw, columns_raw, dependency_depth
            )
            logger.debug(f"Built measure view data: {len(measures_data)} measures")

            logger.debug("Building relationship view data...")
            relationships_data = self.build_relationship_view_data(
                relationships_raw, tables_raw, row_counts
            )
            logger.debug(f"Built relationship view data: {len(relationships_data.get('nodes', []))} nodes, {len(relationships_data.get('edges', []))} edges")

            # Build dependency graph
            logger.debug("Building dependency graph...")
            dependency_graph = self.build_dependency_graph(
                tables_raw, columns_raw, measures_raw, include_hidden, dependency_depth
            )
            logger.debug(f"Built dependency graph: {len(dependency_graph.get('nodes', []))} nodes, {len(dependency_graph.get('edges', []))} edges")

            # Calculate statistics
            statistics = self._calculate_statistics(
                tables_data, measures_data, relationships_data
            )

            # Collect table preview data (sample rows)
            logger.debug("Collecting table preview data...")
            table_previews = self._collect_table_previews(tables_raw, columns_raw, limit=10)
            logger.debug(f"Collected previews for {len(table_previews)} tables")

            return {
                "success": True,
                "tables": tables_data,
                "measures": measures_data,
                "relationships": relationships_data,
                "dependency_graph": dependency_graph,
                "statistics": statistics,
                "table_previews": table_previews,
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "include_hidden": include_hidden,
                    "dependency_depth": dependency_depth,
                },
            }

        except Exception as e:
            logger.error(f"Error collecting model data: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Failed to collect model data: {str(e)}",
            }

    def build_table_view_data(
        self,
        tables_raw: List[Dict],
        columns_raw: List[Dict],
        measures_raw: List[Dict],
        relationships_raw: List[Dict],
        dependency_depth: int,
        row_counts: Dict[str, int] = None,
    ) -> List[Dict[str, Any]]:
        """Build comprehensive table view data.

        Args:
            tables_raw: Raw table data from INFO.TABLES
            columns_raw: Raw column data from INFO.COLUMNS
            measures_raw: Raw measure data from INFO.MEASURES
            relationships_raw: Raw relationship data from INFO.RELATIONSHIPS
            dependency_depth: Maximum depth for dependency analysis
            row_counts: Optional dictionary mapping table name to row count

        Returns:
            List of table dictionaries with all dependency information
        """
        tables_data = []

        # First, build a set of key columns from relationships
        # Format: (table_name, column_name)
        key_columns = set()
        for rel in relationships_raw:
            from_table = self._get_field(rel, "FromTable")
            to_table = self._get_field(rel, "ToTable")
            from_column = self._get_field(rel, "FromColumn")
            to_column = self._get_field(rel, "ToColumn")

            if from_table and from_column:
                key_columns.add((from_table, from_column))
            if to_table and to_column:
                key_columns.add((to_table, to_column))

        for table in tables_raw:
            table_name = self._get_field(table, "Name")
            if not table_name:
                continue

            # Get columns for this table
            table_columns = []
            for col in columns_raw:
                if self._get_field(col, "Table") != table_name:
                    continue

                col_name = self._get_column_name(col)
                is_key = (table_name, col_name) in key_columns

                # Get data type with fallback - try ExplicitDataType first, then InferredDataType, then Type
                data_type_raw = (
                    self._get_field(col, "ExplicitDataType") or
                    self._get_field(col, "InferredDataType") or
                    self._get_field(col, "Type")
                )

                # Map numeric data type codes to readable names
                data_type = self._map_data_type_to_name(data_type_raw)

                # Also map the Type field for compatibility
                type_raw = self._get_field(col, "Type")
                type_mapped = self._map_data_type_to_name(type_raw)

                table_columns.append({
                    "name": col_name,
                    "data_type": data_type,
                    "type": type_mapped,
                    "hidden": self._get_bool_field(col, "IsHidden", False),
                    "key": is_key,
                })

            # Debug: Log if no columns found for this table
            if len(table_columns) == 0 and len(columns_raw) > 0:
                logger.debug(f"No columns found for table '{table_name}'. Sample column tables: {[self._get_field(c, 'Table') for c in columns_raw[:3]]}")

            # Get measures for this table
            table_measures = [
                {
                    "name": self._get_field(m, "Name"),
                    "expression": self._get_field(m, "Expression"),
                    "format": self._get_field(m, "FormatString"),
                    "folder": self._get_field(m, "DisplayFolder"),
                    "hidden": self._get_bool_field(m, "IsHidden", False),
                }
                for m in measures_raw
                if self._get_field(m, "Table") == table_name
            ]

            # Get relationships involving this table
            relationships_in = []
            relationships_out = []
            for rel in relationships_raw:
                from_table = self._get_field(rel, "FromTable")
                to_table = self._get_field(rel, "ToTable")

                if to_table == table_name:
                    relationships_in.append(
                        {
                            "from_table": from_table,
                            "from_column": self._get_field(rel, "FromColumn"),
                            "to_column": self._get_field(rel, "ToColumn"),
                            "active": bool(self._get_field(rel, "IsActive")),
                            "cardinality": self._get_field(rel, "Cardinality"),
                            "direction": self._get_field(rel, "CrossFilterDirection"),
                        }
                    )

                if from_table == table_name:
                    relationships_out.append(
                        {
                            "to_table": to_table,
                            "from_column": self._get_field(rel, "FromColumn"),
                            "to_column": self._get_field(rel, "ToColumn"),
                            "active": bool(self._get_field(rel, "IsActive")),
                            "cardinality": self._get_field(rel, "Cardinality"),
                            "direction": self._get_field(rel, "CrossFilterDirection"),
                        }
                    )

            # Analyze column usage in measures (from other tables)
            used_in_measures = []
            for measure in measures_raw:
                measure_table = self._get_field(measure, "Table")
                measure_name = self._get_field(measure, "Name")
                measure_expr = self._get_field(measure, "Expression", "")

                if not measure_expr:
                    continue

                # Simple pattern matching for table references
                # More sophisticated parsing would use dax_parser
                if f"'{table_name}'" in measure_expr or f"[{table_name}]" in measure_expr:
                    used_in_measures.append(
                        {
                            "measure_table": measure_table,
                            "measure_name": measure_name,
                        }
                    )

            # Get row count from TOM if available
            table_row_count = 0
            if row_counts:
                table_row_count = row_counts.get(table_name, 0)

            # Determine table type (fact vs dimension)
            # Simple heuristic: tables with mostly outgoing relationships are likely facts
            table_type = self._determine_table_type(
                len(relationships_in), len(relationships_out), table_name
            )

            # Calculate complexity
            complexity = self._calculate_table_complexity(
                len(table_columns), len(table_measures),
                len(relationships_in) + len(relationships_out)
            )

            tables_data.append(
                {
                    "name": table_name,
                    "hidden": self._get_bool_field(table, "IsHidden", False),
                    "row_count": table_row_count,
                    "description": self._get_field(table, "Description", ""),
                    "table_type": table_type,
                    "complexity": complexity,
                    "columns": table_columns,
                    "measures": table_measures,
                    "relationships_in": relationships_in,
                    "relationships_out": relationships_out,
                    "used_in_measures": used_in_measures,
                    "statistics": {
                        "column_count": len(table_columns),
                        "measure_count": len(table_measures),
                        "relationship_count": len(relationships_in)
                        + len(relationships_out),
                        "usage_count": len(used_in_measures),
                    },
                }
            )

        return tables_data

    def build_measure_view_data(
        self, measures_raw: List[Dict], columns_raw: List[Dict], dependency_depth: int
    ) -> List[Dict[str, Any]]:
        """Build comprehensive measure view data with dependencies.

        Args:
            measures_raw: Raw measure data from INFO.MEASURES
            columns_raw: Raw column data from INFO.COLUMNS
            dependency_depth: Maximum depth for dependency analysis

        Returns:
            List of measure dictionaries with dependency information
        """
        measures_data = []

        # Create measure lookup for dependency analysis
        measure_lookup = {
            (self._get_field(m, "Table"), self._get_field(m, "Name")): m
            for m in measures_raw
        }

        for measure in measures_raw:
            table_name = self._get_field(measure, "Table")
            measure_name = self._get_field(measure, "Name")
            expression = self._get_field(measure, "Expression", "")

            if not table_name or not measure_name:
                continue

            # Parse dependencies from expression
            depends_on = self._parse_measure_dependencies(
                expression, measure_lookup, columns_raw
            )

            # Find measures that use this measure
            used_by_measures = []
            for other_measure in measures_raw:
                other_table = self._get_field(other_measure, "Table")
                other_name = self._get_field(other_measure, "Name")
                other_expr = self._get_field(other_measure, "Expression", "")

                # Skip self
                if other_table == table_name and other_name == measure_name:
                    continue

                # Simple pattern matching for measure references
                if (
                    f"[{measure_name}]" in other_expr
                    or f"'{table_name}'[{measure_name}]" in other_expr
                ):
                    used_by_measures.append(
                        {"table": other_table, "measure": other_name}
                    )

            # Calculate measure complexity based on DAX expression
            complexity = self._calculate_measure_complexity(
                expression,
                len(depends_on.get("measures", [])) + len(depends_on.get("columns", []))
            )

            measures_data.append(
                {
                    "table": table_name,
                    "name": measure_name,
                    "expression": expression,
                    "format": self._get_field(measure, "FormatString", ""),
                    "folder": self._get_field(measure, "DisplayFolder", ""),
                    "description": self._get_field(measure, "Description", ""),
                    "hidden": self._get_bool_field(measure, "IsHidden", False),
                    "complexity": complexity,
                    "depends_on": depends_on,
                    "used_by_measures": used_by_measures,
                    "statistics": {
                        "dependency_count": len(depends_on.get("measures", []))
                        + len(depends_on.get("columns", [])),
                        "usage_count": len(used_by_measures),
                    },
                }
            )

        return measures_data

    def build_relationship_view_data(
        self, relationships_raw: List[Dict], tables_raw: List[Dict], row_counts: Dict[str, int] = None
    ) -> Dict[str, Any]:
        """Build relationship graph data for visualization.

        Args:
            relationships_raw: Raw relationship data from INFO.RELATIONSHIPS
            tables_raw: Raw table data from INFO.TABLES
            row_counts: Optional dictionary mapping table name to row count

        Returns:
            Dictionary with nodes and edges for graph visualization
        """
        # Build nodes (tables)
        nodes = []
        table_lookup = {self._get_field(t, "Name"): t for t in tables_raw}

        for table in tables_raw:
            table_name = self._get_field(table, "Name")
            if not table_name:
                continue

            # Get row count from TOM if available
            table_row_count = 0
            if row_counts:
                table_row_count = row_counts.get(table_name, 0)

            nodes.append(
                {
                    "id": table_name,
                    "label": table_name,
                    "hidden": self._get_bool_field(table, "IsHidden", False),
                    "row_count": table_row_count,
                }
            )

        # Build edges (relationships)
        edges = []
        for idx, rel in enumerate(relationships_raw):
            from_table = self._get_field(rel, "FromTable")
            to_table = self._get_field(rel, "ToTable")
            from_column = self._get_field(rel, "FromColumn")
            to_column = self._get_field(rel, "ToColumn")

            if not all([from_table, to_table, from_column, to_column]):
                continue

            edges.append(
                {
                    "id": f"rel_{idx}",
                    "from": from_table,
                    "to": to_table,
                    "from_column": from_column,
                    "to_column": to_column,
                    "active": bool(self._get_field(rel, "IsActive")),
                    "cardinality": self._get_field(rel, "Cardinality", ""),
                    "direction": self._get_field(rel, "CrossFilterDirection", ""),
                }
            )

        return {"nodes": nodes, "edges": edges}

    def _parse_measure_dependencies(
        self,
        expression: str,
        measure_lookup: Dict[Tuple[str, str], Dict],
        columns_raw: List[Dict],
    ) -> Dict[str, List[Dict]]:
        """Parse measure dependencies from DAX expression.

        Args:
            expression: DAX expression string
            measure_lookup: Dictionary mapping (table, measure) to measure data
            columns_raw: Raw column data for validation

        Returns:
            Dictionary with 'measures' and 'columns' lists
        """
        depends_on = {"measures": [], "columns": [], "tables": []}

        if not expression:
            return depends_on

        # Simple pattern matching (production would use dax_parser)
        # Match patterns like 'Table'[Measure] or [Measure]
        import re

        # Match qualified references: 'Table'[Object]
        qualified_pattern = r"'([^']+)'\s*\[([^\]]+)\]"
        for match in re.finditer(qualified_pattern, expression):
            table = match.group(1)
            obj = match.group(2)

            # Check if it's a measure
            if (table, obj) in measure_lookup:
                depends_on["measures"].append({"table": table, "measure": obj})
            else:
                # Assume it's a column
                depends_on["columns"].append({"table": table, "column": obj})

            if table not in [t["name"] for t in depends_on.get("tables", [])]:
                depends_on.setdefault("tables", []).append({"name": table})

        # Match unqualified references: [Object]
        unqualified_pattern = r"(?<!')\[([^\]]+)\]"
        for match in re.finditer(unqualified_pattern, expression):
            obj = match.group(1)

            # Try to find in measures (any table)
            found = False
            for (table, measure_name), _ in measure_lookup.items():
                if measure_name == obj:
                    depends_on["measures"].append({"table": table, "measure": obj})
                    found = True
                    break

            if not found:
                # Assume it's a column (table unknown)
                depends_on["columns"].append({"table": "", "column": obj})

        # Deduplicate
        depends_on["measures"] = list(
            {(m["table"], m["measure"]): m for m in depends_on["measures"]}.values()
        )
        depends_on["columns"] = list(
            {(c["table"], c["column"]): c for c in depends_on["columns"]}.values()
        )

        return depends_on

    def _calculate_statistics(
        self,
        tables_data: List[Dict],
        measures_data: List[Dict],
        relationships_data: Dict,
    ) -> Dict[str, Any]:
        """Calculate summary statistics for the model.

        Args:
            tables_data: Processed table data
            measures_data: Processed measure data
            relationships_data: Processed relationship data

        Returns:
            Dictionary with summary statistics
        """
        return {
            "total_tables": len(tables_data),
            "total_columns": sum(len(t["columns"]) for t in tables_data),
            "total_measures": len(measures_data),
            "total_relationships": len(relationships_data.get("edges", [])),
            "active_relationships": sum(
                1 for e in relationships_data.get("edges", []) if e.get("active")
            ),
            "inactive_relationships": sum(
                1 for e in relationships_data.get("edges", []) if not e.get("active")
            ),
            "measures_with_dependencies": sum(
                1 for m in measures_data if m["statistics"]["dependency_count"] > 0
            ),
            "unused_measures": sum(
                1 for m in measures_data if m["statistics"]["usage_count"] == 0
            ),
            "tables_with_no_relationships": sum(
                1 for t in tables_data if t["statistics"]["relationship_count"] == 0
            ),
        }

    def _collect_table_previews(self, tables_raw: List[Dict], columns_raw: List[Dict], limit: int = 10) -> Dict[str, Dict]:
        """Collect sample data from tables for preview.

        Args:
            tables_raw: Raw table data from INFO.TABLES
            columns_raw: Raw column data from INFO.COLUMNS
            limit: Maximum number of rows to collect per table

        Returns:
            Dictionary mapping table names to preview data with columns and rows
        """
        previews = {}
        success_count = 0
        fail_count = 0

        # Cap table previews to avoid excessive DAX queries and memory usage
        MAX_PREVIEW_TABLES = 25
        for table in tables_raw[:MAX_PREVIEW_TABLES]:
            table_name = self._get_field(table, "Name")
            if not table_name:
                continue

            try:
                logger.info(f"Collecting preview for table: {table_name}")

                # Use the execute_with_table_reference_fallback method which tries multiple formats
                result = self.query_executor.execute_with_table_reference_fallback(
                    table_name=table_name,
                    max_rows=limit
                )

                # Check if query succeeded
                if not result.get("success"):
                    error_msg = result.get('error', 'Unknown error')
                    logger.warning(f"Skipping '{table_name}' - {error_msg}")
                    fail_count += 1
                    continue

                # Check if we got rows back
                rows = result.get("rows", [])
                if not rows or len(rows) == 0:
                    logger.warning(f"Table '{table_name}' query succeeded but returned 0 rows (empty table)")
                    fail_count += 1
                    continue

                # We have data - process it
                try:
                    columns = list(rows[0].keys())

                    # Sanitize rows to ensure JSON serialization works
                    sanitized_rows = []
                    for row_idx, row in enumerate(rows[:limit]):
                        sanitized_row = {}
                        for key, value in row.items():
                            try:
                                # Convert problematic types to strings
                                if value is None:
                                    sanitized_row[key] = None
                                elif isinstance(value, (str, int, float, bool)):
                                    sanitized_row[key] = value
                                elif hasattr(value, 'isoformat'):  # DateTime objects
                                    sanitized_row[key] = value.isoformat()
                                else:
                                    # Convert other types to string
                                    sanitized_row[key] = str(value)
                            except Exception as col_error:
                                logger.warning(f"Error converting column '{key}' in row {row_idx} of '{table_name}': {col_error}")
                                sanitized_row[key] = f"<conversion error: {type(value).__name__}>"
                        sanitized_rows.append(sanitized_row)

                    previews[table_name] = {
                        "columns": columns,
                        "rows": sanitized_rows
                    }

                    logger.info(f"✓ Collected {len(sanitized_rows)} rows for table '{table_name}'")
                    success_count += 1
                except Exception as sanitize_error:
                    logger.error(f"Error sanitizing data for '{table_name}': {sanitize_error}", exc_info=True)
                    fail_count += 1

            except Exception as e:
                logger.error(f"Error collecting preview for table '{table_name}': {e}", exc_info=True)
                fail_count += 1
                continue

        logger.info(f"Table preview collection complete: {success_count} succeeded, {fail_count} failed out of {len(tables_raw)} tables")
        return previews

    def _map_data_type_to_name(self, data_type_value) -> str:
        """Map Power BI data type code/value to readable name.

        Args:
            data_type_value: Data type value from Power BI (can be int, string, or None)

        Returns:
            Readable data type name
        """
        # If it's already a string and looks like a type name, return it
        if isinstance(data_type_value, str) and data_type_value:
            # If it's already a readable name (contains letters), return as-is
            if any(c.isalpha() for c in data_type_value):
                return data_type_value

        # Power BI Data Type codes (from ADOMD.NET)
        # https://docs.microsoft.com/en-us/dotnet/api/microsoft.analysisservices.datatype
        type_mapping = {
            # Common numeric codes
            1: "String",
            2: "Int64",
            3: "Double",
            4: "Decimal",
            5: "DateTime",
            6: "Currency",
            7: "Boolean",
            8: "Binary",
            9: "Unknown",
            10: "Variant",
            11: "Date",
            # Alternative mappings
            "1": "String",
            "2": "Int64",
            "3": "Double",
            "4": "Decimal",
            "5": "DateTime",
            "6": "Currency",
            "7": "Boolean",
            "8": "Binary",
            "9": "Unknown",
            "10": "Variant",
            "11": "Date",
        }

        # Try to map the value
        if data_type_value in type_mapping:
            return type_mapping[data_type_value]

        # Try converting to int if it's a string number
        if isinstance(data_type_value, str):
            try:
                int_value = int(data_type_value)
                if int_value in type_mapping:
                    return type_mapping[int_value]
            except (ValueError, TypeError):
                pass

        # Default fallback
        return "String"

    def _get_column_name(self, col: Dict) -> Optional[str]:
        """Get column name from ExplicitName or InferredName.

        Args:
            col: Column dictionary from INFO.COLUMNS()

        Returns:
            Column name or None
        """
        # Try bracketed keys first, then unbracketed
        return (self._get_field(col, "ExplicitName") or
                self._get_field(col, "InferredName") or
                self._get_field(col, "Name"))

    def _get_field(
        self, obj: Dict, field: str, default: Any = None
    ) -> Any:
        """Get field value handling both bracketed and unbracketed keys.

        Args:
            obj: Dictionary to extract from
            field: Field name
            default: Default value if not found

        Returns:
            Field value or default
        """
        if not isinstance(obj, dict):
            return default

        # Try bracketed key first (DMV queries typically return bracketed keys)
        bracketed = f"[{field}]"
        if bracketed in obj:
            value = obj[bracketed]
            # Treat None and empty string as missing, but allow False/0
            if value is not None and value != "":
                return value

        # Try direct key
        if field in obj:
            value = obj[field]
            # Treat None and empty string as missing, but allow False/0
            if value is not None and value != "":
                return value

        return default

    def _get_bool_field(self, obj: Dict, field: str, default: bool = False) -> bool:
        """Get boolean field value, properly handling string representations.

        Args:
            obj: Dictionary to extract from
            field: Field name
            default: Default value if not found

        Returns:
            Boolean value
        """
        value = self._get_field(obj, field, default)

        # Handle None
        if value is None:
            return default

        # Handle boolean
        if isinstance(value, bool):
            return value

        # Handle numeric (0 = False, non-zero = True)
        if isinstance(value, (int, float)):
            return bool(value)

        # Handle string representations
        if isinstance(value, str):
            value_lower = value.lower().strip()
            if value_lower in ('true', '1', 'yes', 'y'):
                return True
            if value_lower in ('false', '0', 'no', 'n', ''):
                return False
            # Non-empty string that's not a boolean representation
            # This is likely data, return default to be safe
            return default

        return default

    def _determine_table_type(self, relationships_in: int, relationships_out: int, table_name: str) -> str:
        """Determine if table is a fact or dimension table.

        Args:
            relationships_in: Number of incoming relationships
            relationships_out: Number of outgoing relationships
            table_name: Name of the table

        Returns:
            'fact' or 'dimension'
        """
        # Check naming patterns - only f_ prefix indicates fact table
        # All other tables are dimensions by default
        table_lower = table_name.lower()

        # Only tables starting with 'f_' or 'f ' are facts
        if table_lower.startswith('f_') or table_lower.startswith('f '):
            return 'fact'

        # Everything else is a dimension
        return 'dimension'

    def _calculate_table_complexity(self, column_count: int, measure_count: int, relationship_count: int) -> str:
        """Calculate table complexity based on its characteristics.

        Args:
            column_count: Number of columns
            measure_count: Number of measures
            relationship_count: Number of relationships

        Returns:
            'low', 'medium', or 'high'
        """
        # Calculate a complexity score
        score = 0

        # Weight different factors
        score += column_count * 0.5  # Columns contribute less to complexity
        score += measure_count * 2   # Measures are more complex
        score += relationship_count * 1.5  # Relationships add complexity

        # Classify based on score
        if score < 10:
            return 'low'
        elif score < 30:
            return 'medium'
        else:
            return 'high'

    def _calculate_measure_complexity(self, expression: str, dependency_count: int) -> str:
        """Calculate measure complexity based on DAX expression and dependencies.

        Args:
            expression: DAX expression
            dependency_count: Number of dependencies (measures + columns)

        Returns:
            'low', 'medium', or 'high'
        """
        if not expression:
            return 'low'

        # Calculate complexity score
        score = 0

        # Factor 1: Expression length
        expr_length = len(expression)
        if expr_length < 100:
            score += 1
        elif expr_length < 300:
            score += 2
        else:
            score += 3

        # Factor 2: Number of dependencies
        score += min(dependency_count, 5)  # Cap at 5

        # Factor 3: Check for complex DAX functions
        complex_functions = [
            'CALCULATE', 'FILTER', 'ALL', 'ALLEXCEPT', 'RELATED', 'RELATEDTABLE',
            'SUMX', 'AVERAGEX', 'COUNTX', 'MINX', 'MAXX',
            'VAR', 'RETURN', 'SWITCH', 'IF',
            'DATEADD', 'DATESYTD', 'DATESBETWEEN',
            'EARLIER', 'EARLIEST', 'RANKX', 'TOPN'
        ]

        function_count = sum(1 for func in complex_functions if func in expression.upper())
        score += min(function_count, 5)  # Cap at 5

        # Factor 4: Nesting level (count parentheses)
        nesting_level = expression.count('(')
        if nesting_level > 10:
            score += 3
        elif nesting_level > 5:
            score += 2
        elif nesting_level > 2:
            score += 1

        # Classify
        if score < 5:
            return 'low'
        elif score < 10:
            return 'medium'
        else:
            return 'high'

    def build_dependency_graph(
        self,
        tables_raw: List[Dict],
        columns_raw: List[Dict],
        measures_raw: List[Dict],
        include_hidden: bool = False,
        max_depth: int = 5,
        focus_node: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build comprehensive dependency graph for measures, columns, and tables.

        Args:
            tables_raw: Raw table data from INFO.TABLES
            columns_raw: Raw column data from INFO.COLUMNS
            measures_raw: Raw measure data from INFO.MEASURES
            include_hidden: Include hidden objects in the graph
            max_depth: Maximum dependency traversal depth
            focus_node: Optional node ID to center the graph around (format: "table|object")

        Returns:
            Dictionary with nodes, edges, and statistics
        """
        try:
            logger.info(f"Building dependency graph (max_depth={max_depth}, focus_node={focus_node})")

            nodes = []
            edges = []
            node_ids = set()

            # 1. Add table nodes
            for table in tables_raw:
                table_name = self._get_field(table, "Name")
                if not table_name:
                    continue

                is_hidden = self._get_bool_field(table, "IsHidden", False)
                if not include_hidden and is_hidden:
                    continue

                node_id = table_name
                node_ids.add(node_id)

                # Count related objects
                table_columns = [c for c in columns_raw if self._get_field(c, "Table") == table_name]
                table_measures = [m for m in measures_raw if self._get_field(m, "Table") == table_name]

                nodes.append({
                    "id": node_id,
                    "label": table_name,
                    "type": "table",
                    "table": table_name,
                    "hidden": is_hidden,
                    "row_count": 0,  # Will be filled later if available
                    "column_count": len(table_columns),
                    "measure_count": len(table_measures),
                })

            # 2. Add column nodes and create edges to parent tables
            for col in columns_raw:
                table_name = self._get_field(col, "Table")
                col_name = self._get_column_name(col)

                if not table_name or not col_name:
                    continue

                is_hidden = self._get_bool_field(col, "IsHidden", False)
                if not include_hidden and is_hidden:
                    continue

                node_id = f"{table_name}|{col_name}"
                node_ids.add(node_id)

                # Get data type
                data_type_raw = (
                    self._get_field(col, "ExplicitDataType") or
                    self._get_field(col, "InferredDataType") or
                    self._get_field(col, "Type")
                )
                data_type = self._map_data_type_to_name(data_type_raw)

                nodes.append({
                    "id": node_id,
                    "label": col_name,
                    "type": "column",
                    "table": table_name,
                    "hidden": is_hidden,
                    "data_type": data_type,
                    "used_in_count": 0,  # Will be calculated when parsing measures
                })

                # Add edge from column to its parent table
                if table_name in node_ids:
                    edges.append({
                        "from": node_id,
                        "to": table_name,
                        "type": "column_to_table",
                        "strength": 1,
                    })

            # 3. Add measure nodes and build edges from DAX parsing
            for measure in measures_raw:
                table_name = self._get_field(measure, "Table")
                measure_name = self._get_field(measure, "Name")
                expression = self._get_field(measure, "Expression", "")

                if not table_name or not measure_name:
                    continue

                is_hidden = self._get_bool_field(measure, "IsHidden", False)
                if not include_hidden and is_hidden:
                    continue

                measure_id = f"{table_name}|{measure_name}"
                node_ids.add(measure_id)

                # Calculate complexity
                complexity = self._calculate_measure_complexity(expression, 0)

                nodes.append({
                    "id": measure_id,
                    "label": measure_name,
                    "type": "measure",
                    "table": table_name,
                    "hidden": is_hidden,
                    "expression": expression,
                    "complexity": complexity,
                    "folder": self._get_field(measure, "DisplayFolder", ""),
                    "description": self._get_field(measure, "Description", ""),
                })

                # Parse dependencies from DAX expression
                if expression and self.dependency_analyzer:
                    try:
                        refs = self.dependency_analyzer._parse_references(expression)

                        # Add edges for measure dependencies
                        for ref_table, ref_measure in refs.get("measures", []):
                            if not ref_table or not ref_measure:
                                continue

                            target_id = f"{ref_table}|{ref_measure}"

                            # Only add edge if target node exists or will exist
                            edges.append({
                                "from": measure_id,
                                "to": target_id,
                                "type": "measure_to_measure",
                                "strength": 1,
                            })

                        # Add edges for column dependencies
                        for ref_table, ref_col in refs.get("columns", []):
                            if not ref_table or not ref_col:
                                continue

                            target_id = f"{ref_table}|{ref_col}"

                            # Only add edge if target node exists
                            if target_id in node_ids:
                                edges.append({
                                    "from": measure_id,
                                    "to": target_id,
                                    "type": "measure_to_column",
                                    "strength": 1,
                                })

                                # Increment used_in_count for the column
                                for node in nodes:
                                    if node["id"] == target_id and node["type"] == "column":
                                        node["used_in_count"] = node.get("used_in_count", 0) + 1

                        # Add edges for table dependencies (implicit)
                        for ref_table in refs.get("tables", []):
                            if not ref_table or ref_table == table_name:
                                continue

                            # Only add edge if target table node exists
                            if ref_table in node_ids:
                                edges.append({
                                    "from": measure_id,
                                    "to": ref_table,
                                    "type": "measure_to_table",
                                    "strength": 1,
                                })

                    except Exception as e:
                        logger.warning(f"Failed to parse dependencies for measure {measure_id}: {e}")

            # 4. Filter by focus node if specified
            if focus_node:
                logger.info(f"Filtering graph by focus node: {focus_node}")
                nodes, edges = self._filter_graph_by_focus(nodes, edges, focus_node, max_depth)

            # 5. Calculate statistics
            measure_nodes = [n for n in nodes if n["type"] == "measure"]
            column_nodes = [n for n in nodes if n["type"] == "column"]
            table_nodes = [n for n in nodes if n["type"] == "table"]

            # Detect circular dependencies
            circular_refs = self._detect_circular_dependencies(edges)

            statistics = {
                "total_nodes": len(nodes),
                "measure_count": len(measure_nodes),
                "column_count": len(column_nodes),
                "table_count": len(table_nodes),
                "total_edges": len(edges),
                "max_depth": max_depth,
                "circular_references": circular_refs,
                "edge_types": {
                    "measure_to_measure": sum(1 for e in edges if e["type"] == "measure_to_measure"),
                    "measure_to_column": sum(1 for e in edges if e["type"] == "measure_to_column"),
                    "measure_to_table": sum(1 for e in edges if e["type"] == "measure_to_table"),
                    "column_to_table": sum(1 for e in edges if e["type"] == "column_to_table"),
                }
            }

            logger.info(f"Built dependency graph: {len(nodes)} nodes, {len(edges)} edges")

            return {
                "nodes": nodes,
                "edges": edges,
                "statistics": statistics,
            }

        except Exception as e:
            logger.error(f"Error building dependency graph: {e}", exc_info=True)
            return {
                "nodes": [],
                "edges": [],
                "statistics": {
                    "total_nodes": 0,
                    "measure_count": 0,
                    "column_count": 0,
                    "table_count": 0,
                    "total_edges": 0,
                    "max_depth": max_depth,
                    "circular_references": [],
                    "edge_types": {},
                },
                "error": str(e)
            }

    def _filter_graph_by_focus(
        self,
        nodes: List[Dict],
        edges: List[Dict],
        focus_node: str,
        max_depth: int
    ) -> Tuple[List[Dict], List[Dict]]:
        """Filter graph to show only nodes within max_depth of focus_node.

        Args:
            nodes: All graph nodes
            edges: All graph edges
            focus_node: Node ID to focus on
            max_depth: Maximum depth to traverse

        Returns:
            Tuple of (filtered_nodes, filtered_edges)
        """
        # Build adjacency list (bidirectional)
        adjacency = {}
        for edge in edges:
            from_id = edge["from"]
            to_id = edge["to"]

            if from_id not in adjacency:
                adjacency[from_id] = []
            if to_id not in adjacency:
                adjacency[to_id] = []

            adjacency[from_id].append(to_id)
            adjacency[to_id].append(from_id)  # Bidirectional

        # BFS to find all nodes within max_depth
        visited = {focus_node: 0}  # node_id -> depth
        queue = [(focus_node, 0)]

        while queue:
            current_id, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            for neighbor_id in adjacency.get(current_id, []):
                if neighbor_id not in visited:
                    visited[neighbor_id] = depth + 1
                    queue.append((neighbor_id, depth + 1))

        # Filter nodes and edges
        filtered_node_ids = set(visited.keys())
        filtered_nodes = [n for n in nodes if n["id"] in filtered_node_ids]
        filtered_edges = [
            e for e in edges
            if e["from"] in filtered_node_ids and e["to"] in filtered_node_ids
        ]

        logger.info(f"Filtered graph: {len(filtered_nodes)}/{len(nodes)} nodes, {len(filtered_edges)}/{len(edges)} edges")

        return filtered_nodes, filtered_edges

    def _detect_circular_dependencies(self, edges: List[Dict]) -> List[Dict]:
        """Detect circular dependencies in the dependency graph.

        Args:
            edges: List of edges in the graph

        Returns:
            List of circular dependency paths
        """
        # Build adjacency list
        adjacency = {}
        for edge in edges:
            from_id = edge["from"]
            to_id = edge["to"]

            if from_id not in adjacency:
                adjacency[from_id] = []
            adjacency[from_id].append(to_id)

        # DFS to detect cycles
        circular_paths = []
        visited = set()
        rec_stack = set()

        def dfs(node_id, path):
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)

            for neighbor in adjacency.get(node_id, []):
                if neighbor not in visited:
                    if dfs(neighbor, path):
                        return True
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle_path = path[cycle_start:] + [neighbor]
                    circular_paths.append({
                        "path": cycle_path,
                        "length": len(cycle_path) - 1
                    })
                    return True

            path.pop()
            rec_stack.remove(node_id)
            return False

        # Check all nodes
        for node_id in adjacency.keys():
            if node_id not in visited:
                dfs(node_id, [])

        return circular_paths[:10]  # Limit to first 10 circular paths

    def generate_html(
        self, model_data: Dict[str, Any], output_dir: Optional[str] = None
    ) -> Tuple[Optional[str], List[str]]:
        """Generate interactive HTML file with embedded data.

        Args:
            model_data: Complete model data from collect_all_model_data()
            output_dir: Output directory for HTML file

        Returns:
            Tuple of (html_path, error_notes)
        """
        if not model_data.get("success"):
            return None, [model_data.get("error", "Unknown error")]

        try:
            # Prepare output directory
            html_dir = ensure_dir(output_dir)
            html_path = os.path.join(
                html_dir,
                safe_filename("dependency_explorer", f"explorer_{now_iso()}") + ".html",
            )

            # Generate HTML content
            html_content = self._render_html_template(model_data)

            # Write to file
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            logger.info(f"Generated interactive explorer: {html_path}")
            return html_path, []

        except Exception as e:
            logger.error(f"Error generating HTML: {e}", exc_info=True)
            return None, [f"Failed to generate HTML: {str(e)}"]

    def _render_html_template(self, model_data: Dict[str, Any]) -> str:
        """Render complete HTML template with embedded data and JavaScript.

        Args:
            model_data: Complete model data

        Returns:
            HTML string
        """
        # Embed data as JSON with proper escaping for JavaScript context
        # Use separators without spaces to minimize size
        # ensure_ascii=True to avoid Unicode issues in some browsers
        try:
            model_json = json.dumps(model_data, separators=(',', ':'), ensure_ascii=True)
        except (TypeError, ValueError) as json_error:
            logger.error(f"JSON serialization error: {json_error}")
            # Try to identify which part is failing
            if 'table_previews' in model_data:
                logger.error(f"Table previews keys: {list(model_data['table_previews'].keys())}")
                # Remove table_previews and try again
                model_data_copy = model_data.copy()
                model_data_copy['table_previews'] = {}
                model_json = json.dumps(model_data_copy, separators=(',', ':'), ensure_ascii=True)
                logger.warning("Removed all table previews due to JSON serialization error")
            else:
                raise

        # Escape for safe embedding in HTML/JavaScript
        # Replace </script> tags that could break out of script context
        model_json = model_json.replace('</', '<\\/')

        # Load comprehensive HTML template
        return self._get_complete_html_template(model_json)

    def _get_complete_html_template(self, model_json: str) -> str:
        """Get the complete HTML template with all features.

        Args:
            model_json: JSON string of model data

        Returns:
            Complete HTML string
        """
        import re

        # CRITICAL: Do brace replacements on the template FIRST, before inserting JSON
        # Otherwise the JSON data gets corrupted by the brace replacements!

        # The template was designed for .format() which required {{ for literal {
        # Now with .replace(), we need to unescape: {{ -> { and }} -> }
        # But we must preserve:
        #   - Vue templates: {{{{ -> {{
        #   - JavaScript template literals: ${{...}} -> ${...}

        html = HTML_TEMPLATE

        # Step 1: Protect Vue interpolations (4 braces -> 2 braces)
        html = html.replace('{{{{', '___VUE_OPEN___')
        html = html.replace('}}}}', '___VUE_CLOSE___')

        # Step 2: Protect JavaScript template literals using regex
        # Match ${{...}} and replace with ${...}
        # Use [\s\S]+? to match any characters (including braces in square brackets)
        html = re.sub(r'\$\{\{([\s\S]+?)\}\}', r'___JS_TPL___\1___JS_END___', html)

        # Step 3: Replace remaining escaped braces
        html = html.replace('{{', '{')
        html = html.replace('}}', '}')

        # Step 4: Restore protected patterns
        html = html.replace('___VUE_OPEN___', '{{')
        html = html.replace('___VUE_CLOSE___', '}}')
        html = html.replace('___JS_TPL___', '${')
        html = html.replace('___JS_END___', '}')

        # Step 5: NOW insert the JSON data after template processing
        html = html.replace('{model_json}', model_json)

        return html


# Comprehensive HTML template with Vue.js, D3.js, and full interactivity
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Power BI Model Explorer</title>
    <script>
        // Early diagnostic check
        console.log('[DIAGNOSTIC] JavaScript is running');
        console.log('[DIAGNOSTIC] Current URL:', window.location.href);
    </script>
    <script src="https://cdn.jsdelivr.net/npm/vue@3.4.21/dist/vue.global.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        // Check if libraries loaded
        console.log('[DIAGNOSTIC] Vue loaded:', typeof Vue !== 'undefined');
        console.log('[DIAGNOSTIC] D3 loaded:', typeof d3 !== 'undefined');
        if (typeof Vue === 'undefined') {{
            alert('CRITICAL ERROR: Vue.js failed to load from CDN. Check your internet connection or open the browser console for details.');
        }}
    </script>
    <style>
        :root {{
            --primary: #5B7FFF;
            --primary-dark: #4A6BEE;
            --primary-light: #7D9AFF;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --bg-dark: #1e293b;
            --text-dark: #0f172a;
            --bg-light: #F5F7FF;
            --accent: #FF6B9D;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #F5F7FF 0%, #E8ECFF 100%);
        }}

        .dark-mode {{
            background: #0f172a;
            color: #e2e8f0;
        }}

        .dark-mode .bg-white {{
            background: #1e293b !important;
        }}

        .dark-mode .text-gray-900 {{
            color: #f1f5f9 !important;
        }}

        .dark-mode .text-gray-600, .dark-mode .text-gray-500 {{
            color: #cbd5e1 !important;
        }}

        .dark-mode .border-gray-200, .dark-mode .border-gray-300 {{
            border-color: #475569 !important;
        }}

        .dark-mode .bg-gray-50 {{
            background: #334155 !important;
        }}

        .dark-mode .bg-gray-100 {{
            background: #475569 !important;
        }}

        .dark-mode .list-item:hover {{
            background-color: #334155 !important;
        }}

        .dark-mode .list-item.selected {{
            background-color: #1e40af !important;
        }}

        .dark-mode .stat-card {{
            background: #1e293b !important;
            border: 1px solid #475569;
        }}

        .dark-mode .code-block {{
            background: #0f172a;
            border: 1px solid #475569;
        }}

        .list-item {{
            transition: all 0.15s ease;
        }}

        .list-item:hover {{
            background-color: #E8ECFF;
            transform: translateX(4px);
        }}

        .list-item.selected {{
            background: linear-gradient(90deg, #E8ECFF 0%, #D4DBFF 100%);
            border-left: 4px solid var(--primary);
            box-shadow: 0 2px 8px rgba(91, 127, 255, 0.15);
        }}

        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}

        .badge-primary {{ background: #E8ECFF; color: #4A6BEE; }}
        .badge-success {{ background: #d1fae5; color: #065f46; }}
        .badge-danger {{ background: #fee2e2; color: #991b1b; }}
        .badge-warning {{ background: #fef3c7; color: #92400e; }}
        .badge-gray {{ background: #f1f5f9; color: #475569; }}

        #graph-container {{
            border: 1px solid #e2e8f0;
            border-radius: 0.5rem;
            background: white;
            overflow: hidden;
        }}

        .dependency-tree {{
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 0.875rem;
        }}

        .tree-node {{
            padding: 0.5rem;
            margin: 0.25rem 0;
            border-left: 2px solid #cbd5e1;
            cursor: pointer;
            transition: all 0.15s;
        }}

        .tree-node:hover {{
            background: #f1f5f9;
            border-left-color: var(--primary);
        }}

        .scrollable {{
            max-height: calc(100vh - 250px);
            overflow-y: auto;
        }}

        .scrollable::-webkit-scrollbar {{
            width: 8px;
        }}

        .scrollable::-webkit-scrollbar-track {{
            background: #f1f5f9;
        }}

        .scrollable::-webkit-scrollbar-thumb {{
            background: #cbd5e1;
            border-radius: 4px;
        }}

        .scrollable::-webkit-scrollbar-thumb:hover {{
            background: #94a3b8;
        }}

        .graph-controls {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            padding: 0.5rem;
            border-radius: 0.5rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            z-index: 100;
        }}

        .code-block {{
            background: #1e293b;
            color: #e2e8f0;
            padding: 1rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 0.875rem;
            line-height: 1.5;
        }}

        .stat-card {{
            background: white;
            padding: 1.5rem;
            border-radius: 0.75rem;
            box-shadow: 0 2px 8px rgba(91, 127, 255, 0.08);
            border: 1px solid #E0E7FF;
            transition: all 0.2s;
        }}

        .stat-card:hover {{
            box-shadow: 0 8px 16px rgba(91, 127, 255, 0.15);
            transform: translateY(-2px);
            border-color: var(--primary-light);
        }}

        .graph-node {{
            cursor: pointer;
        }}

        .graph-node.highlighted {{
            stroke: var(--primary);
            stroke-width: 3px;
        }}

        .graph-link {{
            stroke: #CBD5E1;
            stroke-width: 2px;
            fill: none;
        }}

        .graph-link.active {{
            stroke: var(--primary);
            stroke-width: 3px;
        }}

        .graph-link.inactive {{
            stroke: #E2E8F0;
            stroke-dasharray: 5, 5;
            opacity: 0.5;
        }}

        .graph-link.highlighted {{
            stroke-width: 4px;
            opacity: 1 !important;
            stroke: var(--primary-dark);
        }}

        .fade-enter-active, .fade-leave-active {{
            transition: opacity 0.3s;
        }}

        .fade-enter-from, .fade-leave-to {{
            opacity: 0;
        }}

        /* Override Tailwind blue colors with Finvision brand colors */
        .border-blue-500 {{
            border-color: var(--primary) !important;
        }}

        .text-blue-600 {{
            color: var(--primary) !important;
        }}

        .bg-blue-500 {{
            background-color: var(--primary) !important;
        }}

        .hover\\:bg-blue-600:hover {{
            background-color: var(--primary-dark) !important;
        }}

        .focus\\:ring-blue-500:focus {{
            --tw-ring-color: var(--primary) !important;
        }}

        .bg-blue-50 {{
            background-color: var(--bg-light) !important;
        }}

        .border-blue-200 {{
            border-color: #C7D2FE !important;
        }}
    </style>
</head>
<body>
    <div id="app">
        <!-- Header -->
        <div class="bg-white shadow-sm border-b" style="background: linear-gradient(135deg, #5B7FFF 0%, #7D9AFF 100%); border: none;">
            <div class="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
                <div class="flex justify-between items-center">
                    <div>
                        <h1 class="text-3xl font-bold" style="color: white;">Power BI Model Explorer</h1>
                        <p class="text-sm mt-1" style="color: rgba(255,255,255,0.9);">
                            {{{{ modelData.statistics.total_tables }}}} tables ·
                            {{{{ modelData.statistics.total_measures }}}} measures ·
                            {{{{ modelData.statistics.total_relationships }}}} relationships
                        </p>
                    </div>
                    <div class="flex items-center space-x-2">
                        <input
                            v-model="searchQuery"
                            type="text"
                            placeholder="Search... (press / to focus)"
                            class="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent w-64"
                        />
                        <button
                            @click="exportToCSV"
                            class="px-3 py-2 text-white rounded-lg transition text-sm"
                            style="background: linear-gradient(135deg, #5B7FFF 0%, #7D9AFF 100%);"
                            onmouseover="this.style.background='linear-gradient(135deg, #4A6BEE 0%, #5B7FFF 100%)';"
                            onmouseout="this.style.background='linear-gradient(135deg, #5B7FFF 0%, #7D9AFF 100%)';"
                            title="Export to CSV"
                        >
                            📄 CSV
                        </button>
                        <button
                            @click="exportToJSON"
                            class="px-3 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg transition text-sm"
                            title="Export to JSON"
                        >
                            📦 JSON
                        </button>
                        <button
                            @click="showCommandPalette = true"
                            class="px-3 py-2 bg-purple-500 hover:bg-purple-600 text-white rounded-lg transition text-sm"
                            title="Command Palette (Ctrl/Cmd+K)"
                        >
                            ⌘
                        </button>
                        <button
                            @click="toggleDarkMode"
                            class="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg transition"
                            title="Toggle Dark Mode"
                        >
                            {{{{ darkMode ? '☀️' : '🌙' }}}}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Tabs -->
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6">
            <div class="border-b border-gray-200">
                <nav class="-mb-px flex space-x-8">
                    <button
                        @click="activeTab = 'overview'"
                        :class="{{
                            'border-blue-500 text-blue-600': activeTab === 'overview',
                            'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300': activeTab !== 'overview'
                       }}"
                        class="whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition"
                    >
                        🏠 Overview
                    </button>
                    <button
                        @click="activeTab = 'tables'"
                        :class="{{
                            'border-blue-500 text-blue-600': activeTab === 'tables',
                            'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300': activeTab !== 'tables'
                       }}"
                        class="whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition"
                    >
                        📊 Tables ({{{{ modelData.tables?.length || 0 }}}})
                    </button>
                    <button
                        @click="activeTab = 'measures'"
                        :class="{{
                            'border-blue-500 text-blue-600': activeTab === 'measures',
                            'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300': activeTab !== 'measures'
                       }}"
                        class="whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition"
                    >
                        📈 Measures ({{{{ modelData.measures?.length || 0 }}}})
                    </button>
                    <button
                        @click="activeTab = 'relationships'"
                        :class="{{
                            'border-blue-500 text-blue-600': activeTab === 'relationships',
                            'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300': activeTab !== 'relationships'
                       }}"
                        class="whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition"
                    >
                        🔗 Relationships ({{{{ modelData.relationships?.edges?.length || 0 }}}})
                    </button>
                    <button
                        @click="activeTab = 'statistics'"
                        :class="{{
                            'border-blue-500 text-blue-600': activeTab === 'statistics',
                            'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300': activeTab !== 'statistics'
                       }}"
                        class="whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition"
                    >
                        📊 Statistics
                    </button>
                </nav>
            </div>
        </div>

        <!-- Content -->
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6 pb-12">
            <!-- Overview Dashboard -->
            <div v-if="activeTab === 'overview'" class="grid grid-cols-12 gap-6">
                <!-- Left Panel: Scrollable List -->
                <div class="col-span-7">
                    <div class="bg-white rounded-lg shadow">
                        <div class="p-4 border-b">
                            <h2 class="text-xl font-bold text-gray-900 mb-2">Model Explorer</h2>
                            <p class="text-sm text-gray-600 mb-3">Browse all tables and measures in your Power BI model</p>

                            <!-- Filter Buttons -->
                            <div class="flex gap-2">
                                <button
                                    @click="overviewFilter = 'all'"
                                    :class="{{
                                        'bg-blue-500 text-white': overviewFilter === 'all',
                                        'bg-white text-gray-700 border': overviewFilter !== 'all'
                                   }}"
                                    class="px-3 py-1.5 rounded-lg font-medium transition text-sm"
                                >
                                    All
                                </button>
                                <button
                                    @click="overviewFilter = 'dimensions'"
                                    :class="{{
                                        'bg-blue-500 text-white': overviewFilter === 'dimensions',
                                        'bg-white text-gray-700 border': overviewFilter !== 'dimensions'
                                   }}"
                                    class="px-3 py-1.5 rounded-lg font-medium transition text-sm"
                                >
                                    Dimensions
                                </button>
                                <button
                                    @click="overviewFilter = 'facts'"
                                    :class="{{
                                        'bg-blue-500 text-white': overviewFilter === 'facts',
                                        'bg-white text-gray-700 border': overviewFilter !== 'facts'
                                   }}"
                                    class="px-3 py-1.5 rounded-lg font-medium transition text-sm"
                                >
                                    Facts
                                </button>
                                <button
                                    @click="overviewFilter = 'measures'"
                                    :class="{{
                                        'bg-blue-500 text-white': overviewFilter === 'measures',
                                        'bg-white text-gray-700 border': overviewFilter !== 'measures'
                                   }}"
                                    class="px-3 py-1.5 rounded-lg font-medium transition text-sm"
                                >
                                    Measures
                                </button>
                            </div>
                        </div>

                        <!-- Scrollable List -->
                        <div class="scrollable" style="max-height: calc(100vh - 300px);">
                            <!-- Table Items -->
                            <div
                                v-for="table in overviewFilteredTables"
                                :key="'table-' + table.name"
                                @click="selectTableFromOverview(table)"
                                class="list-item border-b p-3 cursor-pointer hover:bg-gray-50"
                            >
                                <div class="flex items-center justify-between">
                                    <div class="flex items-center gap-3 flex-1 min-w-0">
                                        <div :class="{{
                                            'bg-green-100': table.table_type === 'dimension',
                                            'bg-blue-100': table.table_type === 'fact'
                                       }}" class="w-10 h-10 rounded flex items-center justify-center text-lg flex-shrink-0">
                                            {{{{ table.table_type === 'fact' ? '📊' : '📁' }}}}
                                        </div>
                                        <div class="flex-1 min-w-0">
                                            <h3 class="font-semibold text-sm text-gray-900 truncate">
                                                {{{{ table.table_type === 'fact' ? 'f' : 'd' }}}} {{{{ table.name }}}}
                                            </h3>
                                            <div class="flex items-center gap-3 mt-1 text-xs text-gray-500">
                                                <span>{{{{ table.statistics.column_count }}}} cols</span>
                                                <span>{{{{ table.statistics.measure_count }}}} meas</span>
                                                <span>{{{{ table.statistics.relationship_count }}}} rels</span>
                                            </div>
                                        </div>
                                        <span :class="{{
                                            'bg-green-100 text-green-800': table.complexity === 'low',
                                            'bg-yellow-100 text-yellow-800': table.complexity === 'medium',
                                            'bg-red-100 text-red-800': table.complexity === 'high'
                                       }}" class="px-2 py-1 rounded text-xs font-semibold uppercase flex-shrink-0">
                                            {{{{ table.complexity }}}}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            <!-- Measure Items (when showing measures) - Grouped by folder -->
                            <template v-for="(measures, folder) in measuresByFolder" :key="'folder-' + folder">
                                <!-- Folder Header -->
                                <div class="bg-gray-100 px-3 py-2 border-b sticky top-0 z-10">
                                    <h3 class="text-sm font-semibold text-gray-700">
                                        <span v-if="folder !== '(No folder)'">📁 {{{{ folder }}}}</span>
                                        <span v-else class="text-gray-400">📂 {{{{ folder }}}}</span>
                                        <span class="ml-2 text-xs font-normal text-gray-500">({{{{ measures.length }}}})</span>
                                    </h3>
                                </div>

                                <!-- Measures in this folder -->
                                <div
                                    v-for="measure in measures"
                                    :key="'measure-' + measure.table + '-' + measure.name"
                                    @click="selectMeasureFromOverview(measure)"
                                    class="list-item border-b p-3 cursor-pointer hover:bg-gray-50"
                                >
                                    <div class="flex items-center justify-between">
                                        <div class="flex items-center gap-3 flex-1 min-w-0">
                                            <div class="bg-pink-100 w-10 h-10 rounded flex items-center justify-center text-lg flex-shrink-0">
                                                🧮
                                            </div>
                                            <div class="flex-1 min-w-0">
                                                <h3 class="font-semibold text-sm text-gray-900 truncate">m {{{{ measure.name }}}}</h3>
                                                <div class="flex items-center gap-3 mt-1 text-xs text-gray-500">
                                                    <span>{{{{ measure.statistics.dependency_count }}}} deps</span>
                                                    <span>{{{{ measure.statistics.usage_count }}}} used by</span>
                                                </div>
                                            </div>
                                            <span :class="{{
                                                'bg-green-100 text-green-800': measure.complexity === 'low',
                                                'bg-yellow-100 text-yellow-800': measure.complexity === 'medium',
                                                'bg-red-100 text-red-800': measure.complexity === 'high'
                                           }}" class="px-2 py-1 rounded text-xs font-semibold uppercase flex-shrink-0">
                                                {{{{ measure.complexity }}}}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            </template>
                        </div>
                    </div>
                </div>

                <!-- Right Panel: Model Summary -->
                <div class="col-span-5">
                    <div class="bg-white rounded-lg shadow p-6 sticky top-6">
                        <h2 class="text-xl font-bold text-gray-900 mb-4">📊 Model Summary</h2>

                        <!-- Model Statistics -->
                        <div class="space-y-4 mb-6">
                            <div class="border-b pb-3">
                                <h3 class="text-sm font-semibold text-gray-700 mb-2">Overview</h3>
                                <div class="space-y-2">
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Total Tables</span>
                                        <span class="font-bold text-lg text-blue-600">{{{{ modelData.statistics.total_tables }}}}</span>
                                    </div>
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Total Measures</span>
                                        <span class="font-bold text-lg text-pink-600">{{{{ modelData.statistics.total_measures }}}}</span>
                                    </div>
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Total Relationships</span>
                                        <span class="font-bold text-lg text-purple-600">{{{{ modelData.statistics.total_relationships }}}}</span>
                                    </div>
                                </div>
                            </div>

                            <div class="border-b pb-3">
                                <h3 class="text-sm font-semibold text-gray-700 mb-2">Table Types</h3>
                                <div class="space-y-2">
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">📁 Dimensions</span>
                                        <span class="font-semibold text-green-600">{{{{ modelData.statistics.dimension_tables }}}}</span>
                                    </div>
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">📊 Facts</span>
                                        <span class="font-semibold text-blue-600">{{{{ modelData.statistics.fact_tables }}}}</span>
                                    </div>
                                </div>
                            </div>

                            <div class="border-b pb-3">
                                <h3 class="text-sm font-semibold text-gray-700 mb-2">Relationships</h3>
                                <div class="space-y-2">
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Active</span>
                                        <span class="font-semibold text-green-600">{{{{ modelData.statistics.active_relationships }}}}</span>
                                    </div>
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Inactive</span>
                                        <span class="font-semibold text-red-600">{{{{ modelData.statistics.inactive_relationships }}}}</span>
                                    </div>
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Disconnected Tables</span>
                                        <span class="font-semibold text-yellow-600">{{{{ modelData.statistics.tables_with_no_relationships }}}}</span>
                                    </div>
                                </div>
                            </div>

                            <div>
                                <h3 class="text-sm font-semibold text-gray-700 mb-2">Model Health</h3>
                                <div class="space-y-2">
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Unused Measures</span>
                                        <span class="font-semibold" :class="{{
                                            'text-green-600': modelData.statistics.unused_measures === 0,
                                            'text-yellow-600': modelData.statistics.unused_measures > 0
                                        }}">{{{{ modelData.statistics.unused_measures }}}}</span>
                                    </div>
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm text-gray-600">Measures with Dependencies</span>
                                        <span class="font-semibold text-blue-600">{{{{ modelData.statistics.measures_with_dependencies }}}}</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Model Complexity Badge -->
                        <div class="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg p-4 border border-blue-200">
                            <div class="text-center">
                                <div class="text-xs text-gray-600 mb-1">Model Complexity</div>
                                <div class="text-2xl font-bold" :class="{{
                                    'text-green-600': modelData.statistics.total_tables < 10 && modelData.statistics.total_measures < 50,
                                    'text-yellow-600': (modelData.statistics.total_tables >= 10 && modelData.statistics.total_tables < 30) || (modelData.statistics.total_measures >= 50 && modelData.statistics.total_measures < 150),
                                    'text-red-600': modelData.statistics.total_tables >= 30 || modelData.statistics.total_measures >= 150
                                }}">
                                    <span v-if="modelData.statistics.total_tables < 10 && modelData.statistics.total_measures < 50">LOW</span>
                                    <span v-else-if="modelData.statistics.total_tables >= 30 || modelData.statistics.total_measures >= 150">HIGH</span>
                                    <span v-else>MEDIUM</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tables View -->
            <div v-if="activeTab === 'tables'" class="grid grid-cols-12 gap-6">
                <div class="col-span-4">
                    <div class="bg-white rounded-lg shadow">
                        <div class="p-4 border-b">
                            <h3 class="text-lg font-semibold">Tables</h3>
                        </div>
                        <div class="scrollable">
                            <div
                                v-for="table in filteredTables"
                                :key="table.name"
                                @click="selectTable(table)"
                                :class="{{'selected': selectedTable?.name === table.name}}"
                                class="list-item p-4 border-b cursor-pointer"
                            >
                                <div class="flex justify-between items-start">
                                    <div class="flex-1">
                                        <div class="font-semibold text-gray-900">{{{{ table.name }}}}</div>
                                        <div class="text-sm text-gray-500 mt-1">
                                            {{{{ table.statistics.column_count }}}} columns ·
                                            {{{{ table.statistics.measure_count }}}} measures
                                        </div>
                                        <div class="flex gap-1 mt-2">
                                            <span class="px-2 py-0.5 rounded text-xs font-semibold" :class="{{
                                                'bg-green-100 text-green-800': table.table_type === 'dimension',
                                                'bg-blue-100 text-blue-800': table.table_type === 'fact'
                                           }}">
                                                {{{{ table.table_type }}}}
                                            </span>
                                            <span class="px-2 py-0.5 rounded text-xs font-semibold" :class="{{
                                                'bg-green-100 text-green-800': table.complexity === 'low',
                                                'bg-yellow-100 text-yellow-800': table.complexity === 'medium',
                                                'bg-red-100 text-red-800': table.complexity === 'high'
                                           }}">
                                                {{{{ table.complexity }}}}
                                            </span>
                                        </div>
                                    </div>
                                    <span v-if="table.hidden" class="badge badge-gray">Hidden</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="col-span-8">
                    <div v-if="selectedTable" class="bg-white rounded-lg shadow p-6">
                        <div class="border-b pb-4 mb-4">
                            <div class="flex justify-between items-start">
                                <div>
                                    <h2 class="text-2xl font-bold text-gray-900">{{{{ selectedTable.name }}}}</h2>
                                    <p v-if="selectedTable.description" class="text-gray-600 mt-2">
                                        {{{{ selectedTable.description }}}}
                                    </p>
                                    <div class="flex gap-2 mt-3">
                                        <span class="px-3 py-1 rounded-full text-sm font-semibold" :class="{{
                                            'bg-green-100 text-green-800': selectedTable.table_type === 'dimension',
                                            'bg-blue-100 text-blue-800': selectedTable.table_type === 'fact'
                                       }}">
                                            {{{{ selectedTable.table_type.toUpperCase() }}}}
                                        </span>
                                        <span class="px-3 py-1 rounded-full text-sm font-semibold" :class="{{
                                            'bg-green-100 text-green-800': selectedTable.complexity === 'low',
                                            'bg-yellow-100 text-yellow-800': selectedTable.complexity === 'medium',
                                            'bg-red-100 text-red-800': selectedTable.complexity === 'high'
                                       }}">
                                            Complexity: {{{{ selectedTable.complexity.toUpperCase() }}}}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Statistics -->
                        <div class="grid grid-cols-4 gap-4 mb-6">
                            <div class="stat-card">
                                <div class="text-sm text-gray-500">Rows</div>
                                <div class="text-2xl font-bold mt-1">{{{{ formatNumber(selectedTable.row_count) }}}}</div>
                            </div>
                            <div class="stat-card">
                                <div class="text-sm text-gray-500">Columns</div>
                                <div class="text-2xl font-bold mt-1">{{{{ selectedTable.statistics.column_count }}}}</div>
                            </div>
                            <div class="stat-card">
                                <div class="text-sm text-gray-500">Measures</div>
                                <div class="text-2xl font-bold mt-1">{{{{ selectedTable.statistics.measure_count }}}}</div>
                            </div>
                            <div class="stat-card">
                                <div class="text-sm text-gray-500">Relationships</div>
                                <div class="text-2xl font-bold mt-1">{{{{ selectedTable.statistics.relationship_count }}}}</div>
                            </div>
                        </div>

                        <!-- Tabs for different sections -->
                        <div class="border-b mb-4">
                            <nav class="-mb-px flex space-x-4">
                                <button
                                    @click="tableDetailTab = 'columns'"
                                    :class="{{
                                        'border-blue-500 text-blue-600': tableDetailTab === 'columns',
                                        'border-transparent text-gray-500': tableDetailTab !== 'columns'
                                   }}"
                                    class="py-2 px-1 border-b-2 font-medium text-sm"
                                >
                                    Columns ({{{{ selectedTable.columns.length }}}})
                                </button>
                                <button
                                    @click="tableDetailTab = 'measures'"
                                    :class="{{
                                        'border-blue-500 text-blue-600': tableDetailTab === 'measures',
                                        'border-transparent text-gray-500': tableDetailTab !== 'measures'
                                   }}"
                                    class="py-2 px-1 border-b-2 font-medium text-sm"
                                >
                                    Measures ({{{{ selectedTable.measures.length }}}})
                                </button>
                                <button
                                    @click="tableDetailTab = 'relationships'"
                                    :class="{{
                                        'border-blue-500 text-blue-600': tableDetailTab === 'relationships',
                                        'border-transparent text-gray-500': tableDetailTab !== 'relationships'
                                   }}"
                                    class="py-2 px-1 border-b-2 font-medium text-sm"
                                >
                                    Relationships ({{{{ selectedTable.statistics.relationship_count }}}})
                                </button>
                                <button
                                    @click="tableDetailTab = 'usage'"
                                    :class="{{
                                        'border-blue-500 text-blue-600': tableDetailTab === 'usage',
                                        'border-transparent text-gray-500': tableDetailTab !== 'usage'
                                   }}"
                                    class="py-2 px-1 border-b-2 font-medium text-sm"
                                >
                                    Usage ({{{{ selectedTable.used_in_measures.length }}}})
                                </button>
                                <button
                                    @click="tableDetailTab = 'preview'; loadTablePreview(selectedTable.name)"
                                    :class="{{
                                        'border-blue-500 text-blue-600': tableDetailTab === 'preview',
                                        'border-transparent text-gray-500': tableDetailTab !== 'preview'
                                   }}"
                                    class="py-2 px-1 border-b-2 font-medium text-sm"
                                >
                                    📊 Data Preview
                                </button>
                            </nav>
                        </div>

                        <!-- Columns -->
                        <div v-if="tableDetailTab === 'columns'">
                            <div v-if="selectedTable.columns.length === 0" class="text-center py-8 text-gray-500">
                                No columns found for this table
                            </div>
                            <div v-else class="space-y-2">
                                <div
                                    v-for="column in selectedTable.columns"
                                    :key="column.name"
                                    @click="showColumnDetails(selectedTable, column)"
                                    class="p-3 border rounded hover:bg-gray-50 cursor-pointer transition"
                                >
                                    <div class="flex justify-between items-center">
                                        <div class="flex-1">
                                            <div class="flex items-center gap-2">
                                                <span class="font-semibold text-gray-900">{{{{ column.name || '(unnamed column)' }}}}</span>
                                                <span v-if="column.key" class="px-2 py-0.5 bg-yellow-100 text-yellow-800 rounded text-xs font-semibold">🔑 Key</span>
                                            </div>
                                            <div class="text-sm text-gray-600 mt-1">
                                                Type: <span class="font-medium text-blue-600">{{{{ column.data_type || 'String' }}}}</span>
                                            </div>
                                        </div>
                                        <span class="text-sm text-gray-400">→</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Measures -->
                        <div v-if="tableDetailTab === 'measures'" class="space-y-2">
                            <div
                                v-for="measure in selectedTable.measures"
                                :key="measure.name"
                                class="p-3 border rounded hover:bg-gray-50 cursor-pointer"
                                @click="jumpToMeasure(selectedTable.name, measure.name)"
                            >
                                <div class="flex justify-between items-center">
                                    <div>
                                        <span class="font-semibold">{{{{ measure.name }}}}</span>
                                        <span v-if="measure.folder" class="text-sm text-gray-500 ml-2">
                                            📁 {{{{ measure.folder }}}}
                                        </span>
                                    </div>
                                    <button class="text-blue-600 text-sm hover:underline">
                                        View →
                                    </button>
                                </div>
                            </div>
                        </div>

                        <!-- Relationships -->
                        <div v-if="tableDetailTab === 'relationships'">
                            <div v-if="selectedTable.relationships_in.length > 0" class="mb-4">
                                <h4 class="font-semibold mb-2">Incoming ({{{{ selectedTable.relationships_in.length }}}})</h4>
                                <div class="space-y-2">
                                    <div
                                        v-for="(rel, idx) in selectedTable.relationships_in"
                                        :key="'in-' + idx"
                                        @click="showRelationshipDetails(rel)"
                                        class="p-3 border rounded bg-green-50 hover:bg-green-100 cursor-pointer"
                                    >
                                        <div class="flex items-center justify-between">
                                            <div>
                                                <span class="font-semibold">{{{{ rel.from_table }}}}</span>
                                                <span class="text-gray-500">[{{{{ rel.from_column }}}}]</span>
                                                <span class="mx-2">→</span>
                                                <span class="font-semibold">{{{{ selectedTable.name }}}}</span>
                                                <span class="text-gray-500">[{{{{ rel.to_column }}}}]</span>
                                            </div>
                                            <div class="flex items-center space-x-2">
                                                <span :class="rel.active ? 'badge-success' : 'badge-danger'" class="badge">
                                                    {{{{ rel.active ? 'Active' : 'Inactive' }}}}
                                                </span>
                                                <span class="badge badge-gray">{{{{ rel.cardinality }}}}</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div v-if="selectedTable.relationships_out.length > 0">
                                <h4 class="font-semibold mb-2">Outgoing ({{{{ selectedTable.relationships_out.length }}}})</h4>
                                <div class="space-y-2">
                                    <div
                                        v-for="(rel, idx) in selectedTable.relationships_out"
                                        :key="'out-' + idx"
                                        @click="showRelationshipDetails(rel)"
                                        class="p-3 border rounded bg-blue-50 hover:bg-blue-100 cursor-pointer"
                                    >
                                        <div class="flex items-center justify-between">
                                            <div>
                                                <span class="font-semibold">{{{{ selectedTable.name }}}}</span>
                                                <span class="text-gray-500">[{{{{ rel.from_column }}}}]</span>
                                                <span class="mx-2">→</span>
                                                <span class="font-semibold">{{{{ rel.to_table }}}}</span>
                                                <span class="text-gray-500">[{{{{ rel.to_column }}}}]</span>
                                            </div>
                                            <div class="flex items-center space-x-2">
                                                <span :class="rel.active ? 'badge-success' : 'badge-danger'" class="badge">
                                                    {{{{ rel.active ? 'Active' : 'Inactive' }}}}
                                                </span>
                                                <span class="badge badge-gray">{{{{ rel.cardinality }}}}</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div v-if="selectedTable.statistics.relationship_count === 0" class="text-center py-8 text-gray-500">
                                No relationships for this table
                            </div>
                        </div>

                        <!-- Usage -->
                        <div v-if="tableDetailTab === 'usage'">
                            <div v-if="selectedTable.used_in_measures.length > 0" class="space-y-2">
                                <div
                                    v-for="(usage, idx) in selectedTable.used_in_measures"
                                    :key="idx"
                                    class="p-3 border rounded hover:bg-gray-50 cursor-pointer"
                                    @click="jumpToMeasure(usage.measure_table, usage.measure_name)"
                                >
                                    <div class="flex justify-between items-center">
                                        <div>
                                            <span class="font-semibold">{{{{ usage.measure_table }}}}</span>
                                            <span class="text-gray-500"> / </span>
                                            <span>{{{{ usage.measure_name }}}}</span>
                                        </div>
                                        <button class="text-blue-600 text-sm hover:underline">
                                            View →
                                        </button>
                                    </div>
                                </div>
                            </div>
                            <div v-else class="text-center py-8 text-gray-500">
                                This table is not referenced in any measures
                            </div>
                        </div>

                        <!-- Data Preview -->
                        <div v-if="tableDetailTab === 'preview'">
                            <!-- Loading state -->
                            <div v-if="tablePreviewLoading" class="flex items-center justify-center py-12">
                                <div class="text-center">
                                    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
                                    <p class="mt-4 text-gray-600">Loading data preview...</p>
                                </div>
                            </div>

                            <!-- Error state -->
                            <div v-else-if="tablePreviewError" class="bg-red-50 border border-red-200 rounded p-4 text-red-800">
                                <div class="flex items-start">
                                    <span class="text-2xl mr-3">⚠️</span>
                                    <div>
                                        <strong class="font-semibold">Error loading data preview</strong>
                                        <p class="text-sm mt-1">{{{{ tablePreviewError }}}}</p>
                                        <button @click="loadTablePreview(selectedTable.name)" class="mt-2 text-sm text-red-600 hover:underline">
                                            Try again
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- Data table -->
                            <div v-else-if="tablePreviewData && tablePreviewData.rows" class="overflow-x-auto">
                                <div class="mb-3 text-sm text-gray-600">
                                    Showing {{{{ tablePreviewData.rows.length }}}} of {{{{ formatNumber(selectedTable.row_count) }}}} rows
                                </div>
                                <table class="min-w-full divide-y divide-gray-200 border">
                                    <thead class="bg-gray-50">
                                        <tr>
                                            <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-r sticky left-0 bg-gray-50 z-10">
                                                #
                                            </th>
                                            <th
                                                v-for="column in tablePreviewData.columns"
                                                :key="column"
                                                class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-r whitespace-nowrap"
                                            >
                                                {{{{ column }}}}
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody class="bg-white divide-y divide-gray-200">
                                        <tr v-for="(row, rowIdx) in tablePreviewData.rows" :key="rowIdx" class="hover:bg-gray-50">
                                            <td class="px-3 py-2 text-sm text-gray-500 border-r sticky left-0 bg-white font-medium">
                                                {{{{ rowIdx + 1 }}}}
                                            </td>
                                            <td
                                                v-for="column in tablePreviewData.columns"
                                                :key="column"
                                                class="px-3 py-2 text-sm text-gray-900 border-r whitespace-nowrap"
                                            >
                                                {{{{ formatCellValue(row[column]) }}}}
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>

                            <!-- Empty state -->
                            <div v-else class="text-center py-8 text-gray-500">
                                Click "📊 Data Preview" to load sample data
                            </div>
                        </div>
                    </div>
                    <div v-else class="bg-white rounded-lg shadow p-12 text-center text-gray-500">
                        <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                        </svg>
                        <p class="mt-4">Select a table from the list to view its details</p>
                    </div>
                </div>
            </div>

            <!-- Measures View -->
            <div v-if="activeTab === 'measures'" class="grid grid-cols-12 gap-6">
                <div class="col-span-4">
                    <div class="bg-white rounded-lg shadow">
                        <div class="p-4 border-b">
                            <h3 class="text-lg font-semibold">Measures</h3>
                            <select v-model="measureFilterTable" class="mt-2 w-full px-3 py-2 border rounded">
                                <option value="">All Tables</option>
                                <option v-for="table in uniqueMeasureTables" :key="table" :value="table">
                                    {{{{ table }}}}
                                </option>
                            </select>
                        </div>
                        <div class="scrollable">
                            <template v-for="(measure, index) in filteredMeasures" :key="measure.table + '.' + measure.name">
                                <!-- Show folder header when folder changes -->
                                <div
                                    v-if="index === 0 || measure.table !== filteredMeasures[index - 1].table || measure.folder !== filteredMeasures[index - 1].folder"
                                    class="px-4 py-2 bg-gray-100 border-b sticky top-0"
                                    style="z-index: 1;"
                                >
                                    <div class="text-xs font-semibold text-gray-600">
                                        {{{{ measure.table }}}}
                                        <span v-if="measure.folder" class="ml-1">→ 📁 {{{{ measure.folder }}}}</span>
                                        <span v-else class="ml-1 text-gray-400">→ (No folder)</span>
                                    </div>
                                </div>
                                <div
                                    @click="selectMeasure(measure)"
                                    :class="{{'selected': selectedMeasure?.name === measure.name && selectedMeasure?.table === measure.table}}"
                                    class="list-item p-4 border-b cursor-pointer"
                                >
                                    <div class="font-semibold text-gray-900">{{{{ measure.name }}}}</div>
                                    <div class="text-sm text-gray-500 mt-1">
                                        <span v-if="measure.statistics">
                                            {{{{ measure.statistics.dependency_count }}}} deps ·
                                            {{{{ measure.statistics.usage_count }}}} used by
                                        </span>
                                    </div>
                                </div>
                            </template>
                        </div>
                    </div>
                </div>

                <div class="col-span-8">
                    <div v-if="selectedMeasure" class="bg-white rounded-lg shadow p-6">
                        <div class="border-b pb-4 mb-4">
                            <div class="flex justify-between items-start">
                                <div>
                                    <h2 class="text-2xl font-bold text-gray-900">{{{{ selectedMeasure.name }}}}</h2>
                                    <p class="text-gray-600 mt-1">{{{{ selectedMeasure.table }}}}</p>
                                    <p v-if="selectedMeasure.description" class="text-gray-600 mt-2">
                                        {{{{ selectedMeasure.description }}}}
                                    </p>
                                    <div class="flex gap-2 mt-3">
                                        <span class="px-3 py-1 rounded-full text-sm font-semibold bg-pink-100 text-pink-800">
                                            MEASURE
                                        </span>
                                        <span class="px-3 py-1 rounded-full text-sm font-semibold" :class="{{
                                            'bg-green-100 text-green-800': selectedMeasure.complexity === 'low',
                                            'bg-yellow-100 text-yellow-800': selectedMeasure.complexity === 'medium',
                                            'bg-red-100 text-red-800': selectedMeasure.complexity === 'high'
                                       }}">
                                            Complexity: {{{{ selectedMeasure.complexity.toUpperCase() }}}}
                                        </span>
                                    </div>
                                </div>
                                <div class="flex items-center space-x-2">
                                    <span v-if="selectedMeasure.hidden" class="badge badge-gray">Hidden</span>
                                    <span v-if="selectedMeasure.folder" class="badge badge-primary">
                                        📁 {{{{ selectedMeasure.folder }}}}
                                    </span>
                                </div>
                            </div>
                        </div>

                        <!-- DAX Expression -->
                        <div class="mb-6">
                            <h3 class="text-lg font-semibold mb-2">DAX Expression</h3>
                            <div class="code-block" style="white-space: pre-wrap; font-family: 'Consolas', 'Monaco', 'Courier New', monospace; line-height: 1.5;" v-html="formatDAX(selectedMeasure.expression)"></div>
                        </div>

                        <!-- Dependencies (What this measure uses) -->
                        <div v-if="selectedMeasure.depends_on && (selectedMeasure.depends_on.measures.length > 0 || selectedMeasure.depends_on.columns.length > 0)" class="mb-6">
                            <h3 class="text-lg font-semibold mb-3">Dependencies (Uses)</h3>

                            <div v-if="selectedMeasure.depends_on.measures.length > 0" class="mb-4">
                                <h4 class="text-sm font-semibold text-gray-600 mb-2">
                                    Measures ({{{{ selectedMeasure.depends_on.measures.length }}}})
                                </h4>
                                <div class="space-y-2">
                                    <div
                                        v-for="(dep, idx) in selectedMeasure.depends_on.measures"
                                        :key="'dep-m-' + idx"
                                        class="p-3 border rounded bg-blue-50 hover:bg-blue-100 cursor-pointer"
                                        @click="jumpToMeasure(dep.table, dep.measure)"
                                    >
                                        <div class="flex justify-between items-center">
                                            <div>
                                                <span class="font-semibold">{{{{ dep.table }}}}</span>
                                                <span class="text-gray-500"> / </span>
                                                <span>{{{{ dep.measure }}}}</span>
                                            </div>
                                            <button class="text-blue-600 text-sm hover:underline">View →</button>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div v-if="selectedMeasure.depends_on.columns.length > 0">
                                <h4 class="text-sm font-semibold text-gray-600 mb-2">
                                    Columns ({{{{ selectedMeasure.depends_on.columns.length }}}})
                                </h4>
                                <div class="space-y-2">
                                    <div
                                        v-for="(col, idx) in selectedMeasure.depends_on.columns"
                                        :key="'dep-c-' + idx"
                                        class="p-3 border rounded bg-green-50"
                                    >
                                        <span v-if="col.table" class="font-semibold">{{{{ col.table }}}}</span>
                                        <span v-if="col.table" class="text-gray-500"> / </span>
                                        <span>{{{{ col.column }}}}</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Used By (What measures use this) -->
                        <div v-if="selectedMeasure.used_by_measures && selectedMeasure.used_by_measures.length > 0" class="mb-6">
                            <h3 class="text-lg font-semibold mb-3">Used By ({{{{ selectedMeasure.used_by_measures.length }}}} measures)</h3>
                            <div class="space-y-2">
                                <div
                                    v-for="(usage, idx) in selectedMeasure.used_by_measures"
                                    :key="'usage-' + idx"
                                    class="p-3 border rounded bg-purple-50 hover:bg-purple-100 cursor-pointer"
                                    @click="jumpToMeasure(usage.table, usage.measure)"
                                >
                                    <div class="flex justify-between items-center">
                                        <div>
                                            <span class="font-semibold">{{{{ usage.table }}}}</span>
                                            <span class="text-gray-500"> / </span>
                                            <span>{{{{ usage.measure }}}}</span>
                                        </div>
                                        <button class="text-blue-600 text-sm hover:underline">View →</button>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div v-if="selectedMeasure.statistics.usage_count === 0" class="p-4 bg-yellow-50 border border-yellow-200 rounded">
                            <p class="text-yellow-800">
                                ⚠️ This measure is not used by any other measures. It may be unused or only referenced in reports.
                            </p>
                        </div>
                    </div>
                    <div v-else class="bg-white rounded-lg shadow p-12 text-center text-gray-500">
                        <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        <p class="mt-4">Select a measure from the list to view its details</p>
                    </div>
                </div>
            </div>

            <!-- Relationships Graph View -->
            <div v-if="activeTab === 'relationships'">
                <div class="bg-white rounded-lg shadow p-6">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-2xl font-bold text-gray-900">Relationship Graph</h2>
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">Filter Table:</label>
                            <select v-model="graphFilterTable" @change="initGraph" class="px-3 py-1 border rounded text-sm">
                                <option value="">All Tables</option>
                                <option v-for="table in allGraphTables" :key="table" :value="table">
                                    {{{{ table }}}}
                                </option>
                            </select>
                            <label class="text-sm font-medium text-gray-700 ml-4">Layout:</label>
                            <select v-model="graphLayout" @change="changeGraphLayout(graphLayout)" class="px-3 py-1 border rounded text-sm">
                                <option value="tree">🌳 D3 Tree (Recommended)</option>
                                <option value="dagre">📊 Dagre (Layered)</option>
                                <option value="force">🔗 Force Directed</option>
                                <option value="hierarchical">Hierarchical (Old)</option>
                                <option value="radial">Radial (Tiered)</option>
                            </select>
                            <label class="flex items-center space-x-2 ml-4">
                                <input type="checkbox" v-model="showInactiveRelationships" class="rounded">
                                <span class="text-sm">Show Inactive</span>
                            </label>
                            <button @click="resetGraph" class="px-3 py-1 bg-gray-100 hover:bg-gray-200 rounded text-sm">
                                Reset View
                            </button>
                        </div>
                    </div>

                    <!-- Legend -->
                    <div class="mb-4 flex items-center gap-6 text-sm">
                        <div class="flex items-center gap-2">
                            <div class="w-4 h-4 rounded-full" style="background: linear-gradient(180deg, #7D9AFF 0%, #5B7FFF 100%);"></div>
                            <span class="text-gray-600">Dimension (d_)</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <div class="w-4 h-4 rounded-full" style="background: linear-gradient(180deg, #FFA76F 0%, #FF8C42 100%);"></div>
                            <span class="text-gray-600">Fact (f_)</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <div class="w-4 h-4 rounded-full" style="background: linear-gradient(180deg, #B794F6 0%, #9F7AEA 100%);"></div>
                            <span class="text-gray-600">Slicer (s_)</span>
                        </div>
                    </div>

                    <div id="graph-container" style="height: 700px; position: relative;">
                        <svg id="graph-svg" width="100%" height="100%"></svg>
                    </div>

                    <div v-if="selectedNode" class="mt-4 p-4 bg-blue-50 border border-blue-200 rounded">
                        <h3 class="font-semibold text-lg mb-2">Selected: {{{{ selectedNode }}}}</h3>
                        <div class="text-sm text-gray-700">
                            Click on a table to highlight its relationships
                        </div>
                    </div>
                </div>
            </div>

            <!-- Statistics View -->
            <div v-if="activeTab === 'statistics'">
                <div class="grid grid-cols-3 gap-6">
                    <div class="stat-card">
                        <h3 class="text-lg font-semibold mb-4">Model Overview</h3>
                        <div class="space-y-2">
                            <div class="flex justify-between">
                                <span class="text-gray-600">Total Tables</span>
                                <span class="font-semibold">{{{{ modelData.statistics.total_tables }}}}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-600">Total Columns</span>
                                <span class="font-semibold">{{{{ modelData.statistics.total_columns }}}}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-600">Total Measures</span>
                                <span class="font-semibold">{{{{ modelData.statistics.total_measures }}}}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-600">Total Relationships</span>
                                <span class="font-semibold">{{{{ modelData.statistics.total_relationships }}}}</span>
                            </div>
                        </div>
                    </div>

                    <div class="stat-card">
                        <h3 class="text-lg font-semibold mb-4">Relationships</h3>
                        <div class="space-y-2">
                            <div class="flex justify-between">
                                <span class="text-gray-600">Active</span>
                                <span class="font-semibold text-green-600">{{{{ modelData.statistics.active_relationships }}}}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-600">Inactive</span>
                                <span class="font-semibold text-red-600">{{{{ modelData.statistics.inactive_relationships }}}}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-600">Disconnected Tables</span>
                                <span class="font-semibold text-yellow-600">{{{{ modelData.statistics.tables_with_no_relationships }}}}</span>
                            </div>
                        </div>
                    </div>

                    <div class="stat-card">
                        <h3 class="text-lg font-semibold mb-4">Measures</h3>
                        <div class="space-y-2">
                            <div class="flex justify-between">
                                <span class="text-gray-600">With Dependencies</span>
                                <span class="font-semibold">{{{{ modelData.statistics.measures_with_dependencies }}}}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-600">Unused</span>
                                <span class="font-semibold text-yellow-600">{{{{ modelData.statistics.unused_measures }}}}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Command Palette Modal -->
            <div v-if="showCommandPalette" @click="showCommandPalette = false" class="fixed inset-0 bg-black bg-opacity-50 flex items-start justify-center pt-20 z-50">
                <div @click.stop class="bg-white rounded-lg shadow-2xl w-full max-w-2xl p-6">
                    <h3 class="text-xl font-bold mb-4">⌨️ Keyboard Shortcuts</h3>
                    <div class="space-y-3">
                        <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                            <span class="font-medium">/</span>
                            <span class="text-gray-600">Focus search box</span>
                        </div>
                        <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                            <span class="font-medium">Ctrl/Cmd + K</span>
                            <span class="text-gray-600">Toggle command palette</span>
                        </div>
                        <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                            <span class="font-medium">Alt + ← / →</span>
                            <span class="text-gray-600">Navigate between tabs</span>
                        </div>
                        <div class="flex justify-between items-center p-2 bg-gray-50 rounded">
                            <span class="font-medium">Escape</span>
                            <span class="text-gray-600">Close modals / Clear search</span>
                        </div>
                    </div>
                    <div class="mt-6 border-t pt-4">
                        <h4 class="font-semibold mb-3">Quick Actions</h4>
                        <div class="grid grid-cols-2 gap-2">
                            <button @click="exportToCSV(); showCommandPalette = false" class="p-2 bg-blue-500 text-white rounded hover:bg-blue-600">
                                📄 Export CSV
                            </button>
                            <button @click="exportToJSON(); showCommandPalette = false" class="p-2 bg-green-500 text-white rounded hover:bg-green-600">
                                📦 Export JSON
                            </button>
                            <button @click="toggleDarkMode(); showCommandPalette = false" class="p-2 bg-gray-700 text-white rounded hover:bg-gray-800">
                                {{{{ darkMode ? '☀️ Light Mode' : '🌙 Dark Mode' }}}}
                            </button>
                            <button @click="resetGraph(); showCommandPalette = false" class="p-2 bg-purple-500 text-white rounded hover:bg-purple-600">
                                🔄 Reset Graph
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Column Details Modal -->
            <div v-if="showColumnModal && selectedColumn" @click="showColumnModal = false" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                <div @click.stop class="bg-white rounded-lg shadow-2xl w-full max-w-3xl p-6 max-h-96 overflow-y-auto">
                    <div class="flex justify-between items-start mb-4">
                        <div>
                            <h3 class="text-2xl font-bold">{{{{ selectedColumn.column.name }}}}</h3>
                            <p class="text-gray-600">{{{{ selectedColumn.table.name }}}}</p>
                        </div>
                        <button @click="showColumnModal = false" class="text-gray-400 hover:text-gray-600 text-2xl">×</button>
                    </div>
                    <div class="space-y-4">
                        <div>
                            <h4 class="font-semibold mb-2">Column Properties</h4>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <span class="text-sm text-gray-600">Data Type:</span>
                                    <p class="font-medium">{{{{ selectedColumn.column.data_type }}}}</p>
                                </div>
                                <div>
                                    <span class="text-sm text-gray-600">Key:</span>
                                    <p class="font-medium">{{{{ selectedColumn.column.key ? 'Yes' : 'No' }}}}</p>
                                </div>
                                <div>
                                    <span class="text-sm text-gray-600">Hidden:</span>
                                    <p class="font-medium">{{{{ selectedColumn.column.hidden ? 'Yes' : 'No' }}}}</p>
                                </div>
                            </div>
                        </div>
                        <div>
                            <h4 class="font-semibold mb-2">Usage in Model</h4>
                            <p class="text-sm text-gray-600">
                                This column is used in {{{{ selectedColumn.table.used_in_measures.length }}}} measures
                                and {{{{ selectedColumn.table.relationships_in.length + selectedColumn.table.relationships_out.length }}}} relationships.
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Relationship Details Modal -->
            <div v-if="showRelationshipModal && selectedRelationship" @click="showRelationshipModal = false" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                <div @click.stop class="bg-white rounded-lg shadow-2xl w-full max-w-3xl p-6">
                    <div class="flex justify-between items-start mb-4">
                        <h3 class="text-2xl font-bold">Relationship Details</h3>
                        <button @click="showRelationshipModal = false" class="text-gray-400 hover:text-gray-600 text-2xl">×</button>
                    </div>
                    <div class="space-y-4">
                        <div class="bg-blue-50 p-4 rounded-lg">
                            <div class="flex items-center justify-between text-lg">
                                <div>
                                    <span class="font-bold">{{{{ selectedRelationship.from_table }}}}</span>
                                    <span class="text-gray-600 text-sm ml-1">[{{{{ selectedRelationship.from_column }}}}]</span>
                                </div>
                                <span class="text-2xl mx-4">→</span>
                                <div>
                                    <span class="font-bold">{{{{ selectedRelationship.to_table }}}}</span>
                                    <span class="text-gray-600 text-sm ml-1">[{{{{ selectedRelationship.to_column }}}}]</span>
                                </div>
                            </div>
                        </div>
                        <div class="grid grid-cols-3 gap-4">
                            <div class="p-3 bg-gray-50 rounded">
                                <span class="text-sm text-gray-600">Status:</span>
                                <p class="font-semibold" :class="selectedRelationship.active ? 'text-green-600' : 'text-red-600'">
                                    {{{{ selectedRelationship.active ? 'Active' : 'Inactive' }}}}
                                </p>
                            </div>
                            <div class="p-3 bg-gray-50 rounded">
                                <span class="text-sm text-gray-600">Cardinality:</span>
                                <p class="font-semibold">{{{{ selectedRelationship.cardinality }}}}</p>
                            </div>
                            <div class="p-3 bg-gray-50 rounded">
                                <span class="text-sm text-gray-600">Direction:</span>
                                <p class="font-semibold">{{{{ selectedRelationship.direction }}}}</p>
                            </div>
                        </div>
                        <div class="border-t pt-4">
                            <h4 class="font-semibold mb-2">Relationship Type</h4>
                            <p class="text-gray-600">
                                This is a <span class="font-medium">{{{{ selectedRelationship.cardinality }}}}</span> relationship
                                {{{{ selectedRelationship.active ? 'that is currently active' : 'that is currently inactive' }}}}.
                                Cross-filtering behavior: <span class="font-medium">{{{{ selectedRelationship.direction }}}}</span>.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        console.log('[DIAGNOSTIC] Main script starting...');
        console.log('[DIAGNOSTIC] Vue object:', Vue);

        const {{ createApp }} = Vue;
        console.log('[DIAGNOSTIC] createApp function:', createApp);

        const app = createApp({{
            data() {{
                return {{
                    activeTab: 'overview',
                    overviewFilter: 'all',
                    tableDetailTab: 'columns',
                    selectedTable: null,
                    selectedMeasure: null,
                    selectedNode: null,
                    selectedColumn: null,
                    selectedRelationship: null,
                    searchQuery: '',
                    measureFilterTable: '',
                    graphFilterTable: '',
                    darkMode: false,
                    showInactiveRelationships: true,
                    graphLayout: 'tree',  // Default to new D3 tree layout
                    showColumnModal: false,
                    showRelationshipModal: false,
                    showCommandPalette: false,
                    modelData: {model_json},
                    graphSimulation: null,
                    graphSvg: null,
                                                            dependencyLayout: 'hierarchical',
                                        dependencySimulation: null,
                    dependencyFocusMeasure: '',
                    dependencyFocusTable: '',
                    dependencyDepth: 3,
                    // Table preview properties
                    tablePreviewData: null,
                    tablePreviewLoading: false,
                    tablePreviewError: null
                }};
            }},
            computed: {{
                overviewFilteredTables() {{
                    let tables = this.modelData.tables || [];

                    // Apply overview filter
                    if (this.overviewFilter === 'dimensions') {{
                        tables = tables.filter(t => t.table_type === 'dimension');
                    }} else if (this.overviewFilter === 'facts') {{
                        tables = tables.filter(t => t.table_type === 'fact');
                    }} else if (this.overviewFilter === 'measures') {{
                        return []; // Don't show tables when filtering for measures
                    }}

                    // Filter by search query
                    if (this.searchQuery) {{
                        const query = this.searchQuery.toLowerCase();
                        tables = tables.filter(t =>
                            t.name.toLowerCase().includes(query)
                        );
                    }}

                    // Sort alphabetically by name
                    return tables.sort((a, b) => a.name.localeCompare(b.name));
                }},
                overviewFilteredMeasures() {{
                    let measures = this.modelData.measures || [];

                    // Only show measures when filter is 'all' or 'measures'
                    if (this.overviewFilter !== 'all' && this.overviewFilter !== 'measures') {{
                        return [];
                    }}

                    // Filter by search query
                    if (this.searchQuery) {{
                        const query = this.searchQuery.toLowerCase();
                        measures = measures.filter(m =>
                            m.name.toLowerCase().includes(query)
                        );
                    }}

                    // Sort by folder first, then by name
                    return measures.sort((a, b) => {{
                        const folderA = a.folder || '';
                        const folderB = b.folder || '';

                        // First sort by folder
                        if (folderA !== folderB) {{
                            return folderA.localeCompare(folderB);
                        }}

                        // Then by name within the same folder
                        return a.name.localeCompare(b.name);
                    }});
                }},
                measuresByFolder() {{
                    const measures = this.overviewFilteredMeasures;
                    const grouped = {{}};

                    measures.forEach(measure => {{
                        const folder = measure.folder || '(No folder)';
                        if (!grouped[folder]) {{
                            grouped[folder] = [];
                        }}
                        grouped[folder].push(measure);
                    }});

                    return grouped;
                }},
                filteredTables() {{
                    let tables = this.modelData.tables || [];

                    // Filter by search query
                    if (this.searchQuery) {{
                        const query = this.searchQuery.toLowerCase();
                        tables = tables.filter(t =>
                            t.name.toLowerCase().includes(query)
                        );
                    }}

                    // Sort alphabetically by name
                    return tables.sort((a, b) => a.name.localeCompare(b.name));
                }},
                filteredMeasures() {{
                    let measures = this.modelData.measures || [];

                    // Filter by table if selected
                    if (this.measureFilterTable) {{
                        measures = measures.filter(m => m.table === this.measureFilterTable);
                    }}

                    // Filter by search query
                    if (this.searchQuery) {{
                        const query = this.searchQuery.toLowerCase();
                        measures = measures.filter(m =>
                            m.name.toLowerCase().includes(query) ||
                            m.table.toLowerCase().includes(query) ||
                            (m.folder && m.folder.toLowerCase().includes(query))
                        );
                    }}

                    // Sort by table, then folder (hierarchically), then measure name
                    return measures.sort((a, b) => {{
                        // First, sort by table
                        const tableCompare = a.table.localeCompare(b.table);
                        if (tableCompare !== 0) return tableCompare;

                        // Then, sort by folder (treating empty folder as coming first)
                        const folderA = a.folder || '';
                        const folderB = b.folder || '';
                        const folderCompare = folderA.localeCompare(folderB);
                        if (folderCompare !== 0) return folderCompare;

                        // Finally, sort by measure name
                        return a.name.localeCompare(b.name);
                    }});
                }},
                uniqueMeasureTables() {{
                    const tables = new Set((this.modelData.measures || []).map(m => m.table));
                    return Array.from(tables).sort();
                }},
                allGraphTables() {{
                    const nodes = this.modelData.relationships?.nodes || [];
                    return nodes.map(n => n.id).sort();
                }},
                
                            // Sort by folder first, then by label
                            const folderA = a.folder || '';
                            const folderB = b.folder || '';
                            if (folderA !== folderB) {{
                                return folderA.localeCompare(folderB);
                            }}
                            return a.label.localeCompare(b.label);
                        }});

                    // Group by folder
                    const byFolder = {{}};
                    measures.forEach(m => {{
                        const folder = m.folder || '(No Folder)';
                        if (!byFolder[folder]) {{
                            byFolder[folder] = [];
                        }}
                        byFolder[folder].push(m);
                    }});

                    return byFolder;
                }},
                
                
            methods: {{
                selectTableFromOverview(table) {{
                    this.activeTab = 'tables';
                    this.selectedTable = table;
                    this.tableDetailTab = 'columns';
                }},
                selectMeasureFromOverview(measure) {{
                    this.activeTab = 'measures';
                    this.selectedMeasure = measure;
                }},
                selectTable(table) {{
                    this.selectedTable = table;
                    this.tableDetailTab = 'columns';
                }},
                selectMeasure(measure) {{
                    this.selectedMeasure = measure;
                }},
                jumpToMeasure(table, measureName) {{
                    this.activeTab = 'measures';
                    this.$nextTick(() => {{
                        const measure = (this.modelData.measures || []).find(
                            m => m.table === table && m.name === measureName
                        );
                        if (measure) {{
                            this.selectedMeasure = measure;
                            this.measureFilterTable = '';
                            this.searchQuery = '';
                        }}
                    }});
                }},
                formatNumber(num) {{
                    return new Intl.NumberFormat().format(num);
                }},
                formatCellValue(value) {{
                    if (value === null || value === undefined) {{
                        return '(null)';
                    }}
                    if (typeof value === 'number') {{
                        return new Intl.NumberFormat().format(value);
                    }}
                    if (typeof value === 'boolean') {{
                        return value ? 'true' : 'false';
                    }}
                    // Truncate long strings
                    const str = String(value);
                    if (str.length > 50) {{
                        return str.substring(0, 50) + '...';
                    }}
                    return str;
                }},
                async loadTablePreview(tableName) {{
                    this.tablePreviewLoading = true;
                    this.tablePreviewError = null;
                    this.tablePreviewData = null;

                    try {{
                        // Simulate loading delay
                        await new Promise(resolve => setTimeout(resolve, 500));

                        // Check if preview data exists in model data
                        if (this.modelData.table_previews && this.modelData.table_previews[tableName]) {{
                            this.tablePreviewData = this.modelData.table_previews[tableName];
                        }} else {{
                            // Generate helpful error message with debug info
                            const totalTablesWithData = this.modelData.table_previews ? Object.keys(this.modelData.table_previews).length : 0;
                            const availableTables = this.modelData.table_previews ? Object.keys(this.modelData.table_previews).join(', ') : 'none';

                            console.log('DEBUG: Looking for table:', tableName);
                            console.log('DEBUG: Available preview tables:', availableTables);
                            console.log('DEBUG: Total tables with data:', totalTablesWithData);

                            if (totalTablesWithData > 0) {{
                                throw new Error(`Preview data not available for this table. Data was collected for ${{totalTablesWithData}} other tables: ${{availableTables}}. This table may have had query errors, special characters, or complex data types that prevented data collection.`);
                            }} else {{
                                throw new Error('Table preview data not available. No table data was collected during export. Check the generation logs for details.');
                            }}
                        }}
                    }} catch (error) {{
                        this.tablePreviewError = error.message;
                    }} finally {{
                        this.tablePreviewLoading = false;
                    }}
                }},
                formatDAX(dax) {{
                    if (!dax) return '';

                    // DAX formatting with syntax highlighting
                    let formatted = dax;

                    // Keywords that should start on new lines
                    const keywords = [
                        'VAR', 'RETURN', 'EVALUATE', 'DEFINE', 'MEASURE', 'COLUMN', 'TABLE',
                        'IF', 'SWITCH', 'CALCULATE', 'FILTER', 'ALL', 'ALLEXCEPT', 'ALLSELECTED',
                        'SUMX', 'AVERAGEX', 'COUNTX', 'MINX', 'MAXX', 'RANKX',
                        'ADDCOLUMNS', 'SELECTCOLUMNS', 'SUMMARIZE', 'GROUPBY',
                        'DATEADD', 'DATESYTD', 'DATESBETWEEN', 'PARALLELPERIOD'
                    ];

                    // Add line breaks before major keywords (if not already formatted)
                    // Only if the DAX doesn't already have proper formatting
                    if (!formatted.includes('\\n') && formatted.length > 80) {{
                        keywords.forEach(keyword => {{
                            const regex = new RegExp('\\\\b(' + keyword + ')\\\\s*\\\\(', 'gi');
                            formatted = formatted.replace(regex, '\\n    $1(');
                        }});

                        // Add line break before RETURN
                        formatted = formatted.replace(/\\s+RETURN\\s+/gi, '\\nRETURN\\n    ');

                        // Add line break after VAR declarations
                        formatted = formatted.replace(/\\s+VAR\\s+/gi, '\\nVAR ');
                    }}

                    // Clean up multiple blank lines
                    formatted = formatted.replace(/\\n\\s*\\n\\s*\\n/g, '\\n\\n');

                    // Apply syntax highlighting
                    formatted = this.highlightDAX(formatted);

                    return formatted.trim();
                }},
                highlightDAX(dax) {{
                    if (!dax) return '';

                    // Escape HTML first
                    let highlighted = dax
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;');

                    // Create unique placeholders for elements we want to protect from further processing
                    const protectedElements = [];
                    let placeholderIndex = 0;

                    // Function to create placeholder
                    const createPlaceholder = (content) => {{
                        const placeholder = `___PROTECTED_${{placeholderIndex++}}___`;
                        protectedElements.push({{ placeholder: placeholder, content: content }});
                        return placeholder;
                    }};

                    // 1. Comments first (green like Power BI) - protect these from all other processing
                    highlighted = highlighted.replace(/(--[^\\n]*)/g, (match) =>
                        createPlaceholder('<span style="color: #008000; font-style: italic;">' + match + '</span>')
                    );
                    highlighted = highlighted.replace(/\\/\\*[\\s\\S]*?\\*\\//g, (match) =>
                        createPlaceholder('<span style="color: #008000; font-style: italic;">' + match + '</span>')
                    );

                    // 2. String literals (orange/amber like Power BI) - protect from keyword matching
                    highlighted = highlighted.replace(/"([^"]*)"/g, (match, p1) =>
                        createPlaceholder('<span style="color: #D83B01;">"' + p1 + '"</span>')
                    );

                    // 3. Table and column references [Table[Column]] (dark color) - protect from keyword matching
                    highlighted = highlighted.replace(/\\[([^\\]]+)\\]/g, (match, p1) =>
                        createPlaceholder('<span style="color: #0078D4; font-weight: 500;">[' + p1 + ']</span>')
                    );

                    // 4. DAX Keywords (purple like Power BI) - protect from further processing
                    const keywords = [
                        'VAR', 'RETURN', 'EVALUATE', 'DEFINE', 'MEASURE', 'COLUMN', 'TABLE',
                        'ORDER BY', 'ASC', 'DESC', 'IN', 'NOT', 'AND', 'OR', 'TRUE', 'FALSE',
                        'BLANK'
                    ];

                    keywords.forEach(keyword => {{
                        const regex = new RegExp('\\\\b(' + keyword + ')\\\\b', 'gi');
                        highlighted = highlighted.replace(regex, (match) =>
                            createPlaceholder('<span style="color: #AF00DB; font-weight: bold;">' + match + '</span>')
                        );
                    }});

                    // 5. DAX Functions (blue like Power BI)
                    const functions = [
                        'IF', 'SWITCH', 'IFERROR', 'ISBLANK', 'HASONEVALUE',
                        'CALCULATE', 'FILTER', 'ALL', 'ALLEXCEPT', 'ALLSELECTED', 'ALLNOBLANKROW',
                        'SUM', 'SUMX', 'AVERAGE', 'AVERAGEX', 'COUNT', 'COUNTX', 'COUNTA', 'COUNTAX',
                        'MIN', 'MINX', 'MAX', 'MAXX', 'RANKX', 'TOPN', 'DISTINCT', 'VALUES',
                        'RELATED', 'RELATEDTABLE', 'EARLIER', 'EARLIEST', 'LOOKUPVALUE',
                        'ADDCOLUMNS', 'SELECTCOLUMNS', 'SUMMARIZE', 'SUMMARIZECOLUMNS', 'GROUPBY',
                        'CONCATENATEX', 'PRODUCTX', 'DIVIDE', 'FORMAT', 'FIXED', 'CURRENCY',
                        'CALENDAR', 'CALENDARAUTO', 'DATE', 'DATEADD', 'DATESYTD', 'DATESMTD', 'DATESQTD',
                        'DATESBETWEEN', 'DATESINPERIOD', 'PREVIOUSMONTH', 'PREVIOUSQUARTER', 'PREVIOUSYEAR',
                        'PARALLELPERIOD', 'SAMEPERIODLASTYEAR', 'TOTALYTD', 'TOTALMTD', 'TOTALQTD',
                        'STARTOFMONTH', 'STARTOFQUARTER', 'STARTOFYEAR', 'ENDOFMONTH', 'ENDOFQUARTER', 'ENDOFYEAR',
                        'USERELATIONSHIP', 'CROSSFILTER', 'REMOVEFILTERS', 'KEEPFILTERS',
                        'HASONEFILTER', 'ISCROSSFILTERED', 'ISFILTERED', 'SELECTEDVALUE', 'SELECTEDVALUE',
                        'HASONEVALUE', 'FIRSTNONBLANK', 'LASTNONBLANK', 'FIRSTDATE', 'LASTDATE'
                    ];

                    functions.forEach(func => {{
                        const regex = new RegExp('\\\\b(' + func + ')\\\\s*\\\\(', 'gi');
                        highlighted = highlighted.replace(regex, (match) =>
                            createPlaceholder('<span style="color: #0078D4; font-weight: 600;">' + match.replace('(', '') + '</span>(')
                        );
                    }});

                    // 6. Variable names (after VAR keyword) - teal/cyan like Power BI
                    highlighted = highlighted.replace(/(<span[^>]*>VAR<\\/span>)\\s+([a-zA-Z_][a-zA-Z0-9_]*)/gi, (match, p1, p2) =>
                        createPlaceholder(p1 + ' <span style="color: #098658; font-weight: 600;">' + p2 + '</span>')
                    );

                    // 7. Numbers (teal like Power BI) - only match numbers outside of existing HTML tags
                    highlighted = highlighted.replace(/\\b(\\d+\\.?\\d*)\\b/g, '<span style="color: #098658;">$1</span>');

                    // Restore protected elements
                    protectedElements.reverse().forEach(item => {{
                        highlighted = highlighted.replace(item.placeholder, item.content);
                    }});

                    return highlighted;
                }},
                initGraph() {{
                    if (!this.modelData.relationships) return;

                    const svg = d3.select('#graph-svg');
                    const container = document.getElementById('graph-container');
                    const width = container.clientWidth;
                    const height = container.clientHeight;

                    svg.selectAll('*').remove();

                    // Add gradient definitions for different table types
                    const defs = svg.append('defs');

                    // Dimension table gradient (blue)
                    const dimGradient = defs.append('linearGradient')
                        .attr('id', 'dimGradient')
                        .attr('x1', '0%')
                        .attr('y1', '0%')
                        .attr('x2', '0%')
                        .attr('y2', '100%');
                    dimGradient.append('stop')
                        .attr('offset', '0%')
                        .attr('style', 'stop-color:#7D9AFF;stop-opacity:1');
                    dimGradient.append('stop')
                        .attr('offset', '100%')
                        .attr('style', 'stop-color:#5B7FFF;stop-opacity:1');

                    // Fact table gradient (orange/amber)
                    const factGradient = defs.append('linearGradient')
                        .attr('id', 'factGradient')
                        .attr('x1', '0%')
                        .attr('y1', '0%')
                        .attr('x2', '0%')
                        .attr('y2', '100%');
                    factGradient.append('stop')
                        .attr('offset', '0%')
                        .attr('style', 'stop-color:#FFA76F;stop-opacity:1');
                    factGradient.append('stop')
                        .attr('offset', '100%')
                        .attr('style', 'stop-color:#FF8C42;stop-opacity:1');

                    // Slicer table gradient (purple)
                    const slicerGradient = defs.append('linearGradient')
                        .attr('id', 'slicerGradient')
                        .attr('x1', '0%')
                        .attr('y1', '0%')
                        .attr('x2', '0%')
                        .attr('y2', '100%');
                    slicerGradient.append('stop')
                        .attr('offset', '0%')
                        .attr('style', 'stop-color:#B794F6;stop-opacity:1');
                    slicerGradient.append('stop')
                        .attr('offset', '100%')
                        .attr('style', 'stop-color:#9F7AEA;stop-opacity:1');

                    const g = svg.append('g');

                    // Zoom behavior
                    const zoom = d3.zoom()
                        .scaleExtent([0.1, 4])
                        .on('zoom', (event) => {{
                            g.attr('transform', event.transform);
                        }});

                    svg.call(zoom);

                    // Prepare data - filter by selected table if specified
                    let allNodes = (this.modelData.relationships.nodes || []);
                    let allEdges = (this.modelData.relationships.edges || []);

                    // Filter by table if selected
                    if (this.graphFilterTable) {{
                        // Get all tables connected to the selected table
                        const connectedTables = new Set([this.graphFilterTable]);
                        allEdges.forEach(e => {{
                            if (e.from === this.graphFilterTable) {{
                                connectedTables.add(e.to);
                            }}
                            if (e.to === this.graphFilterTable) {{
                                connectedTables.add(e.from);
                            }}
                        }});

                        // Filter nodes to only show connected tables
                        allNodes = allNodes.filter(n => connectedTables.has(n.id));

                        // Filter edges to only show relationships involving the selected table
                        allEdges = allEdges.filter(e =>
                            e.from === this.graphFilterTable || e.to === this.graphFilterTable
                        );
                    }}

                    // Helper function to determine table type based on naming convention
                    const getTableType = (tableName) => {{
                        const name = (tableName || '').toLowerCase().trim();
                        // Check for fact tables: f_, f<space>, or fact
                        if (name.startsWith('f_') || name.startsWith('f ') || name.startsWith('fact')) {{
                            return 'fact';
                        }}
                        // Check for slicer tables: s_, s<space>, or slicer
                        else if (name.startsWith('s_') || name.startsWith('s ') || name.startsWith('slicer')) {{
                            return 'slicer';
                        }}
                        // Everything else is dimension (including d_, d<space>, dim, etc.)
                        else {{
                            return 'dimension';
                        }}
                    }};

                    const nodes = allNodes.map(n => ({{
                        ...n,
                        x: width / 2 + (Math.random() - 0.5) * 200,
                        y: height / 2 + (Math.random() - 0.5) * 200,
                        tableType: getTableType(n.id)
                    }}));

                    let edges = allEdges.map(e => ({{
                        ...e,
                        source: e.from,
                        target: e.to
                    }}));

                    if (!this.showInactiveRelationships) {{
                        edges = edges.filter(e => e.active);
                    }}

                    // Apply layout based on selection
                    let simulation;
                    if (this.graphLayout === 'radial') {{
                        // Improved tiered radial layout - group by table type
                        const factTables = nodes.filter(n => n.tableType === 'fact');
                        const dimensionTables = nodes.filter(n => n.tableType === 'dimension');
                        const slicerTables = nodes.filter(n => n.tableType === 'slicer');
                        const otherTables = nodes.filter(n => !n.tableType || (n.tableType !== 'fact' && n.tableType !== 'dimension' && n.tableType !== 'slicer'));

                        const tiers = [
                            {{ nodes: factTables, radius: Math.min(width, height) / 6, color: 'fact' }},
                            {{ nodes: dimensionTables, radius: Math.min(width, height) / 3.5, color: 'dimension' }},
                            {{ nodes: slicerTables, radius: Math.min(width, height) / 2.5, color: 'slicer' }},
                            {{ nodes: otherTables, radius: Math.min(width, height) / 2, color: 'other' }}
                        ].filter(tier => tier.nodes.length > 0);

                        tiers.forEach(tier => {{
                            const angleStep = (2 * Math.PI) / Math.max(tier.nodes.length, 1);
                            tier.nodes.forEach((node, i) => {{
                                const angle = i * angleStep;
                                node.x = width / 2 + tier.radius * Math.cos(angle);
                                node.y = height / 2 + tier.radius * Math.sin(angle);
                                node.fx = node.x;
                                node.fy = node.y;
                            }});
                        }});

                        simulation = d3.forceSimulation(nodes)
                            .force('link', d3.forceLink(edges).id(d => d.id).distance(120))
                            .force('charge', d3.forceManyBody().strength(-80))
                            .force('collision', d3.forceCollide().radius(40));
                    }} else if (this.graphLayout === 'tree') {{
                        // D3 Tree Layout (NEW - Hierarchical tree structure)
                        this.renderTreeGraph(g, nodes, edges, width, height);
                        return; // Exit early - tree uses different rendering
                    }} else if (this.graphLayout === 'dagre') {{
                        // Dagre Layout (NEW - DAG layered layout)
                        this.renderDagreGraph(g, svg, nodes, edges, width, height);
                        return; // Exit early - dagre uses different rendering
                    }} else if (this.graphLayout === 'hierarchical') {{
                        // True hierarchical layout based on relationship depth
                        // Calculate depths for each node using BFS from fact tables
                        const nodeDepths = new Map();
                        const factNodes = nodes.filter(n => n.tableType === 'fact');

                        // If no fact tables, use nodes with most incoming connections
                        let startNodes = factNodes;
                        if (startNodes.length === 0) {{
                            const incomingCounts = new Map();
                            nodes.forEach(n => incomingCounts.set(n.id, 0));
                            edges.forEach(e => {{
                                incomingCounts.set(e.to, (incomingCounts.get(e.to) || 0) + 1);
                            }});
                            const maxIncoming = Math.max(...incomingCounts.values());
                            startNodes = nodes.filter(n => incomingCounts.get(n.id) === maxIncoming);
                            if (startNodes.length === 0) startNodes = [nodes[0]];
                        }}

                        // BFS to assign depths
                        const queue = startNodes.map(n => ({{ id: n.id, depth: 0 }}));
                        const visited = new Set(startNodes.map(n => n.id));

                        startNodes.forEach(n => nodeDepths.set(n.id, 0));

                        while (queue.length > 0) {{
                            const {{ id, depth }} = queue.shift();

                            // Find connected nodes through edges
                            edges.forEach(e => {{
                                if (e.from === id && !visited.has(e.to)) {{
                                    visited.add(e.to);
                                    nodeDepths.set(e.to, depth + 1);
                                    queue.push({{ id: e.to, depth: depth + 1 }});
                                }} else if (e.to === id && !visited.has(e.from)) {{
                                    visited.add(e.from);
                                    nodeDepths.set(e.from, depth + 1);
                                    queue.push({{ id: e.from, depth: depth + 1 }});
                                }}
                            }});
                        }}

                        // Assign depth to unvisited nodes
                        nodes.forEach(n => {{
                            if (!nodeDepths.has(n.id)) {{
                                nodeDepths.set(n.id, 99); // Put disconnected nodes at the end
                            }}
                        }});

                        // Group nodes by depth
                        const depthGroups = new Map();
                        nodes.forEach(n => {{
                            const depth = nodeDepths.get(n.id);
                            if (!depthGroups.has(depth)) {{
                                depthGroups.set(depth, []);
                            }}
                            depthGroups.get(depth).push(n);
                        }});

                        // Position nodes in layers
                        const depths = Array.from(depthGroups.keys()).sort((a, b) => a - b);
                        const layerHeight = height / (depths.length + 1);

                        depths.forEach((depth, layerIdx) => {{
                            const nodesInLayer = depthGroups.get(depth);
                            const nodeWidth = width / (nodesInLayer.length + 1);

                            nodesInLayer.forEach((node, nodeIdx) => {{
                                node.x = nodeWidth * (nodeIdx + 1);
                                node.y = layerHeight * (layerIdx + 1);
                            }});
                        }});

                        simulation = d3.forceSimulation(nodes)
                            .force('link', d3.forceLink(edges).id(d => d.id).distance(100))
                            .force('charge', d3.forceManyBody().strength(-300))
                            .force('collision', d3.forceCollide().radius(50))
                            .force('y', d3.forceY(d => {{
                                const depth = nodeDepths.get(d.id);
                                const layerIdx = depths.indexOf(depth);
                                return layerHeight * (layerIdx + 1);
                            }}).strength(0.8));
                    }} else {{
                        // Enhanced force-directed layout with better parameters for large graphs
                        const linkDistance = nodes.length > 50 ? 120 : 150;
                        const chargeStrength = nodes.length > 50 ? -800 : -500;
                        const collisionRadius = nodes.length > 50 ? 45 : 50;

                        simulation = d3.forceSimulation(nodes)
                            .force('link', d3.forceLink(edges).id(d => d.id).distance(linkDistance))
                            .force('charge', d3.forceManyBody().strength(chargeStrength))
                            .force('center', d3.forceCenter(width / 2, height / 2))
                            .force('collision', d3.forceCollide().radius(collisionRadius))
                            .force('x', d3.forceX(width / 2).strength(0.05))
                            .force('y', d3.forceY(height / 2).strength(0.05));
                    }}

                    this.graphSimulation = simulation;

                    // Create links
                    const link = g.append('g')
                        .selectAll('line')
                        .data(edges)
                        .join('line')
                        .attr('class', d => `graph-link ${{d.active ? 'active' : 'inactive'}}`)
                        .attr('stroke-width', 2)
                        .on('mouseover', function(event, d) {{
                            d3.select(this).classed('highlighted', true);

                            // Show tooltip
                            const tooltip = g.append('g')
                                .attr('class', 'tooltip')
                                .attr('transform', `translate(${{event.x}},${{event.y}})`);

                            tooltip.append('rect')
                                .attr('fill', 'white')
                                .attr('stroke', '#cbd5e1')
                                .attr('rx', 4)
                                .attr('x', -100)
                                .attr('y', -40)
                                .attr('width', 200)
                                .attr('height', 80);

                            tooltip.append('text')
                                .attr('y', -20)
                                .attr('text-anchor', 'middle')
                                .style('font-size', '12px')
                                .text(`${{d.from}} → ${{d.to}}`);

                            tooltip.append('text')
                                .attr('y', 0)
                                .attr('text-anchor', 'middle')
                                .style('font-size', '10px')
                                .style('fill', '#666')
                                .text(`${{d.from_column}} → ${{d.to_column}}`);

                            tooltip.append('text')
                                .attr('y', 20)
                                .attr('text-anchor', 'middle')
                                .style('font-size', '10px')
                                .text(`${{d.cardinality}} | ${{d.active ? 'Active' : 'Inactive'}}`);
                        }})
                        .on('mouseout', function() {{
                            d3.select(this).classed('highlighted', false);
                            g.selectAll('.tooltip').remove();
                        }});

                    // Create nodes
                    const node = g.append('g')
                        .selectAll('circle')
                        .data(nodes)
                        .join('circle')
                        .attr('class', 'graph-node')
                        .attr('r', d => 25 + Math.sqrt(d.row_count || 0) / 1000)
                        .attr('fill', d => {{
                            if (d.tableType === 'fact') return 'url(#factGradient)';
                            if (d.tableType === 'slicer') return 'url(#slicerGradient)';
                            return 'url(#dimGradient)';
                        }})
                        .attr('stroke', d => {{
                            if (d.tableType === 'fact') return '#E67E22';
                            if (d.tableType === 'slicer') return '#8B5CF6';
                            return '#4A6BEE';
                        }})
                        .attr('stroke-width', 2.5)
                        .style('cursor', 'pointer')
                        .call(d3.drag()
                            .on('start', (event, d) => {{
                                if (!event.active) simulation.alphaTarget(0.3).restart();
                                d.fx = d.x;
                                d.fy = d.y;
                            }})
                            .on('drag', (event, d) => {{
                                d.fx = event.x;
                                d.fy = event.y;
                            }})
                            .on('end', (event, d) => {{
                                if (!event.active) simulation.alphaTarget(0);
                                d.fx = null;
                                d.fy = null;
                            }})
                        )
                        .on('click', (event, d) => {{
                            this.selectedNode = d.id;
                            this.highlightConnections(d.id);
                        }});

                    // Create labels
                    const label = g.append('g')
                        .selectAll('text')
                        .data(nodes)
                        .join('text')
                        .text(d => d.label)
                        .attr('font-size', 12)
                        .attr('font-weight', 'bold')
                        .attr('text-anchor', 'middle')
                        .attr('dy', -30)
                        .style('pointer-events', 'none')
                        .style('fill', '#1e293b');

                    // Update positions
                    simulation.on('tick', () => {{
                        link
                            .attr('x1', d => d.source.x)
                            .attr('y1', d => d.source.y)
                            .attr('x2', d => d.target.x)
                            .attr('y2', d => d.target.y);

                        node
                            .attr('cx', d => d.x)
                            .attr('cy', d => d.y);

                        label
                            .attr('x', d => d.x)
                            .attr('y', d => d.y);
                    }});
                }},
                highlightConnections(nodeId) {{
                    const svg = d3.select('#graph-svg');

                    // Reset all
                    svg.selectAll('.graph-node').classed('highlighted', false).attr('opacity', 0.3);
                    svg.selectAll('.graph-link').attr('opacity', 0.1);

                    // Highlight selected node
                    svg.selectAll('.graph-node').filter(d => d.id === nodeId)
                        .classed('highlighted', true)
                        .attr('opacity', 1);

                    // Highlight connected nodes and links
                    const edges = this.modelData.relationships.edges || [];
                    const connectedNodes = new Set([nodeId]);

                    edges.forEach(edge => {{
                        if (edge.from === nodeId || edge.to === nodeId) {{
                            connectedNodes.add(edge.from);
                            connectedNodes.add(edge.to);
                        }}
                    }});

                    svg.selectAll('.graph-node').filter(d => connectedNodes.has(d.id))
                        .attr('opacity', 1);

                    svg.selectAll('.graph-link').filter(d =>
                        d.from === nodeId || d.to === nodeId
                    ).attr('opacity', 1).classed('highlighted', true);
                }},

                // NEW: D3 Tree Layout Renderer
                renderTreeGraph(g, nodes, edges, width, height) {{
                    const treeData = this.buildHierarchyForTree(nodes, edges);
                    const treeLayout = d3.tree()
                        .size([height - 100, width - 200])
                        .separation((a, b) => (a.parent === b.parent ? 1 : 1.5));

                    const root = d3.hierarchy(treeData);
                    const tree = treeLayout(root);

                    const treeG = g.append('g').attr('transform', 'translate(100, 50)');

                    // Draw links
                    treeG.selectAll('.link')
                        .data(tree.links())
                        .join('path')
                        .attr('class', 'tree-link')
                        .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x))
                        .attr('fill', 'none')
                        .attr('stroke', '#10b981')
                        .attr('stroke-width', 2)
                        .attr('opacity', 0.6);

                    // Draw nodes
                    const nodeGroup = treeG.selectAll('.node')
                        .data(tree.descendants())
                        .join('g')
                        .attr('class', 'graph-node')
                        .attr('transform', d => `translate(${{d.y}},${{d.x}})`)
                        .style('cursor', 'pointer')
                        .on('click', (event, d) => {{
                            this.selectedNode = d.data.id;
                            this.highlightConnections(d.data.id);
                        }});

                    nodeGroup.append('circle')
                        .attr('r', 8)
                        .attr('fill', d => {{
                            const node = nodes.find(n => n.id === d.data.id);
                            return node && node.tableType === 'fact' ? '#FF8C42' :
                                   node && node.tableType === 'slicer' ? '#9F7AEA' : '#5B7FFF';
                        }})
                        .attr('stroke', '#1f2937')
                        .attr('stroke-width', 2);

                    nodeGroup.append('text')
                        .attr('dy', -15)
                        .attr('text-anchor', 'middle')
                        .attr('fill', '#1f2937')
                        .style('font-size', '12px')
                        .style('font-weight', 'bold')
                        .text(d => d.data.label || d.data.id);
                }},

                buildHierarchyForTree(nodes, edges) {{
                    const hasIncoming = new Set(edges.map(e => e.to));
                    const roots = nodes.filter(n => !hasIncoming.has(n.id) || n.tableType === 'fact');

                    if (roots.length === 0 && nodes.length > 0) roots.push(nodes[0]);

                    const buildNode = (nodeId, visited = new Set()) => {{
                        if (visited.has(nodeId)) return null;
                        visited.add(nodeId);

                        const node = nodes.find(n => n.id === nodeId);
                        if (!node) return null;

                        const children = edges
                            .filter(e => e.from === nodeId)
                            .map(e => buildNode(e.to, visited))
                            .filter(c => c !== null);

                        return {{
                            id: nodeId,
                            label: node.label || nodeId,
                            children: children.length > 0 ? children : undefined
                        }};
                    }};

                    if (roots.length === 1) {{
                        return buildNode(roots[0].id);
                    }} else {{
                        return {{
                            id: '__root__',
                            label: 'Model',
                            children: roots.map(r => buildNode(r.id)).filter(c => c !== null)
                        }};
                    }}
                }},

                // NEW: Dagre Layout Renderer
                renderDagreGraph(g, svg, nodes, edges, width, height) {{
                    const dagreG = new dagre.graphlib.Graph();
                    dagreG.setGraph({{ rankdir: 'LR', nodesep: 70, ranksep: 100 }});
                    dagreG.setDefaultEdgeLabel(() => ({{}}));

                    nodes.forEach(node => {{
                        dagreG.setNode(node.id, {{ label: node.label || node.id, width: 120, height: 40 }});
                    }});

                    edges.forEach(edge => {{
                        dagreG.setEdge(edge.from, edge.to);
                    }});

                    dagre.layout(dagreG);

                    const dagreGroup = g.append('g').attr('transform', 'translate(20,20)');

                    // Add arrow marker
                    svg.select('defs').append('marker')
                        .attr('id', 'dagre-arrow')
                        .attr('viewBox', '-0 -5 10 10')
                        .attr('refX', 8)
                        .attr('refY', 0)
                        .attr('orient', 'auto')
                        .attr('markerWidth', 6)
                        .attr('markerHeight', 6)
                        .append('path')
                        .attr('d', 'M 0,-5 L 10,0 L 0,5')
                        .attr('fill', '#94a3b8');

                    // Draw edges
                    edges.forEach(edge => {{
                        const edgeData = dagreG.edge(edge.from, edge.to);
                        if (edgeData && edgeData.points) {{
                            dagreGroup.append('path')
                                .attr('d', d3.line()
                                    .x(d => d.x)
                                    .y(d => d.y)
                                    (edgeData.points))
                                .attr('fill', 'none')
                                .attr('stroke', edge.active ? '#10b981' : '#ef4444')
                                .attr('stroke-width', edge.active ? 3 : 2)
                                .attr('opacity', 0.6)
                                .attr('marker-end', 'url(#dagre-arrow)');
                        }}
                    }});

                    // Draw nodes
                    dagreG.nodes().forEach(v => {{
                        const node = dagreG.node(v);
                        const nodeData = nodes.find(n => n.id === v);

                        const nodeGroup = dagreGroup.append('g')
                            .attr('class', 'graph-node')
                            .attr('transform', `translate(${{node.x}},${{node.y}})`)
                            .style('cursor', 'pointer')
                            .on('click', () => {{
                                this.selectedNode = v;
                                this.highlightConnections(v);
                            }});

                        nodeGroup.append('rect')
                            .attr('x', -60)
                            .attr('y', -20)
                            .attr('width', 120)
                            .attr('height', 40)
                            .attr('rx', 5)
                            .attr('fill', nodeData && nodeData.tableType === 'fact' ? '#FF8C42' :
                                          nodeData && nodeData.tableType === 'slicer' ? '#9F7AEA' : '#5B7FFF')
                            .attr('stroke', '#1f2937')
                            .attr('stroke-width', 2);

                        nodeGroup.append('text')
                            .attr('text-anchor', 'middle')
                            .attr('dy', 5)
                            .attr('fill', 'white')
                            .style('font-size', '12px')
                            .style('font-weight', 'bold')
                            .text(node.label);
                    }});
                }},

                resetGraph() {{
                    this.selectedNode = null;
                    const svg = d3.select('#graph-svg');
                    svg.selectAll('.graph-node').classed('highlighted', false).attr('opacity', 1);
                    svg.selectAll('.graph-link').attr('opacity', 1).classed('highlighted', false);

                    if (this.graphSimulation) {{
                        this.graphSimulation.alpha(1).restart();
                    }}
                }},
                exportToCSV() {{
                    let data, filename;
                    if (this.activeTab === 'tables') {{
                        data = this.filteredTables.map(t => ({{
                            Name: t.name,
                            Rows: t.row_count,
                            Columns: t.statistics.column_count,
                            Measures: t.statistics.measure_count,
                            Relationships: t.statistics.relationship_count,
                            Hidden: t.hidden
                        }}));
                        filename = 'tables.csv';
                    }} else if (this.activeTab === 'measures') {{
                        data = this.filteredMeasures.map(m => ({{
                            Table: m.table,
                            Measure: m.name,
                            Folder: m.folder || '',
                            Dependencies: m.statistics.dependency_count,
                            UsedBy: m.statistics.usage_count,
                            Hidden: m.hidden
                        }}));
                        filename = 'measures.csv';
                    }} else {{
                        alert('Export not available for this view');
                        return;
                    }}

                    const headers = Object.keys(data[0]);
                    const csv = [
                        headers.join(','),
                        ...data.map(row => headers.map(h => `"${{row[h]}}"`).join(','))
                    ].join('\\n');

                    const blob = new Blob([csv], {{ type: 'text/csv' }});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    a.click();
                    URL.revokeObjectURL(url);
                }},
                exportToJSON() {{
                    const data = {{
                        tables: this.modelData.tables,
                        measures: this.modelData.measures,
                        relationships: this.modelData.relationships,
                        statistics: this.modelData.statistics,
                        exported_at: new Date().toISOString()
                    }};

                    const json = JSON.stringify(data, null, 2);
                    const blob = new Blob([json], {{ type: 'application/json' }});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'model_data.json';
                    a.click();
                    URL.revokeObjectURL(url);
                }},
                showColumnDetails(table, column) {{
                    this.selectedColumn = {{ table, column }};
                    this.showColumnModal = true;
                }},
                showRelationshipDetails(relationship) {{
                    this.selectedRelationship = relationship;
                    this.showRelationshipModal = true;
                }},
                handleKeydown(event) {{
                    // Forward slash: Focus search
                    if (event.key === '/' && !event.ctrlKey && !event.metaKey) {{
                        event.preventDefault();
                        document.querySelector('input[type="text"]')?.focus();
                    }}
                    // Ctrl/Cmd + K: Toggle command palette
                    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {{
                        event.preventDefault();
                        this.showCommandPalette = !this.showCommandPalette;
                    }}
                    // Escape: Close modals/clear search
                    if (event.key === 'Escape') {{
                        this.showColumnModal = false;
                        this.showRelationshipModal = false;
                        this.showCommandPalette = false;
                        if (this.searchQuery) {{
                            this.searchQuery = '';
                        }}
                    }}
                    // Arrow keys: Navigate tabs
                    if (event.altKey) {{
                        if (event.key === 'ArrowRight') {{
                            const tabs = ['tables', 'measures', 'relationships', 'statistics'];
                            const idx = tabs.indexOf(this.activeTab);
                            this.activeTab = tabs[(idx + 1) % tabs.length];
                        }} else if (event.key === 'ArrowLeft') {{
                            const tabs = ['tables', 'measures', 'relationships', 'statistics'];
                            const idx = tabs.indexOf(this.activeTab);
                            this.activeTab = tabs[(idx - 1 + tabs.length) % tabs.length];
                        }}
                    }}
                }},
                toggleDarkMode() {{
                    this.darkMode = !this.darkMode;
                    document.body.classList.toggle('dark-mode', this.darkMode);
                }},
                changeGraphLayout(layout) {{
                    this.graphLayout = layout;
                    if (this.activeTab === 'relationships') {{
                        this.$nextTick(() => {{
                            this.initGraph();
                        }});
                    }}
                }},
                
            mounted() {{
                console.log('Power BI Model Explorer loaded');
                console.log('Model data:', this.modelData);

                // Add keyboard event listener
                window.addEventListener('keydown', this.handleKeydown);
            }},
            beforeUnmount() {{
                // Clean up keyboard event listener
                window.removeEventListener('keydown', this.handleKeydown);
            }}
        }});

        // Mount with error handling
        try {{
            app.mount('#app');
            console.log('Vue app mounted successfully!');
        }} catch (error) {{
            console.error('ERROR mounting Vue app:', error);
            console.error('Stack:', error.stack);

            // Display error to user
            document.body.innerHTML = `
                <div style="padding: 40px; font-family: monospace; background: #fee; border: 2px solid #c00; margin: 20px;">
                    <h1 style="color: #c00;">Vue Mounting Error</h1>
                    <p><strong>Error:</strong> ${{error.message}}</p>
                    <pre style="background: #fff; padding: 10px; overflow: auto;">${{error.stack}}</pre>
                    <p>Please check the browser console for more details, or contact support with this error message.</p>
                </div>
            `;
        }}
    </script>
</body>
</html>"""


def generate_interactive_dependency_explorer(
    connection_state,
    output_dir: Optional[str] = None,
    include_hidden: bool = True,
    dependency_depth: int = 5,
) -> Tuple[Optional[str], List[str]]:
    """Generate interactive dependency explorer HTML.

    Args:
        connection_state: Active connection state
        output_dir: Output directory for HTML file
        include_hidden: Include hidden objects (default: True)
        dependency_depth: Maximum dependency depth

    Returns:
        Tuple of (html_file_path, list_of_warnings)

    Raises:
        TypeError: If parameter types are invalid
        ValueError: If parameter values are out of valid range
        FileNotFoundError: If output_dir doesn't exist and can't be created
    """
    # Input validation
    if not isinstance(include_hidden, bool):
        raise TypeError(f"include_hidden must be boolean, got {type(include_hidden).__name__}")

    if not isinstance(dependency_depth, int):
        raise TypeError(f"dependency_depth must be integer, got {type(dependency_depth).__name__}")

    if dependency_depth < 1 or dependency_depth > 10:
        raise ValueError(f"dependency_depth must be between 1 and 10, got {dependency_depth}")

    if output_dir is not None and not isinstance(output_dir, str):
        raise TypeError(f"output_dir must be string or None, got {type(output_dir).__name__}")

    try:
        explorer = InteractiveDependencyExplorer(connection_state)
        model_data = explorer.collect_all_model_data(include_hidden, dependency_depth)

        if not model_data.get("success"):
            return None, [model_data.get("error", "Unknown error")]

        return explorer.generate_html(model_data, output_dir)

    except Exception as e:
        logger.error(f"Error generating dependency explorer: {e}", exc_info=True)
        return None, [f"Failed to generate explorer: {str(e)}"]
