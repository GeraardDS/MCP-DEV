"""
PBIP Conditional Formatting Engine - Manages CF rules on visuals.

Conditional formatting rules are stored in ``visual.json`` under
``visual.objects.{container}[].properties.{prop}`` with special ``rules``
or ``solid.color`` structures that reference expressions/measures.

All public functions return ``Dict[str, Any]`` with ``success: bool`` plus
data, or ``error: str`` on failure.  No MCP awareness.
"""

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        if page_folder.name.lower() == name_lower:
            return page_folder
        display = get_page_display_name(page_folder)
        if display.lower() == name_lower:
            return page_folder
    return None


def _resolve_visual(page_folder: Path, visual_name: str) -> Optional[tuple]:
    """Resolve a visual ID or title to ``(visual_folder, visual_data)``."""
    visuals_dir = page_folder / "visuals"
    if not visuals_dir.is_dir():
        return None

    name_lower = visual_name.lower()
    for vf in visuals_dir.iterdir():
        if not vf.is_dir():
            continue
        vdata = load_json_file(vf / "visual.json")
        if vdata is None:
            continue

        # Direct folder-name or visual name match
        if vf.name.lower() == name_lower or vdata.get("name", "").lower() == name_lower:
            return vf, vdata

        # Title match
        vco = vdata.get("visual", {}).get("visualContainerObjects", {})
        for t in vco.get("title", []):
            txt = t.get("properties", {}).get("text", {})
            lit = txt.get("expr", {}).get("Literal", {}).get("Value", "")
            if lit.startswith("'") and lit.endswith("'"):
                lit = lit[1:-1]
            if lit.lower() == name_lower:
                return vf, vdata

    return None


def _is_cf_property(prop_value: Any) -> bool:
    """Check whether a property value looks like a conditional-formatting entry.

    CF entries typically contain ``rules``, ``expr`` with ``FillRule``/``Conditional``,
    or a ``solid.color.expr`` with a measure/conditional reference.
    """
    if not isinstance(prop_value, dict):
        return False

    # Direct rules array
    if "rules" in prop_value:
        return True

    # Expression-based CF (color scales, data bars, etc.)
    expr = prop_value.get("expr") or prop_value.get("solid", {}).get("color", {}).get("expr")
    if isinstance(expr, dict):
        if "FillRule" in expr or "Conditional" in expr or "Aggregation" in expr:
            return True
        # Measure-driven colour
        if "Measure" in expr:
            return True

    return False


def _extract_cf_info(
    container_name: str,
    prop_name: str,
    prop_value: Any,
) -> Dict[str, Any]:
    """Build a summary dict describing one CF entry."""
    info: Dict[str, Any] = {
        "container": container_name,
        "property": prop_name,
        "type": "unknown",
        "details": {},
    }

    if "rules" in prop_value:
        info["type"] = "rules"
        info["details"]["rule_count"] = len(prop_value["rules"])
        return info

    expr = (
        prop_value.get("expr")
        or prop_value.get("solid", {}).get("color", {}).get("expr")
    )
    if isinstance(expr, dict):
        if "FillRule" in expr:
            fill_rule = expr["FillRule"]
            info["type"] = "color_scale"
            strategy = fill_rule.get("Strategy", {})
            info["details"]["strategy"] = list(strategy.keys()) if strategy else []
            # Extract min/max colours if available
            for bound in ("Minimum", "Maximum", "MidPoint"):
                bound_data = fill_rule.get(bound)
                if isinstance(bound_data, dict):
                    color_val = bound_data.get("Color", bound_data.get("color", ""))
                    info["details"][bound.lower()] = color_val
            return info

        if "Conditional" in expr:
            info["type"] = "conditional"
            cond = expr["Conditional"]
            info["details"]["cases"] = len(cond.get("Cases", []))
            return info

        if "Measure" in expr:
            info["type"] = "measure_based"
            measure = expr["Measure"]
            info["details"]["table"] = (
                measure.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
            )
            info["details"]["measure"] = measure.get("Property", "")
            return info

    return info


