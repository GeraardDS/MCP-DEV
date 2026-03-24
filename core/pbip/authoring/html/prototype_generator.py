"""
Prototype Generator — PBIP to HTML Conversion

Reads a PBIP page and generates an interactive HTML prototype
for layout prototyping with drag-and-drop.

Key behaviors:
- Calculates ABSOLUTE positions by walking parent group chains
- Hides visuals marked isHidden (renders them dimmed with a toggle)
- Renders visual groups as transparent containers
- Resolves ThemeDataColor references to hex colors
- Optionally queries live Power BI data for measure values
"""

import logging
import math
import tempfile
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.utilities.pbip_utils import load_json_file, get_page_display_name

logger = logging.getLogger(__name__)

MAX_PARENT_DEPTH = 50

# Default Power BI theme colors (FODASH theme)
# These can be overridden by reading the actual theme file
DEFAULT_THEME_COLORS = [
    "#4A59A3",  # 0 - Dark blue
    "#454555",  # 1 - Dark gray
    "#AAAABC",  # 2 - Silver/gray
    "#7BB6B3",  # 3 - Teal
    "#158582",  # 4 - Dark teal
    "#324B4A",  # 5 - Very dark teal
    "#A7A475",  # 6 - Olive
    "#F1F1E6",  # 7 - Light cream
]


