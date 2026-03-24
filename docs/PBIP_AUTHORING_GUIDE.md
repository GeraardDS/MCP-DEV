# PBIP Report Authoring & Prototyping — Full Flow Guide

## Overview

Two new MCP tools enable full report authoring in Power BI's PBIP format:

| Tool | Purpose |
|------|---------|
| `11_PBIP_Authoring` | Create, clone, and delete pages/visuals |
| `11_PBIP_Prototype` | Generate pages from specs, HTML prototyping |

---

## Quick Reference

### 11_PBIP_Authoring Operations

| Operation | Description | Key Params |
|-----------|-------------|------------|
| `clone_page` | Clone a page with all visuals | `source_page`, `new_display_name` |
| `clone_report` | Clone entire report | `target_path`, `new_report_name` |
| `create_page` | Create empty page | `page_name`, `width`, `height` |
| `create_visual` | Add visual to page | `page_id`, `visual_type`, `position`, `measures`, `columns` |
| `create_visual_group` | Add visual group container | `page_id`, `group_name`, `position` |
| `delete_page` | Remove page | `page_id` or `page_name` |
| `delete_visual` | Remove visual | `page_id`, `visual_id`, `delete_children` |
| `list_templates` | Show available visual types | _(none)_ |
| `get_template` | Get template structure | `visual_type` |

### 11_PBIP_Prototype Operations

| Operation | Description | Key Params |
|-----------|-------------|------------|
| `generate_from_spec` | Create page from JSON spec | `spec` |
| `generate_html` | Export page to interactive HTML | `page_name`, `auto_open` |
| `apply_html` | Apply HTML changes back to PBIP | `state`, `dry_run` |

---

## Flow 1: Clone an Existing Page

Use this when you want to duplicate a page as a starting point.

```
Tool: 11_PBIP_Authoring
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "clone_page",
    "source_page": "Global Wealth",
    "new_display_name": "Global Wealth v2"
}
```

This creates a complete copy with all visuals, groups, and filters — all IDs regenerated.

---

## Flow 2: Generate a Page from Spec (Recommended)

This is the primary workflow. Claude builds a structured spec, the tool creates the PBIP files.

```
Tool: 11_PBIP_Prototype
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "generate_from_spec",
    "spec": {
        "page_name": "Financial Overview",
        "width": 1920,
        "height": 1080,
        "background_color": "#E6E6E6",
        "visuals": [
            {
                "type": "shape",
                "position": {"x": 0, "y": 0, "width": 1920, "height": 60},
                "formatting": {"fill": {"fillColor": "#4A59A3"}}
            },
            {
                "type": "card",
                "title": "Net Asset Value",
                "position": {"x": 20, "y": 80, "width": 250, "height": 120},
                "measures": [{"table": "m Measure", "measure": "Net Asset Value"}]
            },
            {
                "type": "card",
                "title": "Total MWR",
                "position": {"x": 290, "y": 80, "width": 250, "height": 120},
                "measures": [{"table": "m Measure", "measure": "Total MWR"}]
            },
            {
                "type": "columnChart",
                "title": "Monthly Performance",
                "position": {"x": 20, "y": 220, "width": 900, "height": 400},
                "category": [{"table": "s Date", "column": "Month Year"}],
                "values": [
                    {"table": "m Measure", "measure": "NAV Performance"},
                    {"table": "m Measure", "measure": "Total Performance"}
                ],
                "formatting": {
                    "legend": {"show": true, "position": "TopRight"}
                }
            },
            {
                "type": "donutChart",
                "title": "NAV by Currency",
                "position": {"x": 940, "y": 220, "width": 400, "height": 400},
                "category": [{"table": "d Asset", "column": "Currency"}],
                "values": [{"table": "m Measure", "measure": "Net Asset Value"}]
            },
            {
                "type": "slicer",
                "title": "Family",
                "position": {"x": 20, "y": 640, "width": 200, "height": 60},
                "columns": [{"table": "d Family", "column": "Family Name"}],
                "slicer_mode": "Dropdown",
                "single_select": true
            },
            {
                "type": "slicer",
                "title": "Period",
                "position": {"x": 240, "y": 640, "width": 200, "height": 60},
                "columns": [{"table": "d Date", "column": "Period"}],
                "slicer_mode": "Dropdown"
            },
            {
                "type": "visualGroup",
                "group_name": "KPI Bar",
                "position": {"x": 560, "y": 80, "width": 800, "height": 120},
                "children": [
                    {
                        "type": "card",
                        "title": "Performance MTD",
                        "position": {"x": 10, "y": 10, "width": 180, "height": 80},
                        "measures": [{"table": "m Measure", "measure": "Performance MTD"}]
                    },
                    {
                        "type": "card",
                        "title": "Performance YTD",
                        "position": {"x": 200, "y": 10, "width": 180, "height": 80},
                        "measures": [{"table": "m Measure", "measure": "Performance YTD"}]
                    }
                ]
            }
        ]
    }
}
```

