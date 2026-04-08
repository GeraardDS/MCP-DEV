"""
Visual Alignment Engine for PBIP Reports

Multi-visual alignment and distribution operations. Reads visual positions
from visual.json files, computes alignment targets or equal spacing, and
writes the updated positions back.

No MCP awareness — pure domain logic operating on PBIP file structures.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.utilities.pbip_utils import (
    load_json_file,
    save_json_file,
    get_page_display_name,
)

logger = logging.getLogger(__name__)

# Supported alignment modes
_VALID_ALIGNMENTS = {"left", "right", "top", "bottom", "center_h", "center_v"}

# Supported distribution directions
_VALID_DIRECTIONS = {"horizontal", "vertical"}


def _find_page_folder(definition_path: Path, page_name: str) -> Optional[Path]:
    """Find page folder by display name (case-insensitive partial match) or page ID.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID

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


def _find_visual_folder(
    page_folder: Path, visual_name: str
) -> Optional[Path]:
    """Find visual folder by visual name/ID or title (case-insensitive).

    Args:
        page_folder: Path to the page folder
        visual_name: Visual ID, name, or title text

    Returns:
        Path to the visual folder, or None if not found
    """
    visuals_dir = page_folder / "visuals"
    if not visuals_dir.exists():
        return None

    # Try direct ID match first
    direct = visuals_dir / visual_name
    if direct.is_dir():
        return direct

    # Fall back to name/title matching
    name_lower = visual_name.lower()
    for visual_folder in visuals_dir.iterdir():
        if not visual_folder.is_dir():
            continue
        visual_json_path = visual_folder / "visual.json"
        visual_data = load_json_file(visual_json_path)
        if not visual_data:
            continue

        # Check visual name field
        if visual_data.get("name", "").lower() == name_lower:
            return visual_folder

        # Check visualGroup displayName
        vg = visual_data.get("visualGroup", {})
        if vg.get("displayName", "").lower() == name_lower:
            return visual_folder

        # Check title in visualContainerObjects
        vco = visual_data.get("visual", {}).get("visualContainerObjects", {})
        title_list = vco.get("title", [])
        for t in title_list:
            props = t.get("properties", {})
            text = props.get("text", {})
            expr = text.get("expr", {})
            lit = expr.get("Literal", {})
            val = lit.get("Value", "")
            if val and name_lower in val.lower().strip("'"):
                return visual_folder

    return None