def _adjust_color(hex_color: str, percent: float) -> str:
    """Adjust a hex color by percent (-1 to 1). Negative = darker, positive = lighter."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)

    if percent > 0:
        # Lighten: blend toward white
        r = int(r + (255 - r) * percent)
        g = int(g + (255 - g) * percent)
        b = int(b + (255 - b) * percent)
    elif percent < 0:
        # Darken: blend toward black
        factor = 1 + percent  # percent is negative, so this is < 1
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)

    r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    return f"#{r:02x}{g:02x}{b:02x}"


class PrototypeGenerator:
    """Generate interactive HTML prototypes from PBIP pages."""

    def __init__(self, theme_colors: List[str] = None):
        self._theme_colors = theme_colors or DEFAULT_THEME_COLORS

    def generate(
        self,
        definition_path: Path,
        page_name: str,
        output_path: Optional[str] = None,
        auto_open: bool = True,
        include_data: bool = False,
        query_executor: Any = None,
        visual_query_builder: Any = None,
    ) -> Dict[str, Any]:
        """Generate an HTML prototype from a PBIP page.

        Args:
            definition_path: Path to the report's definition/ folder
            page_name: Page display name or ID
            output_path: Custom output file path (auto-generated if None)
            auto_open: Whether to open in browser
            include_data: Whether to include live data
            query_executor: QueryExecutor instance for live data queries
            visual_query_builder: VisualQueryBuilder for proper filter context

        Returns:
            Dict with success, path, visual_count
        """
        # Try to load theme colors from the report
        self._load_theme_from_report(definition_path)

        page_dir = self._find_page(definition_path, page_name)
        if not page_dir:
            return {"success": False, "error": f"Page not found: {page_name}"}

        page_json = load_json_file(page_dir / "page.json")
        if not page_json:
            return {"success": False, "error": "Could not read page.json"}

        display_name = page_json.get("displayName", page_name)
        width = page_json.get("width", 1280)
        height = page_json.get("height", 720)

        # Read all visuals with proper hierarchy handling
        visuals = self._read_visuals_with_hierarchy(page_dir)

        # Query live data using the debug tool's VisualQueryBuilder
        if include_data and query_executor and visual_query_builder:
            self._populate_live_data_via_debug(
                visuals, query_executor, visual_query_builder, display_name
            )
        elif include_data and query_executor:
            self._populate_live_data(visuals, query_executor)

        from core.pbip.authoring.html.html_template import generate_html_page

        html = generate_html_page(
            page_name=display_name,
            page_width=width,
            page_height=height,
            visuals=visuals,
        )

        if output_path:
            out_path = Path(output_path)
        else:
            out_path = (
                Path(tempfile.gettempdir())
                / f"pbip_prototype_{display_name.replace(' ', '_')}.html"
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        if auto_open:
            webbrowser.open(str(out_path))

        visible_count = sum(1 for v in visuals if not v.get("is_hidden"))
        return {
            "success": True,
            "path": str(out_path),
            "page_name": display_name,
            "visual_count": len(visuals),
            "visible_count": visible_count,
            "hidden_count": len(visuals) - visible_count,
        }

    def _load_theme_from_report(self, definition_path: Path) -> None:
        """Try to load theme colors from the report's static resources."""
        report_root = definition_path.parent
        resources_dir = report_root / "StaticResources" / "RegisteredResources"
        if not resources_dir.exists():
            return
        for json_file in resources_dir.glob("*.json"):
            try:
                data = load_json_file(json_file)
                if data and "dataColors" in data:
                    colors = data["dataColors"]
                    if isinstance(colors, list) and len(colors) >= 3:
                        self._theme_colors = colors
                        return
            except Exception:
                continue

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

    def _read_visuals_with_hierarchy(self, page_dir: Path) -> List[Dict[str, Any]]:
        """Read all visuals, computing absolute positions via parent chain."""
        visuals_dir = page_dir / "visuals"
        if not visuals_dir.exists():
            return []

        # Pass 1: Load all raw visual data keyed by name
        raw_visuals: Dict[str, Dict[str, Any]] = {}
        for visual_folder in visuals_dir.iterdir():
            if not visual_folder.is_dir():
                continue
            visual_json = load_json_file(visual_folder / "visual.json")
            if visual_json:
                name = visual_json.get("name", visual_folder.name)
                raw_visuals[name] = visual_json

        # Pass 2: Identify hidden groups
        hidden_groups = set()
        for name, data in raw_visuals.items():
            if "visualGroup" in data:
                vg = data.get("visualGroup", {})
                if data.get("isHidden", False) or vg.get("isHidden", False):
                    hidden_groups.add(name)

        # Pass 3: Extract info with absolute positions
        visuals = []
        for name, data in raw_visuals.items():
            visual_info = self._extract_visual_info(data, raw_visuals, hidden_groups)
            visuals.append(visual_info)

        # Sort by z-index
        visuals.sort(key=lambda v: v["position"].get("z", 0))

        return visuals

    def _get_parent_group_offset(
        self, visual_data: Dict[str, Any], all_visuals: Dict[str, Dict[str, Any]]
    ) -> Dict[str, float]:
        """Calculate cumulative offset from parent group chain."""
        total_x = 0.0
        total_y = 0.0
        parent_name = visual_data.get("parentGroupName")
        visited = set()
        depth = 0

        while parent_name and parent_name not in visited and depth < MAX_PARENT_DEPTH:
            visited.add(parent_name)
            depth += 1
            parent_data = all_visuals.get(parent_name)
            if not parent_data:
                break
            parent_pos = parent_data.get("position", {})
            total_x += parent_pos.get("x", 0)
            total_y += parent_pos.get("y", 0)
            parent_name = parent_data.get("parentGroupName")

        return {"x": total_x, "y": total_y}

    def _is_hidden_by_parent(
        self,
        visual_data: Dict[str, Any],
        all_visuals: Dict[str, Dict[str, Any]],
        hidden_groups: set,
    ) -> bool:
        """Check if any ancestor group is hidden."""
        parent_name = visual_data.get("parentGroupName")
        visited = set()
        depth = 0
        while parent_name and parent_name not in visited and depth < MAX_PARENT_DEPTH:
            if parent_name in hidden_groups:
                return True
            visited.add(parent_name)
            depth += 1
            parent_data = all_visuals.get(parent_name)
            if not parent_data:
                break
            parent_name = parent_data.get("parentGroupName")
        return False

    def _extract_visual_info(
        self,
        data: Dict[str, Any],
        all_visuals: Dict[str, Dict[str, Any]],
        hidden_groups: set,
    ) -> Dict[str, Any]:
        """Extract display info with absolute positioning."""
        visual = data.get("visual", {})
        visual_type = visual.get("visualType", "")
        is_group = "visualGroup" in data

        if is_group:
            visual_type = "group"

        pos = data.get("position", {})
        stored_x = pos.get("x", 0)
        stored_y = pos.get("y", 0)

        offset = self._get_parent_group_offset(data, all_visuals)
        abs_x = stored_x + offset["x"]
        abs_y = stored_y + offset["y"]

        is_hidden = data.get("isHidden", False)
        if is_group:
            vg = data.get("visualGroup", {})
            is_hidden = is_hidden or vg.get("isHidden", False)
        if not is_hidden:
            is_hidden = self._is_hidden_by_parent(data, all_visuals, hidden_groups)

        # Title
        title = ""
        vco = visual.get("visualContainerObjects", {})
        title_list = vco.get("title", [])
        for t in title_list:
            props = t.get("properties", {})
            text = props.get("text", {})
            expr = text.get("expr", {})
            lit = expr.get("Literal", {})
            val = lit.get("Value", "")
            if val:
                title = val.strip("'")

        visual_name = data.get("name", "")
        if is_group:
            title = data.get("visualGroup", {}).get("displayName", title or visual_name)

        fields = self._extract_fields(visual)
        is_data = bool(fields.get("measures") or fields.get("columns"))

        fill_color = self._extract_fill_color(visual)

        result = {
            "id": visual_name,
            "visual_type": visual_type,
            "visual_name": visual_name,
            "title": title,
            "position": {
                "x": abs_x,
                "y": abs_y,
                "width": pos.get("width", 200),
                "height": pos.get("height", 100),
                "z": pos.get("z", 0),
            },
            "fields": fields,
            "is_data_visual": is_data,
            "is_visual_group": is_group,
            "is_hidden": is_hidden,
            "parent_group": data.get("parentGroupName", ""),
        }
        if fill_color:
            result["fill_color"] = fill_color
        return result

    def _extract_fields(self, visual: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
        """Extract measure and column references from visual query state."""
        measures = []
        columns = []

        query_state = visual.get("query", {}).get("queryState", {})
        for bucket_name, bucket_data in query_state.items():
            projections = bucket_data.get("projections", [])
            for proj in projections:
                field = proj.get("field", {})
                display_name = proj.get("displayName", proj.get("nativeQueryRef", ""))

                if "Measure" in field:
                    m = field["Measure"]
                    table = m.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                    prop = m.get("Property", "")
                    if table and prop:
                        measures.append(
                            {
                                "table": table,
                                "measure": prop,
                                "display_name": display_name or prop,
                            }
                        )
                elif "Column" in field:
                    c = field["Column"]
                    table = c.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                    prop = c.get("Property", "")
                    if table and prop:
                        columns.append(
                            {
                                "table": table,
                                "column": prop,
                                "display_name": display_name or prop,
                            }
                        )

        return {"measures": measures, "columns": columns}

    def _extract_fill_color(self, visual: Dict[str, Any]) -> Optional[str]:
        """Extract fill color from visual objects, resolving ThemeDataColor references."""
        objects = visual.get("objects", {})
        fill_list = objects.get("fill", [])
        for fill_entry in fill_list:
            props = fill_entry.get("properties", {})
            fill_color = props.get("fillColor", {})
            solid = fill_color.get("solid", {})
            color = solid.get("color", {})
            expr = color.get("expr", {})

            # Direct literal color
            lit = expr.get("Literal", {})
            val = lit.get("Value", "")
            if val:
                return val.strip("'")

            # ThemeDataColor reference
            tdc = expr.get("ThemeDataColor", {})
            if tdc:
                color_id = tdc.get("ColorId", 0)
                percent = tdc.get("Percent", 0)
                if color_id < len(self._theme_colors):
                    base = self._theme_colors[color_id]
                    if percent != 0:
                        return _adjust_color(base, percent)
                    return base

        return None

    def _populate_live_data_via_debug(
        self,
        visuals: List[Dict[str, Any]],
        query_executor: Any,
        visual_query_builder: Any,
        page_name: str,
    ) -> None:
        """Query each visual using the debug tool's VisualQueryBuilder.

        This provides proper filter context (slicers, page filters, report filters)
        so measure values match what Power BI actually shows.
        """
        # Data visual types that need tabular queries
        tabular_types = {
            "columnChart",
            "barChart",
            "lineChart",
            "areaChart",
            "lineClusteredColumnComboChart",
            "lineStackedColumnComboChart",
            "donutChart",
            "pieChart",
            "waterfallChart",
            "clusteredColumnChart",
            "clusteredBarChart",
            "stackedColumnChart",
            "ribbonChart",
            "table",
            "tableEx",
            "matrix",
            "pivotTable",
        }
        # Card types that need scalar queries
        scalar_types = {"card", "cardVisual", "multiRowCard", "kpi", "gauge"}

        for v in visuals:
            if v.get("is_hidden") or v.get("is_visual_group"):
                continue

            vtype = v.get("visual_type", "")
            vid = v.get("id", "")
            measures = v.get("fields", {}).get("measures", [])
            columns = v.get("fields", {}).get("columns", [])

            if not measures:
                continue

            try:
                # Use VisualQueryBuilder to build proper DAX with filter context
                result = visual_query_builder.build_visual_query(
                    page_name=page_name,
                    visual_id=vid,
                    include_slicers=True,
                )
                if not result or not result.query:
                    continue

                # Execute the query
                query = result.query
                exec_result = query_executor.validate_and_execute_dax(query, top_n=50)

                if not exec_result.get("success"):
                    # Try without format string measures (they can cause errors)
                    # Strip the secondary EVALUATE block if present
                    lines = query.split("\n")
                    # Find last EVALUATE and remove it + everything after
                    last_eval_idx = None
                    for i in range(len(lines) - 1, -1, -1):
                        if lines[i].strip().startswith("EVALUATE") and i > 10:
                            last_eval_idx = i
                            break
                    if last_eval_idx and last_eval_idx > 5:
                        # Check if there's another EVALUATE before it
                        has_prior = any(
                            l.strip().startswith("EVALUATE") for l in lines[:last_eval_idx]
                        )
                        if has_prior:
                            query = "\n".join(lines[:last_eval_idx])
                            exec_result = query_executor.validate_and_execute_dax(query, top_n=50)

                if not exec_result.get("success"):
                    continue

                rows = exec_result.get("rows", [])
                if not rows:
                    continue

                if vtype in tabular_types and columns:
                    v["table_data"] = rows
                elif vtype in scalar_types or (not columns and measures):
                    # Extract scalar values from first row
                    data_values = {}
                    row = rows[0] if rows else {}
                    for m in measures:
                        key = f"{m['table']}.{m['measure']}"
                        val = self._find_measure_in_row(row, m["measure"])
                        if val is not None:
                            data_values[key] = self._format_value(val)
                    if data_values:
                        v["data_values"] = data_values
                else:
                    # Has both columns and measures — treat as table data
                    v["table_data"] = rows

            except Exception as e:
                logger.debug(f"Debug query failed for visual {vid}: {e}")

    @staticmethod
    def _find_measure_in_row(row: dict, measure_name: str) -> Any:
        """Find a measure value in a DAX result row by partial key match."""
        if not isinstance(row, dict):
            return None
        # DAX result keys are like '[Measure_Name]' or 'Measure_Name'
        measure_clean = measure_name.replace(" ", "_").replace("-", "_").replace("%", "_")
        for k, v in row.items():
            # Skip format string columns and metadata
            if "FormatString" in k or k.startswith("v__") or k == "[IsGrandTotalRowTotal]":
                continue
            k_clean = (
                k.replace("[", "")
                .replace("]", "")
                .replace(" ", "_")
                .replace("-", "_")
                .replace("%", "_")
            )
            if measure_clean.lower() in k_clean.lower():
                try:
                    return float(v) if v is not None else None
                except (ValueError, TypeError):
                    return v
        return None

    def _populate_live_data(self, visuals: List[Dict[str, Any]], query_executor: Any) -> None:
        """Query Power BI model for measure values AND tabular data.

        For each visible data visual:
        - Cards/KPIs: scalar measure query
        - Charts/tables: SUMMARIZECOLUMNS with category + measures → row data
        - Donuts: SUMMARIZECOLUMNS with category + value
        """
        measure_cache: Dict[str, str] = {}

        for v in visuals:
            if v.get("is_hidden") or v.get("is_visual_group"):
                continue

            vtype = v.get("visual_type", "")
            measures = v.get("fields", {}).get("measures", [])
            columns = v.get("fields", {}).get("columns", [])

            if not measures:
                continue

            # Cards/KPIs — scalar queries
            if vtype in (
                "card",
                "cardVisual",
                "multiRowCard",
                "kpi",
                "gauge",
            ) or (not columns and measures):
                data_values = {}
                for m in measures:
                    table = m.get("table", "")
                    measure = m.get("measure", "")
                    key = f"{table}.{measure}"

                    if key in measure_cache:
                        data_values[key] = measure_cache[key]
                        continue

                    try:
                        dax = f'EVALUATE {{ "{table}"[{measure}] }}'
                        result = query_executor.validate_and_execute_dax(dax, top_n=1)
                        if result.get("success"):
                            rows = result.get("rows", [])
                            if rows:
                                row = rows[0]
                                val = list(row.values())[0] if isinstance(row, dict) else row
                                if val is not None:
                                    formatted = self._format_value(val)
                                    data_values[key] = formatted
                                    measure_cache[key] = formatted
                    except Exception as e:
                        logger.debug(f"Scalar query failed for {key}: {e}")

                if data_values:
                    v["data_values"] = data_values

            # Charts and tables — tabular queries with SUMMARIZECOLUMNS
            elif columns and measures:
                try:
                    rows_data = self._query_tabular_data(query_executor, columns, measures, vtype)
                    if rows_data:
                        v["table_data"] = rows_data
                except Exception as e:
                    logger.debug(f"Tabular query failed for {v.get('id', '')}: {e}")

    def _query_tabular_data(
        self,
        query_executor: Any,
        columns: List[Dict[str, str]],
        measures: List[Dict[str, str]],
        vtype: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Run SUMMARIZECOLUMNS to get tabular data for charts/tables."""
        # Build column references for SUMMARIZECOLUMNS
        col_refs = []
        for c in columns:
            table = c.get("table", "")
            column = c.get("column", "")
            col_refs.append(f"'{table}'[{column}]")

        # Build measure references
        measure_refs = []
        for m in measures:
            table = m.get("table", "")
            measure = m.get("measure", "")
            display = m.get("display_name", measure)
            measure_refs.append(f'"{display}", [{measure}]')

        col_list = ", ".join(col_refs)
        measure_list = ", ".join(measure_refs)

        # Limit rows based on visual type
        top_n = 20
        if vtype in ("pivotTable", "matrix", "table", "tableEx"):
            top_n = 30
        elif vtype in ("donutChart", "pieChart"):
            top_n = 10

        dax = f"EVALUATE TOPN({top_n}, SUMMARIZECOLUMNS({col_list}, {measure_list}))"

        result = query_executor.validate_and_execute_dax(dax, top_n=0)
        if result.get("success"):
            rows = result.get("rows", [])
            return rows
        return None

    @staticmethod
    def _format_value(val: Any) -> str:
        """Format a measure value for display."""
        if val is None:
            return ""
        if isinstance(val, (int, float)):
            abs_val = abs(val)
            if abs_val >= 1_000_000_000:
                return f"{val / 1_000_000_000:,.1f}B"
            elif abs_val >= 1_000_000:
                return f"{val / 1_000_000:,.1f}M"
            elif abs_val >= 1000:
                return f"{val:,.0f}"
            elif abs_val < 1 and abs_val > 0:
                return f"{val:.1%}"
            else:
                return f"{val:,.1f}"
        return str(val)