### Spec Format Reference

```
{
    "page_name": string (required),
    "width": int (default: 1280),
    "height": int (default: 720),
    "background_color": string (hex, e.g., "#E6E6E6"),
    "insert_after": string (page ID to insert after),
    "visuals": [
        {
            "type": string (required — see list_templates for options),
            "title": string,
            "position": {
                "x": number, "y": number,
                "width": number, "height": number,
                "z": int (z-order, optional)
            },

            // Data bindings (use whichever is natural):
            "measures": [{"table": str, "measure": str, "bucket?": str}],
            "columns": [{"table": str, "column": str, "bucket?": str}],
            "category": [{"table": str, "column": str}],   // → Category bucket
            "values": [{"table": str, "measure": str}],     // → Values/Y bucket
            "rows": [{"table": str, "column": str}],        // → Rows bucket (matrix)

            // Slicer options:
            "slicer_mode": "Dropdown" | "List",
            "single_select": bool,
            "sync_group": string,

            // Visual group with children:
            "group_name": string,
            "children": [visual_spec...],  // child positions are relative to group

            // Formatting overrides (nested dict):
            "formatting": {
                "config_type": {"property": value, ...},
                ...
            },

            // Sort:
            "sort": {"table": str, "field": str, "direction?": "Ascending"|"Descending"},

            // Other:
            "parent_group": string (visual ID),
            "hidden": bool
        }
    ]
}
```

### Available Visual Types

**Charts**: columnChart, barChart, lineChart, areaChart, donutChart, pieChart, waterfallChart,
lineClusteredColumnComboChart, clusteredColumnChart, clusteredBarChart, stackedColumnChart, ribbonChart

**Tables**: table/tableEx, matrix/pivotTable

**KPI/Cards**: card/cardVisual, multiRowCard, kpi, gauge

**Slicers**: slicer

**Layout**: shape, textbox, actionButton, image

**Groups**: visualGroup/group

### Bucket Names Per Visual Type

| Visual Type | Category | Values | Other Buckets |
|-------------|----------|--------|---------------|
| columnChart, barChart, lineChart | Category | Y | — |
| donutChart, pieChart | Category | Y | — |
| stackedColumnChart, ribbonChart | Category | Y | Series |
| lineClusteredColumnComboChart | Category | Y | Y2 (secondary axis) |
| table, tableEx | — | Values | — |
| matrix, pivotTable | — | Values | Rows, Columns |
| card, cardVisual | — | Data | — |
| multiRowCard | — | Values | — |
| kpi | — | Value | TrendAxis, Goal |
| gauge | — | Value | MinValue, MaxValue, TargetValue |
| slicer | — | Values | — |

---

## Flow 3: HTML Prototyping (Visual Layout)

### Step 1: Generate HTML from existing page

```
Tool: 11_PBIP_Prototype
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "generate_html",
    "page_name": "Global Wealth",
    "auto_open": true
}
```

Opens an interactive HTML page where you can:
- **Drag** visuals to reposition
- **Resize** via corner handle
- **Click** to see properties (type, position, data bindings)
- **Export State** button saves JSON to clipboard

### Step 2: Make changes in the HTML

Drag and resize visuals in the browser. The layout is a 1:1 representation of the PBIP page canvas.

### Step 3: Apply changes back to PBIP

