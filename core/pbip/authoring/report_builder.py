"""
Report Builder for PBIP Report Authoring

Orchestrates full page/report generation from structured specs.
This is the primary interface for LLM-driven report creation —
Claude builds a spec JSON, and ReportBuilder creates the actual PBIP files.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pbip.authoring.id_generator import generate_visual_id
from core.pbip.authoring.visual_builder import VisualBuilder
from core.pbip.authoring.page_builder import PageBuilder
from core.pbip.authoring.visual_templates import TEMPLATE_REGISTRY

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Build PBIP pages/reports from structured specifications.

    Spec format (simplified JSON that Claude can produce reliably):

    {
        "page_name": "Financial Overview",
        "width": 1920,
        "height": 1080,
        "background_color": "#E6E6E6",
        "visuals": [
            {
                "type": "card",
                "title": "Net Asset Value",
                "position": {"x": 20, "y": 20, "width": 200, "height": 100},
                "measures": [{"table": "m Measure", "measure": "Net Asset Value"}]
            },
            {
                "type": "columnChart",
                "title": "Monthly Performance",
                "position": {"x": 20, "y": 140, "width": 600, "height": 300},
                "category": [{"table": "s Date", "column": "Month"}],
                "values": [{"table": "m Measure", "measure": "NAV Performance"}],
                "formatting": {"legend": {"show": true}}
            },
            {
                "type": "slicer",
                "title": "Period",
                "position": {"x": 640, "y": 20, "width": 200, "height": 60},
                "columns": [{"table": "d Date", "column": "Period"}],
                "slicer_mode": "Dropdown",
                "single_select": true
            },
            {
                "type": "shape",
                "position": {"x": 0, "y": 0, "width": 1920, "height": 60},
                "formatting": {"fill": {"fillColor": "#4A59A3"}}
            },
            {
                "type": "visualGroup",
                "group_name": "KPI Section",
                "position": {"x": 0, "y": 60, "width": 1920, "height": 120},
                "children": [
                    {
                        "type": "card",
                        "title": "Total Value",
                        "position": {"x": 20, "y": 10, "width": 200, "height": 80},
                        "measures": [{"table": "m Measure", "measure": "Total Value"}]
                    }
                ]
            }
        ]
    }
    """

    def generate_from_spec(
        self,
        definition_path: Path,
        spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate a complete PBIP page from a structured specification.

        Args:
            definition_path: Path to the report's definition/ folder
            spec: Page specification dict (see class docstring for format)

        Returns:
            Dict with page_id, visual_count, visual_ids, path, and any errors
        """
        errors: List[str] = []
        visual_ids: List[Dict[str, str]] = []

        # Validate spec
        page_name = spec.get("page_name")
        if not page_name:
            return {"success": False, "error": "spec.page_name is required"}

        # Create page builder
        page_builder = PageBuilder(
            definition_path=definition_path,
            display_name=page_name,
        )

        width = spec.get("width", 1280)
        height = spec.get("height", 720)
        page_builder.set_dimensions(int(width), int(height))

        bg_color = spec.get("background_color")
        if bg_color:
            page_builder.set_background_color(bg_color)

        # Process visuals
        visuals_spec = spec.get("visuals", [])
        for i, visual_spec in enumerate(visuals_spec):
            try:
                built_visuals = self._build_visual_from_spec(visual_spec, page_builder.page_id)
                for bv in built_visuals:
                    page_builder.add_visual(bv)
                    visual_ids.append(
                        {
                            "id": bv["name"],
                            "type": visual_spec.get("type", "unknown"),
                            "title": visual_spec.get("title", ""),
                        }
                    )
            except Exception as e:
                errors.append(f"Visual {i} ({visual_spec.get('type', '?')}): {e}")

        # Process page-level filters
        for f in spec.get("filters", []):
            page_builder.add_filter(f)

        # Build the page
        insert_after = spec.get("insert_after")
        result = page_builder.build(insert_after=insert_after)

        result["visual_ids"] = visual_ids
        if errors:
            result["errors"] = errors
            result["errors_count"] = len(errors)

        return result

    def _build_visual_from_spec(
        self,
        spec: Dict[str, Any],
        page_id: str,
    ) -> List[Dict[str, Any]]:
        """Build one or more visual dicts from a spec entry.

        For visual groups with children, returns the group + all child visuals.

        Args:
            spec: Single visual specification
            page_id: Parent page ID (for context)

        Returns:
            List of visual.json dicts
        """
        visual_type = spec.get("type", "")
        if not visual_type:
            raise ValueError("visual type is required")

        # Handle visual groups with children
        if visual_type in ("visualGroup", "group"):
            return self._build_visual_group_from_spec(spec)

        # Validate type
        if visual_type not in TEMPLATE_REGISTRY:
            raise ValueError(
                f"Unknown visual type: '{visual_type}'. "
                f"Available: {', '.join(sorted(set(TEMPLATE_REGISTRY.keys())))}"
            )

        builder = VisualBuilder(visual_type)

        # Position
        pos = spec.get("position", {})
        builder.position(
            x=pos.get("x", 0),
            y=pos.get("y", 0),
            width=pos.get("width", 300),
            height=pos.get("height", 200),
            z=pos.get("z", 0),
            tab_order=pos.get("tab_order", 0),
        )

        # Title
        title = spec.get("title")
        if title:
            builder.set_title(title)

        # Data bindings - measures (flexible input)
        for m in spec.get("measures", []):
            builder.add_measure(
                table=m.get("table", ""),
                measure=m.get("measure", ""),
                bucket=m.get("bucket"),
                display_name=m.get("display_name"),
            )

        # Data bindings via "values" key (alias for measures)
        for m in spec.get("values", []):
            builder.add_measure(
                table=m.get("table", ""),
                measure=m.get("measure", ""),
                bucket=m.get("bucket"),
                display_name=m.get("display_name"),
            )

        # Data bindings - columns
        for c in spec.get("columns", []):
            builder.add_column(
                table=c.get("table", ""),
                column=c.get("column", ""),
                bucket=c.get("bucket"),
                display_name=c.get("display_name"),
            )

        # Data bindings via "category" key (alias for columns in Category bucket)
        for c in spec.get("category", []):
            builder.add_column(
                table=c.get("table", ""),
                column=c.get("column", ""),
                bucket="Category",
                display_name=c.get("display_name"),
            )

        # Data bindings via "rows" key (for matrix)
        for r in spec.get("rows", []):
            builder.add_column(
                table=r.get("table", ""),
                column=r.get("column", ""),
                bucket="Rows",
                display_name=r.get("display_name"),
            )

        # Parent group
        parent = spec.get("parent_group")
        if parent:
            builder.in_group(parent)

        # Hidden
        if spec.get("hidden"):
            builder.hidden()

        # Sort
        sort = spec.get("sort")
        if sort:
            builder.set_sort(
                table=sort.get("table", ""),
                field=sort.get("field", ""),
                field_type=sort.get("field_type", "Measure"),
                direction=sort.get("direction", "Descending"),
            )

        # Slicer config
        slicer_mode = spec.get("slicer_mode")
        if slicer_mode:
            builder.set_slicer_mode(
                mode=slicer_mode,
                single_select=spec.get("single_select", False),
            )

        # Sync group (slicers)
        sync_group = spec.get("sync_group")
        if sync_group:
            builder.set_sync_group(sync_group)

        # Formatting overrides
        formatting = spec.get("formatting", {})
        if isinstance(formatting, dict):
            for config_type, props in formatting.items():
                if isinstance(props, dict):
                    for prop_name, value in props.items():
                        builder.set_formatting(config_type, prop_name, value)
        elif isinstance(formatting, list):
            for fmt in formatting:
                builder.set_formatting(
                    config_type=fmt.get("config_type", ""),
                    property_name=fmt.get("property_name", ""),
                    value=fmt.get("value"),
                )

        return [builder.build()]

    def _build_visual_group_from_spec(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build a visual group and its children from spec.

        Returns the group visual followed by all child visuals.
        """
        group_id = generate_visual_id()

        # Build the group itself
        group_builder = VisualBuilder("visualGroup", name=group_id)
        pos = spec.get("position", {})
        group_builder.position(
            x=pos.get("x", 0),
            y=pos.get("y", 0),
            width=pos.get("width", 400),
            height=pos.get("height", 300),
            z=pos.get("z", 0),
        )
        group_builder.set_group_name(spec.get("group_name", "Group"))

        parent = spec.get("parent_group")
        if parent:
            group_builder.in_group(parent)

        result = [group_builder.build()]

        # Build children with parentGroupName set to this group
        for child_spec in spec.get("children", []):
            child_spec = dict(child_spec)  # Don't mutate original
            child_spec["parent_group"] = group_id
            child_visuals = self._build_visual_from_spec(child_spec, "")
            result.extend(child_visuals)

        return result
