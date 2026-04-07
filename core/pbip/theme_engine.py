"""
PBIP Theme Engine - Manages theme files in PBIP report definitions.

The theme is referenced from ``report.json`` via
``themeCollection.customTheme.name`` and the actual theme JSON lives in
``{report_path}/StaticResources/RegisteredResources/{theme_name}``.
Here *report_path* is the ``.Report`` folder (parent of ``definition/``).

All public functions return ``Dict[str, Any]`` with ``success: bool`` plus
data, or ``error: str`` on failure.  No MCP awareness.
"""

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utilities.pbip_utils import load_json_file, save_json_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_report_path(report_path: Path) -> Path:
    """Ensure *report_path* points to the ``.Report`` folder.

    Accepts the .Report folder directly, or a ``definition/`` folder (goes up one).
    """
    report_path = Path(report_path)
    if report_path.name == "definition":
        report_path = report_path.parent
    return report_path


def _load_theme_ref(report_path: Path) -> Optional[Dict[str, Any]]:
    """Read ``report.json`` and return the ``themeCollection.customTheme`` dict."""
    definition_path = report_path / "definition"
    report_json_path = definition_path / "report.json"
    report_data = load_json_file(report_json_path)
    if report_data is None:
        return None
    return report_data.get("themeCollection", {}).get("customTheme")


def _resolve_theme_path(report_path: Path) -> Optional[Path]:
    """Resolve the filesystem path of the current theme JSON file."""
    theme_ref = _load_theme_ref(report_path)
    if not theme_ref:
        return None

    theme_name = theme_ref.get("name", "")
    theme_type = theme_ref.get("type", "RegisteredResources")

    if not theme_name:
        return None

    theme_path = report_path / "StaticResources" / theme_type / theme_name
    if theme_path.is_file():
        return theme_path

    # Fallback: try without the type sub-folder
    alt = report_path / "StaticResources" / "RegisteredResources" / theme_name
    if alt.is_file():
        return alt

    return None


def _load_theme_data(report_path: Path) -> Optional[Dict[str, Any]]:
    """Load and return the raw theme JSON dict."""
    tpath = _resolve_theme_path(report_path)
    if not tpath:
        return None
    return load_json_file(tpath)


