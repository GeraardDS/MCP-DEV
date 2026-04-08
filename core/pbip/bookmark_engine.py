"""
PBIP Bookmark Engine - Manages bookmarks in PBIP report definitions.

Bookmarks live in ``definition/bookmarks/`` as individual
``{id}.bookmark.json`` files.  Each file contains the bookmark's display name,
target page, capture options, visual states, and filter states.

All public functions return ``Dict[str, Any]`` with ``success: bool`` plus
data, or ``error: str`` on failure.  No MCP awareness.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pbip.authoring.id_generator import generate_visual_id
from core.utilities.pbip_utils import load_json_file, save_json_file

logger = logging.getLogger(__name__)

# Schema version for generated bookmarks
BOOKMARK_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/"
    "item/report/definition/bookmark/1.1.0/schema.json"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bookmarks_dir(definition_path: Path) -> Path:
    """Return the bookmarks directory, creating it if needed."""
    bdir = definition_path / "bookmarks"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir


def _find_bookmark_file(definition_path: Path, bookmark_id: str) -> Optional[Path]:
    """Locate a bookmark file by ID (exact match on filename stem)."""
    bdir = definition_path / "bookmarks"
    if not bdir.is_dir():
        return None

    # Direct match
    direct = bdir / f"{bookmark_id}.bookmark.json"
    if direct.is_file():
        return direct

    # Fallback: scan for matching ``name`` field
    id_lower = bookmark_id.lower()
    for bfile in bdir.iterdir():
        if not bfile.name.endswith(".bookmark.json"):
            continue
        data = load_json_file(bfile)
        if data and data.get("name", "").lower() == id_lower:
            return bfile
        # Also allow matching by displayName
        if data and data.get("displayName", "").lower() == id_lower:
            return bfile

    return None


def _summarize_bookmark(bfile: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact summary dict for one bookmark."""
    options = data.get("options", {})
    state = data.get("state", {})

    # Extract affected visual IDs from state
    visual_containers = state.get("visualContainers", [])
    affected_visuals = [vc.get("id", vc.get("name", "")) for vc in visual_containers]

    capture = []
    if options.get("captureData"):
        capture.append("data")
    if options.get("captureDisplay"):
        capture.append("display")
    if options.get("captureCurrentPage"):
        capture.append("currentPage")
    if options.get("captureAllPages"):
        capture.append("allPages")

    return {
        "id": data.get("name", bfile.stem.replace(".bookmark", "")),
        "display_name": data.get("displayName", ""),
        "file": str(bfile),
        "target_page": state.get("currentPage") or state.get("page"),
        "capture": capture,
        "affected_visual_count": len(affected_visuals),
        "affected_visuals": affected_visuals[:20],  # cap for readability
        "has_filters": bool(state.get("filters")),
        "has_slicer_states": bool(state.get("slicerStates")),
        "exploration_state": state.get("explorationState"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_bookmarks(definition_path: Path) -> Dict[str, Any]:
    """List all bookmarks with display name, page, and capture settings.

    Args:
        definition_path: Path to the report ``definition/`` folder.

    Returns:
        ``{success, bookmarks, count}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    bdir = definition_path / "bookmarks"

    if not bdir.is_dir():
        return {"success": True, "bookmarks": [], "count": 0}

    bookmarks: List[Dict[str, Any]] = []
    for bfile in sorted(bdir.iterdir()):
        if not bfile.name.endswith(".bookmark.json"):
            continue
        data = load_json_file(bfile)
        if data is None:
            logger.warning("Skipping unreadable bookmark file: %s", bfile)
            continue
        bookmarks.append(_summarize_bookmark(bfile, data))

    return {"success": True, "bookmarks": bookmarks, "count": len(bookmarks)}


def create_bookmark(
    definition_path: Path,
    display_name: str,
    page_name: Optional[str] = None,
    capture_data: bool = True,
    capture_display: bool = True,
) -> Dict[str, Any]:
    """Create a new bookmark.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        display_name: Human-readable bookmark name.
        page_name: Optional target page (display-name or ID).
        capture_data: Whether the bookmark captures data state.
        capture_display: Whether the bookmark captures display state.

    Returns:
        ``{success, bookmark_id, file}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    bdir = _bookmarks_dir(definition_path)

    bookmark_id = generate_visual_id()

    state: Dict[str, Any] = {}
    if page_name:
        state["currentPage"] = page_name

    bookmark_data: Dict[str, Any] = {
        "$schema": BOOKMARK_SCHEMA,
        "name": bookmark_id,
        "displayName": display_name,
        "options": {
            "captureData": capture_data,
            "captureDisplay": capture_display,
            "captureCurrentPage": page_name is not None,
        },
        "state": state,
    }

    bfile = bdir / f"{bookmark_id}.bookmark.json"
    if not save_json_file(bfile, bookmark_data):
        return {"success": False, "error": f"Failed to write bookmark file: {bfile}"}

    logger.info("Created bookmark '%s' (%s)", display_name, bookmark_id)
    return {"success": True, "bookmark_id": bookmark_id, "display_name": display_name, "file": str(bfile)}


def rename_bookmark(
    definition_path: Path,
    bookmark_id: str,
    new_name: str,
) -> Dict[str, Any]:
    """Rename a bookmark's display name.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        bookmark_id: Bookmark ID or current display name.
        new_name: New display name.

    Returns:
        ``{success, bookmark_id, old_name, new_name}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    bfile = _find_bookmark_file(definition_path, bookmark_id)
    if not bfile:
        return {"success": False, "error": f"Bookmark not found: {bookmark_id}"}

    data = load_json_file(bfile)
    if data is None:
        return {"success": False, "error": f"Cannot read bookmark file: {bfile}"}

    old_name = data.get("displayName", "")
    data["displayName"] = new_name

    if not save_json_file(bfile, data):
        return {"success": False, "error": f"Failed to write bookmark file: {bfile}"}

    logger.info("Renamed bookmark '%s' -> '%s'", old_name, new_name)
    return {"success": True, "bookmark_id": data.get("name", bookmark_id), "old_name": old_name, "new_name": new_name}


def delete_bookmark(
    definition_path: Path,
    bookmark_id: str,
) -> Dict[str, Any]:
    """Delete a bookmark file.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        bookmark_id: Bookmark ID or display name.

    Returns:
        ``{success, deleted_id, file}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    bfile = _find_bookmark_file(definition_path, bookmark_id)
    if not bfile:
        return {"success": False, "error": f"Bookmark not found: {bookmark_id}"}

    data = load_json_file(bfile)
    display = data.get("displayName", bookmark_id) if data else bookmark_id
    resolved_id = data.get("name", bookmark_id) if data else bookmark_id

    try:
        bfile.unlink()
    except OSError as e:
        return {"success": False, "error": f"Failed to delete bookmark file: {e}"}

    logger.info("Deleted bookmark '%s' (%s)", display, resolved_id)
    return {"success": True, "deleted_id": resolved_id, "display_name": display, "file": str(bfile)}


def set_bookmark_capture(
    definition_path: Path,
    bookmark_id: str,
    capture_data: Optional[bool] = None,
    capture_display: Optional[bool] = None,
    capture_current_page: Optional[bool] = None,
) -> Dict[str, Any]:
    """Configure what a bookmark captures.

    Only provided parameters are updated; ``None`` leaves the value unchanged.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        bookmark_id: Bookmark ID or display name.
        capture_data: Whether to capture data state.
        capture_display: Whether to capture display/visibility state.
        capture_current_page: Whether to capture the current page.

    Returns:
        ``{success, options}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    bfile = _find_bookmark_file(definition_path, bookmark_id)
    if not bfile:
        return {"success": False, "error": f"Bookmark not found: {bookmark_id}"}

    data = load_json_file(bfile)
    if data is None:
        return {"success": False, "error": f"Cannot read bookmark file: {bfile}"}

    options = data.setdefault("options", {})
    if capture_data is not None:
        options["captureData"] = capture_data
    if capture_display is not None:
        options["captureDisplay"] = capture_display
    if capture_current_page is not None:
        options["captureCurrentPage"] = capture_current_page

    if not save_json_file(bfile, data):
        return {"success": False, "error": f"Failed to write bookmark file: {bfile}"}

    return {"success": True, "bookmark_id": data.get("name", bookmark_id), "options": options}


def set_affected_visuals(
    definition_path: Path,
    bookmark_id: str,
    visual_ids: Optional[List[str]] = None,
    all_visuals: bool = False,
) -> Dict[str, Any]:
    """Set which visuals are affected by this bookmark.

    When *all_visuals* is ``True``, the ``visualContainers`` list is cleared so
    the bookmark applies to every visual on the page (default PBI behaviour).
    When *visual_ids* is provided, only those visuals are included.

    Args:
        definition_path: Path to the report ``definition/`` folder.
        bookmark_id: Bookmark ID or display name.
        visual_ids: Explicit list of visual IDs to include.
        all_visuals: If ``True``, affects all visuals (clears container list).

    Returns:
        ``{success, affected_count}`` or ``{error}``.
    """
    definition_path = Path(definition_path)
    bfile = _find_bookmark_file(definition_path, bookmark_id)
    if not bfile:
        return {"success": False, "error": f"Bookmark not found: {bookmark_id}"}

    data = load_json_file(bfile)
    if data is None:
        return {"success": False, "error": f"Cannot read bookmark file: {bfile}"}

    state = data.setdefault("state", {})

    if all_visuals:
        # Remove explicit container list so bookmark affects all visuals
        state.pop("visualContainers", None)
        affected_count = -1  # signals "all"
    else:
        containers = []
        for vid in (visual_ids or []):
            containers.append({"id": vid, "isHidden": False})
        state["visualContainers"] = containers
        affected_count = len(containers)

    if not save_json_file(bfile, data):
        return {"success": False, "error": f"Failed to write bookmark file: {bfile}"}

    return {
        "success": True,
        "bookmark_id": data.get("name", bookmark_id),
        "all_visuals": all_visuals,
        "affected_count": affected_count,
    }
