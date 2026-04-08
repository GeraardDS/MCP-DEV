"""
Page Builder for PBIP Report Authoring

Creates PBIP page folder structures with page.json, visual folders,
and updates pages.json ordering.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pbip.authoring.id_generator import generate_visual_id
from core.utilities.pbip_utils import load_json_file, save_json_file

logger = logging.getLogger(__name__)

# Schema version for generated pages
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.2.0/schema.json"


class PageBuilder:
    """Builder for creating PBIP report pages with visuals."""

    def __init__(
        self,
        definition_path: Path,
        display_name: str,
        page_id: Optional[str] = None,
    ):
        """Initialize the page builder.

        Args:
            definition_path: Path to the report's definition/ folder
            display_name: Display name for the new page
            page_id: Optional page ID (auto-generated if not provided)
        """
        self._definition_path = Path(definition_path)
        self._display_name = display_name
        self._page_id = page_id or generate_visual_id()
        self._width = 1280
        self._height = 720
        self._display_option = 1  # FitToPage
        self._visuals: List[Dict[str, Any]] = []
        self._filters: List[Dict[str, Any]] = []
        self._interactions: List[Dict[str, Any]] = []
        self._background_color: Optional[str] = None

    def set_dimensions(self, width: int, height: int) -> "PageBuilder":
        """Set page dimensions.

        Common sizes:
        - 1280 x 720: Default (16:9)
        - 1920 x 1080: Full HD (16:9)
        - 1366 x 768: Common laptop (16:9)
        - 1024 x 768: 4:3 aspect
        """
        self._width = width
        self._height = height
        return self

    def add_visual(self, visual_dict: Dict[str, Any]) -> "PageBuilder":
        """Add a visual to the page.

        Args:
            visual_dict: Complete visual.json dict (from VisualBuilder.build())
        """
        self._visuals.append(visual_dict)
        return self

    def add_filter(self, filter_dict: Dict[str, Any]) -> "PageBuilder":
        """Add a page-level filter."""
        self._filters.append(filter_dict)
        return self

    def add_interaction(
        self, source_visual: str, target_visual: str, interaction_type: str = "Filter"
    ) -> "PageBuilder":
        """Add a visual interaction rule.

        Args:
            source_visual: Source visual ID
            target_visual: Target visual ID
            interaction_type: "NoFilter", "Filter", or "Highlight"
        """
        self._interactions.append(
            {
                "source": source_visual,
                "target": target_visual,
                "type": interaction_type,
            }
        )
        return self

    def set_background_color(self, hex_color: str) -> "PageBuilder":
        """Set page background color."""
        self._background_color = hex_color
        return self

    @property
    def page_id(self) -> str:
        """Get the page ID."""
        return self._page_id

    def build(self, insert_after: Optional[str] = None) -> Dict[str, Any]:
        """Create the page folder structure and write files.

        Args:
            insert_after: Page ID to insert this page after (default: end)

        Returns:
            Dict with page_id, display_name, visual_count, path
        """
        page_folder = self._definition_path / "pages" / self._page_id
        page_folder.mkdir(parents=True, exist_ok=True)

        # Build page.json
        page_json = self._build_page_json()
        save_json_file(page_folder / "page.json", page_json)

        # Create visual folders
        visuals_folder = page_folder / "visuals"
        if self._visuals:
            visuals_folder.mkdir(exist_ok=True)
            for visual_dict in self._visuals:
                visual_id = visual_dict.get("name", generate_visual_id())
                visual_folder = visuals_folder / visual_id
                visual_folder.mkdir(exist_ok=True)
                save_json_file(visual_folder / "visual.json", visual_dict)

        # Update pages.json
        self._update_pages_json(insert_after)

        return {
            "success": True,
            "page_id": self._page_id,
            "display_name": self._display_name,
            "visual_count": len(self._visuals),
            "path": str(page_folder),
        }

    def _build_page_json(self) -> Dict[str, Any]:
        """Build the page.json content."""
        page_data: Dict[str, Any] = {
            "$schema": PAGE_SCHEMA,
            "name": self._page_id,
            "displayName": self._display_name,
            "displayOption": self._display_option,
            "height": self._height,
            "width": self._width,
        }

        # Add filters
        if self._filters:
            page_data["filterConfig"] = {"filters": self._filters}

        # Add interactions
        if self._interactions:
            page_data["interactions"] = self._interactions

        # Add background
        if self._background_color:
            page_data["objects"] = {
                "background": [
                    {
                        "properties": {
                            "color": {
                                "solid": {
                                    "color": {
                                        "expr": {
                                            "Literal": {"Value": f"'{self._background_color}'"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }

        return page_data

    def _update_pages_json(self, insert_after: Optional[str] = None) -> None:
        """Add this page to pages.json ordering."""
        pages_json_path = self._definition_path / "pages.json"
        pages_meta = load_json_file(pages_json_path)

        if not pages_meta:
            pages_meta = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
                "pageOrder": [],
            }

        page_order = pages_meta.get("pageOrder", [])

        if insert_after and insert_after in page_order:
            idx = page_order.index(insert_after) + 1
            page_order.insert(idx, self._page_id)
        else:
            page_order.append(self._page_id)

        pages_meta["pageOrder"] = page_order
        save_json_file(pages_json_path, pages_meta)
