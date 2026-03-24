"""
Prototype Parser — HTML State to PBIP Translation

Parses the exported JSON state from an HTML prototype and applies
layout changes (position moves, resizes) back to the PBIP report.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utilities.pbip_utils import (
    load_json_file,
    save_json_file,
    get_page_display_name,
)

logger = logging.getLogger(__name__)


class PrototypeParser:
    """Parse and apply HTML prototype state to PBIP pages."""

    def apply_state(
        self,
        definition_path: Path,
        state: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Apply exported state from HTML prototype to PBIP.

        The state format (from the HTML Export button):
        {
            "page_name": "Global Wealth",
            "visuals": [
                {
                    "id": "abc123...",
                    "visual_type": "columnChart",
                    "position": {"x": 100, "y": 200, "width": 600, "height": 300},
                    "title": "Monthly Performance",
                    "fields": {...},
                    "parent_group": ""
                }
            ]
        }

        Args:
            definition_path: Path to the report's definition/ folder
            state: Exported state JSON from HTML prototype
            dry_run: If True, report changes without saving

        Returns:
            Dict with success, changes list, change_count
        """
        page_name = state.get("page_name", "")
        visual_states = state.get("visuals", [])

        if not page_name:
            return {"success": False, "error": "state.page_name is required"}

        # Find the page
        page_dir = self._find_page(definition_path, page_name)
        if not page_dir:
            return {"success": False, "error": f"Page not found: {page_name}"}

        visuals_dir = page_dir / "visuals"
        if not visuals_dir.exists():
            return {"success": False, "error": "No visuals folder found"}

        changes: List[Dict[str, Any]] = []
        errors: List[str] = []

        for vs in visual_states:
            vid = vs.get("id", "")
            if not vid:
                continue

            visual_folder = visuals_dir / vid
            if not visual_folder.exists():
                errors.append(f"Visual folder not found: {vid}")
                continue

            visual_json_path = visual_folder / "visual.json"
            visual_data = load_json_file(visual_json_path)
            if not visual_data:
                errors.append(f"Could not read visual.json for: {vid}")
                continue

            # Compare positions
            new_pos = vs.get("position", {})
            old_pos = visual_data.get("position", {})

            pos_changed = False
            change_detail: Dict[str, Any] = {"visual_id": vid, "changes": []}

            for key in ("x", "y", "width", "height"):
                new_val = new_pos.get(key)
                old_val = old_pos.get(key, 0)
                if new_val is not None and abs(float(new_val) - float(old_val)) > 0.5:
                    change_detail["changes"].append(
                        {
                            "property": key,
                            "old": old_val,
                            "new": new_val,
                        }
                    )
                    pos_changed = True

            if pos_changed:
                if not dry_run:
                    # Apply position changes
                    for key in ("x", "y", "width", "height"):
                        new_val = new_pos.get(key)
                        if new_val is not None:
                            visual_data["position"][key] = float(new_val)
                    save_json_file(visual_json_path, visual_data)

                change_detail["status"] = "would_change" if dry_run else "changed"
                changes.append(change_detail)

        return {
            "success": True,
            "dry_run": dry_run,
            "page_name": page_name,
            "changes": changes,
            "change_count": len(changes),
            "errors": errors if errors else None,
        }

    def _find_page(self, definition_path: Path, page_name: str) -> Optional[Path]:
        """Find a page folder by display name or ID."""
        pages_dir = definition_path / "pages"
        if not pages_dir.exists():
            return None

        direct = pages_dir / page_name
        if direct.exists() and direct.is_dir():
            return direct

        name_lower = page_name.lower()
        for page_folder in pages_dir.iterdir():
            if not page_folder.is_dir():
                continue
            display = get_page_display_name(page_folder)
            if display.lower() == name_lower or name_lower in display.lower():
                return page_folder

        return None
