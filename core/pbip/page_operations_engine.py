"""
Page Operations Engine for PBIP Reports

Page-level operations beyond create/clone/delete (which exist in clone_engine.py
and page_builder.py). Handles reordering, resizing, display options, backgrounds,
wallpapers, drillthrough configuration, tooltip pages, and visibility.

No MCP awareness — pure domain logic operating on PBIP file structures.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from core.utilities.pbip_utils import (
    load_json_file,
    save_json_file,
    get_page_display_name,
)

logger = logging.getLogger(__name__)

# Valid display option mappings
_DISPLAY_OPTIONS = {
    "fittopage": 1,
    "fittowidth": 2,
    "actualsize": 3,
}


def _find_page_folder(definition_path: Path, page_name: str) -> Optional[Path]:
    """Find page folder by display name (case-insensitive partial match) or page ID.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID (hex string)

    Returns:
        Path to the page folder, or None if not found
    """
    pages_dir = definition_path / "pages"
    if not pages_dir.exists():
        return None

    # Try direct ID match first
    direct = pages_dir / page_name
    if direct.is_dir():
        return direct

    # Fall back to display name matching (case-insensitive)
    name_lower = page_name.lower()
    for page_folder in pages_dir.iterdir():
        if not page_folder.is_dir():
            continue
        display_name = get_page_display_name(page_folder)
        if display_name.lower() == name_lower or name_lower in display_name.lower():
            return page_folder

    return None


def _resolve_page_id(definition_path: Path, page_name: str) -> Optional[str]:
    """Resolve a page name or ID to the actual page folder name (ID).

    Returns the folder name (which is the page ID), or None if not found.
    """
    folder = _find_page_folder(definition_path, page_name)
    return folder.name if folder else None


def reorder_pages(definition_path: Path, page_order: list) -> Dict[str, Any]:
    """Reorder pages. page_order is list of page IDs or display names in desired order.

    Updates pages.json which contains the page ordering.

    Args:
        definition_path: Path to the report's definition/ folder
        page_order: List of page IDs or display names in desired order

    Returns:
        Dict with success status and the new page order
    """
    pages_json_path = definition_path / "pages.json"
    pages_meta = load_json_file(pages_json_path)
    if not pages_meta:
        return {"success": False, "error": "Could not read pages.json"}

    existing_order = pages_meta.get("pageOrder", [])
    existing_set = set(existing_order)

    # Resolve display names to IDs
    resolved_order = []
    for entry in page_order:
        if entry in existing_set:
            resolved_order.append(entry)
        else:
            page_id = _resolve_page_id(definition_path, entry)
            if page_id and page_id in existing_set:
                resolved_order.append(page_id)
            else:
                return {
                    "success": False,
                    "error": f"Page not found: '{entry}'. Available pages: {existing_order}",
                }

    # Check for duplicates
    if len(set(resolved_order)) != len(resolved_order):
        return {"success": False, "error": "Duplicate pages in page_order"}

    # Any pages not in the new order get appended at the end (preserves unlisted pages)
    remaining = [pid for pid in existing_order if pid not in resolved_order]
    final_order = resolved_order + remaining

    pages_meta["pageOrder"] = final_order
    if not save_json_file(pages_json_path, pages_meta):
        return {"success": False, "error": "Failed to write pages.json"}

    return {
        "success": True,
        "page_order": final_order,
        "pages_reordered": len(resolved_order),
        "pages_appended": len(remaining),
    }


def resize_page(
    definition_path: Path,
    page_name: str,
    width: int = None,
    height: int = None,
) -> Dict[str, Any]:
    """Resize a page canvas. Updates page.json width/height.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        width: New page width in pixels (None to keep current)
        height: New page height in pixels (None to keep current)

    Returns:
        Dict with success status and updated dimensions
    """
    if width is None and height is None:
        return {"success": False, "error": "At least one of width or height must be provided"}

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    page_json_path = page_folder / "page.json"
    page_data = load_json_file(page_json_path)
    if not page_data:
        return {"success": False, "error": f"Could not read page.json for '{page_name}'"}

    old_width = page_data.get("width", 1280)
    old_height = page_data.get("height", 720)

    if width is not None:
        page_data["width"] = width
    if height is not None:
        page_data["height"] = height

    if not save_json_file(page_json_path, page_data):
        return {"success": False, "error": "Failed to write page.json"}

    return {
        "success": True,
        "page": page_data.get("displayName", page_folder.name),
        "old_dimensions": {"width": old_width, "height": old_height},
        "new_dimensions": {
            "width": page_data.get("width"),
            "height": page_data.get("height"),
        },
    }


def set_display_options(
    definition_path: Path,
    page_name: str,
    display_option: str,
) -> Dict[str, Any]:
    """Set page display option: FitToPage, FitToWidth, ActualSize.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        display_option: One of "FitToPage", "FitToWidth", "ActualSize"

    Returns:
        Dict with success status and applied option
    """
    option_key = display_option.lower().replace("_", "")
    option_value = _DISPLAY_OPTIONS.get(option_key)
    if option_value is None:
        return {
            "success": False,
            "error": (
                f"Invalid display option: '{display_option}'. "
                f"Valid options: FitToPage, FitToWidth, ActualSize"
            ),
        }

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    page_json_path = page_folder / "page.json"
    page_data = load_json_file(page_json_path)
    if not page_data:
        return {"success": False, "error": f"Could not read page.json for '{page_name}'"}

    old_option = page_data.get("displayOption", 1)
    page_data["displayOption"] = option_value

    if not save_json_file(page_json_path, page_data):
        return {"success": False, "error": "Failed to write page.json"}

    return {
        "success": True,
        "page": page_data.get("displayName", page_folder.name),
        "old_display_option": old_option,
        "new_display_option": option_value,
        "display_option_name": display_option,
    }


def _build_color_property(color: str) -> Dict[str, Any]:
    """Build a Power BI color property from a hex color string.

    Args:
        color: Hex color string (e.g., '#E6E6E6')

    Returns:
        Color property dict with Literal expression
    """
    return {
        "solid": {
            "color": {
                "expr": {
                    "Literal": {"Value": f"'{color}'"}
                }
            }
        }
    }


def _build_transparency_property(transparency: float) -> Dict[str, Any]:
    """Build a Power BI transparency property.

    Args:
        transparency: Transparency percentage (0-100)

    Returns:
        Transparency property dict with Literal expression
    """
    return {
        "expr": {
            "Literal": {"Value": f"{transparency}D"}
        }
    }


def set_page_background(
    definition_path: Path,
    page_name: str,
    color: str = None,
    transparency: float = None,
) -> Dict[str, Any]:
    """Set page background color/transparency. Updates page.json objects.background.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        color: Hex color string (e.g., '#E6E6E6')
        transparency: Transparency percentage (0-100)

    Returns:
        Dict with success status and applied settings
    """
    if color is None and transparency is None:
        return {"success": False, "error": "At least one of color or transparency must be provided"}

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    page_json_path = page_folder / "page.json"
    page_data = load_json_file(page_json_path)
    if not page_data:
        return {"success": False, "error": f"Could not read page.json for '{page_name}'"}

    objects = page_data.setdefault("objects", {})
    bg_list = objects.setdefault("background", [{}])
    if not bg_list:
        bg_list.append({})
    properties = bg_list[0].setdefault("properties", {})

    if color is not None:
        properties["color"] = _build_color_property(color)
    if transparency is not None:
        properties["transparency"] = _build_transparency_property(transparency)

    if not save_json_file(page_json_path, page_data):
        return {"success": False, "error": "Failed to write page.json"}

    return {
        "success": True,
        "page": page_data.get("displayName", page_folder.name),
        "background": {
            "color": color,
            "transparency": transparency,
        },
    }


def set_page_wallpaper(
    definition_path: Path,
    page_name: str,
    color: str = None,
    transparency: float = None,
) -> Dict[str, Any]:
    """Set page wallpaper (outspacePane). Updates page.json objects.outspacePane.

    The wallpaper is the area outside the page canvas visible in FitToPage mode.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        color: Hex color string (e.g., '#F0F0F0')
        transparency: Transparency percentage (0-100)

    Returns:
        Dict with success status and applied settings
    """
    if color is None and transparency is None:
        return {"success": False, "error": "At least one of color or transparency must be provided"}

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    page_json_path = page_folder / "page.json"
    page_data = load_json_file(page_json_path)
    if not page_data:
        return {"success": False, "error": f"Could not read page.json for '{page_name}'"}

    objects = page_data.setdefault("objects", {})
    wallpaper_list = objects.setdefault("outspacePane", [{}])
    if not wallpaper_list:
        wallpaper_list.append({})
    properties = wallpaper_list[0].setdefault("properties", {})

    if color is not None:
        properties["color"] = _build_color_property(color)
    if transparency is not None:
        properties["transparency"] = _build_transparency_property(transparency)

    if not save_json_file(page_json_path, page_data):
        return {"success": False, "error": "Failed to write page.json"}

    return {
        "success": True,
        "page": page_data.get("displayName", page_folder.name),
        "wallpaper": {
            "color": color,
            "transparency": transparency,
        },
    }


def set_drillthrough(
    definition_path: Path,
    page_name: str,
    table: str = None,
    field: str = None,
    clear: bool = False,
) -> Dict[str, Any]:
    """Configure drillthrough filters on a page.

    Sets or clears drillthrough filter configuration in page.json. When a
    drillthrough field is set, the page becomes a drillthrough target page.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        table: Source table for drillthrough field
        field: Column name for drillthrough field
        clear: If True, remove drillthrough configuration

    Returns:
        Dict with success status and drillthrough configuration
    """
    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    page_json_path = page_folder / "page.json"
    page_data = load_json_file(page_json_path)
    if not page_data:
        return {"success": False, "error": f"Could not read page.json for '{page_name}'"}

    if clear:
        # Remove drillthrough configuration
        page_data.pop("drillthrough", None)
        # Also remove drillthrough filters from filterConfig
        filter_config = page_data.get("filterConfig", {})
        filters = filter_config.get("filters", [])
        filter_config["filters"] = [
            f for f in filters if f.get("type") != "Drillthrough"
        ]
        if not filter_config["filters"]:
            page_data.pop("filterConfig", None)

        if not save_json_file(page_json_path, page_data):
            return {"success": False, "error": "Failed to write page.json"}

        return {
            "success": True,
            "page": page_data.get("displayName", page_folder.name),
            "drillthrough": "cleared",
        }

    if not table or not field:
        return {
            "success": False,
            "error": "Both 'table' and 'field' are required to set drillthrough (or use clear=True)",
        }

    # Build drillthrough filter
    drillthrough_filter = {
        "name": f"Drillthrough_{table}_{field}".replace(" ", "_"),
        "type": "Drillthrough",
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": field,
            }
        },
        "howCreated": "User",
    }

    filter_config = page_data.setdefault("filterConfig", {})
    filters = filter_config.setdefault("filters", [])

    # Remove any existing drillthrough filter for this field
    filters = [
        f for f in filters
        if not (f.get("type") == "Drillthrough" and f.get("name") == drillthrough_filter["name"])
    ]
    filters.append(drillthrough_filter)
    filter_config["filters"] = filters

    if not save_json_file(page_json_path, page_data):
        return {"success": False, "error": "Failed to write page.json"}

    return {
        "success": True,
        "page": page_data.get("displayName", page_folder.name),
        "drillthrough": {
            "table": table,
            "field": field,
        },
    }


def set_tooltip_page(
    definition_path: Path,
    page_name: str,
    enabled: bool = True,
    width: int = 320,
    height: int = 240,
) -> Dict[str, Any]:
    """Configure a page as a tooltip page. Sets page type and dimensions.

    Tooltip pages are smaller pages that appear on hover. Power BI uses
    pageType=1 and typically 320x240 dimensions.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        enabled: True to make this a tooltip page, False to revert to normal
        width: Tooltip page width (default 320)
        height: Tooltip page height (default 240)

    Returns:
        Dict with success status and tooltip configuration
    """
    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    page_json_path = page_folder / "page.json"
    page_data = load_json_file(page_json_path)
    if not page_data:
        return {"success": False, "error": f"Could not read page.json for '{page_name}'"}

    if enabled:
        page_data["pageType"] = 1  # Tooltip page type
        page_data["width"] = width
        page_data["height"] = height
    else:
        page_data.pop("pageType", None)
        # Restore default dimensions when reverting
        page_data["width"] = 1280
        page_data["height"] = 720

    if not save_json_file(page_json_path, page_data):
        return {"success": False, "error": "Failed to write page.json"}

    return {
        "success": True,
        "page": page_data.get("displayName", page_folder.name),
        "tooltip": {
            "enabled": enabled,
            "width": page_data["width"],
            "height": page_data["height"],
        },
    }


def set_page_visibility(
    definition_path: Path,
    page_name: str,
    hidden: bool,
) -> Dict[str, Any]:
    """Hide or show a page. Updates page.json visibility property.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        hidden: True to hide the page, False to show it

    Returns:
        Dict with success status and visibility state
    """
    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    page_json_path = page_folder / "page.json"
    page_data = load_json_file(page_json_path)
    if not page_data:
        return {"success": False, "error": f"Could not read page.json for '{page_name}'"}

    if hidden:
        page_data["visibility"] = 1  # Hidden
    else:
        # Remove visibility property to show the page (default is visible)
        page_data.pop("visibility", None)

    if not save_json_file(page_json_path, page_data):
        return {"success": False, "error": "Failed to write page.json"}

    return {
        "success": True,
        "page": page_data.get("displayName", page_folder.name),
        "hidden": hidden,
    }
