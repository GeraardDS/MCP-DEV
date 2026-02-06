"""
Hybrid Reader - Read and analyze hybrid analysis packages

Provides efficient reading of hybrid analysis packages with automatic
multi-part file reassembly and intelligent caching.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from core.model.tmdl_parser import TMDLParser
from core.utilities.json_utils import load_json

logger = logging.getLogger(__name__)


class HybridReader:
    """Read and analyze hybrid analysis package"""

    def __init__(self, analysis_path: str):
        """
        Initialize hybrid reader

        Args:
            analysis_path: Path to exported analysis folder
        """
        self.analysis_path = Path(analysis_path)
        self.analysis_dir = self.analysis_path / "analysis"
        self.tmdl_dir = self.analysis_path / "tmdl"
        self.sample_data_dir = self.analysis_path / "sample_data"

        # Validate structure
        if not self.analysis_path.exists():
            raise ValueError(f"Analysis path not found: {analysis_path}")

        # Detect format type
        test_metadata_path = self.analysis_path / "test_metadata.json"
        if test_metadata_path.exists():
            # test_metadata_extraction format
            self.format_type = "test_metadata"
            logger.info(f"Detected test_metadata format at {analysis_path}")
        elif self.analysis_dir.exists():
            # Full hybrid analysis format
            self.format_type = "hybrid_analysis"
            logger.info(f"Detected hybrid_analysis format at {analysis_path}")
        else:
            raise ValueError(f"Invalid analysis structure - expected either test_metadata.json or analysis/ folder at {analysis_path}")

        # Cache for loaded files (bounded by known file types)
        self._cache = {}
        # Known cache keys: metadata, catalog, measures, dependencies,
        # relationships, unused_columns, report_dependencies
        self._max_cache_keys = 10

    def read_metadata(self) -> Dict[str, Any]:
        """
        Read metadata.json (supports both formats)

        Returns:
            Metadata dictionary (with file paths sanitized)
        """
        if "metadata" not in self._cache:
            if self.format_type == "test_metadata":
                # Read test_metadata.json
                metadata_path = self.analysis_path / "test_metadata.json"
                self._cache["metadata"] = self._read_json(metadata_path)
            else:
                # Read analysis/metadata.json
                metadata_path = self.analysis_dir / "metadata.json"
                self._cache["metadata"] = self._read_json(metadata_path)

        # Sanitize file paths to prevent Claude from prompting to copy files
        return self._sanitize_file_paths(self._cache["metadata"])

    def read_catalog(self, object_filter: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Read catalog.json (with automatic multi-part reassembly)
        Note: Measures are now in separate measures.json file
        For test_metadata format, returns minimal catalog with table names and row counts

        Args:
            object_filter: Optional filter for selective loading

        Returns:
            Catalog dictionary (without measures - use read_measures() for measures)
        """
        if "catalog" not in self._cache:
            if self.format_type == "test_metadata":
                # Build minimal catalog from test_metadata.json
                metadata = self.read_metadata()
                row_counts_data = metadata.get("row_counts", {})

                # Create minimal catalog with table info from by_table array
                tables = []
                by_table = row_counts_data.get("by_table", [])
                for table_info in by_table:
                    tables.append({
                        "name": table_info.get("table", ""),
                        "row_count": table_info.get("row_count", 0),
                        "type": "table"
                    })

                # Extract counts from nested structure
                statistics = metadata.get("statistics", {})
                row_counts_data = metadata.get("row_counts", {})

                total_columns = statistics.get("columns", {}).get("total", 0)
                total_rows = row_counts_data.get("total_rows", 0)

                self._cache["catalog"] = {
                    "tables": tables,
                    "columns": [],   # Not available in test_metadata
                    "summary": {
                        "total_tables": len(tables),
                        "total_columns": total_columns,
                        "total_rows": total_rows,
                        "note": "Limited catalog from test_metadata format - only table names and row counts available. Measures are in separate measures.json file."
                    }
                }
            else:
                # Full hybrid analysis format
                catalog_path = self.analysis_dir / "catalog.json"
                manifest_path = self.analysis_dir / "catalog.manifest.json"

                if catalog_path.exists():
                    # Single file
                    self._cache["catalog"] = self._read_json(catalog_path)
                elif manifest_path.exists():
                    # Multi-part file - reassemble
                    self._cache["catalog"] = self._reassemble_multipart("catalog")
                else:
                    raise ValueError("Catalog file not found (neither single file nor manifest)")

        # Apply filter if provided
        catalog = self._cache["catalog"]
        if object_filter:
            catalog = self._filter_catalog(catalog, object_filter)

        # Sanitize file paths to prevent Claude from prompting to copy files
        return self._sanitize_file_paths(catalog)

    def read_measures(self) -> Dict[str, Any]:
        """
        Read measures.json (with automatic multi-part reassembly)
        For test_metadata format, returns empty measures list

        Returns:
            Measures dictionary with 'measures' list and 'total_count'
        """
        if "measures" not in self._cache:
            if self.format_type == "test_metadata":
                # test_metadata format doesn't include separate measures file
                metadata = self.read_metadata()
                statistics = metadata.get("statistics", {})
                total_measures = statistics.get("measures", {}).get("total", 0)

                self._cache["measures"] = {
                    "measures": [],
                    "total_count": total_measures,
                    "note": "Measures list not available in test_metadata format"
                }
            else:
                # Full hybrid analysis format
                measures_path = self.analysis_dir / "measures.json"
                manifest_path = self.analysis_dir / "measures.manifest.json"

                if measures_path.exists():
                    # Single file
                    self._cache["measures"] = self._read_json(measures_path)
                elif manifest_path.exists():
                    # Multi-part file - reassemble
                    self._cache["measures"] = self._reassemble_multipart("measures")
                else:
                    raise ValueError("Measures file not found (neither single file nor manifest)")

        return self._cache["measures"]

    def read_dependencies(self) -> Dict[str, Any]:
        """
        Read dependencies.json (with automatic multi-part reassembly)
        For test_metadata format, returns empty dependencies

        Returns:
            Dependencies dictionary
        """
        if "dependencies" not in self._cache:
            if self.format_type == "test_metadata":
                # test_metadata format doesn't include dependencies
                self._cache["dependencies"] = {
                    "dependencies": [],
                    "note": "Dependencies not available in test_metadata format"
                }
            else:
                # Full hybrid analysis format
                dependencies_path = self.analysis_dir / "dependencies.json"
                manifest_path = self.analysis_dir / "dependencies.manifest.json"

                if dependencies_path.exists():
                    # Single file
                    self._cache["dependencies"] = self._read_json(dependencies_path)
                elif manifest_path.exists():
                    # Multi-part file - reassemble
                    self._cache["dependencies"] = self._reassemble_multipart("dependencies")
                else:
                    raise ValueError("Dependencies file not found (neither single file nor manifest)")

        return self._cache["dependencies"]

    def read_relationships(self) -> Dict[str, Any]:
        """
        Read relationships.json
        For test_metadata format, attempts to read from TMDL fallback

        Returns:
            Relationships dictionary with 'relationships' list and 'summary'
        """
        if "relationships" not in self._cache:
            if self.format_type == "test_metadata":
                # test_metadata format doesn't include relationships.json, try TMDL fallback
                logger.debug("test_metadata format - attempting TMDL fallback for relationships")
                relationships_list = self.get_relationships_from_tmdl()

                # Calculate summary
                active_count = sum(1 for r in relationships_list if r.get('isActive', True))
                inactive_count = len(relationships_list) - active_count
                bidirectional_count = sum(1 for r in relationships_list if r.get('crossFilteringBehavior') == 'BothDirections')
                many_to_many_count = sum(1 for r in relationships_list if r.get('cardinality') == 'ManyToMany')

                self._cache["relationships"] = {
                    "relationships": relationships_list,
                    "total_count": len(relationships_list),
                    "summary": {
                        "total": len(relationships_list),
                        "active": active_count,
                        "inactive": inactive_count,
                        "bidirectional": bidirectional_count,
                        "many_to_many": many_to_many_count
                    },
                    "note": "Relationships parsed from TMDL (test_metadata format)"
                }
            else:
                # Full hybrid analysis format
                relationships_path = self.analysis_dir / "relationships.json"

                if relationships_path.exists():
                    # Read from JSON file
                    self._cache["relationships"] = self._read_json(relationships_path)
                    logger.debug(f"Loaded relationships from {relationships_path}")
                else:
                    # Fallback to TMDL if JSON doesn't exist
                    logger.warning("relationships.json not found, falling back to TMDL parsing")
                    relationships_list = self.get_relationships_from_tmdl()

                    # Calculate summary
                    active_count = sum(1 for r in relationships_list if r.get('isActive', True))
                    inactive_count = len(relationships_list) - active_count
                    bidirectional_count = sum(1 for r in relationships_list if r.get('crossFilteringBehavior') == 'BothDirections')
                    many_to_many_count = sum(1 for r in relationships_list if r.get('cardinality') == 'ManyToMany')

                    self._cache["relationships"] = {
                        "relationships": relationships_list,
                        "total_count": len(relationships_list),
                        "summary": {
                            "total": len(relationships_list),
                            "active": active_count,
                            "inactive": inactive_count,
                            "bidirectional": bidirectional_count,
                            "many_to_many": many_to_many_count
                        },
                        "note": "Relationships parsed from TMDL (fallback)"
                    }

        return self._cache["relationships"]

    def read_unused_columns(self) -> Dict[str, Any]:
        """
        Read unused_columns.json

        Returns:
            Unused columns dictionary with 'summary', 'unused_columns', and 'unused_by_table'
        """
        if "unused_columns" not in self._cache:
            if self.format_type == "test_metadata":
                # Not available in test_metadata format
                self._cache["unused_columns"] = {
                    "summary": {
                        "total_unused_columns": 0,
                        "total_columns": 0,
                        "unused_percentage": 0.0
                    },
                    "unused_columns": [],
                    "unused_by_table": {},
                    "note": "Unused columns not available in test_metadata format"
                }
            else:
                # Full hybrid analysis format
                unused_columns_path = self.analysis_dir / "unused_columns.json"

                if unused_columns_path.exists():
                    # Read from JSON file
                    self._cache["unused_columns"] = self._read_json(unused_columns_path)
                    logger.debug(f"Loaded unused_columns from {unused_columns_path}")
                else:
                    # File doesn't exist
                    logger.warning("unused_columns.json not found - may not have been generated during export")
                    self._cache["unused_columns"] = {
                        "summary": {
                            "total_unused_columns": 0,
                            "total_columns": 0,
                            "unused_percentage": 0.0
                        },
                        "unused_columns": [],
                        "unused_by_table": {},
                        "note": "unused_columns.json not found - ensure export was run with dependency analysis enabled"
                    }

        return self._cache["unused_columns"]

    def read_report_dependencies(self) -> Dict[str, Any]:
        """
        Read report_dependencies.json (visual-level dependencies)

        Returns:
            Report dependencies dictionary with 'summary', 'visual_dependencies', 'visuals_by_page', and 'page_summaries'
        """
        if "report_dependencies" not in self._cache:
            if self.format_type == "test_metadata":
                # Not available in test_metadata format
                self._cache["report_dependencies"] = {
                    "summary": {
                        "total_pages": 0,
                        "total_visuals": 0
                    },
                    "visual_dependencies": [],
                    "visuals_by_page": {},
                    "page_summaries": {},
                    "note": "Report dependencies not available in test_metadata format"
                }
            else:
                # Full hybrid analysis format
                report_deps_path = self.analysis_dir / "report_dependencies.json"

                if report_deps_path.exists():
                    # Check if it's a multipart file
                    manifest_path = self.analysis_dir / "report_dependencies.manifest.json"
                    if manifest_path.exists():
                        # Read and reassemble multipart file
                        self._cache["report_dependencies"] = self._reassemble_multipart("report_dependencies")
                        logger.debug(f"Loaded report_dependencies from multipart files")
                    else:
                        # Single file
                        self._cache["report_dependencies"] = self._read_json(report_deps_path)
                        logger.debug(f"Loaded report_dependencies from {report_deps_path}")
                else:
                    # File doesn't exist
                    logger.warning("report_dependencies.json not found - may not have been generated during export")
                    self._cache["report_dependencies"] = {
                        "summary": {
                            "total_pages": 0,
                            "total_visuals": 0
                        },
                        "visual_dependencies": [],
                        "visuals_by_page": {},
                        "page_summaries": {},
                        "note": "report_dependencies.json not found - ensure export was run with a report.pbir file"
                    }

        return self._cache["report_dependencies"]

    def read_tmdl_file(self, relative_path: str) -> str:
        """
        Read TMDL file content
        Not available for test_metadata format

        Args:
            relative_path: Relative path from tmdl directory (e.g., "tables/DimDate.tmdl")

        Returns:
            TMDL file content
        """
        if self.format_type == "test_metadata":
            raise ValueError("TMDL files not available in test_metadata format. Use full hybrid analysis export for TMDL access.")

        tmdl_path = (self.tmdl_dir / relative_path).resolve()
        # Prevent path traversal attacks
        tmdl_dir_resolved = self.tmdl_dir.resolve()
        if not str(tmdl_path).startswith(str(tmdl_dir_resolved)):
            raise ValueError(f"Path traversal detected: {relative_path}")
        if not tmdl_path.exists():
            raise ValueError(f"TMDL file not found: {relative_path}")

        with open(tmdl_path, 'r', encoding='utf-8') as f:
            return f.read()

    def list_sample_data_tables(self) -> List[str]:
        """
        List tables with available sample data (parquet files including multi-part)

        Returns:
            List of table names with sample data
        """
        if not self.sample_data_dir.exists():
            return []

        # Find all .parquet files in sample_data directory
        parquet_files = list(self.sample_data_dir.glob("*.parquet"))

        # Extract unique table names (handle multi-part files like table_name_part0.parquet)
        table_names = set()
        for f in parquet_files:
            stem = f.stem
            # Remove _partN suffix if present
            if "_part" in stem:
                # Extract table name before _part
                table_name = stem.rsplit("_part", 1)[0]
                table_names.add(table_name)
            else:
                table_names.add(stem)

        return sorted(list(table_names))

    def read_sample_data(self, table_name: str, max_rows: int = 100) -> Optional[Dict[str, Any]]:
        """
        Read sample data for table (parquet file or multi-part parquet files)

        Args:
            table_name: Table name
            max_rows: Maximum rows to return (default: 100)

        Returns:
            Sample data as dictionary or None if not available
        """
        if not self.sample_data_dir.exists():
            return None

        try:
            import polars as pl
        except ImportError:
            logger.warning("Polars not available, cannot read sample data")
            return None

        # Check for single file first
        parquet_path = self.sample_data_dir / f"{table_name}.parquet"
        if parquet_path.exists():
            try:
                df = pl.read_parquet(parquet_path)
                return {
                    "columns": df.columns,
                    "row_count": len(df),
                    "data": df.to_dicts()[:max_rows],
                    "is_multipart": False
                }
            except Exception as e:
                logger.error(f"Error reading sample data for {table_name}: {e}")
                return None

        # Check for multi-part files (table_name_part0.parquet, table_name_part1.parquet, etc.)
        part_files = sorted(self.sample_data_dir.glob(f"{table_name}_part*.parquet"))
        if not part_files:
            return None

        try:
            # Read and concatenate all parts
            logger.debug(f"Reading {len(part_files)} parts for table '{table_name}'")
            dfs = []
            for part_file in part_files:
                df_part = pl.read_parquet(part_file)
                dfs.append(df_part)

            # Concatenate all parts
            df = pl.concat(dfs)

            return {
                "columns": df.columns,
                "row_count": len(df),
                "data": df.to_dicts()[:max_rows],
                "is_multipart": True,
                "part_count": len(part_files)
            }
        except Exception as e:
            logger.error(f"Error reading multi-part sample data for {table_name}: {e}")
            return None

    def find_objects(
        self,
        object_type: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Find objects matching filters

        Args:
            object_type: "tables" | "measures" | "relationships" | "roles"
            filters: Optional filters (name_pattern, folder, etc.)

        Returns:
            List of matching objects
        """
        if object_type == "tables":
            catalog = self.read_catalog()
            objects = catalog.get("tables", [])
        elif object_type == "measures":
            measures_data = self.read_measures()
            objects = measures_data.get("measures", [])
        elif object_type == "roles":
            catalog = self.read_catalog()
            objects = catalog.get("roles", [])
        else:
            return []

        # Apply filters
        if filters:
            objects = self._apply_filters(objects, filters)

        return objects

    def get_object_definition(
        self,
        object_name: str,
        object_type: str
    ) -> Dict[str, Any]:
        """
        Get full TMDL definition for an object with parsed DAX and metadata
        Supports both exact name match and pattern matching

        Args:
            object_name: Object name or pattern (e.g., "base.*scenario" for pattern matching)
            object_type: "table" | "measure" | "role"

        Returns:
            Object definition with TMDL content and parsed DAX
        """
        if object_type == "measure":
            # Detect if this is a pattern (contains regex special chars)
            import re
            is_pattern = bool(re.search(r'[.*+?[\]{}()\\|^$]', object_name))

            # Try exact match first
            measure_def = self.get_measure_from_tmdl(object_name, use_pattern=False)

            # If not found and looks like it might be a search query, try pattern matching
            if not measure_def and (is_pattern or ' ' in object_name or '-' in object_name):
                logger.info(f"Exact match failed, trying pattern search for: {object_name}")
                # Convert friendly search terms to regex patterns
                search_pattern = object_name
                # Replace spaces and hyphens with flexible patterns
                search_pattern = search_pattern.replace(' ', '[-_ ]?')
                search_pattern = search_pattern.replace('-', '[-_ ]?')
                measure_def = self.get_measure_from_tmdl(search_pattern, use_pattern=True)

            if measure_def:
                actual_name = measure_def.get("name", object_name)
                return {
                    "name": actual_name,
                    "type": "measure",
                    "table": measure_def.get("table"),
                    "dax_expression": measure_def.get("expression"),
                    "description": measure_def.get("description"),
                    "display_folder": measure_def.get("displayFolder"),
                    "format_string": measure_def.get("formatString"),
                    "is_hidden": measure_def.get("isHidden"),
                    "source": "tmdl_parsed",
                    "search_query": object_name if actual_name != object_name else None
                }

        # Fallback to catalog-based lookup
        catalog = self.read_catalog()

        if object_type == "table":
            tables = catalog.get("tables", [])
            for table in tables:
                if table["name"] == object_name:
                    tmdl_path = table.get("tmdl_path", "").replace("tmdl/", "")
                    if tmdl_path and self.tmdl_dir.exists():
                        tmdl_content = self.read_tmdl_file(tmdl_path)
                        # Parse table TMDL
                        parsed = TMDLParser.parse_table_metadata(tmdl_content)
                        columns = TMDLParser.parse_all_columns(tmdl_content)
                        measures = TMDLParser.parse_all_measures(tmdl_content)

                        return {
                            "name": object_name,
                            "type": "table",
                            "metadata": table,
                            "parsed_metadata": parsed,
                            "columns": columns,
                            "measures": measures,
                            "tmdl": tmdl_content
                        }
                    else:
                        return {
                            "name": object_name,
                            "type": "table",
                            "metadata": table,
                            "note": "TMDL not available in test_metadata format"
                        }

        elif object_type == "measure":
            measures_data = self.read_measures()
            measures = measures_data.get("measures", [])
            for measure in measures:
                if measure["name"] == object_name:
                    return {
                        "name": object_name,
                        "type": "measure",
                        "metadata": measure,
                        "note": "Measure found in measures.json but TMDL parsing failed"
                    }

        raise ValueError(f"{object_type} '{object_name}' not found")

    def analyze_dependencies(
        self,
        object_name: str,
        direction: str = "both"
    ) -> Dict[str, Any]:
        """
        Analyze dependencies for an object

        Args:
            object_name: Object name (table, measure, column)
                        For measures, can be with or without brackets: "MeasureName" or "[MeasureName]"
            direction: "dependencies" | "referenced_by" | "both"

        Returns:
            Dependency information
        """
        dependencies = self.read_dependencies()

        # Normalize object name - try both with and without brackets for measures
        search_names = [object_name]

        # If it's not already bracketed, add bracketed version
        if not object_name.startswith('['):
            search_names.append(f"[{object_name}]")
        # If it's bracketed, also try without brackets
        if object_name.startswith('[') and object_name.endswith(']'):
            search_names.append(object_name[1:-1])

        # Search in measures, columns, tables
        for category in ["measures", "columns", "tables"]:
            category_data = dependencies.get(category, {})

            # Try all search name variations
            for search_name in search_names:
                if search_name in category_data:
                    dep_info = category_data[search_name]

                    result = {
                        "object": search_name,  # Return the actual key found
                        "object_requested": object_name,  # Original requested name
                        "category": category
                    }

                    if direction in ["dependencies", "both"]:
                        result["dependencies"] = dep_info.get("dependencies", {})

                    if direction in ["referenced_by", "both"]:
                        result["referenced_by"] = dep_info.get("referenced_by", {})

                    return result

        return {
            "object": object_name,
            "found": False,
            "message": f"Object '{object_name}' not found in dependencies (searched: {', '.join(search_names)})"
        }

    def _read_json(self, path: Path) -> Dict[str, Any]:
        """Read JSON file using centralized JSON utility with orjson optimization"""
        return load_json(path)

    def _reassemble_multipart(self, file_type: str) -> Dict[str, Any]:
        """
        Reassemble multi-part file

        Args:
            file_type: "catalog", "measures", or "dependencies"

        Returns:
            Complete reassembled dictionary
        """
        manifest_path = self.analysis_dir / f"{file_type}.manifest.json"
        manifest = self._read_json(manifest_path)

        logger.info(f"Reassembling {file_type} from {manifest['total_parts']} parts")

        # Load all parts
        parts_data = []
        for part_info in manifest["parts"]:
            part_path = self.analysis_dir / part_info["filename"]
            part_data = self._read_json(part_path)
            parts_data.append(part_data)

        # Merge based on file type
        if file_type == "catalog":
            return self._merge_catalog_parts(parts_data)
        elif file_type == "measures":
            return self._merge_measures_parts(parts_data)
        elif file_type == "dependencies":
            return self._merge_dependencies_parts(parts_data)
        elif file_type == "report_dependencies":
            return self._merge_report_dependencies_parts(parts_data)
        else:
            raise ValueError(f"Unknown file type: {file_type}")

    def _merge_catalog_parts(self, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge catalog parts into single structure (measures are now in separate file)"""
        merged = {
            "tables": [],
            "relationships_path": "",
            "roles": [],
            "optimization_summary": {}
        }

        for part in parts:
            merged["tables"].extend(part.get("tables", []))
            # Only take roles, etc. from first part
            if part.get("relationships_path"):
                merged["relationships_path"] = part["relationships_path"]
            if part.get("roles"):
                merged["roles"] = part["roles"]
            if part.get("optimization_summary"):
                merged["optimization_summary"] = part["optimization_summary"]

        return merged

    def _merge_measures_parts(self, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge measures parts into single structure"""
        merged = {
            "measures": [],
            "total_count": 0
        }

        for part in parts:
            merged["measures"].extend(part.get("measures", []))
            # Only take total_count from first part
            if part.get("total_count") and merged["total_count"] == 0:
                merged["total_count"] = part["total_count"]

        return merged

    def _merge_dependencies_parts(self, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge dependencies parts into single structure"""
        merged = {
            "measures": {},
            "columns": {},
            "tables": {},
            "summary": {}
        }

        for part in parts:
            merged["measures"].update(part.get("measures", {}))
            # Only take columns, tables, summary from first part
            if part.get("columns"):
                merged["columns"] = part["columns"]
            if part.get("tables"):
                merged["tables"] = part["tables"]
            if part.get("summary"):
                merged["summary"] = part["summary"]

        return merged

    def _merge_report_dependencies_parts(self, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge report_dependencies parts into single structure"""
        merged = {
            "visual_dependencies": [],
            "visuals_by_page": {},
            "page_summaries": {},
            "summary": {},
            "analysis_notes": {}
        }

        for part in parts:
            merged["visual_dependencies"].extend(part.get("visual_dependencies", []))
            # Only take visuals_by_page, page_summaries, summary, analysis_notes from first part
            if part.get("visuals_by_page"):
                merged["visuals_by_page"] = part["visuals_by_page"]
            if part.get("page_summaries"):
                merged["page_summaries"] = part["page_summaries"]
            if part.get("summary"):
                merged["summary"] = part["summary"]
            if part.get("analysis_notes"):
                merged["analysis_notes"] = part["analysis_notes"]

        return merged

    def _filter_catalog(
        self,
        catalog: Dict[str, Any],
        filters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply filters to catalog"""
        # TODO: Implement filtering logic
        return catalog

    def _apply_filters(
        self,
        objects: List[Dict[str, Any]],
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply filters to object list"""
        result = objects

        # Filter by name pattern
        if "name_pattern" in filters:
            import re
            try:
                pattern = re.compile(filters["name_pattern"])
            except re.error:
                # If invalid regex, treat as literal string
                pattern = re.compile(re.escape(filters["name_pattern"]))
            result = [obj for obj in result if pattern.search(obj.get("name", ""))]

        # Filter by folder (for measures)
        if "folder" in filters:
            result = [obj for obj in result if obj.get("display_folder") == filters["folder"]]

        # Filter by table
        if "table" in filters:
            result = [obj for obj in result if obj.get("table") == filters["table"]]

        # Filter by hidden
        if "is_hidden" in filters:
            result = [obj for obj in result if obj.get("is_hidden") == filters["is_hidden"]]

        return result

    def _sanitize_file_paths(self, data: Any) -> Any:
        """
        Remove file path fields from data to prevent Claude from prompting to copy files.
        Recursively sanitizes dictionaries and lists.

        Args:
            data: Data structure to sanitize

        Returns:
            Sanitized data with file paths replaced by boolean flags
        """
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                # Replace path fields with has_* boolean flags
                if key in ["sample_data_path", "tmdl_path"]:
                    # Convert path to boolean flag
                    has_key = f"has_{key.replace('_path', '')}"
                    sanitized[has_key] = bool(value)
                else:
                    # Recursively sanitize nested structures
                    sanitized[key] = self._sanitize_file_paths(value)
            return sanitized
        elif isinstance(data, list):
            return [self._sanitize_file_paths(item) for item in data]
        else:
            return data

    def get_relationships_from_tmdl(self) -> List[Dict[str, Any]]:
        """
        Parse relationships directly from TMDL files

        Returns:
            List of relationship definitions
        """
        if self.format_type == "test_metadata":
            return []

        if not self.tmdl_dir.exists():
            return []

        # Check for relationships.tmdl
        rel_path = self.tmdl_dir / "relationships.tmdl"
        if not rel_path.exists():
            # Try definition/relationships.tmdl
            rel_path = self.tmdl_dir / "definition" / "relationships.tmdl"
            if not rel_path.exists():
                logger.warning("relationships.tmdl not found")
                return []

        try:
            content = self.read_tmdl_file("relationships.tmdl")
            relationships = TMDLParser.parse_relationships(content)
            return relationships
        except Exception as e:
            logger.error(f"Error parsing relationships from TMDL: {e}")
            return []

    def get_measure_from_tmdl(self, measure_name: str, use_pattern: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get a specific measure definition from TMDL files
        Supports both direct TMDL structure and definition/ subfolder structure

        Args:
            measure_name: Name of measure (or pattern if use_pattern=True)
            use_pattern: If True, treat measure_name as a regex pattern for flexible search

        Returns:
            Measure definition or None
        """
        if self.format_type == "test_metadata":
            logger.debug("TMDL not available in test_metadata format")
            return None

        if not self.tmdl_dir.exists():
            logger.debug(f"TMDL directory not found: {self.tmdl_dir}")
            return None

        # Try both direct path and definition/ subfolder for expressions.tmdl
        expr_paths = [
            self.tmdl_dir / "expressions.tmdl",
            self.tmdl_dir / "definition" / "expressions.tmdl"
        ]

        for expr_path in expr_paths:
            if expr_path.exists():
                logger.debug(f"Searching for measure in {expr_path}")
                try:
                    content = expr_path.read_text(encoding='utf-8')
                    if use_pattern:
                        # Search all measures for pattern match
                        all_measures = TMDLParser.parse_all_measures(content)
                        import re
                        pattern = re.compile(measure_name, re.IGNORECASE)
                        for measure in all_measures:
                            if pattern.search(measure["name"]):
                                logger.info(f"Found measure '{measure['name']}' matching pattern '{measure_name}'")
                                return measure
                    else:
                        measure_def = TMDLParser.parse_measure(content, measure_name)
                        if measure_def:
                            logger.info(f"Found measure '{measure_name}' in expressions.tmdl")
                            return measure_def
                except Exception as e:
                    logger.debug(f"Error parsing measure from {expr_path}: {e}")

        # Try table TMDL files - both direct and definition/ subfolder
        tables_dirs = [
            self.tmdl_dir / "tables",
            self.tmdl_dir / "definition" / "tables"
        ]

        for tables_dir in tables_dirs:
            if tables_dir.exists():
                logger.debug(f"Searching for measure in {tables_dir}")
                for table_file in tables_dir.glob("*.tmdl"):
                    try:
                        content = table_file.read_text(encoding='utf-8')
                        if use_pattern:
                            # Search all measures for pattern match
                            all_measures = TMDLParser.parse_all_measures(content)
                            import re
                            pattern = re.compile(measure_name, re.IGNORECASE)
                            for measure in all_measures:
                                if pattern.search(measure["name"]):
                                    measure["table"] = table_file.stem
                                    logger.info(f"Found measure '{measure['name']}' in {table_file.name}")
                                    return measure
                        else:
                            measure_def = TMDLParser.parse_measure(content, measure_name)
                            if measure_def:
                                measure_def["table"] = table_file.stem
                                logger.info(f"Found measure '{measure_name}' in {table_file.name}")
                                return measure_def
                    except Exception as e:
                        logger.debug(f"Error parsing measure from {table_file}: {e}")

        logger.warning(f"Measure '{measure_name}' not found in any TMDL files")
        return None

    def find_measures_by_pattern(self, pattern: str) -> List[Dict[str, Any]]:
        """
        Find all measures matching a pattern

        Args:
            pattern: Regex pattern to match measure names

        Returns:
            List of matching measure definitions
        """
        if self.format_type == "test_metadata":
            logger.debug("TMDL not available in test_metadata format")
            return []

        if not self.tmdl_dir.exists():
            logger.debug(f"TMDL directory not found: {self.tmdl_dir}")
            return []

        matching_measures = []
        import re
        regex_pattern = re.compile(pattern, re.IGNORECASE)

        # Search in expressions.tmdl - try both paths
        expr_paths = [
            self.tmdl_dir / "expressions.tmdl",
            self.tmdl_dir / "definition" / "expressions.tmdl"
        ]

        for expr_path in expr_paths:
            if expr_path.exists():
                try:
                    content = expr_path.read_text(encoding='utf-8')
                    all_measures = TMDLParser.parse_all_measures(content)
                    for measure in all_measures:
                        if regex_pattern.search(measure["name"]):
                            measure["table"] = "Model"
                            matching_measures.append(measure)
                    break
                except Exception as e:
                    logger.debug(f"Error parsing {expr_path}: {e}")

        # Search in table files - try both paths
        tables_dirs = [
            self.tmdl_dir / "tables",
            self.tmdl_dir / "definition" / "tables"
        ]

        for tables_dir in tables_dirs:
            if tables_dir.exists():
                for table_file in tables_dir.glob("*.tmdl"):
                    try:
                        content = table_file.read_text(encoding='utf-8')
                        all_measures = TMDLParser.parse_all_measures(content)
                        for measure in all_measures:
                            if regex_pattern.search(measure["name"]):
                                measure["table"] = table_file.stem
                                matching_measures.append(measure)
                    except Exception as e:
                        logger.debug(f"Error parsing {table_file}: {e}")
                break

        logger.info(f"Found {len(matching_measures)} measures matching pattern '{pattern}'")
        return matching_measures

    def get_all_measures_from_tmdl(self) -> List[Dict[str, Any]]:
        """
        Get all measures from TMDL files
        Supports both direct TMDL structure and definition/ subfolder structure

        Returns:
            List of all measure definitions
        """
        if self.format_type == "test_metadata":
            logger.debug("TMDL not available in test_metadata format")
            return []

        if not self.tmdl_dir.exists():
            logger.debug(f"TMDL directory not found: {self.tmdl_dir}")
            return []

        all_measures = []

        # Get measures from expressions.tmdl - try both paths
        expr_paths = [
            self.tmdl_dir / "expressions.tmdl",
            self.tmdl_dir / "definition" / "expressions.tmdl"
        ]

        for expr_path in expr_paths:
            if expr_path.exists():
                logger.debug(f"Reading shared measures from {expr_path}")
                try:
                    content = expr_path.read_text(encoding='utf-8')
                    measures = TMDLParser.parse_all_measures(content)
                    for measure in measures:
                        measure["table"] = "Model"  # Shared measures
                    all_measures.extend(measures)
                    logger.info(f"Found {len(measures)} shared measures in {expr_path.name}")
                    break  # Only read from one location
                except Exception as e:
                    logger.error(f"Error parsing {expr_path}: {e}")

        # Get measures from table files - try both paths
        tables_dirs = [
            self.tmdl_dir / "tables",
            self.tmdl_dir / "definition" / "tables"
        ]

        for tables_dir in tables_dirs:
            if tables_dir.exists():
                logger.debug(f"Reading table measures from {tables_dir}")
                table_count = 0
                for table_file in tables_dir.glob("*.tmdl"):
                    try:
                        content = table_file.read_text(encoding='utf-8')
                        measures = TMDLParser.parse_all_measures(content)
                        for measure in measures:
                            measure["table"] = table_file.stem
                        all_measures.extend(measures)
                        if measures:
                            table_count += 1
                            logger.debug(f"Found {len(measures)} measures in {table_file.name}")
                    except Exception as e:
                        logger.error(f"Error parsing {table_file}: {e}")
                if table_count > 0:
                    logger.info(f"Found measures in {table_count} table files under {tables_dir}")
                break  # Only read from one location

        logger.info(f"Total measures found: {len(all_measures)}")
        return all_measures
