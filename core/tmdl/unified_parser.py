"""
Unified TMDL Parser

Single canonical parser for all TMDL (Tabular Model Definition Language) files.
Replaces the three separate parsers that previously existed:
- core/pbip/pbip_model_analyzer.py TmdlParser (indentation-based)
- core/tmdl/tmdl_parser.py TmdlParser (line-by-line)
- core/model/tmdl_parser.py TMDLParser (static regex)

This parser produces typed TmdlModel dataclasses from core.tmdl.models.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    TmdlAnnotation,
    TmdlCalculationItem,
    TmdlColumn,
    TmdlCulture,
    TmdlDatabase,
    TmdlDatasource,
    TmdlExpression,
    TmdlHierarchy,
    TmdlHierarchyLevel,
    TmdlMeasure,
    TmdlModel,
    TmdlModelProperties,
    TmdlPartition,
    TmdlPerspective,
    TmdlPerspectiveItem,
    TmdlRelationship,
    TmdlRole,
    TmdlTable,
    TmdlTablePermission,
    TmdlTranslation,
)

logger = logging.getLogger(__name__)


class UnifiedTmdlParser:
    """
    Canonical parser for TMDL definition folders.

    Parses the definition/ folder structure into typed TmdlModel dataclasses.
    Handles all TMDL object types: tables, columns, measures, hierarchies,
    partitions, calculation items, relationships, expressions, datasources,
    roles, perspectives, and cultures.
    """

    def __init__(self, tmdl_path: str):
        """
        Initialize parser.

        Args:
            tmdl_path: Path to the TMDL root (contains definition/ folder)
                       or directly to a .SemanticModel folder
        """
        self.tmdl_path = Path(tmdl_path)
        self.definition_path = self.tmdl_path / "definition"

        if not self.definition_path.exists():
            # Try tmdl_path itself as the definition path
            if (self.tmdl_path / "model.tmdl").exists():
                self.definition_path = self.tmdl_path
            else:
                raise FileNotFoundError(
                    f"Definition folder not found at: {self.definition_path}"
                )

        logger.info(f"Initialized unified TMDL parser for: {tmdl_path}")

    def parse_full_model(self) -> TmdlModel:
        """
        Parse the complete TMDL model structure.

        Returns:
            TmdlModel with all parsed components
        """
        logger.info("Parsing full TMDL model")

        model = TmdlModel(
            database=self._parse_database(),
            model=self._parse_model(),
            tables=self._parse_tables(),
            relationships=self._parse_relationships(),
            roles=self._parse_roles(),
            perspectives=self._parse_perspectives(),
            expressions=self._parse_expressions(),
            datasources=self._parse_datasources(),
            cultures=self._parse_cultures(),
        )

        table_count = len(model.tables)
        rel_count = len(model.relationships)
        measure_count = sum(len(t.measures) for t in model.tables)
        logger.info(
            f"Parsed model: {table_count} tables, {measure_count} measures, "
            f"{rel_count} relationships"
        )

        return model

    # ─── Database & Model ────────────────────────────────────────────

    def _parse_database(self) -> Optional[TmdlDatabase]:
        """Parse database.tmdl file."""
        db_file = self.definition_path / "database.tmdl"
        if not db_file.exists():
            logger.warning("database.tmdl not found")
            return None

        content = db_file.read_text(encoding="utf-8")
        lines = content.split("\n")

        db = TmdlDatabase()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("///"):
                continue

            # Database name
            match = re.match(r"^database\s+[\"']?([^\"']+)[\"']?", stripped)
            if match:
                db.name = match.group(1)
                continue

            if ":" in stripped:
                key, value = _parse_property(stripped)
                if key == "compatibilityLevel":
                    db.compatibility_level = int(value) if value else None
                elif key:
                    db.properties[key] = value

        return db

    def _parse_model(self) -> Optional[TmdlModelProperties]:
        """Parse model.tmdl file."""
        model_file = self.definition_path / "model.tmdl"
        if not model_file.exists():
            logger.warning("model.tmdl not found")
            return None

        content = model_file.read_text(encoding="utf-8")
        lines = content.split("\n")

        props = TmdlModelProperties()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("///"):
                continue

            match = re.match(r"^model\s+[\"']?([^\"']+)[\"']?", stripped)
            if match:
                props.name = match.group(1)
                continue

            if ":" in stripped:
                key, value = _parse_property(stripped)
                if key == "culture":
                    props.culture = value
                elif key == "defaultPowerBIDataSourceVersion":
                    props.default_power_bi_data_source_version = value
                elif key == "discourageImplicitMeasures":
                    props.discourage_implicit_measures = _parse_bool(value)
                elif key:
                    props.properties[key] = value

        return props

    # ─── Tables ──────────────────────────────────────────────────────

    def _parse_tables(self) -> List[TmdlTable]:
        """Parse all table .tmdl files."""
        tables_dir = self.definition_path / "tables"
        if not tables_dir.exists():
            logger.warning("tables/ directory not found")
            return []

        tables = []
        for table_file in sorted(tables_dir.glob("*.tmdl")):
            try:
                content = table_file.read_text(encoding="utf-8")
                table = self._parse_table_content(content)
                if table:
                    table._source_file = table_file.name
                    tables.append(table)
            except Exception as e:
                logger.error(f"Error parsing table {table_file.name}: {e}")

        logger.debug(f"Parsed {len(tables)} tables")
        return tables

    def _parse_table_content(self, content: str) -> Optional[TmdlTable]:
        """Parse table TMDL content into TmdlTable."""
        lines = content.split("\n")
        if not lines:
            return None

        # Find table definition line, skip comments
        table_line_idx = 0
        table_match = None
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("///"):
                continue
            table_match = re.match(r"^table\s+[\"']?([^\"']+)[\"']?", stripped)
            if table_match:
                table_line_idx = idx
                break

        if not table_match:
            return None

        table = TmdlTable(name=table_match.group(1))

        i = table_line_idx + 1
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            # Calculation group marker
            if line.startswith("calculationGroup"):
                table.is_calculation_group = True
                i += 1
                continue

            if line.startswith("column "):
                col, i = self._parse_column(lines, i)
                if col:
                    table.columns.append(col)
                continue

            if line.startswith("measure "):
                meas, i = self._parse_measure(lines, i)
                if meas:
                    table.measures.append(meas)
                continue

            if line.startswith("hierarchy "):
                hier, i = self._parse_hierarchy(lines, i)
                if hier:
                    table.hierarchies.append(hier)
                continue

            if line.startswith("partition "):
                part, i = self._parse_partition(lines, i)
                if part:
                    table.partitions.append(part)
                continue

            if line.startswith("calculationItem "):
                ci, i = self._parse_calculation_item(lines, i)
                if ci:
                    table.calculation_items.append(ci)
                continue

            # Bare boolean flag (isHidden without value means true)
            if line == "isHidden":
                table.is_hidden = True
                i += 1
                continue

            if line.startswith("annotation "):
                annot, i = self._parse_annotation(lines, i)
                if annot:
                    table.annotations.append(annot)
                continue

            if ":" in line:
                key, value = _parse_property(line)
                if key == "isHidden":
                    table.is_hidden = _parse_bool(value)
                elif key == "description":
                    table.description = str(value) if value else None
                elif key == "lineageTag":
                    table.lineage_tag = str(value) if value else None
                elif key:
                    table.properties[key] = value

            i += 1

        return table

    # ─── Columns ─────────────────────────────────────────────────────

    def _parse_column(
        self, lines: List[str], start: int
    ) -> Tuple[Optional[TmdlColumn], int]:
        """Parse a column definition."""
        line = lines[start].strip()

        col_match = re.match(r"^column\s+[\"']?([^\"'=]+)[\"']?\s*(=)?", line)
        if not col_match:
            return None, start + 1

        col = TmdlColumn(
            name=col_match.group(1).strip(),
            is_calculated=col_match.group(2) == "=",
        )

        if col.is_calculated:
            col.expression, start = _extract_expression(lines, start)

        i = start + 1
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            if _is_next_object(line):
                break

            # Bare boolean
            if line == "isHidden":
                col.is_hidden = True
                i += 1
                continue
            if line == "isKey":
                col.is_key = True
                i += 1
                continue

            if line.startswith("annotation "):
                annot, i = self._parse_annotation(lines, i)
                if annot:
                    col.annotations.append(annot)
                continue

            if ":" in line:
                key, value = _parse_property(line)
                if key == "dataType":
                    col.data_type = value
                elif key == "sourceColumn":
                    col.source_column = value
                elif key == "description":
                    col.description = str(value) if value else None
                elif key == "displayFolder":
                    col.display_folder = value
                elif key == "formatString":
                    col.format_string = value
                elif key == "dataCategory":
                    col.data_category = value
                elif key == "summarizeBy":
                    col.summarize_by = value
                elif key == "sortByColumn":
                    col.sort_by_column = value
                elif key == "isKey":
                    col.is_key = _parse_bool(value)
                elif key == "isHidden":
                    col.is_hidden = _parse_bool(value)
                elif key == "lineageTag":
                    col.lineage_tag = str(value) if value else None
                elif key:
                    col.properties[key] = value

            i += 1

        return col, i

    # ─── Measures ────────────────────────────────────────────────────

    def _parse_measure(
        self, lines: List[str], start: int
    ) -> Tuple[Optional[TmdlMeasure], int]:
        """Parse a measure definition."""
        line = lines[start].strip()

        # Try quoted name first
        m = re.match(r"^measure\s+[\"']([^\"']+)[\"']\s*=", line)
        if not m:
            # Unquoted name (can contain spaces before =)
            m = re.match(r"^measure\s+([^=]+?)\s*=", line)
        if not m:
            return None, start + 1

        measure = TmdlMeasure(name=m.group(1).strip())
        measure.expression, next_i = _extract_expression(lines, start)

        i = next_i
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            if _is_next_object(line):
                break

            if line == "isHidden":
                measure.is_hidden = True
                i += 1
                continue

            if line.startswith("annotation "):
                annot, i = self._parse_annotation(lines, i)
                if annot:
                    measure.annotations.append(annot)
                continue

            if line.startswith("formatStringDefinition"):
                expr, i = _extract_expression(lines, i, keyword="formatStringDefinition")
                measure.format_string_definition = expr
                continue

            if ":" in line:
                key, value = _parse_property(line)
                if key == "formatString":
                    measure.format_string = value
                elif key == "displayFolder":
                    measure.display_folder = value
                elif key == "description":
                    measure.description = str(value) if value else None
                elif key == "isHidden":
                    measure.is_hidden = _parse_bool(value)
                elif key == "dataCategory":
                    measure.data_category = value
                elif key == "lineageTag":
                    measure.lineage_tag = str(value) if value else None
                elif key:
                    measure.properties[key] = value

            i += 1

        return measure, i

    # ─── Hierarchies ─────────────────────────────────────────────────

    def _parse_hierarchy(
        self, lines: List[str], start: int
    ) -> Tuple[Optional[TmdlHierarchy], int]:
        """Parse a hierarchy definition."""
        line = lines[start].strip()

        m = re.match(r"^hierarchy\s+[\"']?([^\"']+)[\"']?", line)
        if not m:
            return None, start + 1

        hier = TmdlHierarchy(name=m.group(1))

        i = start + 1
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            if _is_next_object(line, include_hierarchy=False):
                break

            if line == "isHidden":
                hier.is_hidden = True
                i += 1
                continue

            if line.startswith("level "):
                level_match = re.match(r"^level\s+[\"']?([^\"']+)[\"']?", line)
                if level_match:
                    level = TmdlHierarchyLevel(name=level_match.group(1))
                    j = i + 1
                    while j < len(lines):
                        prop_line = lines[j].strip()
                        if not prop_line or prop_line.startswith("///"):
                            j += 1
                            continue
                        # Level props are indented under the level
                        raw = lines[j]
                        if not raw.startswith(("\t\t\t", "         ")):
                            # Check if this is still a nested property
                            if prop_line.startswith("level ") or _is_next_object(prop_line):
                                break
                            if ":" not in prop_line:
                                break
                        if ":" in prop_line:
                            key, value = _parse_property(prop_line)
                            if key == "column":
                                level.column = value
                            elif key == "ordinal":
                                level.ordinal = int(value) if value else None
                            elif key == "lineageTag":
                                level.lineage_tag = str(value) if value else None
                        j += 1
                    hier.levels.append(level)
                    i = j
                    continue

            if ":" in line:
                key, value = _parse_property(line)
                if key == "lineageTag":
                    hier.lineage_tag = str(value) if value else None
                elif key == "isHidden":
                    hier.is_hidden = _parse_bool(value)
                elif key:
                    hier.properties[key] = value

            i += 1

        return hier, i

    # ─── Partitions ──────────────────────────────────────────────────

    def _parse_partition(
        self, lines: List[str], start: int
    ) -> Tuple[Optional[TmdlPartition], int]:
        """Parse a partition definition."""
        line = lines[start].strip()

        # "partition 'Name' = m" or "partition Name = entity"
        m = re.match(r"^partition\s+[\"']?([^\"'=]+?)[\"']?\s*=\s*(\w+)", line)
        if not m:
            return None, start + 1

        part = TmdlPartition(name=m.group(1).strip(), type=m.group(2))

        # Extract source expression
        source, next_i = _extract_expression(lines, start, keyword="source")
        if not source:
            # Try from next line
            if start + 1 < len(lines) and "=" in lines[start + 1]:
                source, next_i = _extract_expression(lines, start + 1)
            else:
                next_i = start + 1
        part.source = source

        i = next_i
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            if _is_next_object(line):
                break

            if ":" in line:
                key, value = _parse_property(line)
                if key == "mode":
                    part.mode = value
                elif key == "queryGroup":
                    part.query_group = value
                elif key:
                    part.properties[key] = value

            i += 1

        return part, i

    # ─── Calculation Items ───────────────────────────────────────────

    def _parse_calculation_item(
        self, lines: List[str], start: int
    ) -> Tuple[Optional[TmdlCalculationItem], int]:
        """Parse a calculation item (for calculation groups)."""
        line = lines[start].strip()

        m = re.match(r"^calculationItem\s+[\"']?([^\"'=]+)[\"']?\s*=", line)
        if not m:
            return None, start + 1

        ci = TmdlCalculationItem(name=m.group(1).strip())
        ci.expression, next_i = _extract_expression(lines, start)

        i = next_i
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            if _is_next_object(line, include_calc_item=False):
                break

            if line.startswith("annotation "):
                annot, i = self._parse_annotation(lines, i)
                if annot:
                    ci.annotations.append(annot)
                continue

            if line.startswith("formatStringDefinition"):
                expr, i = _extract_expression(lines, i, keyword="formatStringDefinition")
                ci.format_string_definition = expr
                continue

            if ":" in line:
                key, value = _parse_property(line)
                if key == "ordinal":
                    ci.ordinal = int(value) if value else None
                elif key == "description":
                    ci.description = str(value) if value else None
                elif key == "lineageTag":
                    ci.lineage_tag = str(value) if value else None
                elif key:
                    ci.properties[key] = value

            i += 1

        return ci, i

    # ─── Annotations ─────────────────────────────────────────────────

    def _parse_annotation(
        self, lines: List[str], start: int
    ) -> Tuple[Optional[TmdlAnnotation], int]:
        """Parse an annotation: annotation Name = value"""
        line = lines[start].strip()

        # Multi-line annotation: annotation Name = ```json\n...\n```
        m_multi = re.match(r"^annotation\s+([^\s=]+)\s*=\s*```", line)
        if m_multi:
            name = m_multi.group(1)
            value_lines = []
            i = start + 1
            while i < len(lines):
                if lines[i].strip() == "```":
                    i += 1
                    break
                value_lines.append(lines[i].rstrip())
                i += 1
            return TmdlAnnotation(name=name, value="\n".join(value_lines)), i

        m = re.match(r"^annotation\s+([^\s=]+)\s*=\s*(.+)", line)
        if not m:
            return None, start + 1

        value = m.group(2).strip()
        # Remove quotes
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]

        return TmdlAnnotation(name=m.group(1), value=value), start + 1

    # ─── Relationships ───────────────────────────────────────────────

    def _parse_relationships(self) -> List[TmdlRelationship]:
        """Parse relationships.tmdl file."""
        rel_file = self.definition_path / "relationships.tmdl"
        if not rel_file.exists():
            logger.debug("relationships.tmdl not found")
            return []

        content = rel_file.read_text(encoding="utf-8")
        relationships: List[TmdlRelationship] = []
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            if line.startswith("relationship "):
                rel_match = re.match(r"^relationship\s+(.+)", line)
                if rel_match:
                    rel = TmdlRelationship(id=rel_match.group(1))

                    i += 1
                    while i < len(lines):
                        prop_line = lines[i].strip()

                        if not prop_line or prop_line.startswith("///"):
                            i += 1
                            continue

                        if prop_line.startswith("relationship "):
                            break

                        if prop_line == "isActive":
                            rel.is_active = True
                            i += 1
                            continue

                        if prop_line.startswith("annotation "):
                            annot, i = self._parse_annotation(lines, i)
                            if annot:
                                rel.annotations.append(annot)
                            continue

                        if ":" in prop_line:
                            key, value = _parse_property(prop_line)
                            if key == "fromColumn":
                                rel.from_column = value
                            elif key == "fromCardinality":
                                rel.from_cardinality = value
                            elif key == "toColumn":
                                rel.to_column = value
                            elif key == "toCardinality":
                                rel.to_cardinality = value
                            elif key == "crossFilteringBehavior":
                                rel.cross_filtering_behavior = value
                            elif key == "securityFilteringBehavior":
                                rel.security_filtering_behavior = value
                            elif key == "relyOnReferentialIntegrity":
                                rel.rely_on_referential_integrity = _parse_bool(value)
                            elif key == "isActive":
                                rel.is_active = _parse_bool(value) if value else True
                            elif key:
                                rel.properties[key] = value

                        i += 1

                    relationships.append(rel)
                    continue

            i += 1

        logger.debug(f"Parsed {len(relationships)} relationships")
        return relationships

    # ─── Expressions ─────────────────────────────────────────────────

    def _parse_expressions(self) -> List[TmdlExpression]:
        """Parse expressions.tmdl (shared M expressions and parameters)."""
        expr_file = self.definition_path / "expressions.tmdl"
        if not expr_file.exists():
            logger.debug("expressions.tmdl not found")
            return []

        content = expr_file.read_text(encoding="utf-8")
        expressions: List[TmdlExpression] = []
        lines = content.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            # Look for: expression <name> = <value>
            if line.startswith("expression ") and "=" in line:
                name_part = line[len("expression "):].split("=")[0].strip()
                name_part = name_part.strip("\"'")
                after_equals = line.split("=", 1)[1].strip()

                expr = TmdlExpression(name=name_part)
                expression_text = ""

                if after_equals and not after_equals.endswith("="):
                    # Single-line expression (e.g., parameter)
                    # Remove metadata like 'meta [...]'
                    if " meta " in after_equals:
                        expression_text = after_equals.split(" meta ")[0].strip()
                    else:
                        expression_text = after_equals
                    i += 1
                else:
                    # Multi-line expression
                    expression_lines = []
                    i += 1

                    # Skip leading empty lines
                    while i < len(lines) and not lines[i].strip():
                        i += 1

                    if i < len(lines):
                        first_line = lines[i]
                        indent_level = len(first_line) - len(first_line.lstrip())

                        while i < len(lines):
                            curr_line = lines[i]
                            curr_stripped = curr_line.strip()
                            curr_indent = len(curr_line) - len(curr_line.lstrip())

                            # Stop at non-indented non-empty line
                            if curr_stripped and curr_indent < indent_level:
                                break

                            # Stop at metadata/property/next expression
                            if curr_stripped.startswith((
                                "lineageTag:", "queryGroup:",
                                "annotation ", "expression ",
                            )):
                                break

                            if curr_stripped:
                                expression_lines.append(curr_line.rstrip())

                            i += 1

                    expression_text = "\n".join(expression_lines).strip()

                if expression_text:
                    expr.expression = expression_text

                # Parse trailing properties for this expression
                while i < len(lines):
                    prop_line = lines[i].strip()
                    if not prop_line or prop_line.startswith("///"):
                        i += 1
                        continue
                    if prop_line.startswith("expression ") or not prop_line.startswith(("\t", " ")):
                        # Hit next expression or unindented content
                        if not prop_line.startswith(("lineageTag:", "queryGroup:", "annotation ")):
                            break
                    if ":" in prop_line:
                        key, value = _parse_property(prop_line)
                        if key == "lineageTag":
                            expr.lineage_tag = str(value) if value else None
                        elif key == "queryGroup":
                            expr.query_group = value
                        elif key:
                            expr.properties[key] = value
                        i += 1
                    elif prop_line.startswith("annotation "):
                        annot, i = self._parse_annotation(lines, i)
                        if annot:
                            expr.annotations.append(annot)
                    else:
                        break

                expressions.append(expr)
                continue

            i += 1

        logger.debug(f"Parsed {len(expressions)} expressions")
        return expressions

    # ─── Datasources ─────────────────────────────────────────────────

    def _parse_datasources(self) -> List[TmdlDatasource]:
        """Parse datasources.tmdl file."""
        ds_file = self.definition_path / "datasources.tmdl"
        if not ds_file.exists():
            logger.debug("datasources.tmdl not found")
            return []

        content = ds_file.read_text(encoding="utf-8")
        datasources: List[TmdlDatasource] = []
        lines = content.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            # dataSource <name>
            ds_match = re.match(r"^(?:dataSource|datasource)\s+[\"']?([^\"']+)[\"']?", line, re.IGNORECASE)
            if ds_match:
                ds = TmdlDatasource(name=ds_match.group(1).strip())

                i += 1
                while i < len(lines):
                    prop_line = lines[i].strip()

                    if not prop_line or prop_line.startswith("///"):
                        i += 1
                        continue

                    # Next datasource
                    if re.match(r"^(?:dataSource|datasource)\s+", prop_line, re.IGNORECASE):
                        break

                    if prop_line.startswith("annotation "):
                        annot, i = self._parse_annotation(lines, i)
                        if annot:
                            ds.annotations.append(annot)
                        continue

                    if ":" in prop_line:
                        key, value = _parse_property(prop_line)
                        if key == "type":
                            ds.type = value
                        elif key in ("connectionString", "connectionstring"):
                            ds.connection_string = value
                        elif key == "provider":
                            ds.provider = value
                        elif key:
                            ds.properties[key] = value

                    i += 1

                datasources.append(ds)
                continue

            i += 1

        logger.debug(f"Parsed {len(datasources)} datasources")
        return datasources

    # ─── Roles ───────────────────────────────────────────────────────

    def _parse_roles(self) -> List[TmdlRole]:
        """Parse role .tmdl files."""
        roles_dir = self.definition_path / "roles"
        if not roles_dir.exists():
            logger.debug("roles/ directory not found")
            return []

        roles: List[TmdlRole] = []
        for role_file in sorted(roles_dir.glob("*.tmdl")):
            try:
                content = role_file.read_text(encoding="utf-8")
                role = self._parse_role_content(content)
                if role:
                    role._source_file = role_file.name
                    roles.append(role)
            except Exception as e:
                logger.error(f"Error parsing role {role_file.name}: {e}")

        logger.debug(f"Parsed {len(roles)} roles")
        return roles

    def _parse_role_content(self, content: str) -> Optional[TmdlRole]:
        """Parse a single role TMDL file."""
        lines = content.split("\n")

        role_match = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("///"):
                continue
            role_match = re.match(r"^role\s+[\"']?([^\"']+)[\"']?", stripped)
            if role_match:
                break

        if not role_match:
            return None

        role = TmdlRole(name=role_match.group(1))

        i = 1
        current_table_perm: Optional[TmdlTablePermission] = None

        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            # modelPermission: read
            if ":" in line:
                key, value = _parse_property(line)
                if key == "modelPermission":
                    role.model_permission = value
                elif key == "description":
                    role.description = str(value) if value else None
                elif key == "filterExpression" and current_table_perm:
                    # Single-line filter
                    current_table_perm.filter_expression = str(value) if value else None
                elif key:
                    role.properties[key] = value
                i += 1
                continue

            # tablePermission 'TableName' or tablePermission 'TableName' = ```
            tp_match = re.match(
                r"^tablePermission\s+[\"']?([^\"'=]+?)[\"']?\s*(?:=\s*(.*))?$",
                line,
            )
            if tp_match:
                current_table_perm = TmdlTablePermission(
                    table=tp_match.group(1).strip()
                )
                role.table_permissions.append(current_table_perm)

                # Inline expression: tablePermission 'Name' = ```...```
                inline_val = tp_match.group(2)
                if inline_val is not None:
                    inline_val = inline_val.strip()
                    if inline_val == "```":
                        expr, j = _extract_backtick_expression(lines, i + 1)
                        current_table_perm.filter_expression = expr
                        i = j
                        continue
                    elif inline_val:
                        current_table_perm.filter_expression = inline_val
                        i += 1
                        continue

                # Check for filter expression on next lines
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if not next_line or next_line.startswith("///"):
                        j += 1
                        continue
                    if next_line.startswith("tablePermission ") or next_line.startswith("annotation "):
                        break
                    if ":" in next_line:
                        key, value = _parse_property(next_line)
                        if key == "filterExpression":
                            # Multi-line filter
                            expr, j = _extract_expression(lines, j, keyword="filterExpression")
                            current_table_perm.filter_expression = expr
                            continue
                    j += 1
                i = j
                continue

            if line.startswith("annotation "):
                annot, i = self._parse_annotation(lines, i)
                if annot:
                    role.annotations.append(annot)
                continue

            i += 1

        return role

    # ─── Perspectives ────────────────────────────────────────────────

    def _parse_perspectives(self) -> List[TmdlPerspective]:
        """Parse perspective .tmdl files."""
        persp_dir = self.definition_path / "perspectives"
        if not persp_dir.exists():
            logger.debug("perspectives/ directory not found")
            return []

        perspectives: List[TmdlPerspective] = []
        for persp_file in sorted(persp_dir.glob("*.tmdl")):
            try:
                content = persp_file.read_text(encoding="utf-8")
                persp = self._parse_perspective_content(content)
                if persp:
                    persp._source_file = persp_file.name
                    perspectives.append(persp)
            except Exception as e:
                logger.error(f"Error parsing perspective {persp_file.name}: {e}")

        logger.debug(f"Parsed {len(perspectives)} perspectives")
        return perspectives

    def _parse_perspective_content(self, content: str) -> Optional[TmdlPerspective]:
        """Parse a single perspective TMDL file."""
        lines = content.split("\n")

        persp_match = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("///"):
                continue
            persp_match = re.match(r"^perspective\s+[\"']?([^\"']+)[\"']?", stripped)
            if persp_match:
                break

        if not persp_match:
            return None

        persp = TmdlPerspective(name=persp_match.group(1))

        # Parse perspective table/column/measure entries
        current_table: Optional[str] = None
        i = 1
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            # perspectiveTable 'TableName'
            pt_match = re.match(r"^perspectiveTable\s+[\"']?([^\"']+)[\"']?", line)
            if pt_match:
                current_table = pt_match.group(1)
                persp.items.append(TmdlPerspectiveItem(
                    object_type="table", table=current_table
                ))
                i += 1
                continue

            if current_table:
                # perspectiveColumn 'ColumnName'
                pc_match = re.match(r"^perspectiveColumn\s+[\"']?([^\"']+)[\"']?", line)
                if pc_match:
                    persp.items.append(TmdlPerspectiveItem(
                        object_type="column", table=current_table, name=pc_match.group(1)
                    ))
                    i += 1
                    continue

                # perspectiveMeasure 'MeasureName'
                pm_match = re.match(r"^perspectiveMeasure\s+[\"']?([^\"']+)[\"']?", line)
                if pm_match:
                    persp.items.append(TmdlPerspectiveItem(
                        object_type="measure", table=current_table, name=pm_match.group(1)
                    ))
                    i += 1
                    continue

                # perspectiveHierarchy 'HierarchyName'
                ph_match = re.match(r"^perspectiveHierarchy\s+[\"']?([^\"']+)[\"']?", line)
                if ph_match:
                    persp.items.append(TmdlPerspectiveItem(
                        object_type="hierarchy", table=current_table, name=ph_match.group(1)
                    ))
                    i += 1
                    continue

            if line.startswith("annotation "):
                annot, i = self._parse_annotation(lines, i)
                if annot:
                    persp.annotations.append(annot)
                continue

            if ":" in line:
                key, value = _parse_property(line)
                if key == "description":
                    persp.description = str(value) if value else None
                elif key:
                    persp.properties[key] = value

            i += 1

        return persp

    # ─── Cultures ────────────────────────────────────────────────────

    def _parse_cultures(self) -> List[TmdlCulture]:
        """Parse culture .tmdl files (translations)."""
        cultures_dir = self.definition_path / "cultures"
        if not cultures_dir.exists():
            logger.debug("cultures/ directory not found")
            return []

        cultures: List[TmdlCulture] = []
        for culture_file in sorted(cultures_dir.glob("*.tmdl")):
            try:
                content = culture_file.read_text(encoding="utf-8")
                culture = self._parse_culture_content(content)
                if culture:
                    culture._source_file = culture_file.name
                    cultures.append(culture)
            except Exception as e:
                logger.error(f"Error parsing culture {culture_file.name}: {e}")

        logger.debug(f"Parsed {len(cultures)} cultures")
        return cultures

    def _parse_culture_content(self, content: str) -> Optional[TmdlCulture]:
        """Parse a single culture TMDL file."""
        lines = content.split("\n")

        culture_match = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("///"):
                continue
            culture_match = re.match(r"^culture\s+[\"']?([^\"']+)[\"']?", stripped)
            if culture_match:
                break

        if not culture_match:
            return None

        culture = TmdlCulture(name=culture_match.group(1))

        # Parse translation entries
        current_table: Optional[str] = None
        i = 1
        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            # linguisticMetadata block - skip for now
            if line.startswith("linguisticMetadata"):
                # Skip the entire block (triple-backtick delimited)
                i += 1
                if i < len(lines) and lines[i].strip().startswith("```"):
                    i += 1
                    while i < len(lines) and not lines[i].strip().startswith("```"):
                        i += 1
                    i += 1  # skip closing ```
                continue

            # translationTable 'TableName'
            tt_match = re.match(r"^translationTable\s+[\"']?([^\"']+)[\"']?", line)
            if tt_match:
                current_table = tt_match.group(1)
                i += 1
                continue

            if current_table:
                # translationColumn / translationMeasure / translationHierarchy
                for obj_type, prefix in [
                    ("column", "translationColumn"),
                    ("measure", "translationMeasure"),
                    ("hierarchy", "translationHierarchy"),
                ]:
                    tc_match = re.match(
                        rf"^{prefix}\s+[\"']?([^\"']+)[\"']?", line
                    )
                    if tc_match:
                        trans = TmdlTranslation(
                            object_type=obj_type,
                            table=current_table,
                            name=tc_match.group(1),
                        )
                        # Parse translation properties
                        j = i + 1
                        while j < len(lines):
                            prop_line = lines[j].strip()
                            if not prop_line or prop_line.startswith("///"):
                                j += 1
                                continue
                            if prop_line.startswith(("translation", "linguisticMetadata")):
                                break
                            if ":" in prop_line:
                                key, value = _parse_property(prop_line)
                                if key == "translatedCaption":
                                    trans.translated_caption = value
                                elif key == "translatedDescription":
                                    trans.translated_description = value
                                elif key == "translatedDisplayFolder":
                                    trans.translated_display_folder = value
                            else:
                                break
                            j += 1
                        culture.translations.append(trans)
                        i = j
                        break
                else:
                    # Check for table-level translation caption
                    if ":" in line:
                        key, value = _parse_property(line)
                        if key == "translatedCaption":
                            trans = TmdlTranslation(
                                object_type="table",
                                table=current_table,
                                translated_caption=value,
                            )
                            culture.translations.append(trans)
                    i += 1
                continue

            i += 1

        return culture


# ═════════════════════════════════════════════════════════════════════
# Module-level helper functions
# ═════════════════════════════════════════════════════════════════════

# Object keywords that indicate the start of a new sibling object
_OBJECT_KEYWORDS = frozenset([
    "column ", "measure ", "hierarchy ", "partition ", "calculationItem ",
    "table ", "relationship ", "annotation ",
])


def _is_next_object(
    line: str,
    include_hierarchy: bool = True,
    include_calc_item: bool = True,
) -> bool:
    """Check if this line starts a new object at the same or higher level."""
    for kw in _OBJECT_KEYWORDS:
        if kw == "hierarchy " and not include_hierarchy:
            continue
        if kw == "calculationItem " and not include_calc_item:
            continue
        if line.startswith(kw):
            return True
    return False


def _parse_property(line: str) -> Tuple[Optional[str], Optional[Any]]:
    """Parse 'key: value' or 'key : value'. Returns (key, value)."""
    if ":" not in line:
        return None, None

    parts = line.split(":", 1)
    key = parts[0].strip()
    value = parts[1].strip() if len(parts) > 1 else None

    if value:
        # Remove quotes
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        else:
            # Try numeric conversion
            try:
                if "." in value:
                    value = float(value)
                else:
                    value = int(value)
            except (ValueError, TypeError):
                pass

    return key, value


def _parse_bool(value: Any) -> bool:
    """Parse a TMDL boolean value."""
    if isinstance(value, bool):
        return value
    if value is None:
        return True  # Bare keyword without value means true in TMDL
    return str(value).lower() == "true"


def _extract_expression(
    lines: List[str],
    start: int,
    keyword: Optional[str] = None,
) -> Tuple[Optional[str], int]:
    """
    Extract a multi-line DAX or M expression.

    Handles three forms:
    - Single-line: ``measure X = EXPR``
    - Indented multi-line: ``measure X =\\n\\t\\tEXPR_LINE1\\n\\t\\tEXPR_LINE2``
    - Triple-backtick delimited: ``measure X = ```\\n\\tEXPR\\n\\t```''

    Args:
        lines: All file lines
        start: Start index
        keyword: Optional keyword to look for (e.g., 'source', 'formatStringDefinition')

    Returns:
        (expression_text, next_line_index)
    """
    expr_parts: List[str] = []
    i = start
    line = lines[i].strip()
    inline_expr = False

    if keyword:
        if keyword in line and "=" in line:
            parts = line.split("=", 1)
            if len(parts) > 1:
                expr_start = parts[1].strip()
                if expr_start:
                    # Triple-backtick delimited expression
                    if expr_start == "```":
                        return _extract_backtick_expression(lines, i + 1)
                    expr_parts.append(expr_start)
                    inline_expr = True
            i += 1
    else:
        if "=" in line:
            parts = line.split("=", 1)
            if len(parts) > 1:
                expr_start = parts[1].strip()
                if expr_start:
                    # Triple-backtick delimited expression
                    if expr_start == "```":
                        return _extract_backtick_expression(lines, i + 1)
                    expr_parts.append(expr_start)
                    inline_expr = True
            i += 1

    # If the expression was fully on the same line as the `=`, don't consume
    # indented continuation lines — those belong to the next sibling object.
    if inline_expr:
        if expr_parts:
            return "\n".join(expr_parts).strip(), i
        return None, i

    # Collect indented continuation lines
    base_indent: Optional[int] = None
    while i < len(lines):
        raw = lines[i]
        stripped = raw.lstrip()

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        indent = len(raw) - len(stripped)

        if base_indent is None and stripped:
            base_indent = indent

        # End of expression: less indentation
        if base_indent is not None and indent < base_indent and stripped:
            # Check if this is a property or a new object
            if ":" in stripped and not any(
                kw in stripped for kw in ("CALCULATE(", "VAR ", "RETURN", "let", "in")
            ):
                break
            if _is_next_object(stripped):
                break

        expr_parts.append(stripped)
        i += 1

        # Unindented property line
        if not stripped.startswith((" ", "\t")) and ":" in stripped:
            break

    if expr_parts:
        return "\n".join(expr_parts).strip(), i
    return None, i


def _extract_backtick_expression(
    lines: List[str], start: int
) -> Tuple[Optional[str], int]:
    """
    Extract expression content between triple-backtick delimiters.

    The opening ``` has already been consumed; start points to the first
    line after it.  We collect lines until a closing ``` is found.

    Returns:
        (expression_text, next_line_index after closing ```)
    """
    expr_parts: List[str] = []
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "```":
            # Closing delimiter — advance past it
            return "\n".join(expr_parts).strip() or None, i + 1
        if stripped:
            expr_parts.append(stripped)
        i += 1

    # No closing delimiter found; return what we have
    if expr_parts:
        return "\n".join(expr_parts).strip(), i
    return None, i


# ═════════════════════════════════════════════════════════════════════
# Convenience function
# ═════════════════════════════════════════════════════════════════════


def parse_tmdl_model(tmdl_path: str) -> TmdlModel:
    """
    Parse a TMDL model from a definition folder.

    Args:
        tmdl_path: Path to TMDL root (containing definition/ subfolder)

    Returns:
        Parsed TmdlModel
    """
    parser = UnifiedTmdlParser(tmdl_path)
    return parser.parse_full_model()
