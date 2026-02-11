"""
TMDL Parser - Facade over UnifiedTmdlParser

Provides backward-compatible static methods that parse TMDL string content
and return camelCase dictionaries, delegating to the canonical UnifiedTmdlParser
for actual parsing logic.

Consumers: hybrid_reader.py, hybrid_analyzer.py
"""

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from core.tmdl.unified_parser import UnifiedTmdlParser

logger = logging.getLogger(__name__)

# Shared parser instance for content-level parsing (no directory needed)
_parser = UnifiedTmdlParser.__new__(UnifiedTmdlParser)


class TMDLParser:
    """Facade for TMDL parsing that delegates to UnifiedTmdlParser.

    All methods return camelCase dicts for backward compatibility with
    hybrid_reader.py and hybrid_analyzer.py consumers.
    """

    @staticmethod
    def parse_measure(tmdl_content: str, measure_name: str) -> Optional[Dict[str, Any]]:
        """Parse a specific measure from TMDL content."""
        table = _parser._parse_table_content(tmdl_content)
        if not table:
            return None

        for m in table.measures:
            if m.name == measure_name:
                return _measure_to_camel(m)

        return None

    @staticmethod
    def parse_all_measures(tmdl_content: str) -> List[Dict[str, Any]]:
        """Parse all measures from TMDL content."""
        table = _parser._parse_table_content(tmdl_content)
        if not table:
            return []

        result = [_measure_to_camel(m) for m in table.measures]
        logger.info(f"Parsed {len(result)} measures from TMDL")
        return result

    @staticmethod
    def parse_column(tmdl_content: str, column_name: str) -> Optional[Dict[str, Any]]:
        """Parse a specific column from TMDL content."""
        table = _parser._parse_table_content(tmdl_content)
        if not table:
            return None

        for c in table.columns:
            if c.name == column_name:
                return _column_to_camel(c)

        return None

    @staticmethod
    def parse_all_columns(tmdl_content: str) -> List[Dict[str, Any]]:
        """Parse all columns from TMDL content."""
        table = _parser._parse_table_content(tmdl_content)
        if not table:
            return []

        result = [_column_to_camel(c) for c in table.columns]
        logger.info(f"Parsed {len(result)} columns from TMDL")
        return result

    @staticmethod
    def parse_relationships(tmdl_content: str) -> List[Dict[str, Any]]:
        """Parse relationships from relationships.tmdl content."""
        import re

        relationships = []
        lines = tmdl_content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("///"):
                i += 1
                continue

            if line.startswith("relationship "):
                rel_match = re.match(r"^relationship\s+(.+)", line)
                if rel_match:
                    from core.tmdl.models import TmdlRelationship
                    from core.tmdl.unified_parser import _parse_property, _parse_bool

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
                            elif key == "isActive":
                                rel.is_active = _parse_bool(value) if value else True

                        i += 1

                    relationships.append(_relationship_to_camel(rel))
                    continue

            i += 1

        logger.info(f"Parsed {len(relationships)} relationships from TMDL")
        return relationships

    @staticmethod
    def parse_table_metadata(tmdl_content: str) -> Dict[str, Any]:
        """Parse table-level metadata from table TMDL content."""
        table = _parser._parse_table_content(tmdl_content)
        if not table:
            return {}

        metadata: Dict[str, Any] = {}
        metadata["name"] = table.name

        if table.description:
            metadata["description"] = table.description
        if table.is_hidden:
            metadata["isHidden"] = table.is_hidden

        metadata["hasPartition"] = len(table.partitions) > 0
        metadata["columnCount"] = len(table.columns)
        metadata["measureCount"] = len(table.measures)

        return metadata

    @staticmethod
    def parse_calculation_group(tmdl_content: str) -> Optional[Dict[str, Any]]:
        """Parse calculation group from TMDL content."""
        table = _parser._parse_table_content(tmdl_content)
        if not table or not table.is_calculation_group:
            return None

        calc_items = [
            {"name": ci.name, "expression": ci.expression}
            for ci in table.calculation_items
        ]

        return {"name": table.name, "calculationItems": calc_items}

    @staticmethod
    def parse_file(file_path: Path) -> Dict[str, Any]:
        """Parse a TMDL file and extract all relevant information."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            result = {"file_path": str(file_path), "file_name": file_path.name}

            if file_path.name == "relationships.tmdl":
                result["type"] = "relationships"
                result["relationships"] = TMDLParser.parse_relationships(content)
            elif file_path.name == "expressions.tmdl":
                result["type"] = "expressions"
                result["measures"] = TMDLParser.parse_all_measures(content)
            elif file_path.parent.name == "tables":
                result["type"] = "table"
                result["metadata"] = TMDLParser.parse_table_metadata(content)
                result["columns"] = TMDLParser.parse_all_columns(content)
                result["measures"] = TMDLParser.parse_all_measures(content)
                calc_group = TMDLParser.parse_calculation_group(content)
                if calc_group:
                    result["calculationGroup"] = calc_group
            else:
                result["type"] = "other"
                result["content"] = content

            return result

        except Exception as e:
            logger.error(f"Error parsing TMDL file {file_path}: {e}")
            raise


# ── camelCase conversion helpers ─────────────────────────────────────


def _measure_to_camel(m) -> Dict[str, Any]:
    """Convert TmdlMeasure to camelCase dict for backward compat."""
    return {
        "name": m.name,
        "expression": m.expression,
        "formatString": m.format_string,
        "description": m.description,
        "displayFolder": m.display_folder,
        "isHidden": m.is_hidden,
    }


def _column_to_camel(c) -> Dict[str, Any]:
    """Convert TmdlColumn to camelCase dict for backward compat."""
    return {
        "name": c.name,
        "dataType": c.data_type,
        "sourceColumn": c.source_column,
        "formatString": c.format_string,
        "isHidden": c.is_hidden,
        "isKey": c.is_key,
        "summarizeBy": c.summarize_by,
        "description": c.description,
        "displayFolder": c.display_folder,
    }


def _relationship_to_camel(r) -> Dict[str, Any]:
    """Convert TmdlRelationship to camelCase dict for backward compat."""
    from_card = r.from_cardinality or "many"
    to_card = r.to_cardinality or "one"

    cardinality_map = {
        ("one", "one"): "OneToOne",
        ("one", "many"): "OneToMany",
        ("many", "one"): "ManyToOne",
        ("many", "many"): "ManyToMany",
    }
    cardinality = cardinality_map.get(
        (from_card.lower(), to_card.lower()), "ManyToOne"
    )

    from_table = r.from_table
    from_col = r.from_column_name
    to_table = r.to_table
    to_col = r.to_column_name

    name = f"{from_table or 'Unknown'}.{from_col or 'Unknown'} -> {to_table or 'Unknown'}.{to_col or 'Unknown'}"

    return {
        "name": name,
        "hash": r.id,
        "fromTable": from_table,
        "fromColumn": from_col,
        "toTable": to_table,
        "toColumn": to_col,
        "fromCardinality": from_card,
        "toCardinality": to_card,
        "cardinality": cardinality,
        "crossFilteringBehavior": r.cross_filtering_behavior or "OneDirection",
        "isActive": r.is_active,
        "securityFilteringBehavior": r.security_filtering_behavior or "OneDirection",
    }
