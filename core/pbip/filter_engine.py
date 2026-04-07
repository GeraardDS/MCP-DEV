"""
PBIP Filter Engine - Manages filters at report, page, and visual level.

Filters live in ``filterConfig.filters`` arrays in:
- ``report.json``  (report-level)
- ``page.json``    (page-level)
- ``visual.json``  under ``visual.filters``  (visual-level)

All public functions return ``Dict[str, Any]`` with ``success: bool`` plus
data, or ``error: str`` on failure.  No MCP awareness.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pbip.authoring.id_generator import generate_visual_id
from core.utilities.pbip_utils import (
    load_json_file,
    save_json_file,
    get_page_display_name,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iter_pages(definition_path: Path):
    """Yield ``(page_folder, page_data)`` for every page in the definition."""
    pages_dir = definition_path / "pages"
    if not pages_dir.is_dir():
        return
    for page_folder in sorted(pages_dir.iterdir()):
        if not page_folder.is_dir():
            continue
        page_json_path = page_folder / "page.json"
        page_data = load_json_file(page_json_path)
        if page_data is not None:
            yield page_folder, page_data


def _iter_visuals(page_folder: Path):
    """Yield ``(visual_folder, visual_data)`` for every visual on a page."""
    visuals_dir = page_folder / "visuals"
    if not visuals_dir.is_dir():
        return
    for visual_folder in sorted(visuals_dir.iterdir()):
        if not visual_folder.is_dir():
            continue
        visual_json_path = visual_folder / "visual.json"
        visual_data = load_json_file(visual_json_path)
        if visual_data is not None:
            yield visual_folder, visual_data


def _resolve_page_folder(definition_path: Path, page_name: str) -> Optional[Path]:
    """Resolve a page display-name or ID to its folder."""
    pages_dir = definition_path / "pages"
    if not pages_dir.is_dir():
        return None

    name_lower = page_name.lower()
    for page_folder in pages_dir.iterdir():
        if not page_folder.is_dir():
            continue
        # Direct ID match
        if page_folder.name.lower() == name_lower:
            return page_folder
        # Display-name match
        display = get_page_display_name(page_folder)
        if display.lower() == name_lower:
            return page_folder
    return None


def _resolve_visual_folder(page_folder: Path, visual_name: str) -> Optional[Path]:
    """Resolve a visual ID or title to its folder inside a page."""
    visuals_dir = page_folder / "visuals"
    if not visuals_dir.is_dir():
        return None

    name_lower = visual_name.lower()
    for visual_folder in visuals_dir.iterdir():
        if not visual_folder.is_dir():
            continue
        # Direct ID match
        if visual_folder.name.lower() == name_lower:
            return visual_folder
        # Try matching by visual name stored in visual.json
        vdata = load_json_file(visual_folder / "visual.json")
        if vdata:
            if vdata.get("name", "").lower() == name_lower:
                return visual_folder
            # Match by title text in visualContainerObjects
            vco = vdata.get("visual", {}).get("visualContainerObjects", {})
            title_list = vco.get("title", [])
            for t in title_list:
                txt_expr = t.get("properties", {}).get("text", {})
                txt_val = _extract_literal_text(txt_expr)
                if txt_val and txt_val.lower() == name_lower:
                    return visual_folder
    return None


def _extract_literal_text(expr: Dict) -> Optional[str]:
    """Extract plain text from a Power BI Literal expression wrapper."""
    try:
        val = expr.get("expr", {}).get("Literal", {}).get("Value", "")
        if val.startswith("'") and val.endswith("'"):
            return val[1:-1]
        return val or None
    except (AttributeError, TypeError):
        return None


def _summarize_filter(filt: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact summary dict for a single PBIR filter."""
    field = filt.get("field", {})
    table = ""
    column = ""
    field_type = "Unknown"

    if "Column" in field:
        field_type = "Column"
        col_def = field["Column"]
        table = col_def.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
        column = col_def.get("Property", "")
    elif "Measure" in field:
        field_type = "Measure"
        m_def = field["Measure"]
        table = m_def.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
        column = m_def.get("Property", "")

    values: List[str] = []
    where_list = filt.get("filter", {}).get("Where", [])
    for where in where_list:
        cond = where.get("Condition", {})
        if "In" in cond:
            for vgroup in cond["In"].get("Values", []):
                for v in vgroup:
                    lit = v.get("Literal", {}).get("Value", "")
                    if lit.startswith("'") and lit.endswith("'"):
                        lit = lit[1:-1]
                    values.append(lit)

    return {
        "name": filt.get("name", ""),
        "type": filt.get("type", ""),
        "field_type": field_type,
        "table": table,
        "field": column,
        "howCreated": filt.get("howCreated", ""),
        "values": values,
    }