def _save_theme_data(report_path: Path, data: Dict[str, Any]) -> bool:
    """Persist the theme JSON back to disk."""
    tpath = _resolve_theme_path(report_path)
    if not tpath:
        logger.error("Cannot determine theme file path for saving")
        return False
    return save_json_file(tpath, data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_theme(report_path: Path) -> Dict[str, Any]:
    """Load and return the current theme.

    Args:
        report_path: Path to the ``.Report`` folder (or ``definition/`` inside it).

    Returns:
        ``{success, theme_name, theme_file, colors, fonts, text_classes, visual_styles}``
        or ``{error}``.
    """
    report_path = _resolve_report_path(report_path)
    tpath = _resolve_theme_path(report_path)
    if not tpath:
        return {"success": False, "error": "No theme file found. Check themeCollection in report.json."}

    data = load_json_file(tpath)
    if data is None:
        return {"success": False, "error": f"Cannot read theme file: {tpath}"}

    # Extract key sections
    text_classes = data.get("textClasses", {})
    tc_summary = {}
    for cls_name, cls_def in text_classes.items():
        tc_summary[cls_name] = {
            k: v for k, v in cls_def.items()
        }

    return {
        "success": True,
        "theme_name": data.get("name", ""),
        "theme_file": str(tpath),
        "colors": {
            "dataColors": data.get("dataColors", []),
            "background": data.get("background", ""),
            "foreground": data.get("foreground", ""),
            "tableAccent": data.get("tableAccent", ""),
            "hyperlink": data.get("hyperlink", ""),
            "good": data.get("good", ""),
            "bad": data.get("bad", ""),
            "neutral": data.get("neutral", ""),
            "maximum": data.get("maximum", ""),
            "center": data.get("center", ""),
            "minimum": data.get("minimum", ""),
        },
        "fonts": {
            "fontFamily": data.get("fontFamily", ""),
        },
        "text_classes": tc_summary,
        "visual_styles": list(data.get("visualStyles", {}).keys()),
    }


def set_colors(report_path: Path, colors: Dict[str, Any]) -> Dict[str, Any]:
    """Set theme colors.

    Accepted keys in *colors*:
    - ``dataColors``: ``List[str]`` of hex color codes for series.
    - Any of: ``background``, ``foreground``, ``good``, ``bad``, ``neutral``,
      ``maximum``, ``center``, ``minimum``, ``tableAccent``, ``hyperlink``.

    Args:
        report_path: Path to the ``.Report`` folder (or ``definition/``).
        colors: Dict of color keys to set.

    Returns:
        ``{success, updated_keys}`` or ``{error}``.
    """
    report_path = _resolve_report_path(report_path)
    data = _load_theme_data(report_path)
    if data is None:
        return {"success": False, "error": "Cannot load theme file"}

    allowed_keys = {
        "dataColors", "background", "foreground", "good", "bad",
        "neutral", "maximum", "center", "minimum", "tableAccent",
        "hyperlink", "visitedHyperlink",
        "foregroundNeutralSecondary", "foregroundNeutralTertiary",
        "backgroundLight", "backgroundNeutral",
    }

    updated = []
    for key, value in colors.items():
        if key in allowed_keys:
            data[key] = value
            updated.append(key)
        else:
            logger.warning("Ignoring unknown color key: %s", key)

    if not updated:
        return {"success": False, "error": "No valid color keys provided"}

    if not _save_theme_data(report_path, data):
        return {"success": False, "error": "Failed to save theme file"}

    return {"success": True, "updated_keys": updated, "theme_name": data.get("name", "")}


def set_formatting(
    report_path: Path,
    visual_type: str,
    formatting: Dict[str, Any],
) -> Dict[str, Any]:
    """Set theme-level formatting defaults for a visual type.

    Writes into the ``visualStyles`` section of the theme JSON.

    Args:
        report_path: Path to the ``.Report`` folder (or ``definition/``).
        visual_type: Power BI visual type (e.g., ``"columnChart"``, ``"card"``).
        formatting: Dict of formatting properties to set.  Keys are style
            group names (e.g., ``"legend"``, ``"categoryAxis"``), values are
            property dicts.

    Returns:
        ``{success, visual_type, updated_groups}`` or ``{error}``.
    """
    report_path = _resolve_report_path(report_path)
    data = _load_theme_data(report_path)
    if data is None:
        return {"success": False, "error": "Cannot load theme file"}

    vs = data.setdefault("visualStyles", {})
    vt_styles = vs.setdefault(visual_type, {})

    # The visualStyles schema is:
    # visualStyles.<visualType>.<groupName> = { ... properties ... }
    # We use a wildcard "*" selector that matches all instances of this visual type.
    wildcard = vt_styles.setdefault("*", {})

    updated_groups = []
    for group_name, properties in formatting.items():
        wildcard[group_name] = _merge_deep(wildcard.get(group_name, {}), properties)
        updated_groups.append(group_name)

    if not _save_theme_data(report_path, data):
        return {"success": False, "error": "Failed to save theme file"}

    return {
        "success": True,
        "visual_type": visual_type,
        "updated_groups": updated_groups,
        "theme_name": data.get("name", ""),
    }


def push_visual_to_theme(
    report_path: Path,
    definition_path: Path,
    page_name: str,
    visual_name: str,
) -> Dict[str, Any]:
    """Extract formatting from a visual and push it as theme defaults.

    Reads the visual's ``objects`` section and writes relevant properties
    into ``visualStyles.<visualType>`` in the theme.

    Args:
        report_path: Path to the ``.Report`` folder (or ``definition/``).
        definition_path: Path to the report ``definition/`` folder.
        page_name: Page display name or ID.
        visual_name: Visual ID or title.

    Returns:
        ``{success, visual_type, pushed_groups}`` or ``{error}``.
    """
    report_path = _resolve_report_path(report_path)
    definition_path = Path(definition_path)

    # Find the visual
    visual_data = _find_visual_data(definition_path, page_name, visual_name)
    if visual_data is None:
        return {"success": False, "error": f"Visual not found: {visual_name} on page {page_name}"}

    visual_section = visual_data.get("visual", {})
    visual_type = visual_section.get("visualType", "")
    if not visual_type:
        return {"success": False, "error": "Could not determine visual type"}

    objects = visual_section.get("objects", {})
    if not objects:
        return {"success": False, "error": "Visual has no formatting objects to push"}

    # Load theme
    data = _load_theme_data(report_path)
    if data is None:
        return {"success": False, "error": "Cannot load theme file"}

    vs = data.setdefault("visualStyles", {})
    vt_styles = vs.setdefault(visual_type, {})
    wildcard = vt_styles.setdefault("*", {})

    pushed_groups = []
    for group_name, group_entries in objects.items():
        # Objects in visual.json are arrays; theme uses flat dicts
        if isinstance(group_entries, list) and group_entries:
            props = group_entries[0].get("properties", {})
            if props:
                wildcard[group_name] = copy.deepcopy(props)
                pushed_groups.append(group_name)

    if not pushed_groups:
        return {"success": False, "error": "No formattable object groups found in visual"}

    if not _save_theme_data(report_path, data):
        return {"success": False, "error": "Failed to save theme file"}

    return {
        "success": True,
        "visual_type": visual_type,
        "pushed_groups": pushed_groups,
        "theme_name": data.get("name", ""),
    }


def list_text_classes(report_path: Path) -> Dict[str, Any]:
    """List text class definitions in the theme (title, label, callout, etc.).

    Args:
        report_path: Path to the ``.Report`` folder (or ``definition/``).

    Returns:
        ``{success, text_classes}`` or ``{error}``.
    """
    report_path = _resolve_report_path(report_path)
    data = _load_theme_data(report_path)
    if data is None:
        return {"success": False, "error": "Cannot load theme file"}

    raw = data.get("textClasses", {})
    classes: Dict[str, Dict[str, Any]] = {}
    for cls_name, cls_def in raw.items():
        classes[cls_name] = {
            "fontFace": cls_def.get("fontFace"),
            "fontSize": cls_def.get("fontSize"),
            "fontWeight": cls_def.get("fontWeight"),
            "color": cls_def.get("color"),
        }

    return {"success": True, "text_classes": classes, "count": len(classes)}


def set_font(
    report_path: Path,
    text_class: Optional[str] = None,
    font_family: Optional[str] = None,
    font_size: Optional[int] = None,
    color: Optional[str] = None,
    bold: Optional[bool] = None,
) -> Dict[str, Any]:
    """Set font properties on a text class or globally.

    When *text_class* is ``None``, sets the global ``fontFamily`` on the theme.
    When *text_class* is provided (e.g., ``"title"``, ``"label"``, ``"callout"``),
    updates that specific text class in ``textClasses``.

    Args:
        report_path: Path to the ``.Report`` folder (or ``definition/``).
        text_class: Optional text class name to target.
        font_family: Font family name (e.g., ``"Segoe UI"``).
        font_size: Font size in points.
        color: Hex color string.
        bold: Whether text is bold.

    Returns:
        ``{success, target, updated_properties}`` or ``{error}``.
    """
    report_path = _resolve_report_path(report_path)
    data = _load_theme_data(report_path)
    if data is None:
        return {"success": False, "error": "Cannot load theme file"}

    updated = []

    if text_class is None:
        # Global font setting
        if font_family is not None:
            data["fontFamily"] = font_family
            updated.append("fontFamily")
        if font_size is not None:
            data["fontSize"] = font_size
            updated.append("fontSize")
        target = "global"
    else:
        # Specific text class
        tc = data.setdefault("textClasses", {}).setdefault(text_class, {})
        if font_family is not None:
            tc["fontFace"] = font_family
            updated.append("fontFace")
        if font_size is not None:
            tc["fontSize"] = font_size
            updated.append("fontSize")
        if color is not None:
            tc["color"] = color
            updated.append("color")
        if bold is not None:
            tc["fontWeight"] = "Bold" if bold else "Normal"
            updated.append("fontWeight")
        target = f"textClass:{text_class}"

    if not updated:
        return {"success": False, "error": "No font properties provided to update"}

    if not _save_theme_data(report_path, data):
        return {"success": False, "error": "Failed to save theme file"}

    return {"success": True, "target": target, "updated_properties": updated, "theme_name": data.get("name", "")}


# ---------------------------------------------------------------------------
# Shared internal helpers
# ---------------------------------------------------------------------------

def _merge_deep(base: Dict, overlay: Dict) -> Dict:
    """Recursively merge *overlay* into *base*, returning the merged result."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_deep(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _find_visual_data(
    definition_path: Path,
    page_name: str,
    visual_name: str,
) -> Optional[Dict[str, Any]]:
    """Locate and load a visual.json by page name and visual name/ID."""
    from core.utilities.pbip_utils import get_page_display_name

    pages_dir = definition_path / "pages"
    if not pages_dir.is_dir():
        return None

    name_lower = page_name.lower()
    page_folder: Optional[Path] = None
    for pf in pages_dir.iterdir():
        if not pf.is_dir():
            continue
        if pf.name.lower() == name_lower:
            page_folder = pf
            break
        display = get_page_display_name(pf)
        if display.lower() == name_lower:
            page_folder = pf
            break

    if not page_folder:
        return None

    visuals_dir = page_folder / "visuals"
    if not visuals_dir.is_dir():
        return None

    vis_lower = visual_name.lower()
    for vf in visuals_dir.iterdir():
        if not vf.is_dir():
            continue
        if vf.name.lower() == vis_lower:
            return load_json_file(vf / "visual.json")
        vdata = load_json_file(vf / "visual.json")
        if vdata and vdata.get("name", "").lower() == vis_lower:
            return vdata
        # Title match
        if vdata:
            vco = vdata.get("visual", {}).get("visualContainerObjects", {})
            for t in vco.get("title", []):
                txt = t.get("properties", {}).get("text", {})
                lit = txt.get("expr", {}).get("Literal", {}).get("Value", "")
                if lit.startswith("'") and lit.endswith("'"):
                    lit = lit[1:-1]
                if lit.lower() == vis_lower:
                    return vdata

    return None
