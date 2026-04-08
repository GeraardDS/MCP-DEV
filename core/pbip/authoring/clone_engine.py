"""
Clone Engine for PBIP Report Authoring

Provides deep-cloning of pages and reports with ID regeneration,
and deletion of pages/visuals from PBIP reports.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pbip.authoring.id_generator import generate_visual_id, generate_guid
from core.utilities.pbip_utils import load_json_file, save_json_file

logger = logging.getLogger(__name__)


class CloneEngine:
    """Deep-clone pages and reports with proper ID regeneration."""

    def clone_page(
        self,
        definition_path: Path,
        source_page_id: str,
        new_display_name: Optional[str] = None,
        insert_after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Clone a page and all its visuals with new IDs.

        Two-pass approach:
        1. Copy folder, collect all old IDs, generate mapping
        2. Rewrite all visual.json files with remapped IDs/parentGroupName

        Args:
            definition_path: Path to the report's definition/ folder
            source_page_id: ID of the page to clone
            new_display_name: Optional new name for the cloned page
            insert_after: Page ID to insert after (default: end)

        Returns:
            Dict with page_id, display_name, visual_count, id_mapping
        """
        pages_dir = definition_path / "pages"
        source_page_dir = pages_dir / source_page_id

        if not source_page_dir.exists():
            # Try finding by display name
            found = self._find_page_by_display_name(pages_dir, source_page_id)
            if found:
                source_page_dir = found
                source_page_id = found.name
            else:
                return {"success": False, "error": f"Source page not found: {source_page_id}"}

        # Generate new page ID
        new_page_id = generate_visual_id()
        new_page_dir = pages_dir / new_page_id

        # Copy entire page folder
        shutil.copytree(str(source_page_dir), str(new_page_dir))

        # Pass 1: Build ID mapping for all visuals
        id_mapping = {source_page_id: new_page_id}
        visuals_dir = new_page_dir / "visuals"
        if visuals_dir.exists():
            for visual_folder in visuals_dir.iterdir():
                if visual_folder.is_dir():
                    old_id = visual_folder.name
                    new_id = generate_visual_id()
                    id_mapping[old_id] = new_id

        # Pass 2: Rename visual folders and rewrite visual.json files
        if visuals_dir.exists():
            # Collect folders to rename (avoid modifying during iteration)
            folders_to_rename = []
            for visual_folder in visuals_dir.iterdir():
                if visual_folder.is_dir() and visual_folder.name in id_mapping:
                    folders_to_rename.append(visual_folder)

            for visual_folder in folders_to_rename:
                old_id = visual_folder.name
                new_id = id_mapping[old_id]

                # Update visual.json
                visual_json_path = visual_folder / "visual.json"
                if visual_json_path.exists():
                    visual_data = load_json_file(visual_json_path)
                    if visual_data:
                        self._remap_visual_ids(visual_data, id_mapping)
                        save_json_file(visual_json_path, visual_data)

                # Rename folder (mobile.json inside moves with the folder)
                new_folder = visuals_dir / new_id
                visual_folder.rename(new_folder)

        # Update page.json
        page_json_path = new_page_dir / "page.json"
        page_data = load_json_file(page_json_path)
        if page_data:
            page_data["name"] = new_page_id
            if new_display_name:
                page_data["displayName"] = new_display_name
            else:
                original_name = page_data.get("displayName", source_page_id)
                page_data["displayName"] = f"{original_name} (Copy)"

            # Remap visual interactions
            if "objects" in page_data:
                self._remap_interactions(page_data, id_mapping)

            save_json_file(page_json_path, page_data)

        # Update pages.json ordering
        display_name = page_data.get("displayName", new_page_id) if page_data else new_page_id
        self._update_pages_json(definition_path, new_page_id, insert_after)

        return {
            "success": True,
            "page_id": new_page_id,
            "display_name": display_name,
            "visual_count": len(id_mapping) - 1,  # Exclude the page ID itself
            "id_mapping": id_mapping,
            "path": str(new_page_dir),
        }

    def clone_report(
        self,
        source_report_path: Path,
        target_path: Path,
        new_report_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Clone an entire .Report folder with new IDs.

        Args:
            source_report_path: Path to source .Report folder
            target_path: Path for the new .Report folder
            new_report_name: Optional new report name

        Returns:
            Dict with report_path, page_count, total_visuals
        """
        source_path = Path(source_report_path)
        target = Path(target_path)

        if not source_path.exists():
            return {"success": False, "error": f"Source report not found: {source_path}"}

        if target.exists():
            return {"success": False, "error": f"Target path already exists: {target}"}

        # Copy entire report folder
        shutil.copytree(str(source_path), str(target))

        # Update .platform with new GUID
        platform_path = target / ".platform"
        if platform_path.exists():
            platform_data = load_json_file(platform_path)
            if platform_data:
                if "config" in platform_data:
                    platform_data["config"]["logicalId"] = generate_guid()
                if new_report_name and "metadata" in platform_data:
                    platform_data["metadata"]["displayName"] = new_report_name
                save_json_file(platform_path, platform_data)

        # Regenerate all page and visual IDs
        definition_path = target / "definition"
        total_visuals = 0
        page_count = 0

        if definition_path.exists():
            pages_dir = definition_path / "pages"
            if pages_dir.exists():
                # Build complete ID mapping for ALL pages and visuals
                all_id_mapping: Dict[str, str] = {}
                page_folders = [f for f in pages_dir.iterdir() if f.is_dir()]

                for page_folder in page_folders:
                    old_page_id = page_folder.name
                    new_page_id = generate_visual_id()
                    all_id_mapping[old_page_id] = new_page_id

                    visuals_dir = page_folder / "visuals"
                    if visuals_dir.exists():
                        for visual_folder in visuals_dir.iterdir():
                            if visual_folder.is_dir():
                                old_visual_id = visual_folder.name
                                new_visual_id = generate_visual_id()
                                all_id_mapping[old_visual_id] = new_visual_id
                                total_visuals += 1

                # Apply ID mapping to all files
                for page_folder in page_folders:
                    old_page_id = page_folder.name
                    new_page_id = all_id_mapping[old_page_id]

                    # Remap visuals
                    visuals_dir = page_folder / "visuals"
                    if visuals_dir.exists():
                        folders_to_rename = [
                            f
                            for f in visuals_dir.iterdir()
                            if f.is_dir() and f.name in all_id_mapping
                        ]
                        for visual_folder in folders_to_rename:
                            visual_json_path = visual_folder / "visual.json"
                            if visual_json_path.exists():
                                visual_data = load_json_file(visual_json_path)
                                if visual_data:
                                    self._remap_visual_ids(visual_data, all_id_mapping)
                                    save_json_file(visual_json_path, visual_data)
                            new_visual_folder = visuals_dir / all_id_mapping[visual_folder.name]
                            visual_folder.rename(new_visual_folder)

                    # Update page.json
                    page_json_path = page_folder / "page.json"
                    page_data = load_json_file(page_json_path)
                    if page_data:
                        page_data["name"] = new_page_id
                        if "objects" in page_data:
                            self._remap_interactions(page_data, all_id_mapping)
                        save_json_file(page_json_path, page_data)

                    # Rename page folder
                    new_page_folder = pages_dir / new_page_id
                    page_folder.rename(new_page_folder)
                    page_count += 1

                # Update pages.json with new page IDs
                pages_json_path = definition_path / "pages.json"
                pages_meta = load_json_file(pages_json_path)
                if pages_meta:
                    old_order = pages_meta.get("pageOrder", [])
                    pages_meta["pageOrder"] = [all_id_mapping.get(pid, pid) for pid in old_order]
                    if "activePageName" in pages_meta:
                        old_active = pages_meta["activePageName"]
                        pages_meta["activePageName"] = all_id_mapping.get(old_active, old_active)
                    save_json_file(pages_json_path, pages_meta)

                # Update bookmarks with new IDs
                self._remap_bookmarks(definition_path, all_id_mapping)

        return {
            "success": True,
            "report_path": str(target),
            "page_count": page_count,
            "total_visuals": total_visuals,
        }

    def delete_page(
        self,
        definition_path: Path,
        page_id: str,
    ) -> Dict[str, Any]:
        """Delete a page and update pages.json.

        Args:
            definition_path: Path to the report's definition/ folder
            page_id: ID or display name of the page to delete

        Returns:
            Dict with success status and details
        """
        pages_dir = definition_path / "pages"
        page_dir = pages_dir / page_id

        if not page_dir.exists():
            found = self._find_page_by_display_name(pages_dir, page_id)
            if found:
                page_dir = found
                page_id = found.name
            else:
                return {"success": False, "error": f"Page not found: {page_id}"}

        # Get display name before deletion
        display_name = ""
        page_json = load_json_file(page_dir / "page.json")
        if page_json:
            display_name = page_json.get("displayName", page_id)

        # Count visuals
        visuals_dir = page_dir / "visuals"
        visual_count = 0
        if visuals_dir.exists():
            visual_count = sum(1 for f in visuals_dir.iterdir() if f.is_dir())

        # Remove page folder
        shutil.rmtree(str(page_dir))

        # Update pages.json
        pages_json_path = definition_path / "pages.json"
        pages_meta = load_json_file(pages_json_path)
        if pages_meta:
            old_order = pages_meta.get("pageOrder", [])
            pages_meta["pageOrder"] = [pid for pid in old_order if pid != page_id]
            if pages_meta.get("activePageName") == page_id:
                pages_meta["activePageName"] = (
                    pages_meta["pageOrder"][0] if pages_meta["pageOrder"] else ""
                )
            save_json_file(pages_json_path, pages_meta)

        return {
            "success": True,
            "deleted_page": page_id,
            "display_name": display_name,
            "visuals_removed": visual_count,
        }

    def delete_visual(
        self,
        definition_path: Path,
        page_id: str,
        visual_id: str,
        delete_children: bool = True,
    ) -> Dict[str, Any]:
        """Delete a visual (and optionally its children if it's a group).

        Args:
            definition_path: Path to the report's definition/ folder
            page_id: Page ID or display name
            visual_id: Visual ID or display name to delete
            delete_children: If True, delete child visuals of groups

        Returns:
            Dict with success status and details
        """
        pages_dir = definition_path / "pages"
        page_dir = pages_dir / page_id

        if not page_dir.exists():
            found = self._find_page_by_display_name(pages_dir, page_id)
            if found:
                page_dir = found
                page_id = found.name
            else:
                return {"success": False, "error": f"Page not found: {page_id}"}

        visuals_dir = page_dir / "visuals"
        if not visuals_dir.exists():
            return {"success": False, "error": "No visuals folder found"}

        # Find the visual - by ID or by display name/title
        visual_dir = visuals_dir / visual_id
        resolved_visual_id = visual_id
        if not visual_dir.exists():
            found_visual = self._find_visual_by_name(visuals_dir, visual_id)
            if found_visual:
                visual_dir = found_visual
                resolved_visual_id = found_visual.name
            else:
                return {"success": False, "error": f"Visual not found: {visual_id}"}

        deleted = [resolved_visual_id]

        # Check if it's a group and delete children
        if delete_children:
            children = self._find_child_visuals(visuals_dir, resolved_visual_id)
            for child_dir in children:
                if child_dir.exists():
                    shutil.rmtree(str(child_dir))
                    deleted.append(child_dir.name)

        # Delete the visual itself (including mobile.json if present inside the folder)
        if visual_dir.exists():
            shutil.rmtree(str(visual_dir))

        return {
            "success": True,
            "deleted_visuals": deleted,
            "count": len(deleted),
            "page_id": page_id,
        }

    # --- Private helpers ---

    def _remap_visual_ids(self, visual_data: Dict[str, Any], id_mapping: Dict[str, str]) -> None:
        """Remap visual IDs in a visual.json dict using the ID mapping."""
        # Remap visual name
        old_name = visual_data.get("name", "")
        if old_name in id_mapping:
            visual_data["name"] = id_mapping[old_name]

        # Remap parentGroupName
        parent_group = visual_data.get("parentGroupName", "")
        if parent_group and parent_group in id_mapping:
            visual_data["parentGroupName"] = id_mapping[parent_group]

    def _remap_interactions(self, page_data: Dict[str, Any], id_mapping: Dict[str, str]) -> None:
        """Remap visual interaction references in page.json."""
        interactions = page_data.get("interactions", [])
        for interaction in interactions:
            source = interaction.get("source", "")
            target = interaction.get("target", "")
            if source in id_mapping:
                interaction["source"] = id_mapping[source]
            if target in id_mapping:
                interaction["target"] = id_mapping[target]

    def _remap_bookmarks(self, definition_path: Path, id_mapping: Dict[str, str]) -> None:
        """Remap page and visual IDs in bookmark files."""
        bookmarks_dir = definition_path / "bookmarks"
        if not bookmarks_dir.exists():
            return

        for bookmark_file in bookmarks_dir.glob("*.bookmark.json"):
            data = load_json_file(bookmark_file)
            if not data:
                continue

            modified = False
            exploration = data.get("explorationState", {})

            # Remap activeSection
            if exploration.get("activeSection") in id_mapping:
                exploration["activeSection"] = id_mapping[exploration["activeSection"]]
                modified = True

            # Remap section keys
            sections = exploration.get("sections", {})
            new_sections = {}
            for section_id, section_data in sections.items():
                new_key = id_mapping.get(section_id, section_id)
                if new_key != section_id:
                    modified = True

                # Remap visual container references
                containers = section_data.get("visualContainers", {})
                new_containers = {}
                for vis_id, vis_state in containers.items():
                    new_vis_id = id_mapping.get(vis_id, vis_id)
                    if new_vis_id != vis_id:
                        modified = True
                    new_containers[new_vis_id] = vis_state
                if new_containers:
                    section_data["visualContainers"] = new_containers

                # Remap visual container group references
                groups = section_data.get("visualContainerGroups", {})
                new_groups = {}
                for grp_id, grp_state in groups.items():
                    new_grp_id = id_mapping.get(grp_id, grp_id)
                    if new_grp_id != grp_id:
                        modified = True
                    new_groups[new_grp_id] = grp_state
                if new_groups:
                    section_data["visualContainerGroups"] = new_groups

                new_sections[new_key] = section_data

            if new_sections:
                exploration["sections"] = new_sections

            # Remap targetVisualNames in options
            options = data.get("options", {})
            targets = options.get("targetVisualNames", [])
            if targets:
                new_targets = [id_mapping.get(t, t) for t in targets]
                if new_targets != targets:
                    options["targetVisualNames"] = new_targets
                    modified = True

            if modified:
                save_json_file(bookmark_file, data)

    def _update_pages_json(
        self, definition_path: Path, new_page_id: str, insert_after: Optional[str] = None
    ) -> None:
        """Add a new page to pages.json ordering."""
        pages_json_path = definition_path / "pages.json"
        pages_meta = load_json_file(pages_json_path)
        if not pages_meta:
            pages_meta = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
                "pageOrder": [],
            }

        page_order = pages_meta.get("pageOrder", [])

        if insert_after and insert_after in page_order:
            idx = page_order.index(insert_after) + 1
            page_order.insert(idx, new_page_id)
        else:
            page_order.append(new_page_id)

        pages_meta["pageOrder"] = page_order
        save_json_file(pages_json_path, pages_meta)

    def _find_page_by_display_name(self, pages_dir: Path, name: str) -> Optional[Path]:
        """Find a page folder by display name (case-insensitive partial match)."""
        if not pages_dir.exists():
            return None
        name_lower = name.lower()
        for page_folder in pages_dir.iterdir():
            if not page_folder.is_dir():
                continue
            page_json = load_json_file(page_folder / "page.json")
            if page_json:
                display_name = page_json.get("displayName", "")
                if display_name.lower() == name_lower or name_lower in display_name.lower():
                    return page_folder
        return None

    def _find_visual_by_name(self, visuals_dir: Path, name: str) -> Optional[Path]:
        """Find a visual folder by display name/title."""
        name_lower = name.lower()
        for visual_folder in visuals_dir.iterdir():
            if not visual_folder.is_dir():
                continue
            visual_json = load_json_file(visual_folder / "visual.json")
            if visual_json:
                # Check visual name
                if visual_json.get("name", "").lower() == name_lower:
                    return visual_folder
                # Check visualGroup displayName
                vg = visual_json.get("visualGroup", {})
                if vg.get("displayName", "").lower() == name_lower:
                    return visual_folder
                # Check title in visualContainerObjects
                vco = visual_json.get("visual", {}).get("visualContainerObjects", {})
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

    def _find_child_visuals(self, visuals_dir: Path, parent_id: str) -> List[Path]:
        """Find all child visuals of a visual group."""
        children = []
        for visual_folder in visuals_dir.iterdir():
            if not visual_folder.is_dir():
                continue
            visual_json = load_json_file(visual_folder / "visual.json")
            if visual_json and visual_json.get("parentGroupName") == parent_id:
                children.append(visual_folder)
                # Recurse for nested groups
                children.extend(self._find_child_visuals(visuals_dir, visual_folder.name))
        return children
