"""
PBIP Visual Reference Validator

Scans visual.json files in a PBIP report for field references (measures, columns)
and cross-checks them against the TMDL model. Reports any references to non-existent
objects, which typically occur after measure/column renames or deletions.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def scan_broken_visual_references(
    pbip_path: str, tmdl_model: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Scan all visuals in a PBIP report for broken field references.

    Args:
        pbip_path: Path to PBIP project root, .pbip file, or .Report folder.
        tmdl_model: Optional pre-parsed model dict (from PbipProject.model_data).
                    If None, will parse from TMDL files on disk.

    Returns:
        Dict with broken references and summary stats.
    """
    # Resolve PBIP paths to find both model and report directories
    model_objects = _resolve_model_objects(pbip_path, tmdl_model)
    if "error" in model_objects:
        return {"success": False, "error": model_objects["error"]}

    known_measures = model_objects["measures"]
    known_columns = model_objects["columns"]
    known_tables = model_objects["tables"]

    report_dir = _resolve_report_dir(pbip_path)
    if not report_dir:
        return {"success": False, "error": f"Could not find report directory for: {pbip_path}"}

    pages_dir = os.path.join(report_dir, "pages")
    if not os.path.isdir(pages_dir):
        return {"success": False, "error": f"No pages directory found at: {pages_dir}"}

    # Scan all visual.json files
    broken_refs: List[Dict[str, str]] = []
    total_visuals = 0
    total_refs_checked = 0

    for page_folder in sorted(Path(pages_dir).iterdir()):
        if not page_folder.is_dir():
            continue

        page_name = _get_page_name(page_folder)

        visuals_dir = page_folder / "visuals"
        if not visuals_dir.is_dir():
            continue

        for visual_folder in sorted(visuals_dir.iterdir()):
            if not visual_folder.is_dir():
                continue

            visual_json_path = visual_folder / "visual.json"
            if not visual_json_path.exists():
                continue

            total_visuals += 1

            try:
                with open(visual_json_path, "r", encoding="utf-8") as f:
                    visual_data = json.load(f)
            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON in %s: %s", visual_json_path, e)
                continue
            except Exception as e:
                logger.warning("Error reading %s: %s", visual_json_path, e)
                continue

            visual_title = _extract_visual_title(visual_data)
            visual_type = (
                visual_data.get("visual", {}).get("visualType", "unknown")
            )

            refs = _extract_field_references(visual_data)
            total_refs_checked += len(refs)

            for ref in refs:
                table = ref["table"]
                field = ref["field"]
                ref_type = ref["type"]

                broken, reason = _check_reference(
                    table, field, ref_type,
                    known_measures, known_columns, known_tables,
                )

                if broken:
                    broken_refs.append({
                        "page": page_name,
                        "visual_id": visual_folder.name,
                        "visual_title": visual_title,
                        "visual_type": visual_type,
                        "table": table,
                        "field": field,
                        "ref_type": ref_type,
                        "reason": reason,
                    })

    affected_pages = {r["page"] for r in broken_refs}
    affected_visuals = {r["visual_id"] for r in broken_refs}

    return {
        "success": True,
        "broken_references": broken_refs,
        "summary": {
            "total_visuals_scanned": total_visuals,
            "total_references_checked": total_refs_checked,
            "broken_count": len(broken_refs),
            "affected_pages": len(affected_pages),
            "affected_visuals": len(affected_visuals),
        },
        "model_stats": {
            "known_measures": len(known_measures),
            "known_columns": len(known_columns),
            "known_tables": len(known_tables),
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Model object collection
# ─────────────────────────────────────────────────────────────────────

def _resolve_model_objects(
    pbip_path: str, tmdl_model: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Collect known measures, columns, and tables from the model."""
    known_measures: Set[str] = set()
    known_columns: Set[str] = set()
    known_tables: Set[str] = set()

    # Fast path: use pre-parsed model data if available
    if tmdl_model and tmdl_model.get("tables"):
        for table in tmdl_model["tables"]:
            table_name = table.get("name", "")
            if not table_name:
                continue
            known_tables.add(table_name)

            for m in table.get("measures", []):
                name = m.get("name", "")
                if name:
                    known_measures.add(name)

            for c in table.get("columns", []):
                name = c.get("name", "")
                if name:
                    known_columns.add(name)
                    known_columns.add(f"{table_name}[{name}]")

        return {
            "measures": known_measures,
            "columns": known_columns,
            "tables": known_tables,
        }

    # Slow path: parse TMDL files from disk
    tables_dir = _find_tables_dir(pbip_path)
    if not tables_dir:
        return {"error": "Could not find TMDL tables directory in PBIP project"}

    for item in Path(tables_dir).iterdir():
        if item.is_dir():
            table_name = item.name
            known_tables.add(table_name)

            tmdl_file = item / f"{table_name}.tmdl"
            if not tmdl_file.exists():
                tmdl_files = list(item.glob("*.tmdl"))
                if tmdl_files:
                    tmdl_file = tmdl_files[0]

            if tmdl_file.exists():
                _parse_tmdl_file(tmdl_file, table_name, known_measures, known_columns)

        elif item.suffix == ".tmdl":
            table_name = item.stem
            known_tables.add(table_name)
            _parse_tmdl_file(item, table_name, known_measures, known_columns)

    if not known_measures and not known_columns:
        return {
            "error": "Could not parse any model objects from TMDL. "
                     "Ensure PBIP has a valid semantic model."
        }

    return {
        "measures": known_measures,
        "columns": known_columns,
        "tables": known_tables,
    }


def _find_tables_dir(pbip_path: str) -> Optional[str]:
    """Locate the tables/ directory within a PBIP project."""
    p = Path(pbip_path)

    # Handle .pbip file
    if p.is_file() and p.suffix == ".pbip":
        p = p.parent

    # Search for SemanticModel/definition/tables
    for sm in p.rglob("*.SemanticModel"):
        candidate = sm / "definition" / "tables"
        if candidate.is_dir():
            return str(candidate)

    # Direct definition/tables
    candidate = p / "definition" / "tables"
    if candidate.is_dir():
        return str(candidate)

    return None


_TMDL_MEASURE_RE = re.compile(r"^\s*measure\s+(?:'([^']+)'|(\S+))", re.MULTILINE)
_TMDL_COLUMN_RE = re.compile(r"^\s*column\s+(?:'([^']+)'|(\S+))", re.MULTILINE)


def _parse_tmdl_file(
    tmdl_path: Path,
    table_name: str,
    measures: Set[str],
    columns: Set[str],
) -> None:
    """Parse a TMDL file to extract measure and column names."""
    try:
        with open(tmdl_path, "r", encoding="utf-8") as f:
            content = f.read()

        for match in _TMDL_MEASURE_RE.finditer(content):
            name = match.group(1) or match.group(2)
            if name:
                measures.add(name)

        for match in _TMDL_COLUMN_RE.finditer(content):
            name = match.group(1) or match.group(2)
            if name:
                columns.add(name)
                columns.add(f"{table_name}[{name}]")

    except Exception as e:
        logger.warning("Error parsing TMDL %s: %s", tmdl_path, e)


# ─────────────────────────────────────────────────────────────────────
# Report directory resolution
# ─────────────────────────────────────────────────────────────────────

def _resolve_report_dir(pbip_path: str) -> Optional[str]:
    """Find the report directory (with pages/) for a PBIP project."""
    p = Path(pbip_path)

    # Handle .pbip file
    if p.is_file() and p.suffix == ".pbip":
        report_folder = p.parent / f"{p.stem}.Report"
        definition = report_folder / "definition"
        if definition.is_dir() and (definition / "pages").is_dir():
            return str(definition)
        p = p.parent

    # If pointed at a .Report/definition folder or .Report folder
    if p.is_dir():
        if p.name == "definition" and (p / "pages").is_dir():
            return str(p)
        if p.name.endswith(".Report"):
            definition = p / "definition"
            if definition.is_dir() and (definition / "pages").is_dir():
                return str(definition)

    # Search current dir for .Report folders
    search_dir = p if p.is_dir() else p.parent
    for item in search_dir.iterdir():
        if item.is_dir() and item.name.endswith(".Report"):
            definition = item / "definition"
            if definition.is_dir() and (definition / "pages").is_dir():
                return str(definition)

    return None


# ─────────────────────────────────────────────────────────────────────
# Visual JSON parsing
# ─────────────────────────────────────────────────────────────────────

def _get_page_name(page_folder: Path) -> str:
    """Get display name from page.json."""
    page_json = page_folder / "page.json"
    if page_json.exists():
        try:
            with open(page_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("displayName", page_folder.name)
        except Exception:
            pass
    return page_folder.name


def _extract_visual_title(visual_data: dict) -> str:
    """Extract display title from visual.json."""
    try:
        vc = visual_data.get("visual", {}).get("visualContainerObjects", {})
        title_list = vc.get("title", [])
        if not title_list:
            return ""
        props = title_list[0].get("properties", {})
        text = props.get("text", {})
        if isinstance(text, dict) and "expr" in text:
            expr = text["expr"]
            if isinstance(expr, dict) and "Literal" in expr:
                return expr["Literal"].get("Value", "").strip("'\"")
        return ""
    except Exception:
        return ""


def _extract_field_references(visual_data: dict) -> List[Dict[str, str]]:
    """Extract all field references from a visual.json structure."""
    refs: List[Dict[str, str]] = []
    _walk_for_refs(visual_data, refs)
    # Deduplicate (same field may appear multiple times in a visual)
    seen: Set[Tuple[str, str, str]] = set()
    unique: List[Dict[str, str]] = []
    for r in refs:
        key = (r["table"], r["field"], r["type"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _walk_for_refs(obj: Any, refs: List[Dict[str, str]], depth: int = 0) -> None:
    """Recursively walk JSON to find Column and Measure expression patterns."""
    if depth > 20:
        return

    if isinstance(obj, dict):
        # Column reference: {"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "C"}}
        if "Column" in obj:
            col = obj["Column"]
            if isinstance(col, dict):
                table = col.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                field = col.get("Property", "")
                if field:
                    refs.append({"table": table, "field": field, "type": "column"})

        # Measure reference: {"Measure": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "M"}}
        if "Measure" in obj:
            meas = obj["Measure"]
            if isinstance(meas, dict):
                table = meas.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                field = meas.get("Property", "")
                if field:
                    refs.append({"table": table, "field": field, "type": "measure"})

        for v in obj.values():
            _walk_for_refs(v, refs, depth + 1)

    elif isinstance(obj, list):
        for item in obj:
            _walk_for_refs(item, refs, depth + 1)


# ─────────────────────────────────────────────────────────────────────
# Reference validation
# ─────────────────────────────────────────────────────────────────────

def _check_reference(
    table: str,
    field: str,
    ref_type: str,
    known_measures: Set[str],
    known_columns: Set[str],
    known_tables: Set[str],
) -> Tuple[bool, str]:
    """
    Check if a field reference is broken.

    Returns:
        (is_broken, reason) tuple.
    """
    # Check table exists first (if specified)
    if table and table not in known_tables:
        return True, f"Table '{table}' not found in model"

    if ref_type == "measure":
        if field not in known_measures:
            return True, f"Measure '[{field}]' not found in model"

    elif ref_type == "column":
        qualified = f"{table}[{field}]" if table else field
        if qualified not in known_columns and field not in known_columns:
            return True, f"Column '{qualified}' not found in model"

    else:
        # Unknown type: check both
        if field not in known_measures:
            qualified = f"{table}[{field}]" if table else field
            if qualified not in known_columns and field not in known_columns:
                return True, f"Field '[{field}]' not found as measure or column"

    return False, ""