def _build_color_scale_expr(
    table: str,
    field: str,
    min_color: str,
    max_color: str,
    mid_color: Optional[str] = None,
    field_type: str = "Column",
) -> Dict[str, Any]:
    """Build a FillRule expression for a colour-scale CF rule."""
    if field_type == "Measure":
        input_expr = {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": field,
            }
        }
    else:
        input_expr = {
            "Column": {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": field,
            }
        }

    fill_rule: Dict[str, Any] = {
        "Input": input_expr,
        "Minimum": {"Color": min_color},
        "Maximum": {"Color": max_color},
    }

    if mid_color:
        fill_rule["MidPoint"] = {"Color": mid_color}

    return {"expr": {"FillRule": fill_rule}}


def _build_rules_array(rules_config: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a ``rules`` array from a simplified config.

    Each entry in *rules_config*: ``{value, operator, color}``
    - ``operator``: ``"GreaterThan"``, ``"LessThan"``, ``"Equal"``, etc.
    """
    rules = []
    for rc in rules_config:
        rule: Dict[str, Any] = {}
        if "value" in rc:
            rule["value"] = rc["value"]
        if "operator" in rc:
            rule["inputRole"] = rc.get("input_role", "Value")
            rule["operator"] = rc["operator"]
        if "color" in rc:
            rule["color"] = rc["color"]
        rules.append(rule)
    return {"rules": rules}


def _build_data_bars_expr(
    table: str,
    field: str,
    positive_color: str = "#2196F3",
    negative_color: str = "#F44336",
    field_type: str = "Column",
) -> Dict[str, Any]:
    """Build an expression for data-bar CF."""
    if field_type == "Measure":
        input_expr = {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": field,
            }
        }
    else:
        input_expr = {
            "Column": {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": field,
            }
        }

    return {
        "expr": {
            "FillRule": {
                "Input": input_expr,
                "Strategy": {"DataBars": True},
                "Minimum": {"Color": negative_color},
                "Maximum": {"Color": positive_color},
            }
        }
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_rules(
    definition_path: Path,
    page_name: Optional[str] = None,
    visual_name: Optional[str] = None,
) -> Dict[str, Any]:
    """List all conditional formatting rules across visuals.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        page_name: Optional page restriction.
        visual_name: Optional visual restriction.

    Returns:
        ``{success, rules, count}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    if not definition_path.is_dir():
        return {"success": False, "error": f"Definition path not found: {definition_path}"}

    results: List[Dict[str, Any]] = []

    for page_folder, page_data in _iter_pages(definition_path):
        display = page_data.get("displayName", page_folder.name)
        if page_name and display.lower() != page_name.lower() and page_folder.name.lower() != page_name.lower():
            continue

        for visual_folder, visual_data in _iter_visuals(page_folder):
            vis_name = visual_data.get("name", visual_folder.name)
            vis_type = visual_data.get("visual", {}).get("visualType", "")

            if visual_name:
                # Check by ID
                if vis_name.lower() != visual_name.lower() and visual_folder.name.lower() != visual_name.lower():
                    # Check by title
                    matched = False
                    vco = visual_data.get("visual", {}).get("visualContainerObjects", {})
                    for t in vco.get("title", []):
                        txt = t.get("properties", {}).get("text", {})
                        lit = txt.get("expr", {}).get("Literal", {}).get("Value", "")
                        if lit.startswith("'") and lit.endswith("'"):
                            lit = lit[1:-1]
                        if lit.lower() == visual_name.lower():
                            matched = True
                            break
                    if not matched:
                        continue

            objects = visual_data.get("visual", {}).get("objects", {})
            for container_name, container_entries in objects.items():
                if not isinstance(container_entries, list):
                    continue
                for entry in container_entries:
                    props = entry.get("properties", {})
                    for prop_name, prop_value in props.items():
                        if _is_cf_property(prop_value):
                            rule_info = _extract_cf_info(container_name, prop_name, prop_value)
                            rule_info["page"] = display
                            rule_info["visual"] = vis_name
                            rule_info["visual_type"] = vis_type
                            results.append(rule_info)

    return {"success": True, "rules": results, "count": len(results)}


def add_rule(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    container: str,
    property_name: str,
    rule_type: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Add a conditional formatting rule to a visual.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        page_name: Page display name or ID.
        visual_name: Visual ID or title.
        container: Object container name (e.g., ``"values"``, ``"dataPoint"``).
        property_name: Property to format (e.g., ``"fill"``, ``"fontColor"``).
        rule_type: ``'color_scale'``, ``'rules'``, ``'data_bars'``, ``'icons'``.
        config: Configuration dict (contents depend on *rule_type*):
            - **color_scale**: ``{table, field, min_color, max_color, mid_color?, field_type?}``
            - **rules**: ``{rules: [{value, operator, color}, ...]}``
            - **data_bars**: ``{table, field, positive_color?, negative_color?, field_type?}``
            - **icons**: ``{table, field, icon_set?}``

    Returns:
        ``{success, container, property}`` or ``{error}``.
    """
    definition_path = Path(definition_path)

    page_folder = _resolve_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: {page_name}"}

    resolved = _resolve_visual(page_folder, visual_name)
    if not resolved:
        return {"success": False, "error": f"Visual not found: {visual_name}"}
    visual_folder, visual_data = resolved

    # Build the CF property value
    cf_value: Dict[str, Any]

    if rule_type == "color_scale":
        table = config.get("table", "")
        field = config.get("field", "")
        if not table or not field:
            return {"success": False, "error": "color_scale requires 'table' and 'field' in config"}
        cf_value = _build_color_scale_expr(
            table=table,
            field=field,
            min_color=config.get("min_color", "#FFFFFF"),
            max_color=config.get("max_color", "#118DFF"),
            mid_color=config.get("mid_color"),
            field_type=config.get("field_type", "Column"),
        )

    elif rule_type == "rules":
        rules_list = config.get("rules", [])
        if not rules_list:
            return {"success": False, "error": "'rules' config requires a 'rules' list"}
        cf_value = _build_rules_array(rules_list)

    elif rule_type == "data_bars":
        table = config.get("table", "")
        field = config.get("field", "")
        if not table or not field:
            return {"success": False, "error": "data_bars requires 'table' and 'field' in config"}
        cf_value = _build_data_bars_expr(
            table=table,
            field=field,
            positive_color=config.get("positive_color", "#2196F3"),
            negative_color=config.get("negative_color", "#F44336"),
            field_type=config.get("field_type", "Column"),
        )

    elif rule_type == "icons":
        # Icon sets are less common; provide a basic skeleton
        table = config.get("table", "")
        field = config.get("field", "")
        if not table or not field:
            return {"success": False, "error": "icons requires 'table' and 'field' in config"}
        icon_set = config.get("icon_set", "Arrows3")
        cf_value = {
            "expr": {
                "Conditional": {
                    "IconSet": icon_set,
                    "Expression": {
                        "Column": {
                            "Expression": {"SourceRef": {"Entity": table}},
                            "Property": field,
                        }
                    },
                }
            }
        }

    else:
        return {"success": False, "error": f"Unknown rule_type: {rule_type}. Use: color_scale, rules, data_bars, icons"}

    # Insert into visual objects
    objects = visual_data.setdefault("visual", {}).setdefault("objects", {})
    container_list = objects.setdefault(container, [{}])
    if not container_list:
        container_list.append({})

    container_list[0].setdefault("properties", {})[property_name] = cf_value

    visual_json_path = visual_folder / "visual.json"
    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": f"Failed to write visual.json at {visual_json_path}"}

    return {
        "success": True,
        "container": container,
        "property": property_name,
        "rule_type": rule_type,
        "page": page_name,
        "visual": visual_name,
    }


def remove_rule(
    definition_path: Path,
    page_name: str,
    visual_name: str,
    container: str,
    property_name: str,
) -> Dict[str, Any]:
    """Remove conditional formatting from a specific property.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        page_name: Page display name or ID.
        visual_name: Visual ID or title.
        container: Object container name.
        property_name: Property to remove CF from.

    Returns:
        ``{success, removed}`` or ``{error}``.
    """
    definition_path = Path(definition_path)

    page_folder = _resolve_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: {page_name}"}

    resolved = _resolve_visual(page_folder, visual_name)
    if not resolved:
        return {"success": False, "error": f"Visual not found: {visual_name}"}
    visual_folder, visual_data = resolved

    objects = visual_data.get("visual", {}).get("objects", {})
    container_list = objects.get(container, [])

    removed = False
    for entry in container_list:
        props = entry.get("properties", {})
        if property_name in props:
            if _is_cf_property(props[property_name]):
                del props[property_name]
                removed = True
                break

    if not removed:
        return {
            "success": False,
            "error": f"No CF rule found for {container}.{property_name} on visual {visual_name}",
        }

    # Clean up empty containers
    for entry in list(container_list):
        if not entry.get("properties"):
            container_list.remove(entry)
    if not container_list:
        objects.pop(container, None)

    visual_json_path = visual_folder / "visual.json"
    if not save_json_file(visual_json_path, visual_data):
        return {"success": False, "error": f"Failed to write visual.json at {visual_json_path}"}

    return {
        "success": True,
        "removed": True,
        "container": container,
        "property": property_name,
        "page": page_name,
        "visual": visual_name,
    }


def copy_rule(
    definition_path: Path,
    source_page: str,
    source_visual: str,
    target_page: str,
    target_visual: str,
    container: str,
    property_name: str,
) -> Dict[str, Any]:
    """Copy conditional formatting rules from one visual to another.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        source_page: Source page display name or ID.
        source_visual: Source visual ID or title.
        target_page: Target page display name or ID.
        target_visual: Target visual ID or title.
        container: Object container name to copy from/to.
        property_name: Property name to copy.

    Returns:
        ``{success}`` or ``{error}``.
    """
    definition_path = Path(definition_path)

    # --- Read source ---
    src_page_folder = _resolve_page_folder(definition_path, source_page)
    if not src_page_folder:
        return {"success": False, "error": f"Source page not found: {source_page}"}

    src_resolved = _resolve_visual(src_page_folder, source_visual)
    if not src_resolved:
        return {"success": False, "error": f"Source visual not found: {source_visual}"}
    _src_folder, src_data = src_resolved

    src_objects = src_data.get("visual", {}).get("objects", {})
    src_container_list = src_objects.get(container, [])

    cf_value = None
    for entry in src_container_list:
        props = entry.get("properties", {})
        if property_name in props and _is_cf_property(props[property_name]):
            cf_value = copy.deepcopy(props[property_name])
            break

    if cf_value is None:
        return {
            "success": False,
            "error": f"No CF rule found for {container}.{property_name} on source visual {source_visual}",
        }

    # --- Write target ---
    tgt_page_folder = _resolve_page_folder(definition_path, target_page)
    if not tgt_page_folder:
        return {"success": False, "error": f"Target page not found: {target_page}"}

    tgt_resolved = _resolve_visual(tgt_page_folder, target_visual)
    if not tgt_resolved:
        return {"success": False, "error": f"Target visual not found: {target_visual}"}
    tgt_folder, tgt_data = tgt_resolved

    tgt_objects = tgt_data.setdefault("visual", {}).setdefault("objects", {})
    tgt_container_list = tgt_objects.setdefault(container, [{}])
    if not tgt_container_list:
        tgt_container_list.append({})

    tgt_container_list[0].setdefault("properties", {})[property_name] = cf_value

    tgt_json_path = tgt_folder / "visual.json"
    if not save_json_file(tgt_json_path, tgt_data):
        return {"success": False, "error": f"Failed to write visual.json at {tgt_json_path}"}

    return {
        "success": True,
        "container": container,
        "property": property_name,
        "source": f"{source_visual}@{source_page}",
        "target": f"{target_visual}@{target_page}",
    }