def _build_source_alias(table: str) -> str:
    """Generate a short alias for a table name (first lowercase char)."""
    for ch in table:
        if ch.isalpha():
            return ch.lower()
    return "t"


def _build_filter_dict(
    table: str,
    field: str,
    filter_type: str,
    values: Optional[List] = None,
    operator: Optional[str] = None,
    by_table: Optional[str] = None,
    by_field: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a complete PBIR filter dict."""
    filter_id = generate_visual_id()
    alias = _build_source_alias(table)

    # Field reference
    field_ref: Dict[str, Any] = {
        "Column": {
            "Expression": {"SourceRef": {"Entity": table}},
            "Property": field,
        }
    }

    # Base filter structure
    filt: Dict[str, Any] = {
        "name": filter_id,
        "field": field_ref,
        "type": filter_type,
        "howCreated": "User",
    }

    # Build Where clause depending on type
    column_expr = {
        "Column": {
            "Expression": {"SourceRef": {"Source": alias}},
            "Property": field,
        }
    }

    if filter_type == "Categorical":
        where_values = []
        for v in (values or []):
            if isinstance(v, str):
                where_values.append([{"Literal": {"Value": f"'{v}'"}}])
            elif isinstance(v, (int, float)):
                where_values.append([{"Literal": {"Value": f"{v}D"}}])
            elif isinstance(v, bool):
                where_values.append([{"Literal": {"Value": "true" if v else "false"}}])
            else:
                where_values.append([{"Literal": {"Value": f"'{v}'"}}])

        filt["filter"] = {
            "Version": 2,
            "From": [{"Name": alias, "Entity": table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [column_expr],
                            "Values": where_values,
                        }
                    }
                }
            ],
        }

    elif filter_type == "Advanced":
        # Map friendly operator names to Power BI ComparisonKind integers
        comparison_map = {
            "GreaterThan": 0,
            "GreaterThanOrEqual": 1,
            "LessThan": 2,
            "LessThanOrEqual": 3,
            "Equal": 4,
            "NotEqual": 5,
        }
        comp_kind = comparison_map.get(operator or "GreaterThan", 0)
        right_value = values[0] if values else 0
        if isinstance(right_value, str):
            right_literal = f"'{right_value}'"
        elif isinstance(right_value, (int, float)):
            right_literal = f"{right_value}D"
        else:
            right_literal = f"'{right_value}'"

        filt["filter"] = {
            "Version": 2,
            "From": [{"Name": alias, "Entity": table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Comparison": {
                            "ComparisonKind": comp_kind,
                            "Left": column_expr,
                            "Right": {"Literal": {"Value": right_literal}},
                        }
                    }
                }
            ],
        }

    elif filter_type == "TopN":
        n = int(values[0]) if values else 10
        direction = operator or "Top"
        by_alias = _build_source_alias(by_table or table)

        by_expr: Dict[str, Any]
        if by_table and by_field:
            by_expr = {
                "Measure": {
                    "Expression": {"SourceRef": {"Source": by_alias}},
                    "Property": by_field,
                }
            }
        else:
            by_expr = column_expr

        from_entries = [{"Name": alias, "Entity": table, "Type": 0}]
        if by_table and by_table != table:
            from_entries.append({"Name": by_alias, "Entity": by_table, "Type": 0})

        filt["filter"] = {
            "Version": 2,
            "From": from_entries,
            "Where": [
                {
                    "Condition": {
                        "Top": {
                            "Expression": column_expr,
                            "Count": n,
                            "Direction": 0 if direction == "Top" else 1,
                            "OrderBy": by_expr,
                        }
                    }
                }
            ],
        }

    elif filter_type == "RelativeDate":
        # Basic relative-date skeleton; callers typically provide
        # values = [n_periods] and operator = "InLast" / "InThis" / "InNext"
        n_periods = int(values[0]) if values else 1
        time_unit_map = {"Days": 0, "Weeks": 1, "Months": 2, "Quarters": 3, "Years": 4}
        time_unit = 2  # default months
        if len(values) > 1 and isinstance(values[1], str):
            time_unit = time_unit_map.get(values[1], 2)

        include_today = True
        anchor_map = {"InLast": 0, "InThis": 1, "InNext": 2}
        anchor = anchor_map.get(operator or "InLast", 0)

        filt["filter"] = {
            "Version": 2,
            "From": [{"Name": alias, "Entity": table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "RelativeDate": {
                            "Expression": column_expr,
                            "TimeUnit": time_unit,
                            "NumberOfPeriods": n_periods,
                            "Anchor": anchor,
                            "IncludeToday": include_today,
                        }
                    }
                }
            ],
        }

    return filt


def _get_filters_from_container(data: Dict[str, Any], level: str) -> List[Dict[str, Any]]:
    """Extract the filters list from a report/page/visual container dict.

    For report and page the path is ``filterConfig.filters``.
    For visual the path is ``visual.filters``.
    """
    if level == "visual":
        return data.get("visual", {}).get("filters", [])
    return data.get("filterConfig", {}).get("filters", [])


def _set_filters_on_container(data: Dict[str, Any], level: str, filters: List[Dict[str, Any]]) -> None:
    """Write *filters* back into the appropriate location in *data*."""
    if level == "visual":
        data.setdefault("visual", {})["filters"] = filters
    else:
        data.setdefault("filterConfig", {})["filters"] = filters


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_filters(
    definition_path: Path,
    level: str = "all",
    page_name: Optional[str] = None,
    visual_name: Optional[str] = None,
) -> Dict[str, Any]:
    """List filters at the requested level(s).

    Args:
        definition_path: Path to the report ``definition/`` folder.
        level: ``'report'``, ``'page'``, ``'visual'``, or ``'all'``.
        page_name: Restrict to a specific page (display-name or ID).
        visual_name: Restrict to a specific visual (ID or title).

    Returns:
        ``{success, report_filters, page_filters, visual_filters}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    if not definition_path.is_dir():
        return {"success": False, "error": f"Definition path not found: {definition_path}"}

    result: Dict[str, Any] = {
        "success": True,
        "report_filters": [],
        "page_filters": [],
        "visual_filters": [],
    }

    # --- Report-level ---
    if level in ("report", "all"):
        report_json_path = definition_path / "report.json"
        report_data = load_json_file(report_json_path)
        if report_data:
            for f in _get_filters_from_container(report_data, "report"):
                result["report_filters"].append(_summarize_filter(f))

    # --- Page-level ---
    if level in ("page", "all"):
        for page_folder, page_data in _iter_pages(definition_path):
            display = page_data.get("displayName", page_folder.name)
            if page_name and display.lower() != page_name.lower() and page_folder.name.lower() != page_name.lower():
                continue
            page_filters = _get_filters_from_container(page_data, "page")
            for f in page_filters:
                summary = _summarize_filter(f)
                summary["page"] = display
                result["page_filters"].append(summary)

    # --- Visual-level ---
    if level in ("visual", "all"):
        for page_folder, page_data in _iter_pages(definition_path):
            display = page_data.get("displayName", page_folder.name)
            if page_name and display.lower() != page_name.lower() and page_folder.name.lower() != page_name.lower():
                continue
            for visual_folder, visual_data in _iter_visuals(page_folder):
                vis_name = visual_data.get("name", visual_folder.name)
                if visual_name and vis_name.lower() != visual_name.lower():
                    # Also try title match
                    matched = False
                    vco = visual_data.get("visual", {}).get("visualContainerObjects", {})
                    for t in vco.get("title", []):
                        txt = _extract_literal_text(t.get("properties", {}).get("text", {}))
                        if txt and txt.lower() == visual_name.lower():
                            matched = True
                            break
                    if not matched:
                        continue

                vis_filters = _get_filters_from_container(visual_data, "visual")
                for f in vis_filters:
                    summary = _summarize_filter(f)
                    summary["page"] = display
                    summary["visual"] = vis_name
                    result["visual_filters"].append(summary)

    total = (
        len(result["report_filters"])
        + len(result["page_filters"])
        + len(result["visual_filters"])
    )
    result["total_filters"] = total
    return result


def add_filter(
    definition_path: Path,
    level: str,
    table: str,
    field: str,
    filter_type: str = "Categorical",
    values: Optional[List] = None,
    page_name: Optional[str] = None,
    visual_name: Optional[str] = None,
    operator: Optional[str] = None,
    by_table: Optional[str] = None,
    by_field: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a new filter at the specified level.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        level: ``'report'``, ``'page'``, or ``'visual'``.
        table: Source table name.
        field: Column or measure name.
        filter_type: ``'Categorical'``, ``'Advanced'``, ``'TopN'``, ``'RelativeDate'``.
        values: Filter values (semantics depend on *filter_type*).
        page_name: Required for page/visual level.
        visual_name: Required for visual level.
        operator: Comparison operator for Advanced, direction for TopN, anchor for RelativeDate.
        by_table: Table of the ordering measure (TopN only).
        by_field: Ordering measure name (TopN only).

    Returns:
        ``{success, filter_id}`` or ``{error}``.
    """
    definition_path = Path(definition_path)

    new_filter = _build_filter_dict(
        table=table,
        field=field,
        filter_type=filter_type,
        values=values,
        operator=operator,
        by_table=by_table,
        by_field=by_field,
    )

    if level == "report":
        report_json_path = definition_path / "report.json"
        report_data = load_json_file(report_json_path)
        if report_data is None:
            return {"success": False, "error": f"Cannot read report.json at {report_json_path}"}

        filters = _get_filters_from_container(report_data, "report")
        filters.append(new_filter)
        _set_filters_on_container(report_data, "report", filters)

        if not save_json_file(report_json_path, report_data):
            return {"success": False, "error": "Failed to write report.json"}

        return {"success": True, "filter_id": new_filter["name"], "level": "report"}

    elif level == "page":
        if not page_name:
            return {"success": False, "error": "page_name is required for page-level filters"}

        page_folder = _resolve_page_folder(definition_path, page_name)
        if not page_folder:
            return {"success": False, "error": f"Page not found: {page_name}"}

        page_json_path = page_folder / "page.json"
        page_data = load_json_file(page_json_path)
        if page_data is None:
            return {"success": False, "error": f"Cannot read page.json at {page_json_path}"}

        filters = _get_filters_from_container(page_data, "page")
        filters.append(new_filter)
        _set_filters_on_container(page_data, "page", filters)

        if not save_json_file(page_json_path, page_data):
            return {"success": False, "error": "Failed to write page.json"}

        return {"success": True, "filter_id": new_filter["name"], "level": "page", "page": page_name}

    elif level == "visual":
        if not page_name:
            return {"success": False, "error": "page_name is required for visual-level filters"}
        if not visual_name:
            return {"success": False, "error": "visual_name is required for visual-level filters"}

        page_folder = _resolve_page_folder(definition_path, page_name)
        if not page_folder:
            return {"success": False, "error": f"Page not found: {page_name}"}

        visual_folder = _resolve_visual_folder(page_folder, visual_name)
        if not visual_folder:
            return {"success": False, "error": f"Visual not found: {visual_name}"}

        visual_json_path = visual_folder / "visual.json"
        visual_data = load_json_file(visual_json_path)
        if visual_data is None:
            return {"success": False, "error": f"Cannot read visual.json at {visual_json_path}"}

        filters = _get_filters_from_container(visual_data, "visual")
        filters.append(new_filter)
        _set_filters_on_container(visual_data, "visual", filters)

        if not save_json_file(visual_json_path, visual_data):
            return {"success": False, "error": "Failed to write visual.json"}

        return {
            "success": True,
            "filter_id": new_filter["name"],
            "level": "visual",
            "page": page_name,
            "visual": visual_name,
        }

    return {"success": False, "error": f"Invalid level: {level}. Must be 'report', 'page', or 'visual'."}


def set_filter_values(
    definition_path: Path,
    filter_name: str,
    values: List,
    level: Optional[str] = None,
    page_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Update the values of an existing filter identified by name/ID.

    Searches across all levels unless *level* is specified.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        filter_name: The filter's ``name`` (20-char hex ID) or partial match.
        values: New list of filter values.
        level: Optional restriction to ``'report'``, ``'page'``, or ``'visual'``.
        page_name: Optional page restriction.

    Returns:
        ``{success, updated_at}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    name_lower = filter_name.lower()

    def _update_in(container_data: Dict, container_level: str, json_path: Path, context: str) -> Optional[Dict[str, Any]]:
        """Try to find and update the filter inside *container_data*. Returns result or None."""
        filters = _get_filters_from_container(container_data, container_level)
        for filt in filters:
            if filt.get("name", "").lower() == name_lower:
                # Rebuild the Where.In.Values block
                new_vals = []
                for v in values:
                    if isinstance(v, str):
                        new_vals.append([{"Literal": {"Value": f"'{v}'"}}])
                    elif isinstance(v, (int, float)):
                        new_vals.append([{"Literal": {"Value": f"{v}D"}}])
                    elif isinstance(v, bool):
                        new_vals.append([{"Literal": {"Value": "true" if v else "false"}}])
                    else:
                        new_vals.append([{"Literal": {"Value": f"'{v}'"}}])

                where_list = filt.get("filter", {}).get("Where", [])
                for w in where_list:
                    cond = w.get("Condition", {})
                    if "In" in cond:
                        cond["In"]["Values"] = new_vals
                        break

                _set_filters_on_container(container_data, container_level, filters)
                if save_json_file(json_path, container_data):
                    return {"success": True, "updated_at": context, "filter_name": filter_name}
                return {"success": False, "error": f"Failed to save {json_path}"}
        return None

    # Search report level
    if level in (None, "report"):
        report_json_path = definition_path / "report.json"
        report_data = load_json_file(report_json_path)
        if report_data:
            r = _update_in(report_data, "report", report_json_path, "report")
            if r:
                return r

    # Search page level
    if level in (None, "page", "visual"):
        for page_folder, page_data in _iter_pages(definition_path):
            display = page_data.get("displayName", page_folder.name)
            if page_name and display.lower() != page_name.lower() and page_folder.name.lower() != page_name.lower():
                continue

            if level in (None, "page"):
                r = _update_in(page_data, "page", page_folder / "page.json", f"page:{display}")
                if r:
                    return r

            # Search visual level
            if level in (None, "visual"):
                for visual_folder, visual_data in _iter_visuals(page_folder):
                    r = _update_in(visual_data, "visual", visual_folder / "visual.json", f"visual:{visual_folder.name}@{display}")
                    if r:
                        return r

    return {"success": False, "error": f"Filter not found: {filter_name}"}


def clear_filters(
    definition_path: Path,
    level: str,
    page_name: Optional[str] = None,
    visual_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Remove all filters at the specified level.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        level: ``'report'``, ``'page'``, or ``'visual'``.
        page_name: Required for page/visual level.
        visual_name: Required for visual level.

    Returns:
        ``{success, cleared_count}`` or ``{error}``.
    """
    definition_path = Path(definition_path)

    if level == "report":
        report_json_path = definition_path / "report.json"
        report_data = load_json_file(report_json_path)
        if report_data is None:
            return {"success": False, "error": "Cannot read report.json"}

        old = _get_filters_from_container(report_data, "report")
        count = len(old)
        _set_filters_on_container(report_data, "report", [])
        if not save_json_file(report_json_path, report_data):
            return {"success": False, "error": "Failed to write report.json"}
        return {"success": True, "cleared_count": count, "level": "report"}

    elif level == "page":
        if not page_name:
            return {"success": False, "error": "page_name is required for page-level clear"}

        page_folder = _resolve_page_folder(definition_path, page_name)
        if not page_folder:
            return {"success": False, "error": f"Page not found: {page_name}"}

        page_json_path = page_folder / "page.json"
        page_data = load_json_file(page_json_path)
        if page_data is None:
            return {"success": False, "error": f"Cannot read page.json at {page_json_path}"}

        old = _get_filters_from_container(page_data, "page")
        count = len(old)
        _set_filters_on_container(page_data, "page", [])
        if not save_json_file(page_json_path, page_data):
            return {"success": False, "error": "Failed to write page.json"}
        return {"success": True, "cleared_count": count, "level": "page", "page": page_name}

    elif level == "visual":
        if not page_name:
            return {"success": False, "error": "page_name is required for visual-level clear"}
        if not visual_name:
            return {"success": False, "error": "visual_name is required for visual-level clear"}

        page_folder = _resolve_page_folder(definition_path, page_name)
        if not page_folder:
            return {"success": False, "error": f"Page not found: {page_name}"}

        visual_folder = _resolve_visual_folder(page_folder, visual_name)
        if not visual_folder:
            return {"success": False, "error": f"Visual not found: {visual_name}"}

        visual_json_path = visual_folder / "visual.json"
        visual_data = load_json_file(visual_json_path)
        if visual_data is None:
            return {"success": False, "error": f"Cannot read visual.json at {visual_json_path}"}

        old = _get_filters_from_container(visual_data, "visual")
        count = len(old)
        _set_filters_on_container(visual_data, "visual", [])
        if not save_json_file(visual_json_path, visual_data):
            return {"success": False, "error": "Failed to write visual.json"}
        return {"success": True, "cleared_count": count, "level": "visual", "page": page_name, "visual": visual_name}

    return {"success": False, "error": f"Invalid level: {level}"}


def set_filter_visibility(
    definition_path: Path,
    filter_name: str,
    hidden: bool,
    level: Optional[str] = None,
    page_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Hide or unhide a filter in the filter pane.

    Sets ``objects.general.isHiddenInViewMode`` on the matching filter.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        filter_name: The filter's ``name`` (20-char hex ID).
        hidden: ``True`` to hide, ``False`` to show.
        level: Optional level restriction.
        page_name: Optional page restriction.

    Returns:
        ``{success}`` or ``{error}``.
    """
    return _set_filter_property(
        definition_path, filter_name, "isHiddenInViewMode", hidden, level, page_name
    )


def set_filter_lock(
    definition_path: Path,
    filter_name: str,
    locked: bool,
    level: Optional[str] = None,
    page_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Lock or unlock a filter.

    Sets ``objects.general.isLockedInViewMode`` on the matching filter.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        filter_name: The filter's ``name`` (20-char hex ID).
        locked: ``True`` to lock, ``False`` to unlock.
        level: Optional level restriction.
        page_name: Optional page restriction.

    Returns:
        ``{success}`` or ``{error}``.
    """
    return _set_filter_property(
        definition_path, filter_name, "isLockedInViewMode", locked, level, page_name
    )


def _set_filter_property(
    definition_path: Path,
    filter_name: str,
    prop_name: str,
    prop_value: bool,
    level: Optional[str],
    page_name: Optional[str],
) -> Dict[str, Any]:
    """Generic helper to set a boolean property inside a filter's ``objects.general``."""
    definition_path = Path(definition_path)
    name_lower = filter_name.lower()

    bool_literal = {"expr": {"Literal": {"Value": "true" if prop_value else "false"}}}

    def _apply(container_data: Dict, container_level: str, json_path: Path, context: str) -> Optional[Dict[str, Any]]:
        filters = _get_filters_from_container(container_data, container_level)
        for filt in filters:
            if filt.get("name", "").lower() == name_lower:
                objects = filt.setdefault("objects", {})
                general_list = objects.setdefault("general", [{}])
                if not general_list:
                    general_list.append({})
                general_list[0].setdefault("properties", {})[prop_name] = bool_literal

                _set_filters_on_container(container_data, container_level, filters)
                if save_json_file(json_path, container_data):
                    return {"success": True, "filter_name": filter_name, "property": prop_name, "value": prop_value, "at": context}
                return {"success": False, "error": f"Failed to save {json_path}"}
        return None

    # Search report
    if level in (None, "report"):
        report_json_path = definition_path / "report.json"
        report_data = load_json_file(report_json_path)
        if report_data:
            r = _apply(report_data, "report", report_json_path, "report")
            if r:
                return r

    # Search pages and visuals
    if level in (None, "page", "visual"):
        for page_folder, page_data in _iter_pages(definition_path):
            display = page_data.get("displayName", page_folder.name)
            if page_name and display.lower() != page_name.lower() and page_folder.name.lower() != page_name.lower():
                continue

            if level in (None, "page"):
                r = _apply(page_data, "page", page_folder / "page.json", f"page:{display}")
                if r:
                    return r

            if level in (None, "visual"):
                for visual_folder, visual_data in _iter_visuals(page_folder):
                    r = _apply(visual_data, "visual", visual_folder / "visual.json", f"visual:{visual_folder.name}@{display}")
                    if r:
                        return r

    return {"success": False, "error": f"Filter not found: {filter_name}"}