Click "Export State (JSON)" in the HTML, then:

```
Tool: 11_PBIP_Prototype
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "apply_html",
    "state": { ... paste exported JSON ... },
    "dry_run": true
}
```

Use `dry_run: true` first to preview changes, then `dry_run: false` to apply.

---

## Flow 4: Build a Page Step-by-Step

For more control, build visuals one at a time:

### Step 1: Create empty page
```
Tool: 11_PBIP_Authoring
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "create_page",
    "page_name": "Custom Dashboard",
    "width": 1920,
    "height": 1080
}
```
→ Returns `page_id`

### Step 2: Add visuals
```
Tool: 11_PBIP_Authoring
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "create_visual",
    "page_id": "<page_id from step 1>",
    "visual_type": "columnChart",
    "title": "Revenue Trend",
    "position": {"x": 20, "y": 20, "width": 600, "height": 300},
    "measures": [{"table": "m Measure", "measure": "Revenue"}],
    "columns": [{"table": "d Date", "column": "Month"}]
}
```

### Step 3: Add a visual group with children
```
Tool: 11_PBIP_Authoring
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "create_visual_group",
    "page_id": "<page_id>",
    "group_name": "Header Section",
    "position": {"x": 0, "y": 0, "width": 1920, "height": 80}
}
```
→ Returns `visual_id` (the group ID)

Then add children to the group:
```
Tool: 11_PBIP_Authoring
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "create_visual",
    "page_id": "<page_id>",
    "visual_type": "textbox",
    "position": {"x": 20, "y": 10, "width": 300, "height": 50},
    "parent_group": "<group visual_id>"
}
```

### Step 4: Fine-tune formatting with existing tools

Use `08_Visual_Operations` (update_visual_config) for detailed formatting:
```
Tool: 08_Visual_Operations
{
    "pbip_path": "C:/Repo/MyReport.Report",
    "operation": "update_visual_config",
    "visual_name": "<visual_id>",
    "config_type": "categoryAxis",
    "property_name": "fontSize",
    "property_value": 10
}
```

---

## Flow 5: Clone and Modify

1. Clone an existing page as template
2. Delete unwanted visuals
3. Add new visuals
4. Adjust positions

```
# Clone
11_PBIP_Authoring → clone_page (source: "Global Wealth", name: "Custom View")

# Remove visuals not needed
11_PBIP_Authoring → delete_visual (page: "Custom View", visual: "<id>")

# Add new visuals
11_PBIP_Authoring → create_visual (page: "Custom View", type: "lineChart", ...)

# Adjust positions
08_Visual_Operations → update_position (visual: "<id>", x: 100, y: 200)
```

---

## Flow 6: Clone Entire Report

```
Tool: 11_PBIP_Authoring
{
    "pbip_path": "C:/Repo/Original.Report",
    "operation": "clone_report",
    "target_path": "C:/Repo/Copy.Report",
    "new_report_name": "My Report Copy"
}
```

All page IDs, visual IDs, bookmark references, and interaction references are regenerated.

---

## Tips

1. **Use `generate_from_spec` for new pages** — it's the most efficient. One call creates the entire page with all visuals.

2. **Use `clone_page` + modifications for similar pages** — faster than building from scratch when an existing page is close to what you need.

3. **Spec accepts flexible data binding keys** — `measures`/`values`, `columns`/`category`/`rows` are all accepted. Use whatever feels natural.

4. **Visual groups: child positions are absolute** — when using `generate_from_spec` with `children`, the child positions are relative to the page canvas (the system handles the rest).

5. **After creating pages, open in Power BI Desktop** — save the PBIP project and reopen in Power BI to see the results. Power BI will render all visuals with real data.

6. **Use `list_templates`** to see all 24 supported visual types and their expected data binding bucket names.

7. **Formatting overrides** in the spec use the same config_type/property names as `08_Visual_Operations`. Common ones: `valueAxis.show`, `legend.show`, `legend.position`, `labels.show`, `fill.fillColor`.

8. **HTML prototype is for layout only** — use it to experiment with positioning and visual arrangement. For data binding and formatting, use the MCP tools directly.