def _load_visual_positions(
    page_folder: Path, visual_names: list
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load visual data and positions for the specified visuals.

    Args:
        page_folder: Path to the page folder
        visual_names: List of visual names/IDs to load

    Returns:
        Tuple of (list of visual info dicts, list of error messages).
        Each visual info dict has keys: folder, data, path, position.
    """
    visuals: List[Dict[str, Any]] = []
    errors: List[str] = []

    for name in visual_names:
        vf = _find_visual_folder(page_folder, name)
        if not vf:
            errors.append(f"Visual not found: '{name}'")
            continue

        visual_json_path = vf / "visual.json"
        visual_data = load_json_file(visual_json_path)
        if not visual_data:
            errors.append(f"Could not read visual.json for '{name}'")
            continue

        position = visual_data.get("position", {})
        visuals.append({
            "folder": vf,
            "data": visual_data,
            "path": visual_json_path,
            "position": position,
            "name": name,
        })

    return visuals, errors


def align_visuals(
    definition_path: Path,
    page_name: str,
    visual_names: list,
    alignment: str,
) -> Dict[str, Any]:
    """Align visuals on a page.

    Reads positions, calculates alignment target, and updates positions.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_names: List of visual names/IDs to align
        alignment: Alignment mode: left, right, top, bottom, center_h, center_v

    Returns:
        Dict with success status and alignment details
    """
    alignment_lower = alignment.lower().replace("-", "_")
    if alignment_lower not in _VALID_ALIGNMENTS:
        return {
            "success": False,
            "error": (
                f"Invalid alignment: '{alignment}'. "
                f"Valid options: {', '.join(sorted(_VALID_ALIGNMENTS))}"
            ),
        }

    if len(visual_names) < 2:
        return {"success": False, "error": "At least 2 visuals are required for alignment"}

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    visuals, errors = _load_visual_positions(page_folder, visual_names)
    if errors:
        return {"success": False, "error": "; ".join(errors)}

    if len(visuals) < 2:
        return {"success": False, "error": "Need at least 2 valid visuals for alignment"}

    # Calculate alignment target
    changes: List[Dict[str, Any]] = []

    if alignment_lower == "left":
        target_x = min(v["position"].get("x", 0) for v in visuals)
        for v in visuals:
            old_x = v["position"].get("x", 0)
            v["data"]["position"]["x"] = target_x
            changes.append({"visual": v["name"], "x": old_x, "new_x": target_x})

    elif alignment_lower == "right":
        target_right = max(
            v["position"].get("x", 0) + v["position"].get("width", 0)
            for v in visuals
        )
        for v in visuals:
            old_x = v["position"].get("x", 0)
            width = v["position"].get("width", 0)
            new_x = target_right - width
            v["data"]["position"]["x"] = new_x
            changes.append({"visual": v["name"], "x": old_x, "new_x": new_x})

    elif alignment_lower == "top":
        target_y = min(v["position"].get("y", 0) for v in visuals)
        for v in visuals:
            old_y = v["position"].get("y", 0)
            v["data"]["position"]["y"] = target_y
            changes.append({"visual": v["name"], "y": old_y, "new_y": target_y})

    elif alignment_lower == "bottom":
        target_bottom = max(
            v["position"].get("y", 0) + v["position"].get("height", 0)
            for v in visuals
        )
        for v in visuals:
            old_y = v["position"].get("y", 0)
            height = v["position"].get("height", 0)
            new_y = target_bottom - height
            v["data"]["position"]["y"] = new_y
            changes.append({"visual": v["name"], "y": old_y, "new_y": new_y})

    elif alignment_lower == "center_h":
        # Align all visuals to the average horizontal center
        centers = [
            v["position"].get("x", 0) + v["position"].get("width", 0) / 2
            for v in visuals
        ]
        avg_center = sum(centers) / len(centers)
        for v in visuals:
            old_x = v["position"].get("x", 0)
            width = v["position"].get("width", 0)
            new_x = avg_center - width / 2
            v["data"]["position"]["x"] = new_x
            changes.append({"visual": v["name"], "x": old_x, "new_x": new_x})

    elif alignment_lower == "center_v":
        # Align all visuals to the average vertical center
        centers = [
            v["position"].get("y", 0) + v["position"].get("height", 0) / 2
            for v in visuals
        ]
        avg_center = sum(centers) / len(centers)
        for v in visuals:
            old_y = v["position"].get("y", 0)
            height = v["position"].get("height", 0)
            new_y = avg_center - height / 2
            v["data"]["position"]["y"] = new_y
            changes.append({"visual": v["name"], "y": old_y, "new_y": new_y})

    # Save all updated visuals
    save_errors = []
    for v in visuals:
        if not save_json_file(v["path"], v["data"]):
            save_errors.append(f"Failed to save {v['name']}")

    if save_errors:
        return {"success": False, "error": "; ".join(save_errors)}

    return {
        "success": True,
        "page": get_page_display_name(page_folder),
        "alignment": alignment,
        "visuals_aligned": len(visuals),
        "changes": changes,
    }


def distribute_visuals(
    definition_path: Path,
    page_name: str,
    visual_names: list,
    direction: str,
) -> Dict[str, Any]:
    """Evenly distribute visuals with equal spacing between them.

    Calculates equal gaps between visuals along the specified axis.
    The first and last visuals (in spatial order) stay in place; inner
    visuals are repositioned to create even spacing.

    Args:
        definition_path: Path to the report's definition/ folder
        page_name: Page display name or page ID
        visual_names: List of visual names/IDs to distribute
        direction: Distribution direction: horizontal, vertical

    Returns:
        Dict with success status and distribution details
    """
    direction_lower = direction.lower()
    if direction_lower not in _VALID_DIRECTIONS:
        return {
            "success": False,
            "error": (
                f"Invalid direction: '{direction}'. "
                f"Valid options: {', '.join(sorted(_VALID_DIRECTIONS))}"
            ),
        }

    if len(visual_names) < 3:
        return {
            "success": False,
            "error": "At least 3 visuals are required for distribution",
        }

    page_folder = _find_page_folder(definition_path, page_name)
    if not page_folder:
        return {"success": False, "error": f"Page not found: '{page_name}'"}

    visuals, errors = _load_visual_positions(page_folder, visual_names)
    if errors:
        return {"success": False, "error": "; ".join(errors)}

    if len(visuals) < 3:
        return {
            "success": False,
            "error": "Need at least 3 valid visuals for distribution",
        }

    changes: List[Dict[str, Any]] = []

    if direction_lower == "horizontal":
        # Sort by x position
        visuals.sort(key=lambda v: v["position"].get("x", 0))

        # Calculate total width of all visuals
        total_visual_width = sum(v["position"].get("width", 0) for v in visuals)

        # Calculate total available space
        first_x = visuals[0]["position"].get("x", 0)
        last_x = visuals[-1]["position"].get("x", 0)
        last_width = visuals[-1]["position"].get("width", 0)
        total_span = (last_x + last_width) - first_x

        # Calculate equal gap
        total_gap = total_span - total_visual_width
        gap = total_gap / (len(visuals) - 1) if len(visuals) > 1 else 0

        # Position each visual
        current_x = first_x
        for v in visuals:
            old_x = v["position"].get("x", 0)
            v["data"]["position"]["x"] = current_x
            changes.append({"visual": v["name"], "x": old_x, "new_x": current_x})
            current_x += v["position"].get("width", 0) + gap

    elif direction_lower == "vertical":
        # Sort by y position
        visuals.sort(key=lambda v: v["position"].get("y", 0))

        # Calculate total height of all visuals
        total_visual_height = sum(v["position"].get("height", 0) for v in visuals)

        # Calculate total available space
        first_y = visuals[0]["position"].get("y", 0)
        last_y = visuals[-1]["position"].get("y", 0)
        last_height = visuals[-1]["position"].get("height", 0)
        total_span = (last_y + last_height) - first_y

        # Calculate equal gap
        total_gap = total_span - total_visual_height
        gap = total_gap / (len(visuals) - 1) if len(visuals) > 1 else 0

        # Position each visual
        current_y = first_y
        for v in visuals:
            old_y = v["position"].get("y", 0)
            v["data"]["position"]["y"] = current_y
            changes.append({"visual": v["name"], "y": old_y, "new_y": current_y})
            current_y += v["position"].get("height", 0) + gap

    # Save all updated visuals
    save_errors = []
    for v in visuals:
        if not save_json_file(v["path"], v["data"]):
            save_errors.append(f"Failed to save {v['name']}")

    if save_errors:
        return {"success": False, "error": "; ".join(save_errors)}

    return {
        "success": True,
        "page": get_page_display_name(page_folder),
        "direction": direction,
        "visuals_distributed": len(visuals),
        "gap": round(gap, 2),
        "changes": changes,
    }
