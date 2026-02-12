"""
PBIP Dependency Engine - Comprehensive dependency analysis for PBIP projects.

This module analyzes dependencies between measures, columns, and visuals, building
a complete dependency graph for the Power BI model and report.
"""

import logging
import re
from typing import Dict, List, Set, Tuple, Optional, Any

# Import existing DAX parser
try:
    from core.dax.dax_reference_parser import DaxReferenceIndex, parse_dax_references
    DAX_PARSER_AVAILABLE = True
except ImportError:
    DAX_PARSER_AVAILABLE = False
    logging.warning("DAX parser not available; dependency analysis will be limited")

logger = logging.getLogger(__name__)


class PbipDependencyEngine:
    """Comprehensive dependency analysis for PBIP projects."""

    def __init__(self, model_data: Dict, report_data: Optional[Dict] = None):
        """
        Initialize with parsed model and optional report data.

        Args:
            model_data: Parsed model data from TmdlModelAnalyzer
            report_data: Optional parsed report data from PbirReportAnalyzer
        """
        self.model = model_data
        self.report = report_data
        self.logger = logger

        # Dependency maps
        self.measure_to_measure: Dict[str, List[str]] = {}  # Forward: measure -> measures it depends on
        self.measure_to_measure_reverse: Dict[str, List[str]] = {}  # Reverse: measure -> measures that depend on it
        self.measure_to_column: Dict[str, List[str]] = {}
        self.measure_to_table: Dict[str, Set[str]] = {}  # Measure -> tables referenced at table level (e.g., REMOVEFILTERS('d Period'))
        self.column_to_measure: Dict[str, List[str]] = {}
        self.column_to_field_params: Dict[str, List[str]] = {}  # Column -> field parameter tables that reference it
        self.visual_dependencies: Dict[str, Dict[str, List[str]]] = {}
        self.page_dependencies: Dict[str, Dict[str, Any]] = {}
        self.filter_pane_data: Dict[str, Any] = {}  # Filter pane data at all levels

        # Build reference index for DAX parsing
        self.reference_index: Optional[DaxReferenceIndex] = None
        if DAX_PARSER_AVAILABLE:
            self._build_reference_index()

    def _build_reference_index(self) -> None:
        """Build reference index from model data for DAX parsing."""
        if not DAX_PARSER_AVAILABLE:
            return

        measure_rows = []
        column_rows = []

        # Extract measures
        for table in self.model.get("tables", []):
            table_name = table.get("name", "")

            for measure in table.get("measures", []):
                measure_rows.append({
                    "Table": table_name,
                    "Name": measure.get("name", "")
                })

            for column in table.get("columns", []):
                column_rows.append({
                    "Table": table_name,
                    "Name": column.get("name", "")
                })

        self.reference_index = DaxReferenceIndex(measure_rows, column_rows)

    def analyze_all_dependencies(self) -> Dict[str, Any]:
        """
        Perform comprehensive dependency analysis.

        Returns:
            Dictionary with all dependency information
        """
        self.logger.info("Starting comprehensive dependency analysis")

        # Analyze model dependencies
        self._analyze_measure_dependencies()
        self._analyze_column_usage()
        self._analyze_field_parameters()
        self._build_reverse_indices()

        # Analyze report dependencies (if report data available)
        if self.report:
            self._analyze_visual_dependencies()
            self._analyze_page_dependencies()
            self._analyze_filter_pane()

        # Find unused objects
        unused = self._find_unused_objects()

        result = {
            "measure_to_measure": self.measure_to_measure,
            "measure_to_measure_reverse": self.measure_to_measure_reverse,
            "measure_to_column": self.measure_to_column,
            "measure_to_table": {k: sorted(v) for k, v in self.measure_to_table.items()},
            "column_to_measure": self.column_to_measure,
            "column_to_field_params": self.column_to_field_params,
            "visual_dependencies": self.visual_dependencies,
            "page_dependencies": self.page_dependencies,
            "filter_pane_data": self.filter_pane_data,
            "unused_measures": unused["measures"],
            "unused_columns": unused["columns"],
            "summary": {
                "total_measures": self._count_measures(),
                "total_columns": self._count_columns(),
                "total_tables": len(self.model.get("tables", [])),
                "total_relationships": len(self.model.get("relationships", [])),
                "measures_with_dependencies": len(self.measure_to_measure),
                "columns_used_in_measures": len(self.column_to_measure),
                "unused_measures": len(unused["measures"]),
                "unused_columns": len(unused["columns"])
            }
        }

        if self.report:
            result["summary"]["total_pages"] = len(self.report.get("pages", []))
            result["summary"]["total_visuals"] = sum(
                len(p.get("visuals", []))
                for p in self.report.get("pages", [])
            )

        self.logger.info(
            f"Dependency analysis complete: "
            f"{result['summary']['total_measures']} measures, "
            f"{result['summary']['total_columns']} columns"
        )

        return result

    def _analyze_measure_dependencies(self) -> None:
        """Analyze measure-to-measure and measure-to-column dependencies."""
        if not DAX_PARSER_AVAILABLE:
            self.logger.warning(
                "DAX parser not available; skipping measure dependency analysis"
            )
            return

        # Build a lookup of measure names to their tables for resolving unqualified refs
        measure_name_to_tables = {}
        for table in self.model.get("tables", []):
            table_name = table.get("name", "")
            for measure in table.get("measures", []):
                meas_name = measure.get("name", "")
                if meas_name:
                    normalized_name = meas_name.lower().strip()
                    if normalized_name not in measure_name_to_tables:
                        measure_name_to_tables[normalized_name] = []
                    measure_name_to_tables[normalized_name].append(table_name)

        for table in self.model.get("tables", []):
            table_name = table.get("name", "")

            for measure in table.get("measures", []):
                measure_name = measure.get("name", "")
                measure_key = f"{table_name}[{measure_name}]"
                expression = measure.get("expression", "")

                if not expression:
                    continue

                # Parse DAX expression
                refs = parse_dax_references(expression, self.reference_index)

                # Extract measure dependencies
                measure_deps = []
                for ref_table, ref_measure in refs.get("measures", []):
                    if ref_measure:
                        # Handle empty table name by resolving from our lookup
                        if not ref_table:
                            normalized_ref = ref_measure.lower().strip()
                            tables = measure_name_to_tables.get(normalized_ref, [])
                            if tables:
                                # Use the first matching table (usually measures are in one table)
                                ref_table = tables[0]
                            else:
                                # Unknown measure - skip
                                continue

                        ref_key = f"{ref_table}[{ref_measure}]"
                        # Don't add self-references (case-insensitive)
                        if self._normalize_key(ref_key) != self._normalize_key(measure_key):
                            measure_deps.append(ref_key)

                if measure_deps:
                    self.measure_to_measure[measure_key] = measure_deps

                # Extract column dependencies
                column_deps = []
                for ref_table, ref_column in refs.get("columns", []):
                    if ref_table and ref_column:
                        ref_key = f"{ref_table}[{ref_column}]"
                        column_deps.append(ref_key)

                # Also track table-only references (e.g., REMOVEFILTERS('d Period'))
                # These mean ALL columns of the referenced table are implicitly used
                ref_tables = refs.get("tables", [])
                self._track_table_references(measure_key, ref_tables)

                if column_deps:
                    self.measure_to_column[measure_key] = column_deps

    def _track_table_references(self, measure_key: str, ref_tables: List[str]) -> None:
        """
        Track table-level references from DAX expressions.

        When a DAX function like REMOVEFILTERS('d Period') or ALL('Calendar')
        references a table without a specific column, it means the entire table
        is referenced. We track these so that all columns of the table are
        considered "used" in dependency analysis.
        """
        if not ref_tables:
            return

        # Build a set of known table names for validation
        known_tables = {
            t.get("name", "").lower(): t.get("name", "")
            for t in self.model.get("tables", [])
            if t.get("name", "")
        }

        for tbl in ref_tables:
            tbl_stripped = tbl.strip()
            if not tbl_stripped:
                continue
            # Validate against known tables
            canonical = known_tables.get(tbl_stripped.lower())
            if canonical:
                if measure_key not in self.measure_to_table:
                    self.measure_to_table[measure_key] = set()
                self.measure_to_table[measure_key].add(canonical)

    def _analyze_column_usage(self) -> None:
        """Analyze calculated column dependencies."""
        if not DAX_PARSER_AVAILABLE:
            return

        for table in self.model.get("tables", []):
            table_name = table.get("name", "")

            for column in table.get("columns", []):
                expression = column.get("expression", "")

                if not expression:
                    continue

                column_name = column.get("name", "")
                column_key = f"{table_name}[{column_name}]"

                # Parse expression
                refs = parse_dax_references(expression, self.reference_index)

                # Track column-to-column dependencies
                for ref_table, ref_column in refs.get("columns", []):
                    if ref_table and ref_column:
                        ref_key = f"{ref_table}[{ref_column}]"
                        if ref_key != column_key:
                            # Store in column_to_measure for now
                            # (could create separate column_to_column map)
                            if ref_key not in self.column_to_measure:
                                self.column_to_measure[ref_key] = []
                            if column_key not in self.column_to_measure[ref_key]:
                                self.column_to_measure[ref_key].append(column_key)

                # Also track table-level references in calculated column expressions
                ref_tables = refs.get("tables", [])
                if ref_tables:
                    # Use a pseudo-key for the calculated column as the "measure" reference
                    self._track_table_references(column_key, ref_tables)

    def _analyze_field_parameters(self) -> None:
        """Analyze field parameter tables and track which columns they reference."""
        for table in self.model.get("tables", []):
            table_name = table.get("name", "")
            partitions = table.get("partitions", [])

            for partition in partitions:
                source = partition.get("source", "")
                # Field parameters use NAMEOF('Table'[Column]) in their calculated table expression
                if source and "NAMEOF" in source:
                    # Parse NAMEOF references: NAMEOF('Table'[Column]) or NAMEOF("Table"[Column])
                    nameof_pattern = r"NAMEOF\(['\"]?([^'\"\[]+)['\"]?\[([^\]]+)\]\)"
                    matches = re.findall(nameof_pattern, source)

                    for table_ref, col_ref in matches:
                        column_key = f"{table_ref}[{col_ref}]"

                        # Add to column_to_field_params mapping
                        if column_key not in self.column_to_field_params:
                            self.column_to_field_params[column_key] = []
                        if table_name not in self.column_to_field_params[column_key]:
                            self.column_to_field_params[column_key].append(table_name)
                            self.logger.debug(
                                f"Field parameter '{table_name}' references column '{column_key}'"
                            )

    def _build_reverse_indices(self) -> None:
        """Build reverse indices for dependency lookups."""
        # Build measure_to_measure_reverse index (used by)
        for measure_key, deps in self.measure_to_measure.items():
            for dep_measure_key in deps:
                if dep_measure_key not in self.measure_to_measure_reverse:
                    self.measure_to_measure_reverse[dep_measure_key] = []
                if measure_key not in self.measure_to_measure_reverse[dep_measure_key]:
                    self.measure_to_measure_reverse[dep_measure_key].append(measure_key)

        # Build column_to_measure reverse index (from explicit column references)
        for measure_key, column_deps in self.measure_to_column.items():
            for column_key in column_deps:
                if column_key not in self.column_to_measure:
                    self.column_to_measure[column_key] = []
                if measure_key not in self.column_to_measure[column_key]:
                    self.column_to_measure[column_key].append(measure_key)

        # Build column_to_measure reverse index from table-level references
        # When a measure references REMOVEFILTERS('d Period'), ALL columns of 'd Period'
        # should appear in column_to_measure as being used by that measure
        for measure_key, table_set in self.measure_to_table.items():
            for table_name in table_set:
                # Find all columns in this table
                for table in self.model.get("tables", []):
                    if table.get("name", "") == table_name:
                        for column in table.get("columns", []):
                            col_name = column.get("name", "")
                            if col_name:
                                column_key = f"{table_name}[{col_name}]"
                                if column_key not in self.column_to_measure:
                                    self.column_to_measure[column_key] = []
                                if measure_key not in self.column_to_measure[column_key]:
                                    self.column_to_measure[column_key].append(measure_key)
                        break  # Found the table, no need to continue

    def _analyze_visual_dependencies(self) -> None:
        """Analyze visual-level field usage."""
        if not self.report:
            return

        for page in self.report.get("pages", []):
            page_name = page.get("display_name", page.get("id", ""))

            for visual in page.get("visuals", []):
                visual_id = visual.get("id", "")
                visual_type = visual.get("visual_type", "")
                visual_key = f"{page_name}/{visual_id}"

                fields = visual.get("fields", {})

                visual_deps = {
                    "page": page_name,
                    "visual_id": visual_id,
                    "visual_type": visual_type,
                    "measures": [],
                    "columns": [],
                    "tables": set()
                }

                # Extract columns
                for col in fields.get("columns", []):
                    table = col.get("table", "")
                    column = col.get("column", "")
                    if table and column:
                        col_key = f"{table}[{column}]"
                        visual_deps["columns"].append(col_key)
                        visual_deps["tables"].add(table)

                # Extract measures
                for meas in fields.get("measures", []):
                    table = meas.get("table", "")
                    measure = meas.get("measure", "")
                    if table and measure:
                        meas_key = f"{table}[{measure}]"
                        visual_deps["measures"].append(meas_key)
                        visual_deps["tables"].add(table)

                # Convert set to list for JSON serialization
                visual_deps["tables"] = list(visual_deps["tables"])

                self.visual_dependencies[visual_key] = visual_deps

    def _analyze_page_dependencies(self) -> None:
        """Analyze page-level dependencies (aggregate of all visuals)."""
        if not self.report:
            return

        for page in self.report.get("pages", []):
            page_name = page.get("display_name", page.get("id", ""))

            page_deps = {
                "measures": set(),
                "columns": set(),
                "tables": set(),
                "visual_count": len(page.get("visuals", [])),
                "filter_count": len(page.get("filters", []))
            }

            # Aggregate from visuals
            for visual in page.get("visuals", []):
                fields = visual.get("fields", {})

                for col in fields.get("columns", []):
                    table = col.get("table", "")
                    column = col.get("column", "")
                    if table and column:
                        page_deps["columns"].add(f"{table}[{column}]")
                        page_deps["tables"].add(table)

                for meas in fields.get("measures", []):
                    table = meas.get("table", "")
                    measure = meas.get("measure", "")
                    if table and measure:
                        page_deps["measures"].add(f"{table}[{measure}]")
                        page_deps["tables"].add(table)

            # Add page filters
            for filt in page.get("filters", []):
                field = filt.get("field", {})
                table = field.get("table", "")
                name = field.get("name", "")
                field_type = field.get("type", "")

                if table and name:
                    page_deps["tables"].add(table)
                    if field_type == "Column":
                        page_deps["columns"].add(f"{table}[{name}]")
                    elif field_type == "Measure":
                        page_deps["measures"].add(f"{table}[{name}]")

            # Convert sets to lists
            self.page_dependencies[page_name] = {
                "measures": list(page_deps["measures"]),
                "columns": list(page_deps["columns"]),
                "tables": list(page_deps["tables"]),
                "visual_count": page_deps["visual_count"],
                "filter_count": page_deps["filter_count"]
            }

    def _normalize_key(self, key: str) -> str:
        """
        Normalize a Table[Column] or Table[Measure] key for consistent comparison.
        Handles quoted table names, extra whitespace, and case differences.
        """
        if not key:
            return ""

        # Remove leading/trailing quotes from the entire key
        key = key.strip().strip("'\"")

        # Parse Table[Name] format
        if '[' in key and ']' in key:
            bracket_idx = key.index('[')
            table = key[:bracket_idx].strip().strip("'\"").lower()
            name = key[bracket_idx + 1:].rstrip(']').strip().lower()
            return f"{table}[{name}]"

        return key.lower()

    def _find_unused_objects(self) -> Dict[str, List[str]]:
        """Find measures and columns not used anywhere."""
        # Build set of used measures (normalized keys for comparison)
        used_measures_normalized = set()

        # Build a mapping from normalized key to original key
        all_measure_keys = {}  # normalized -> original
        all_column_keys = {}   # normalized -> original

        for table in self.model.get("tables", []):
            table_name = table.get("name", "")

            for measure in table.get("measures", []):
                measure_key = f"{table_name}[{measure.get('name', '')}]"
                normalized = self._normalize_key(measure_key)
                all_measure_keys[normalized] = measure_key

            for column in table.get("columns", []):
                column_name = column.get("name", "")
                column_key = f"{table_name}[{column_name}]"
                normalized = self._normalize_key(column_key)
                all_column_keys[normalized] = column_key

        # First, find measures directly used in visuals
        measures_in_visuals = set()
        if self.report:
            for visual_deps in self.visual_dependencies.values():
                for m in visual_deps.get("measures", []):
                    measures_in_visuals.add(self._normalize_key(m))

        # Also check page dependencies for measures in filters
        if self.report:
            for page_deps in self.page_dependencies.values():
                for m in page_deps.get("measures", []):
                    measures_in_visuals.add(self._normalize_key(m))

        # Check filter pane for measures (report-level, page-level, visual-level filters)
        if self.report and self.filter_pane_data:
            # Report filters
            for filt in self.filter_pane_data.get("report_filters", []):
                if filt.get("field_type") == "Measure":
                    field_key = filt.get("field_key", "")
                    if field_key:
                        measures_in_visuals.add(self._normalize_key(field_key))

            # Page filters
            for page_data in self.filter_pane_data.get("page_filters", {}).values():
                for filt in page_data.get("filters", []):
                    if filt.get("field_type") == "Measure":
                        field_key = filt.get("field_key", "")
                        if field_key:
                            measures_in_visuals.add(self._normalize_key(field_key))

            # Visual filters
            for visual_data in self.filter_pane_data.get("visual_filters", {}).values():
                for filt in visual_data.get("filters", []):
                    if filt.get("field_type") == "Measure":
                        field_key = filt.get("field_key", "")
                        if field_key:
                            measures_in_visuals.add(self._normalize_key(field_key))

        # Now recursively find all measures that these depend on (transitive closure)
        # If measure A is used in a visual and depends on measure B, then both A and B are used
        def add_dependencies_recursively(measure_key_normalized: str):
            """Recursively add a measure and all its dependencies to used_measures."""
            if measure_key_normalized in used_measures_normalized:
                return  # Already processed
            used_measures_normalized.add(measure_key_normalized)

            # Find the original key to look up dependencies
            # Check both normalized and original forms
            deps = []
            for orig_key, dep_list in self.measure_to_measure.items():
                if self._normalize_key(orig_key) == measure_key_normalized:
                    deps = dep_list
                    break

            for dep_key in deps:
                add_dependencies_recursively(self._normalize_key(dep_key))

        # Process all measures that are directly used in visuals
        for measure_key in measures_in_visuals:
            add_dependencies_recursively(measure_key)

        # ALSO mark as used any measure that is referenced by another used measure (transitive)
        # A measure is used if any measure that uses it is itself used
        changed = True
        while changed:
            changed = False
            for orig_key in self.measure_to_measure_reverse.keys():
                normalized = self._normalize_key(orig_key)
                if normalized not in used_measures_normalized:
                    # Check if any measure that uses this one is itself used
                    users = self.measure_to_measure_reverse.get(orig_key, [])
                    for user_key in users:
                        if self._normalize_key(user_key) in used_measures_normalized:
                            used_measures_normalized.add(normalized)
                            changed = True
                            break

        # Build set of used columns (normalized)
        used_columns_normalized = set()

        # Used in measures (from DAX expressions - explicit column references)
        for deps in self.measure_to_column.values():
            for d in deps:
                used_columns_normalized.add(self._normalize_key(d))

        # Used via table-level references in DAX (e.g., REMOVEFILTERS('d Period'), ALL('Calendar'))
        # When a measure references an entire table, ALL columns of that table are implicitly used
        tables_referenced_by_dax: Set[str] = set()
        for table_set in self.measure_to_table.values():
            tables_referenced_by_dax.update(table_set)

        if tables_referenced_by_dax:
            # Build normalized table name lookup
            tables_ref_lower = {t.lower() for t in tables_referenced_by_dax}
            for table in self.model.get("tables", []):
                table_name = table.get("name", "")
                if table_name.lower() in tables_ref_lower:
                    for column in table.get("columns", []):
                        col_name = column.get("name", "")
                        if col_name:
                            used_columns_normalized.add(
                                self._normalize_key(f"{table_name}[{col_name}]")
                            )

        # Used by other columns (calculated columns)
        for column_key in self.column_to_measure.keys():
            if self.column_to_measure[column_key]:  # If this column is referenced by any measure/column
                used_columns_normalized.add(self._normalize_key(column_key))

        # Used in relationships
        # TMDL parser stores from_column/to_column as full 'Table[Column]' references
        for rel in self.model.get("relationships", []):
            # Handle the full Table[Column] format from TMDL parser
            from_col = rel.get("from_column", "")
            to_col = rel.get("to_column", "")

            if from_col:
                used_columns_normalized.add(self._normalize_key(from_col))
            if to_col:
                used_columns_normalized.add(self._normalize_key(to_col))

            # Also handle legacy format with separate table/column fields
            from_table = rel.get("from_table", "")
            from_col_name = rel.get("from_column_name", "")
            to_table = rel.get("to_table", "")
            to_col_name = rel.get("to_column_name", "")

            if from_table and from_col_name:
                used_columns_normalized.add(self._normalize_key(f"{from_table}[{from_col_name}]"))
            if to_table and to_col_name:
                used_columns_normalized.add(self._normalize_key(f"{to_table}[{to_col_name}]"))

        # Used in visuals (directly in visual fields)
        if self.report:
            for visual_deps in self.visual_dependencies.values():
                for c in visual_deps.get("columns", []):
                    used_columns_normalized.add(self._normalize_key(c))

        # Check all filter pane usage for columns
        if self.report and self.filter_pane_data:
            # Report filters
            for filt in self.filter_pane_data.get("report_filters", []):
                if filt.get("field_type") == "Column":
                    field_key = filt.get("field_key", "")
                    if field_key:
                        used_columns_normalized.add(self._normalize_key(field_key))

            # Page filters
            for page_data in self.filter_pane_data.get("page_filters", {}).values():
                for filt in page_data.get("filters", []):
                    if filt.get("field_type") == "Column":
                        field_key = filt.get("field_key", "")
                        if field_key:
                            used_columns_normalized.add(self._normalize_key(field_key))

            # Visual filters
            for visual_data in self.filter_pane_data.get("visual_filters", {}).values():
                for filt in visual_data.get("filters", []):
                    if filt.get("field_type") == "Column":
                        field_key = filt.get("field_key", "")
                        if field_key:
                            used_columns_normalized.add(self._normalize_key(field_key))

        # Also check page dependencies filters (legacy format)
        if self.report:
            for page_deps in self.page_dependencies.values():
                for c in page_deps.get("columns", []):
                    used_columns_normalized.add(self._normalize_key(c))

        # Check field parameter tables (they reference columns via NAMEOF in partition source)
        for table in self.model.get("tables", []):
            partitions = table.get("partitions", [])
            for partition in partitions:
                source = partition.get("source", "")
                # Field parameters use NAMEOF('Table'[Column]) in their calculated table expression
                if source and "NAMEOF" in source:
                    # Parse NAMEOF references: NAMEOF('Table'[Column]) or NAMEOF("Table"[Column])
                    nameof_pattern = r"NAMEOF\(['\"]?([^'\"\[]+)['\"]?\[([^\]]+)\]\)"
                    matches = re.findall(nameof_pattern, source)
                    for table_ref, col_ref in matches:
                        column_key = f"{table_ref}[{col_ref}]"
                        used_columns_normalized.add(self._normalize_key(column_key))

        # Find unused by comparing normalized keys
        unused_measures = []
        unused_columns = []

        for normalized, original in all_measure_keys.items():
            if normalized not in used_measures_normalized:
                unused_measures.append(original)

        for normalized, original in all_column_keys.items():
            if normalized not in used_columns_normalized:
                unused_columns.append(original)

        return {
            "measures": unused_measures,
            "columns": unused_columns
        }

    def _count_measures(self) -> int:
        """Count total measures in model."""
        return sum(
            len(table.get("measures", []))
            for table in self.model.get("tables", [])
        )

    def _count_columns(self) -> int:
        """Count total columns in model."""
        return sum(
            len(table.get("columns", []))
            for table in self.model.get("tables", [])
        )

    def get_measure_impact(self, measure_key: str) -> Dict[str, Any]:
        """
        Calculate impact of a specific measure (what depends on it).

        Args:
            measure_key: Measure identifier (e.g., "Table[Measure]")

        Returns:
            Dictionary with impact analysis
        """
        impact = {
            "measure": measure_key,
            "used_by_measures": [],
            "used_in_visuals": [],
            "used_in_pages": set(),
            "total_impact": 0
        }

        # Find measures that depend on this one
        for meas_key, deps in self.measure_to_measure.items():
            if measure_key in deps:
                impact["used_by_measures"].append(meas_key)

        # Find visuals using this measure
        for visual_key, visual_deps in self.visual_dependencies.items():
            if measure_key in visual_deps.get("measures", []):
                impact["used_in_visuals"].append(visual_key)
                page = visual_deps.get("page", "")
                if page:
                    impact["used_in_pages"].add(page)

        impact["used_in_pages"] = list(impact["used_in_pages"])
        impact["total_impact"] = (
            len(impact["used_by_measures"]) + len(impact["used_in_visuals"])
        )

        return impact

    def calculate_dependency_depth(self, measure_key: str) -> int:
        """
        Calculate maximum dependency depth for a measure.

        Args:
            measure_key: Measure identifier

        Returns:
            Maximum depth (0 if no dependencies)
        """
        visited = set()

        def dfs(key: str, depth: int) -> int:
            if key in visited:
                return depth
            visited.add(key)

            deps = self.measure_to_measure.get(key, [])
            if not deps:
                return depth

            max_depth = depth
            for dep in deps:
                max_depth = max(max_depth, dfs(dep, depth + 1))

            return max_depth

        return dfs(measure_key, 0)

    def _analyze_filter_pane(self) -> None:
        """
        Analyze filter pane data at all levels: report, page, and visual.

        Collects filters from:
        - Report level (filters on all pages)
        - Page level (filters on specific pages)
        - Visual level (filters on individual visuals)
        """
        if not self.report:
            return

        self.filter_pane_data = {
            "report_filters": [],
            "page_filters": {},
            "visual_filters": {},
            "summary": {
                "total_report_filters": 0,
                "total_page_filters": 0,
                "total_visual_filters": 0,
                "pages_with_filters": 0,
                "visuals_with_filters": 0
            }
        }

        # Extract report-level filters (filters on all pages)
        report_info = self.report.get("report", {})
        report_filters = report_info.get("filters", [])
        for filt in report_filters:
            filter_entry = self._build_filter_entry(filt, "report", "All Pages")
            self.filter_pane_data["report_filters"].append(filter_entry)

        self.filter_pane_data["summary"]["total_report_filters"] = len(report_filters)

        # Extract page-level and visual-level filters
        pages_with_filters = 0
        visuals_with_filters = 0
        total_page_filters = 0
        total_visual_filters = 0

        for page in self.report.get("pages", []):
            page_name = page.get("display_name", page.get("id", ""))
            page_id = page.get("id", "")

            # Page filters
            page_filters = page.get("filters", [])
            if page_filters:
                pages_with_filters += 1
                total_page_filters += len(page_filters)

                self.filter_pane_data["page_filters"][page_name] = {
                    "page_id": page_id,
                    "page_name": page_name,
                    "filters": []
                }

                for filt in page_filters:
                    filter_entry = self._build_filter_entry(filt, "page", page_name)
                    self.filter_pane_data["page_filters"][page_name]["filters"].append(filter_entry)

            # Visual filters
            for visual in page.get("visuals", []):
                visual_id = visual.get("id", "")
                visual_type = visual.get("visual_type", "")
                visual_name = visual.get("visual_name") or visual.get("title") or visual_type
                visual_filters = visual.get("filters", [])

                if visual_filters:
                    visuals_with_filters += 1
                    total_visual_filters += len(visual_filters)

                    visual_key = f"{page_name}/{visual_id}"
                    self.filter_pane_data["visual_filters"][visual_key] = {
                        "visual_id": visual_id,
                        "visual_type": visual_type,
                        "visual_name": visual_name,
                        "page_name": page_name,
                        "filters": []
                    }

                    for filt in visual_filters:
                        filter_entry = self._build_filter_entry(filt, "visual", visual_key)
                        self.filter_pane_data["visual_filters"][visual_key]["filters"].append(filter_entry)

        self.filter_pane_data["summary"]["total_page_filters"] = total_page_filters
        self.filter_pane_data["summary"]["total_visual_filters"] = total_visual_filters
        self.filter_pane_data["summary"]["pages_with_filters"] = pages_with_filters
        self.filter_pane_data["summary"]["visuals_with_filters"] = visuals_with_filters

        self.logger.info(
            f"Filter pane analysis: {len(report_filters)} report filters, "
            f"{total_page_filters} page filters, {total_visual_filters} visual filters"
        )

    def _build_filter_entry(self, filt: Dict, level: str, context: str) -> Dict[str, Any]:
        """
        Build a standardized filter entry from raw filter data.

        Args:
            filt: Raw filter dictionary
            level: Filter level (report, page, visual)
            context: Context info (page name, visual key, etc.)

        Returns:
            Standardized filter entry dictionary
        """
        field = filt.get("field", {})
        field_type = field.get("type", "Unknown")
        table = field.get("table", "")
        name = field.get("name", "")

        # Build field key
        field_key = f"{table}[{name}]" if table and name else ""

        # Extract filter values if available (from report analyzer)
        filter_values_data = filt.get("filter_values", {})
        filter_values = filter_values_data.get("values", []) if filter_values_data else []
        condition_type = filter_values_data.get("condition_type") if filter_values_data else None
        has_values = filter_values_data.get("has_values", False) if filter_values_data else False

        return {
            "name": filt.get("name", ""),
            "field_key": field_key,
            "field_type": field_type,
            "table": table,
            "field_name": name,
            "how_created": filt.get("how_created", ""),
            "filter_type": filt.get("filter_type", filt.get("type", "")),
            "level": level,
            "context": context,
            "filter_values": filter_values,
            "condition_type": condition_type,
            "has_values": has_values
        }
