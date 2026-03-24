"""
HTML Template for PBIP Report Prototyping

Generates a single-file interactive HTML page that closely mirrors
a Power BI report page. Renders visuals with type-appropriate styling:
- Cards show measure values with prominent KPI display
- Charts show placeholder chart shapes (SVG)
- Slicers show dropdown/list appearance
- Shapes render as colored backgrounds (extracting fill_color)
- Tables show column headers with alternating rows
- Groups are invisible containers (toggleable)
- Page navigators render as horizontal tabs
- Action buttons render as small icon-like elements
"""

import math
from typing import Any, Dict, List, Optional


def generate_html_page(
    page_name: str,
    page_width: int,
    page_height: int,
    visuals: List[Dict[str, Any]],
    model_tables: List[str] = None,
) -> str:
    """Generate a complete interactive HTML prototype page."""
    visible = [v for v in visuals if not v.get("is_hidden")]
    hidden = [v for v in visuals if v.get("is_hidden")]

    visual_divs = _render_visual_divs(visible, is_hidden=False)
    hidden_divs = _render_visual_divs(hidden, is_hidden=True)
    visual_data_js = _render_visual_data_js(visuals)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PBIP Prototype: {_esc(page_name)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="toolbar">
    <h2>{_esc(page_name)}</h2>
    <div class="toolbar-actions">
        <span class="info">{page_width}&times;{page_height} &middot; {len(visible)} visible &middot; {len(hidden)} hidden</span>
        <label class="toggle"><input type="checkbox" id="tog-hidden" onchange="toggleHidden()"> Hidden</label>
        <label class="toggle"><input type="checkbox" id="tog-groups" onchange="toggleGroups()"> Groups</label>
        <label class="toggle"><input type="checkbox" checked id="tog-labels" onchange="toggleLabels()"> Labels</label>
        <button onclick="exportState()" class="btn pri">Export JSON</button>
        <button onclick="copyState()" class="btn sec">Copy</button>
    </div>
</div>
<div class="canvas-wrap">
    <div class="canvas" id="canvas" style="width:{page_width}px;height:{page_height}px;">
{visual_divs}
{hidden_divs}
    </div>
</div>
<div id="props" class="props hide">
    <h3>Properties</h3>
    <div id="props-body"></div>
    <button onclick="closeProps()" class="btn sec sm">Close</button>
</div>
<div id="modal" class="modal hide">
    <div class="modal-box">
        <h3>Exported State</h3>
        <textarea id="export-ta" rows="20" readonly></textarea>
        <div class="modal-foot">
            <button onclick="navigator.clipboard.writeText(document.getElementById('export-ta').value)" class="btn pri">Copy</button>
            <button onclick="document.getElementById('modal').classList.add('hide')" class="btn sec">Close</button>
        </div>
    </div>
</div>
<script>
{visual_data_js}
{_JS}
</script>
</body>
</html>"""


def _render_visual_divs(visuals: List[Dict[str, Any]], is_hidden: bool = False) -> str:
    """Render visuals with type-appropriate HTML content."""
    lines = []
    for v in visuals:
        pos = v.get("position", {})
        x, y = pos.get("x", 0), pos.get("y", 0)
        w, h = pos.get("width", 200), pos.get("height", 100)
        z = pos.get("z", 0)
        vid = v.get("id", "")
        vtype = v.get("visual_type", "unknown")
        title = v.get("title", "") or ""
        is_group = v.get("is_visual_group", False)
        fields = v.get("fields", {})
        measures = fields.get("measures", [])
        columns = fields.get("columns", [])
        data_values = v.get("data_values", {})
        fill_color = v.get("fill_color", "")
        table_data = v.get("table_data")

        # Determine CSS class and inner content based on type
        cls, inner = _render_visual_content(
            vtype,
            title,
            measures,
            columns,
            is_group,
            data_values,
            w,
            h,
            fill_color,
            table_data=table_data,
        )

        extra_style = ""
        if is_hidden:
            cls += " v-hidden"

        display = "none" if is_hidden else "block"

        # For shapes with fill_color, apply inline background
        if vtype == "shape" and fill_color:
            extra_style = f"background:{fill_color};"

        # Groups default to display:none
        if is_group and not is_hidden:
            display = "none"
            cls += " v-group-item"

        lines.append(
            f'<div class="v {cls}" id="v-{vid}" data-vid="{vid}" data-vtype="{vtype}" '
            f'style="left:{x:.0f}px;top:{y:.0f}px;width:{w:.0f}px;height:{h:.0f}px;'
            f'z-index:{z};display:{display};{extra_style}" '
            f"onclick=\"sel(event,'{vid}')\" onmousedown=\"dragS(event,'{vid}')\">"
            f"{inner}"
            f'<div class="rh" onmousedown="resS(event,\'{vid}\')"></div>'
            f"</div>"
        )
    return "\n".join(lines)


def _render_visual_content(
    vtype: str,
    title: str,
    measures: list,
    columns: list,
    is_group: bool,
    data_values: dict,
    w: float,
    h: float,
    fill_color: str = "",
    table_data: list = None,
) -> tuple:
    """Return (css_class, inner_html) for a visual based on its type."""
    t = _esc(title)

    # Visual groups -- completely invisible container
    if is_group:
        return "v-group", f'<div class="v-lbl">{t}</div>' if t else ""

    # Shapes -- colored background, no content
    if vtype == "shape":
        return "v-shape", ""

    # Cards -- show measure value prominently as KPI
    if vtype in ("card", "cardVisual"):
        return "v-card", _render_card(t, measures, data_values, w, h)

    # Multi-row cards
    if vtype == "multiRowCard":
        items = ""
        for m in measures[:6]:
            mn = m.get("measure", "")
            key = f"{m.get('table','')}.{mn}"
            val = data_values.get(key, "") if data_values else ""
            items += (
                f'<div class="mrc-item">'
                f'<span class="mrc-val">{val or "---"}</span>'
                f'<span class="mrc-label">{_esc(mn)}</span>'
                f"</div>"
            )
        return "v-mrc", (f'<div class="v-title">{t}</div>' f'<div class="mrc-grid">{items}</div>')

    # Slicers -- dropdown appearance
    if vtype in ("slicer", "advancedSlicerVisual"):
        col = columns[0].get("column", "") if columns else ""
        label = t or _esc(col)
        return "v-slicer", (
            f'<div class="slicer-body">'
            f'<span class="slicer-label">{label}</span>'
            f'<span class="slicer-arrow">&#9662;</span>'
            f"</div>"
        )

    # Column/bar charts — detect waterfall pattern by WF measure names
    if vtype in (
        "columnChart",
        "barChart",
        "clusteredColumnChart",
        "clusteredBarChart",
        "stackedColumnChart",
        "stackedBarChart",
        "hundredPercentStackedColumnChart",
        "hundredPercentStackedBarChart",
    ):
        # Detect waterfall pattern: measures named WF1-WF5
        measure_names_lower = [m.get("measure", "").lower() for m in measures]
        is_waterfall = any("wf1" in mn or "wf2" in mn or "wf3" in mn for mn in measure_names_lower)

        if is_waterfall:
            ms = ", ".join(m.get("display_name", m.get("measure", "")) for m in measures[:3])
            bars = (
                _svg_waterfall_from_data(w, h, table_data, columns, measures)
                if table_data
                else _svg_waterfall(w, h)
            )
            return "v-chart", (
                f'<div class="v-title">{t}</div>'
                f'<div class="chart-body">{bars}</div>'
                f'<div class="chart-legend">{_esc(ms)}</div>'
            )

        ms = ", ".join(m.get("display_name", m.get("measure", "")) for m in measures[:3])
        bars = (
            _svg_bars_from_data(w, h, table_data, columns, measures)
            if table_data
            else _svg_bars(w, h)
        )
        return "v-chart", (
            f'<div class="v-title">{t}</div>'
            f'<div class="chart-body">{bars}</div>'
            f'<div class="chart-legend">{_esc(ms)}</div>'
        )

    # Waterfall charts (explicit type)
    if vtype == "waterfallChart":
        ms = ", ".join(m.get("display_name", m.get("measure", "")) for m in measures[:3])
        bars = (
            _svg_waterfall_from_data(w, h, table_data, columns, measures)
            if table_data
            else _svg_waterfall(w, h)
        )
        return "v-chart", (
            f'<div class="v-title">{t}</div>'
            f'<div class="chart-body">{bars}</div>'
            f'<div class="chart-legend">{_esc(ms)}</div>'
        )

    # Line/area/combo charts
    if vtype in (
        "lineChart",
        "areaChart",
        "lineClusteredColumnComboChart",
        "lineStackedColumnComboChart",
    ):
        ms = ", ".join(m.get("display_name", m.get("measure", "")) for m in measures[:3])
        if table_data:
            chart = _svg_combo_from_data(w, h, table_data, columns, measures)
        elif vtype in ("lineClusteredColumnComboChart", "lineStackedColumnComboChart"):
            chart = _svg_combo(w, h)
        else:
            chart = _svg_line(w, h)
        return "v-chart", (
            f'<div class="v-title">{t}</div>'
            f'<div class="chart-body">{chart}</div>'
            f'<div class="chart-legend">{_esc(ms)}</div>'
        )

    # Donut/pie
    if vtype in ("donutChart", "pieChart"):
        if table_data:
            donut = _svg_donut_from_data(w, h, table_data, columns, measures, vtype == "donutChart")
        else:
            donut = _svg_donut(w, h, vtype == "donutChart")
        return "v-chart v-chart-donut", (
            f'<div class="v-title">{t}</div>' f'<div class="chart-body donut-body">{donut}</div>'
        )

    # Tables/matrices
    if vtype in ("table", "tableEx", "matrix", "pivotTable"):
        return "v-table", _render_table(t, measures, columns, data_values, w, h, table_data)

    # Textbox
    if vtype == "textbox":
        return "v-textbox", f'<div class="tb-text">{t}</div>'

    # Page navigator -- horizontal tabs
    if vtype == "pageNavigator":
        return "v-pagenav", _render_page_navigator(t, w, h)

    # Action buttons -- small icon-like
    if vtype == "actionButton":
        return "v-action-btn", _render_action_button(t, w, h)

    # Bookmark navigator
    if vtype == "bookmarkNavigator":
        return "v-action-btn", _render_action_button(t or "Bookmarks", w, h)

    # Image
    if vtype == "image":
        return "v-img", (
            f'<svg viewBox="0 0 24 24" class="img-icon" fill="none" stroke="#bbb" stroke-width="1.5">'
            f'<rect x="3" y="3" width="18" height="18" rx="2"/>'
            f'<circle cx="8.5" cy="8.5" r="1.5"/>'
            f'<path d="M21 15l-5-5L5 21"/>'
            f"</svg>"
        )

    # KPI/Gauge
    if vtype in ("kpi", "gauge"):
        return "v-card", _render_card(t, measures, data_values, w, h)

    # Fallback
    ms = ", ".join(m.get("measure", "") for m in measures[:3])
    cs = ", ".join(c.get("column", "") for c in columns[:3])
    field_text = _esc(ms) if ms else _esc(cs)
    return "v-default", (
        f'<div class="v-title">{t or vtype}</div>' f'<div class="v-fields">{field_text}</div>'
    )


# ── Card rendering ──────────────────────────────────────────────────


def _render_card(title: str, measures: list, data_values: dict, w: float, h: float) -> str:
    """Render card visual with KPI-style display."""
    if not measures:
        return (
            f'<div class="card-content">'
            f'<div class="card-label">{title}</div>'
            f'<div class="card-value">---</div>'
            f"</div>"
        )

    # Single measure card (most common)
    if len(measures) == 1:
        m = measures[0]
        mn = m.get("measure", "")
        key = f"{m.get('table','')}.{mn}"
        val = str(data_values.get(key, "")) if data_values else ""
        label = title or _esc(mn)
        display_val = _format_value(val) if val else "---"
        # Scale font based on card size
        font_size = min(36, max(16, int(h * 0.25)))
        return (
            f'<div class="card-content">'
            f'<div class="card-label">{label}</div>'
            f'<div class="card-value" style="font-size:{font_size}px">{display_val}</div>'
            f"</div>"
        )

    # Multiple measures -- side by side
    items = ""
    for i, m in enumerate(measures[:4]):
        mn = m.get("measure", "")
        key = f"{m.get('table','')}.{mn}"
        val = str(data_values.get(key, "")) if data_values else ""
        display_val = _format_value(val) if val else "---"
        items += (
            f'<div class="card-multi-item">'
            f'<div class="card-multi-val">{display_val}</div>'
            f'<div class="card-multi-label">{_esc(mn)}</div>'
            f"</div>"
        )
    label = title or ""
    header = f'<div class="card-label">{label}</div>' if label else ""
    return (
        f'<div class="card-content">'
        f"{header}"
        f'<div class="card-multi-row">{items}</div>'
        f"</div>"
    )


def _format_value(val: str) -> str:
    """Format a numeric value for display (add thousands separators)."""
    if not val:
        return "---"
    try:
        num = float(val)
        if num == int(num) and abs(num) >= 1000:
            return f"{int(num):,}"
        elif abs(num) >= 1000:
            return f"{num:,.2f}"
        elif abs(num) < 1 and num != 0:
            return f"{num:.2%}" if abs(num) < 10 else f"{num:.2f}"
        return val
    except (ValueError, TypeError):
        return _esc(str(val))


def _format_chart_label(val: float) -> str:
    """Format a numeric value for chart data labels (compact representation).

    Uses M for millions, K for thousands. Keeps labels short for chart readability.
    """
    if val == 0:
        return "0"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1_000_000_000:
        return f"{sign}{abs_val / 1_000_000_000:.1f}B"
    if abs_val >= 1_000_000:
        return f"{sign}{abs_val / 1_000_000:.1f}M"
    if abs_val >= 1_000:
        return f"{sign}{abs_val / 1_000:.1f}K"
    if abs_val >= 1:
        return f"{sign}{abs_val:.1f}"
    return f"{val:.2%}"


# ── Table rendering ─────────────────────────────────────────────────


def _render_table(
    title: str,
    measures: list,
    columns: list,
    data_values: dict,
    w: float,
    h: float,
    table_data: list = None,
) -> str:
    """Render table/matrix with professional styling and live data."""
    all_fields = columns + measures
    visible_cols = min(len(all_fields), max(2, int(w / 80)))
    display_fields = all_fields[:visible_cols]

    # Build header names: display_name for header text, raw name for DAX lookup
    hdrs = ""
    col_keys = []
    for f in display_fields:
        display = f.get("display_name", f.get("column", f.get("measure", "")))
        raw = f.get("column", f.get("measure", display))  # Raw name for DAX key matching
        is_measure = "measure" in f
        align = "tbl-right" if is_measure else ""
        hdrs += f'<th class="{align}">{_esc(display)}</th>'
        col_keys.append((raw, is_measure))

    rows_html = ""
    if table_data:
        # Use real data — skip total rows for cleaner display
        filtered_rows = [
            r
            for r in table_data
            if not (
                isinstance(r, dict)
                and r.get("[IsGrandTotalRowTotal]") == "True"
                and not any(r.get(k) for k in r if "[" not in k and k != "[IsGrandTotalRowTotal]")
            )
        ]
        for row_idx, row in enumerate(filtered_rows[:30]):
            cls = "tbl-alt" if row_idx % 2 == 1 else ""
            cells = ""
            for col_name, is_measure in col_keys:
                val = _find_row_value(row, col_name)
                formatted = _fmt_cell(val, is_measure)
                align = ' class="tbl-right"' if is_measure else ""
                cells += f"<td{align}>{_esc(formatted)}</td>"
            rows_html += f'<tr class="{cls}">{cells}</tr>'
    else:
        # Placeholder rows
        row_count = min(12, max(2, int((h - 60) / 22)))
        for row_idx in range(row_count):
            cls = "tbl-alt" if row_idx % 2 == 1 else ""
            cells = ""
            for _, is_measure in col_keys:
                align = ' class="tbl-right"' if is_measure else ""
                cells += f"<td{align}>---</td>"
            rows_html += f'<tr class="{cls}">{cells}</tr>'

    header_html = f'<div class="v-title">{title}</div>' if title else ""
    return (
        f"{header_html}"
        f'<div class="tbl-wrap">'
        f'<table class="tbl"><thead><tr>{hdrs}</tr></thead>'
        f"<tbody>{rows_html}</tbody></table>"
        f"</div>"
    )


def _find_row_value(row: dict, col_name: str) -> Any:
    """Find a value in a data row by trying various key formats.

    DAX result keys look like:
    - Columns: "d Assetinstrument[Performance Type]"  or  "'s Waterfall Bucket'[Bucket]"
    - Measures: "[Net_Asset_Value]"  or  "[WF1_Base]"
    - Format strings: "[v__Net_Asset_Value_FormatString]"

    We need to match against display names like "Performance Type", "Net Asset Value".
    """
    if not isinstance(row, dict):
        return None
    # Direct match
    if col_name in row:
        return row[col_name]

    # Normalize: strip all non-alpha chars for fuzzy matching
    def _normalize(s: str) -> str:
        return (
            s.lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("%", "")
            .replace("_", "")
            .replace("/", "")
            .replace("(", "")
            .replace(")", "")
            .replace(".", "")
            .replace(",", "")
        )

    target = _normalize(col_name)

    for k, v in row.items():
        # Skip format string and metadata columns
        if "FormatString" in k or k.startswith("[v__") or k == "[IsGrandTotalRowTotal]":
            continue

        # Extract the field name from DAX key format
        # "d Assetinstrument[Performance Type]" -> "Performance Type"
        # "[Net_Asset_Value]" -> "Net_Asset_Value"
        # "'s Waterfall Bucket'[Bucket]" -> "Bucket"
        field_name = k
        if "[" in k:
            field_name = k.split("[")[-1].rstrip("]")

        if _normalize(field_name) == target:
            return v

    # Fallback: partial match
    for k, v in row.items():
        if "FormatString" in k or k.startswith("[v__") or k == "[IsGrandTotalRowTotal]":
            continue
        field_name = k.split("[")[-1].rstrip("]") if "[" in k else k
        if target in _normalize(field_name) or _normalize(field_name) in target:
            return v

    return None


def _fmt_cell(val: Any, is_measure: bool = False) -> str:
    """Format a cell value for table display.

    DAX results return numbers as strings — handle both.
    """
    if val is None:
        return ""

    # Convert string numbers to float
    num = None
    if isinstance(val, (int, float)):
        num = float(val)
    elif isinstance(val, str):
        try:
            num = float(val)
        except (ValueError, TypeError):
            return val  # Return as-is if not a number

    if num is not None:
        if is_measure:
            abs_v = abs(num)
            if abs_v >= 1_000_000:
                return f"{num:,.0f}"
            elif abs_v >= 100:
                return f"{num:,.0f}"
            elif abs_v >= 1:
                return f"{num:,.1f}"
            elif abs_v > 0:
                return f"{num:.1%}"
            return "0"
        return f"{num:,.0f}" if abs(num) >= 1 else f"{num}"

    return str(val)


# ── Page navigator rendering ────────────────────────────────────────


def _render_page_navigator(title: str, w: float, h: float) -> str:
    """Render page navigator as horizontal tabs."""
    # Generate placeholder tab names
    tab_names = ["Page 1", "Page 2", "Page 3", "Page 4"]
    tabs = ""
    for i, name in enumerate(tab_names):
        active = "pn-tab-active" if i == 0 else ""
        tabs += f'<div class="pn-tab {active}">{name}</div>'
    return f'<div class="pn-tabs">{tabs}</div>'


# ── Action button rendering ─────────────────────────────────────────


def _render_action_button(title: str, w: float, h: float) -> str:
    """Render action button as small icon-like element."""
    label = _esc(title) if title else ""
    # Small buttons get icon only, larger ones get text
    if w < 60 and h < 60:
        # Icon-only: show a small gear/arrow/generic icon
        icon = _get_button_icon(label, 16)
        return f'<div class="ab-icon">{icon}</div>'
    else:
        icon = _get_button_icon(label, 14)
        return f'<div class="ab-body">' f"{icon}" f'<span class="ab-label">{label}</span>' f"</div>"


def _get_button_icon(label: str, size: int) -> str:
    """Return an SVG icon based on button label."""
    lower = label.lower()
    if "left" in lower or "back" in lower or "prev" in lower:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2">'
            f'<polyline points="15 18 9 12 15 6"/></svg>'
        )
    if "right" in lower or "next" in lower or "forward" in lower:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2">'
            f'<polyline points="9 18 15 12 9 6"/></svg>'
        )
    if "setting" in lower or "gear" in lower or "config" in lower:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2">'
            f'<circle cx="12" cy="12" r="3"/>'
            f'<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06'
            f"a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09"
            f"A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83"
            f"l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09"
            f"A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83"
            f"l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09"
            f"a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83"
            f"l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09"
            f'a1.65 1.65 0 0 0-1.51 1z"/>'
            f"</svg>"
        )
    if "info" in lower:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2">'
            f'<circle cx="12" cy="12" r="10"/>'
            f'<line x1="12" y1="16" x2="12" y2="12"/>'
            f'<line x1="12" y1="8" x2="12.01" y2="8"/>'
            f"</svg>"
        )
    # Generic button icon
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2">'
        f'<rect x="3" y="3" width="18" height="18" rx="2"/>'
        f"</svg>"
    )


# ── SVG chart generators ────────────────────────────────────────────


def _svg_bars(w: float, h: float) -> str:
    """Generate SVG bar chart placeholder with filled bars."""
    ch = max(40, h - 60)
    cw = max(60, w - 16)
    bars = ""
    vals = [0.45, 0.72, 0.58, 0.88, 0.35, 0.65, 0.78, 0.42, 0.68, 0.55, 0.82, 0.48]
    n = min(len(vals), max(3, int(cw / 35)))
    total_gap = cw * 0.15
    bar_area = cw - total_gap
    bw = bar_area / n
    gap = total_gap / (n + 1)

    colors = ["#4472C4", "#5B9BD5", "#6DAEDB"]

    for i in range(n):
        bh = vals[i] * (ch - 8)
        x = gap + i * (bw + gap)
        y = ch - bh
        color = colors[i % len(colors)]
        bars += (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
            f'fill="{color}" rx="1"/>'
        )

    # Subtle grid lines
    grid = ""
    for j in range(4):
        gy = ch * j / 4
        grid += f'<line x1="0" y1="{gy:.0f}" x2="{cw}" y2="{gy:.0f}" stroke="#E8E8E8" stroke-width="0.5"/>'

    return (
        f'<svg class="chart-svg" viewBox="0 0 {cw:.0f} {ch:.0f}" preserveAspectRatio="none">'
        f"{grid}{bars}</svg>"
    )


def _svg_waterfall(w: float, h: float) -> str:
    """Generate SVG waterfall chart placeholder."""
    ch = max(40, h - 60)
    cw = max(60, w - 16)
    bars = ""
    # Waterfall: start, increases, decreases, total
    vals = [0.6, 0.15, -0.1, 0.08, -0.12, 0.05, 0.66]
    n = min(len(vals), max(3, int(cw / 45)))
    total_gap = cw * 0.12
    bar_area = cw - total_gap
    bw = bar_area / n
    gap = total_gap / (n + 1)

    running = 0
    for i in range(n):
        val = vals[i] if i < len(vals) else 0.1
        if i == 0:
            # Start bar from bottom
            bh = abs(val) * (ch - 8)
            y = ch - bh
            running = val
            color = "#4472C4"
        elif i == n - 1:
            # Total bar from bottom
            bh = abs(running + val) * (ch - 8) * 0.5
            y = ch - bh
            color = "#4472C4"
        else:
            bh = abs(val) * (ch - 8)
            if val >= 0:
                y = ch - (running + val) * (ch - 8)
                color = "#70AD47"
                running += val
            else:
                y = ch - running * (ch - 8)
                color = "#FF6B6B"
                running += val

        x = gap + i * (bw + gap)
        bars += (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(2, bh):.1f}" '
            f'fill="{color}" rx="1"/>'
        )

    return (
        f'<svg class="chart-svg" viewBox="0 0 {cw:.0f} {ch:.0f}" preserveAspectRatio="none">'
        f"{bars}</svg>"
    )


def _svg_line(w: float, h: float) -> str:
    """Generate SVG line chart placeholder with smooth curve."""
    ch = max(40, h - 60)
    cw = max(60, w - 16)
    vals = [0.42, 0.38, 0.52, 0.48, 0.62, 0.55, 0.68, 0.72, 0.65, 0.78, 0.74, 0.82]
    n = min(len(vals), max(5, int(cw / 30)))
    points = []
    for i in range(n):
        x = 4 + i * ((cw - 8) / max(1, n - 1))
        y = ch - 4 - vals[i] * (ch - 12)
        points.append((x, y))

    # Create smooth bezier path
    path_d = f"M {points[0][0]:.1f},{points[0][1]:.1f}"
    for i in range(1, len(points)):
        px, py = points[i - 1]
        cx, cy = points[i]
        ctrl_x = (px + cx) / 2
        path_d += f" C {ctrl_x:.1f},{py:.1f} {ctrl_x:.1f},{cy:.1f} {cx:.1f},{cy:.1f}"

    # Area fill under line
    area_d = path_d + f" L {points[-1][0]:.1f},{ch} L {points[0][0]:.1f},{ch} Z"

    # Subtle grid
    grid = ""
    for j in range(4):
        gy = ch * j / 4
        grid += f'<line x1="0" y1="{gy:.0f}" x2="{cw}" y2="{gy:.0f}" stroke="#E8E8E8" stroke-width="0.5"/>'

    return (
        f'<svg class="chart-svg" viewBox="0 0 {cw:.0f} {ch:.0f}" preserveAspectRatio="none">'
        f"{grid}"
        f'<path d="{area_d}" fill="#4472C4" opacity="0.08"/>'
        f'<path d="{path_d}" fill="none" stroke="#4472C4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        # Dots at data points
        + "".join(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" fill="#4472C4"/>'
            for px, py in points[:: max(1, n // 6)]
        )
        + f"</svg>"
    )


def _svg_combo(w: float, h: float) -> str:
    """Generate SVG combo chart (columns + line) placeholder."""
    ch = max(40, h - 60)
    cw = max(60, w - 16)
    bar_vals = [0.45, 0.62, 0.55, 0.78, 0.42, 0.68, 0.58, 0.72]
    line_vals = [0.50, 0.55, 0.52, 0.65, 0.48, 0.72, 0.68, 0.78]
    n = min(len(bar_vals), max(3, int(cw / 40)))

    total_gap = cw * 0.15
    bar_area = cw - total_gap
    bw = bar_area / n
    gap = total_gap / (n + 1)

    # Grid
    grid = ""
    for j in range(4):
        gy = ch * j / 4
        grid += f'<line x1="0" y1="{gy:.0f}" x2="{cw}" y2="{gy:.0f}" stroke="#E8E8E8" stroke-width="0.5"/>'

    # Bars
    bars = ""
    for i in range(n):
        bh = bar_vals[i] * (ch - 8)
        x = gap + i * (bw + gap)
        y = ch - bh
        bars += (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
            f'fill="#4472C4" opacity="0.7" rx="1"/>'
        )

    # Line overlay
    line_points = []
    for i in range(n):
        x = gap + i * (bw + gap) + bw / 2
        y = ch - 4 - line_vals[i] * (ch - 12)
        line_points.append((x, y))

    path_d = f"M {line_points[0][0]:.1f},{line_points[0][1]:.1f}"
    for i in range(1, len(line_points)):
        px, py = line_points[i - 1]
        cx, cy = line_points[i]
        ctrl_x = (px + cx) / 2
        path_d += f" C {ctrl_x:.1f},{py:.1f} {ctrl_x:.1f},{cy:.1f} {cx:.1f},{cy:.1f}"

    dots = "".join(
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="#ED7D31"/>' for px, py in line_points
    )

    return (
        f'<svg class="chart-svg" viewBox="0 0 {cw:.0f} {ch:.0f}" preserveAspectRatio="none">'
        f"{grid}{bars}"
        f'<path d="{path_d}" fill="none" stroke="#ED7D31" stroke-width="2.5" stroke-linecap="round"/>'
        f"{dots}"
        f"</svg>"
    )


def _svg_donut(w: float, h: float, is_donut: bool = True) -> str:
    """Generate SVG donut/pie placeholder centered in visual."""
    available_h = h - 30  # reserve space for title
    size = min(w - 16, available_h - 8)
    if size < 20:
        size = 20
    r = size / 2
    cx = w / 2
    cy = available_h / 2 + 26  # offset for title

    inner_r = r * 0.55 if is_donut else 0
    colors = ["#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5"]
    segments = ""
    angles = [0, 95, 195, 280, 330, 360]
    seg_count = min(len(colors), len(angles) - 1)

    for i in range(seg_count):
        a1 = math.radians(angles[i] - 90)
        a2 = math.radians(angles[i + 1] - 90)

        if is_donut:
            # Draw arc segments for donut
            ox1, oy1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            ox2, oy2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            ix1, iy1 = cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1)
            ix2, iy2 = cx + inner_r * math.cos(a2), cy + inner_r * math.sin(a2)
            large = 1 if (angles[i + 1] - angles[i]) > 180 else 0
            d = (
                f"M {ix1:.1f} {iy1:.1f} "
                f"L {ox1:.1f} {oy1:.1f} "
                f"A {r:.0f} {r:.0f} 0 {large} 1 {ox2:.1f} {oy2:.1f} "
                f"L {ix2:.1f} {iy2:.1f} "
                f"A {inner_r:.0f} {inner_r:.0f} 0 {large} 0 {ix1:.1f} {iy1:.1f} Z"
            )
        else:
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            large = 1 if (angles[i + 1] - angles[i]) > 180 else 0
            d = (
                f"M {cx} {cy} L {x1:.1f} {y1:.1f} "
                f"A {r:.0f} {r:.0f} 0 {large} 1 {x2:.1f} {y2:.1f} Z"
            )
        segments += f'<path d="{d}" fill="{colors[i]}"/>'

    return f'<svg class="chart-svg donut" viewBox="0 0 {w:.0f} {h:.0f}">' f"{segments}</svg>"


# ── Data-driven SVG generators ──────────────────────────────────────

_CHART_COLORS = ["#4472C4", "#5B9BD5", "#A5C8E1", "#ED7D31", "#FFC000", "#70AD47", "#264478"]


def _extract_numeric_values(table_data: list, columns: list, measures: list) -> tuple:
    """Extract category labels and numeric values from table_data rows."""
    if not table_data:
        return [], {}

    # Find the category column key
    cat_name = columns[0].get("display_name", columns[0].get("column", "")) if columns else ""

    # Use raw measure names for reliable DAX key matching
    # display_name is often too short (e.g. "NAV") to match DAX result keys
    measure_keys = []
    for m in measures:
        measure_keys.append(m.get("measure", m.get("display_name", "")))

    categories = []
    series_data = {mk: [] for mk in measure_keys}

    for row in table_data:
        if not isinstance(row, dict):
            continue
        # Skip total rows
        if row.get("[IsGrandTotalRowTotal]") == "True":
            continue
        # Find category value
        cat_val = _find_row_value(row, cat_name) if cat_name else ""
        categories.append(str(cat_val) if cat_val is not None else "")

        # Find measure values (DAX returns numbers as strings)
        for mn in measure_keys:
            val = _find_row_value(row, mn)
            try:
                series_data[mn].append(float(val) if val is not None else 0)
            except (ValueError, TypeError):
                series_data[mn].append(0)

    return categories, series_data


def _svg_bars_from_data(w: float, h: float, table_data: list, columns: list, measures: list) -> str:
    """Generate bar chart SVG from actual data with value labels."""
    categories, series_data = _extract_numeric_values(table_data, columns, measures)
    if not categories:
        return _svg_bars(w, h)

    ch = max(60, h - 50)
    cw = max(80, w - 20)
    measure_names = list(series_data.keys())
    n_series = len(measure_names)
    n_cats = len(categories)

    # Find global min/max across all series
    all_vals = []
    for vals in series_data.values():
        all_vals.extend(vals)
    min_val = min(all_vals) if all_vals else 0
    max_val = max(all_vals) if all_vals else 1
    if min_val > 0:
        min_val = 0  # Always include zero
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1

    # Chart area with margins for labels
    margin_top = 15
    margin_bottom = 18
    plot_h = ch - margin_top - margin_bottom
    zero_y = margin_top + (max_val / val_range) * plot_h  # Y position of zero line

    # Grid lines
    grid = ""
    for i in range(5):
        gy = margin_top + i * plot_h / 4
        grid += f'<line x1="0" y1="{gy:.0f}" x2="{cw}" y2="{gy:.0f}" stroke="#e8e8e8" stroke-width="0.5"/>'

    # Bars with value labels
    group_width = cw / n_cats
    bar_width = group_width * 0.65 / max(1, n_series)
    group_pad = group_width * 0.175

    bars = ""
    data_labels = ""
    cat_labels = ""
    for ci, cat in enumerate(categories):
        group_x = ci * group_width
        for si, mn in enumerate(measure_names):
            val = series_data[mn][ci] if ci < len(series_data[mn]) else 0
            bar_h = abs(val) / val_range * plot_h
            bar_x = group_x + group_pad + si * bar_width

            if val >= 0:
                bar_y = zero_y - bar_h
            else:
                bar_y = zero_y

            color = _CHART_COLORS[si % len(_CHART_COLORS)]
            bars += (
                f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_width:.1f}" '
                f'height="{max(1, bar_h):.1f}" fill="{color}" rx="1"/>'
            )

            # Value label above/below bar
            label_val = _format_chart_label(val)
            label_y = bar_y - 2 if val >= 0 else bar_y + bar_h + 8
            label_x = bar_x + bar_width / 2
            data_labels += (
                f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="middle" '
                f'font-size="7" fill="#444" font-weight="500">{label_val}</text>'
            )

        # Category label
        lx = group_x + group_width / 2
        label = _esc(str(cat)[:10])
        cat_labels += (
            f'<text x="{lx:.0f}" y="{ch - 2}" text-anchor="middle" '
            f'font-size="7" fill="#666">{label}</text>'
        )

    return (
        f'<svg class="chart-svg" viewBox="0 0 {cw:.0f} {ch:.0f}" preserveAspectRatio="none">'
        f"{grid}{bars}{data_labels}{cat_labels}</svg>"
    )


def _svg_waterfall_from_data(
    w: float, h: float, table_data: list, columns: list, measures: list
) -> str:
    """Generate waterfall chart SVG from DAX data with WF1-WF5 stacked components.

    The waterfall data has columns:
    - Category column (e.g. 's Waterfall Bucket[Bucket]')
    - [WF1_Base]: Solid bars from 0 (start/end totals)
    - [WF5_Return_Base]: Solid bars from 0 (return base total)
    - [WF2_Blank]: Invisible base (where floating bar starts)
    - [WF3_Negative]: Red decrease portion (stacks on WF2_Blank)
    - [WF4_Positive]: Green increase portion (stacks on WF2_Blank)
    """
    if not table_data:
        return _svg_waterfall(w, h)

    ch = max(60, h - 50)
    cw = max(80, w - 20)

    # Find the category column name
    cat_name = ""
    if columns:
        cat_name = columns[0].get("display_name", columns[0].get("column", ""))

    # Extract waterfall data from rows
    wf_rows = []
    for row in table_data:
        if not isinstance(row, dict):
            continue
        cat_val = _find_row_value(row, cat_name) if cat_name else ""
        if cat_val is None:
            # Try first column key that looks like a category
            for k, v in row.items():
                if "[" in k and "WF" not in k and "FormatString" not in k:
                    cat_val = v
                    break
        cat_str = str(cat_val) if cat_val is not None else ""

        # Extract WF values - try by key substring
        def _get_wf(row_dict, wf_key):
            """Find WF column value by partial key match."""
            for k, v in row_dict.items():
                if wf_key in k:
                    try:
                        return float(v) if v is not None else 0
                    except (ValueError, TypeError):
                        return 0
            return 0

        wf1 = _get_wf(row, "WF1_Base")
        wf2 = _get_wf(row, "WF2_Blank")
        wf3 = _get_wf(row, "WF3_Negative")
        wf4 = _get_wf(row, "WF4_Positive")
        wf5 = _get_wf(row, "WF5_Return_Base")

        wf_rows.append(
            {
                "cat": cat_str,
                "base": wf1,
                "return_base": wf5,
                "blank": wf2,
                "negative": wf3,
                "positive": wf4,
            }
        )

    if not wf_rows:
        return _svg_waterfall(w, h)

    n = len(wf_rows)

    # Determine the display order: NAV Start, Net Contribution, Return Base,
    # NAV Performance, Realised Performance, NAV End
    # The data may come alphabetically sorted, so re-sort if we recognize the buckets
    _BUCKET_ORDER = {
        "NAV Start": 0,
        "Net Contribution": 1,
        "Return Base": 2,
        "NAV Performance": 3,
        "Realised Performance": 4,
        "NAV End": 5,
    }
    known = all(r["cat"] in _BUCKET_ORDER for r in wf_rows)
    if known:
        wf_rows.sort(key=lambda r: _BUCKET_ORDER.get(r["cat"], 99))

    # Find the global max value for scaling
    max_val = 0
    for r in wf_rows:
        vals_to_check = [
            r["base"],
            r["return_base"],
            r["blank"] + r["negative"],
            r["blank"] + r["positive"],
        ]
        max_val = max(max_val, max(abs(v) for v in vals_to_check))
    if max_val == 0:
        max_val = 1

    # Chart layout
    margin_top = 12
    margin_bottom = 18
    plot_h = ch - margin_top - margin_bottom
    bar_area_width = cw
    group_width = bar_area_width / n
    bar_width = group_width * 0.6
    bar_pad = (group_width - bar_width) / 2

    def val_to_y(val):
        """Convert a value to Y coordinate (0 at bottom)."""
        return margin_top + plot_h - (val / max_val * plot_h)

    # Grid lines
    grid = ""
    for i in range(5):
        gy = margin_top + i * plot_h / 4
        grid += (
            f'<line x1="0" y1="{gy:.0f}" x2="{cw}" y2="{gy:.0f}" '
            f'stroke="#e8e8e8" stroke-width="0.5"/>'
        )

    bars = ""
    data_labels = ""
    cat_labels = ""
    connectors = ""

    for i, r in enumerate(wf_rows):
        bx = i * group_width + bar_pad

        if r["base"] > 0:
            # Solid bar from 0 (e.g. NAV Start, NAV End)
            bar_top = val_to_y(r["base"])
            bar_bot = val_to_y(0)
            bar_h = bar_bot - bar_top
            color = "#4472C4"
            bars += (
                f'<rect x="{bx:.1f}" y="{bar_top:.1f}" width="{bar_width:.1f}" '
                f'height="{max(1, bar_h):.1f}" fill="{color}" rx="1"/>'
            )
            # Value label
            label_val = _format_chart_label(r["base"])
            data_labels += (
                f'<text x="{bx + bar_width / 2:.1f}" y="{bar_top - 3:.1f}" '
                f'text-anchor="middle" font-size="7" fill="#444" font-weight="600">'
                f"{label_val}</text>"
            )

        elif r["return_base"] > 0:
            # Return Base - solid bar from 0
            bar_top = val_to_y(r["return_base"])
            bar_bot = val_to_y(0)
            bar_h = bar_bot - bar_top
            color = "#4472C4"
            bars += (
                f'<rect x="{bx:.1f}" y="{bar_top:.1f}" width="{bar_width:.1f}" '
                f'height="{max(1, bar_h):.1f}" fill="{color}" rx="1"/>'
            )
            label_val = _format_chart_label(r["return_base"])
            data_labels += (
                f'<text x="{bx + bar_width / 2:.1f}" y="{bar_top - 3:.1f}" '
                f'text-anchor="middle" font-size="7" fill="#444" font-weight="600">'
                f"{label_val}</text>"
            )

        elif r["negative"] > 0:
            # Floating negative bar: blank is the base, negative stacks down from top of blank
            blank_top = val_to_y(r["blank"] + r["negative"])
            neg_top = val_to_y(r["blank"] + r["negative"])
            neg_bot = val_to_y(r["blank"])
            neg_h = neg_bot - neg_top
            color = "#C00000"
            bars += (
                f'<rect x="{bx:.1f}" y="{neg_top:.1f}" width="{bar_width:.1f}" '
                f'height="{max(1, neg_h):.1f}" fill="{color}" rx="1"/>'
            )
            # Label showing the negative delta
            label_val = _format_chart_label(-r["negative"])
            data_labels += (
                f'<text x="{bx + bar_width / 2:.1f}" y="{neg_top - 3:.1f}" '
                f'text-anchor="middle" font-size="7" fill="#C00000" font-weight="600">'
                f"{label_val}</text>"
            )

        elif r["positive"] > 0:
            # Floating positive bar: blank is the base, positive stacks up from top of blank
            pos_bot = val_to_y(r["blank"])
            pos_top = val_to_y(r["blank"] + r["positive"])
            pos_h = pos_bot - pos_top
            color = "#177310"
            bars += (
                f'<rect x="{bx:.1f}" y="{pos_top:.1f}" width="{bar_width:.1f}" '
                f'height="{max(1, pos_h):.1f}" fill="{color}" rx="1"/>'
            )
            label_val = _format_chart_label(r["positive"])
            data_labels += (
                f'<text x="{bx + bar_width / 2:.1f}" y="{pos_top - 3:.1f}" '
                f'text-anchor="middle" font-size="7" fill="#177310" font-weight="600">'
                f"{label_val}</text>"
            )

        # Category label
        lx = i * group_width + group_width / 2
        cat_short = r["cat"]
        if len(cat_short) > 12:
            cat_short = cat_short[:11] + "."
        cat_labels += (
            f'<text x="{lx:.0f}" y="{ch - 2}" text-anchor="middle" '
            f'font-size="6.5" fill="#666">{_esc(cat_short)}</text>'
        )

    return (
        f'<svg class="chart-svg" viewBox="0 0 {cw:.0f} {ch:.0f}" preserveAspectRatio="none">'
        f"{grid}{bars}{connectors}{data_labels}{cat_labels}</svg>"
    )


def _svg_combo_from_data(
    w: float, h: float, table_data: list, columns: list, measures: list
) -> str:
    """Generate combo chart (bars + line) from actual data with dual-axis scaling.

    First measure(s) render as bars, last measure renders as a line overlay.
    Each axis is scaled independently. Data labels appear on line points.
    X-axis shows category labels (typically month abbreviations).
    """
    categories, series_data = _extract_numeric_values(table_data, columns, measures)
    if not categories:
        return _svg_combo(w, h)

    ch = max(60, h - 50)
    cw = max(80, w - 20)
    measure_names = list(series_data.keys())
    n_cats = len(categories)

    # Split into bar measures and line measures
    bar_measures = measure_names[:-1] if len(measure_names) > 1 else measure_names
    line_measures = [measure_names[-1]] if len(measure_names) > 1 else []

    # Separate scales for bars and line
    bar_vals = []
    for mn in bar_measures:
        bar_vals.extend(series_data[mn])
    bar_min = min(bar_vals) if bar_vals else 0
    bar_max = max(bar_vals) if bar_vals else 1
    if bar_min > 0:
        bar_min = 0
    bar_range = bar_max - bar_min
    if bar_range == 0:
        bar_range = 1

    line_vals_all = []
    for mn in line_measures:
        line_vals_all.extend(series_data[mn])
    line_min = min(line_vals_all) if line_vals_all else 0
    line_max = max(line_vals_all) if line_vals_all else 1
    # Add 15% padding to line scale for label room
    line_pad = (line_max - line_min) * 0.15 if line_max != line_min else 0.1
    line_min -= line_pad
    line_max += line_pad
    line_range = line_max - line_min
    if line_range == 0:
        line_range = 1

    # Chart area
    margin_top = 14
    margin_bottom = 18
    plot_h = ch - margin_top - margin_bottom
    group_width = cw / n_cats

    # Zero line position for bars
    bar_zero_y = margin_top + (bar_max / bar_range) * plot_h

    # Grid lines
    grid = ""
    for i in range(5):
        gy = margin_top + i * plot_h / 4
        grid += (
            f'<line x1="0" y1="{gy:.0f}" x2="{cw}" y2="{gy:.0f}" '
            f'stroke="#e8e8e8" stroke-width="0.5"/>'
        )

    # Bars
    bars_svg = ""
    n_bar_series = max(1, len(bar_measures))
    bar_width = group_width * 0.6 / n_bar_series
    bar_pad_x = group_width * 0.2

    for ci in range(n_cats):
        group_x = ci * group_width
        for si, mn in enumerate(bar_measures):
            val = series_data[mn][ci] if ci < len(series_data[mn]) else 0
            bar_h = abs(val) / bar_range * plot_h

            if val >= 0:
                bar_y = bar_zero_y - bar_h
            else:
                bar_y = bar_zero_y

            bx = group_x + bar_pad_x + si * bar_width
            color = "#4472C4"
            bars_svg += (
                f'<rect x="{bx:.1f}" y="{bar_y:.1f}" width="{bar_width:.1f}" '
                f'height="{max(1, bar_h):.1f}" fill="{color}" opacity="0.85" rx="1"/>'
            )

    # Category labels (x-axis)
    cat_labels = ""
    for ci, cat in enumerate(categories):
        lx = ci * group_width + group_width / 2
        # Format month labels: keep short
        cat_str = str(cat)
        if len(cat_str) > 8:
            cat_str = cat_str[:7]
        cat_labels += (
            f'<text x="{lx:.0f}" y="{ch - 2}" text-anchor="middle" '
            f'font-size="6.5" fill="#666">{_esc(cat_str)}</text>'
        )

    # Line overlay with data labels
    lines_svg = ""
    for mn in line_measures:
        vals = series_data[mn]
        points = []
        for ci in range(n_cats):
            x = ci * group_width + group_width / 2
            val = vals[ci] if ci < len(vals) else 0
            y = margin_top + ((line_max - val) / line_range) * plot_h
            points.append((x, y, val))

        if len(points) > 1:
            # Smooth bezier path
            path_d = f"M {points[0][0]:.1f},{points[0][1]:.1f}"
            for i in range(1, len(points)):
                px, py, _ = points[i - 1]
                cx_p, cy_p, _ = points[i]
                ctrl_x = (px + cx_p) / 2
                path_d += (
                    f" C {ctrl_x:.1f},{py:.1f} {ctrl_x:.1f},{cy_p:.1f} " f"{cx_p:.1f},{cy_p:.1f}"
                )
            lines_svg += (
                f'<path d="{path_d}" fill="none" stroke="#ED7D31" '
                f'stroke-width="2" stroke-linecap="round"/>'
            )

            # Dots and data labels on each point
            for px, py, val in points:
                lines_svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="#ED7D31"/>'
                # Format label: show as percentage if values look like percentages
                if abs(val) < 1:
                    lbl = f"{val:.1%}"
                else:
                    lbl = _format_chart_label(val)
                # Position label above the dot
                ly = py - 6
                lines_svg += (
                    f'<text x="{px:.1f}" y="{ly:.1f}" text-anchor="middle" '
                    f'font-size="7" fill="#ED7D31" font-weight="600">{lbl}</text>'
                )

    return (
        f'<svg class="chart-svg" viewBox="0 0 {cw:.0f} {ch:.0f}" preserveAspectRatio="none">'
        f"{grid}{bars_svg}{lines_svg}{cat_labels}</svg>"
    )


def _svg_donut_from_data(
    w: float,
    h: float,
    table_data: list,
    columns: list,
    measures: list,
    is_donut: bool = True,
) -> str:
    """Generate donut/pie chart from actual data with outside labels and leader lines.

    Labels are positioned outside the donut with lines pointing to each segment.
    Each label shows: Category Name XX.XX%
    """
    categories, series_data = _extract_numeric_values(table_data, columns, measures)
    if not categories or not series_data:
        return _svg_donut(w, h, is_donut)

    # Use first measure's values
    first_measure = list(series_data.keys())[0]
    values = series_data[first_measure]

    total = sum(abs(v) for v in values)
    if total == 0:
        return _svg_donut(w, h, is_donut)

    # Layout: donut centered, labels extend outside with leader lines
    # Reserve space for labels on both sides
    available_h = h - 10
    label_margin = min(w * 0.28, 80)  # Space for labels on each side
    donut_area_w = w - label_margin * 2
    size = min(donut_area_w, available_h - 10)
    if size < 30:
        size = 30
    r = size / 2
    cx = w / 2
    cy = available_h / 2 + 5
    inner_r = r * 0.55 if is_donut else 0

    colors = [
        "#4472C4",
        "#ED7D31",
        "#A5A5A5",
        "#FFC000",
        "#5B9BD5",
        "#70AD47",
        "#264478",
        "#9B59B6",
    ]
    segments = ""
    labels_html = ""

    angle = -90  # Start from top
    label_r = r + 8  # Radius for leader line start (just outside donut)
    text_r = r + 14  # Radius for the elbow point

    for i, (cat, val) in enumerate(zip(categories, values)):
        if val == 0:
            continue
        pct = abs(val) / total
        sweep = pct * 360
        a1 = math.radians(angle)
        a2 = math.radians(angle + sweep)
        mid_angle = math.radians(angle + sweep / 2)
        color = colors[i % len(colors)]

        x1_o = cx + r * math.cos(a1)
        y1_o = cy + r * math.sin(a1)
        x2_o = cx + r * math.cos(a2)
        y2_o = cy + r * math.sin(a2)
        large = 1 if sweep > 180 else 0

        if is_donut:
            x1_i = cx + inner_r * math.cos(a1)
            y1_i = cy + inner_r * math.sin(a1)
            x2_i = cx + inner_r * math.cos(a2)
            y2_i = cy + inner_r * math.sin(a2)
            d = (
                f"M {x1_o:.1f} {y1_o:.1f} "
                f"A {r:.0f} {r:.0f} 0 {large} 1 {x2_o:.1f} {y2_o:.1f} "
                f"L {x2_i:.1f} {y2_i:.1f} "
                f"A {inner_r:.0f} {inner_r:.0f} 0 {large} 0 {x1_i:.1f} {y1_i:.1f} Z"
            )
        else:
            d = (
                f"M {cx} {cy} L {x1_o:.1f} {y1_o:.1f} "
                f"A {r:.0f} {r:.0f} 0 {large} 1 {x2_o:.1f} {y2_o:.1f} Z"
            )
        segments += f'<path d="{d}" fill="{color}" stroke="#fff" stroke-width="1"/>'

        # Leader line from segment midpoint to outside label
        line_start_x = cx + label_r * math.cos(mid_angle)
        line_start_y = cy + label_r * math.sin(mid_angle)
        elbow_x = cx + text_r * math.cos(mid_angle)
        elbow_y = cy + text_r * math.sin(mid_angle)

        # Determine if label goes left or right
        is_right = math.cos(mid_angle) >= 0
        text_end_x = elbow_x + (12 if is_right else -12)
        text_anchor = "start" if is_right else "end"
        text_x = text_end_x + (3 if is_right else -3)

        # Leader line
        labels_html += (
            f'<line x1="{line_start_x:.1f}" y1="{line_start_y:.1f}" '
            f'x2="{elbow_x:.1f}" y2="{elbow_y:.1f}" '
            f'stroke="{color}" stroke-width="0.8"/>'
            f'<line x1="{elbow_x:.1f}" y1="{elbow_y:.1f}" '
            f'x2="{text_end_x:.1f}" y2="{elbow_y:.1f}" '
            f'stroke="{color}" stroke-width="0.8"/>'
        )

        # Label text: "CAT XX.XX%"
        pct_str = f"{pct:.2%}"
        cat_str = _esc(str(cat)[:12])
        labels_html += (
            f'<text x="{text_x:.1f}" y="{elbow_y + 3:.1f}" '
            f'text-anchor="{text_anchor}" font-size="7.5" fill="#444" '
            f'font-weight="500">{cat_str} {pct_str}</text>'
        )

        angle += sweep

    return (
        f'<svg class="chart-svg donut" viewBox="0 0 {w:.0f} {h:.0f}">'
        f"{segments}{labels_html}</svg>"
    )


# ── JS data rendering ───────────────────────────────────────────────


def _render_visual_data_js(visuals: List[Dict[str, Any]]) -> str:
    """Render visual metadata as JS for runtime."""
    import json

    safe = []
    for v in visuals:
        safe.append(
            {
                "id": v.get("id", ""),
                "visual_type": v.get("visual_type", ""),
                "title": v.get("title", ""),
                "visual_name": v.get("visual_name", ""),
                "is_data_visual": v.get("is_data_visual", False),
                "is_visual_group": v.get("is_visual_group", False),
                "is_hidden": v.get("is_hidden", False),
                "position": v.get("position", {}),
                "fields": v.get("fields", {}),
                "parent_group": v.get("parent_group", ""),
            }
        )
    return f"const V={json.dumps(safe)};"


def _esc(text: str) -> str:
    """Escape HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ── CSS ──────────────────────────────────────────────────────────────

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI','Segoe UI Web',Arial,sans-serif;background:#1a1b26;color:#c0caf5;-webkit-font-smoothing:antialiased}

/* Toolbar */
.toolbar{display:flex;justify-content:space-between;align-items:center;padding:5px 12px;background:#24283b;border-bottom:2px solid #3b4261;position:sticky;top:0;z-index:10001}
.toolbar h2{font-size:13px}
.toolbar-actions{display:flex;gap:8px;align-items:center}
.info{font-size:9px;color:#565f89}
.toggle{font-size:9px;color:#9aa5ce;cursor:pointer;display:flex;align-items:center;gap:2px}
.toggle input{cursor:pointer;width:12px;height:12px}
.btn{padding:3px 10px;border:none;border-radius:3px;cursor:pointer;font-size:9px;font-weight:600}
.pri{background:#7aa2f7;color:#1a1b26}.sec{background:#3b4261;color:#c0caf5}.sm{padding:2px 6px;font-size:8px}
.btn:hover{opacity:0.85}

/* Canvas */
.canvas-wrap{display:flex;justify-content:center;padding:16px;overflow:auto;min-height:calc(100vh - 36px)}
.canvas{position:relative;background:#E6E6E6;border:none;box-shadow:0 4px 24px rgba(0,0,0,0.4);flex-shrink:0}

/* ── Base visual ── */
.v{position:absolute;overflow:hidden;cursor:move;transition:box-shadow 0.15s ease}
.v:hover{box-shadow:0 0 0 2px #7aa2f7 !important;z-index:9990!important}
.v.selected{box-shadow:0 0 0 2px #f7768e !important;z-index:9991!important}

/* ── Title and field labels ── */
.v-title{padding:4px 8px 2px;font-size:10px;font-weight:600;color:#333;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-0.01em}
.v-fields{padding:2px 8px;font-size:8px;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.v-lbl{position:absolute;top:0;left:0;font-size:7px;color:rgba(0,0,0,0.2);padding:1px 4px;pointer-events:auto}
.chart-legend{padding:2px 8px;font-size:8px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center}

/* ── Groups — fully invisible ── */
.v-group{background:transparent !important;border:none !important;pointer-events:none;box-shadow:none !important}
.v-group .rh{pointer-events:auto}
.v-group .v-lbl{display:none}

/* ── Shapes — background fills ── */
.v-shape{border:none;border-radius:0}

/* ── Cards / KPI ── */
.v-card{background:#fff;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08);display:flex;flex-direction:column;justify-content:center;overflow:hidden}
.card-content{padding:10px 16px;display:flex;flex-direction:column;justify-content:center;height:100%}
.card-label{font-size:11px;color:#666;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.03em}
.card-value{font-size:28px;font-weight:700;color:#333;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-0.02em;line-height:1.1}
.card-multi-row{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
.card-multi-item{flex:1;min-width:80px}
.card-multi-val{font-size:18px;font-weight:700;color:#333;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-0.02em}
.card-multi-label{font-size:9px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;text-transform:uppercase;letter-spacing:0.02em}

/* ── Multi-row cards ── */
.v-mrc{background:#fff;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08);padding:0;overflow:auto}
.v-mrc .v-title{border-bottom:1px solid #f0f0f0}
.mrc-grid{padding:6px 10px;display:flex;flex-wrap:wrap;gap:8px}
.mrc-item{flex:1;min-width:70px;padding:4px 0;border-bottom:1px solid #f5f5f5}
.mrc-val{font-size:14px;font-weight:700;color:#333;display:block}
.mrc-label{font-size:8px;color:#888;display:block;margin-top:1px;text-transform:uppercase;letter-spacing:0.02em}

/* ── Charts ── */
.v-chart{background:#fff;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08);display:flex;flex-direction:column;overflow:hidden}
.v-chart-donut{align-items:center}
.chart-body{flex:1;display:flex;align-items:flex-end;padding:2px 8px 4px;min-height:0;overflow:hidden}
.donut-body{align-items:center;justify-content:center;padding:0}
.chart-svg{width:100%;height:100%;display:block}
.chart-svg.donut{width:auto;height:100%}

/* ── Tables / Matrices ── */
.v-table{background:#fff;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08);overflow:hidden;display:flex;flex-direction:column}
.v-table .v-title{flex-shrink:0}
.tbl-wrap{flex:1;overflow:auto}
.tbl{width:100%;border-collapse:collapse;font-size:10px}
.tbl th{background:#2C3E6B;color:#fff;padding:5px 8px;text-align:left;font-weight:600;font-size:9px;white-space:nowrap;border-bottom:none;position:sticky;top:0}
.tbl th.tbl-right{text-align:right}
.tbl td{padding:4px 8px;border-bottom:1px solid #eee;color:#555;white-space:nowrap}
.tbl td.tbl-right{text-align:right}
.tbl tr.tbl-alt{background:#F8F9FB}
.tbl tr:hover{background:#EDF0F7}

/* ── Slicers ── */
.v-slicer{background:#fff;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08);display:flex;align-items:center;overflow:hidden}
.slicer-body{display:flex;align-items:center;justify-content:space-between;width:100%;padding:4px 10px;gap:6px}
.slicer-label{font-size:11px;color:#333;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.slicer-arrow{font-size:10px;color:#888;flex-shrink:0}

/* ── Textbox ── */
.v-textbox{background:transparent;border:none;padding:4px 8px;display:flex;align-items:center}
.tb-text{font-size:12px;color:#fff;font-weight:600;text-shadow:0 1px 2px rgba(0,0,0,0.3)}

/* ── Page navigator (tabs) ── */
.v-pagenav{background:transparent;border:none;display:flex;align-items:flex-end;padding:0}
.pn-tabs{display:flex;height:100%;align-items:flex-end;gap:1px;padding:0 4px}
.pn-tab{background:#fff;border-radius:4px 4px 0 0;padding:5px 14px;font-size:10px;color:#555;font-weight:500;white-space:nowrap;box-shadow:0 -1px 2px rgba(0,0,0,0.04);border:1px solid #ddd;border-bottom:none}
.pn-tab-active{background:#4472C4;color:#fff;font-weight:600;border-color:#4472C4}

/* ── Action buttons ── */
.v-action-btn{background:rgba(255,255,255,0.9);border:1px solid #ddd;border-radius:4px;display:flex;align-items:center;justify-content:center;color:#555;overflow:hidden}
.ab-icon{display:flex;align-items:center;justify-content:center;width:100%;height:100%}
.ab-body{display:flex;align-items:center;justify-content:center;gap:4px;padding:4px 8px;width:100%;height:100%}
.ab-label{font-size:9px;color:#555;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── Image ── */
.v-img{background:#F5F5F5;border:1px solid #E0E0E0;border-radius:4px;display:flex;align-items:center;justify-content:center}
.img-icon{width:32px;height:32px}

/* ── Default fallback ── */
.v-default{background:#fff;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08);overflow:hidden}

/* ── Hidden visuals ── */
.v-hidden{opacity:0.25;outline:1px dashed #f7768e}

/* ── Resize handle ── */
.rh{position:absolute;bottom:0;right:0;width:8px;height:8px;cursor:se-resize;background:linear-gradient(135deg,transparent 50%,rgba(0,0,0,0.1) 50%)}

/* ── Properties panel ── */
.props{position:fixed;right:0;top:34px;width:260px;height:calc(100vh - 34px);background:#24283b;border-left:2px solid #3b4261;padding:10px;overflow-y:auto;z-index:10000}
.props h3{font-size:12px;margin-bottom:6px;color:#c0caf5}
.props.hide{display:none}
.pr{margin:3px 0;display:flex;justify-content:space-between;align-items:center}
.pl{font-size:9px;color:#9aa5ce}.pv{font-size:9px;color:#c0caf5;max-width:150px;overflow:hidden;text-overflow:ellipsis}
.pi{width:55px;padding:3px;background:#3b4261;border:1px solid #545c7e;color:#c0caf5;font-size:9px;border-radius:3px}
.ft{font-size:8px;padding:2px 5px;border-radius:3px;margin:1px 0;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ft.m{background:#dbeafe;color:#1e40af}.ft.c{background:#dcfce7;color:#166534}

/* ── Modal ── */
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:20000;display:flex;justify-content:center;align-items:center}
.modal.hide{display:none}
.modal-box{background:#24283b;border-radius:8px;padding:14px;width:600px;max-height:80vh;overflow:auto}
.modal-box h3{margin-bottom:6px;font-size:12px}
.modal-box textarea{width:100%;background:#1a1b26;color:#9ece6a;border:1px solid #3b4261;font-family:'Cascadia Code',monospace;font-size:9px;padding:6px;border-radius:4px;resize:vertical}
.modal-foot{display:flex;gap:6px;margin-top:6px;justify-content:flex-end}
"""

_JS = """
let selId=null,dS=null,rS=null;
function toggleHidden(){const s=document.getElementById('tog-hidden').checked;document.querySelectorAll('.v-hidden').forEach(e=>{e.style.display=s?'block':'none'})}
function toggleGroups(){const s=document.getElementById('tog-groups').checked;document.querySelectorAll('.v-group').forEach(e=>{e.style.display=s?'block':'none'})}
function toggleLabels(){const s=document.getElementById('tog-labels').checked;document.querySelectorAll('.v-title,.v-fields,.v-lbl,.chart-legend').forEach(e=>{e.style.display=s?'':'none'})}
document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('.v-group').forEach(e=>{e.style.display='none'})});
function sel(e,id){e.stopPropagation();document.querySelectorAll('.v.selected').forEach(el=>el.classList.remove('selected'));const el=document.getElementById('v-'+id);if(el)el.classList.add('selected');selId=id;showP(id)}
function showP(id){const p=document.getElementById('props'),c=document.getElementById('props-body'),d=V.find(v=>v.id===id);if(!d)return;const el=document.getElementById('v-'+id);const pos={x:Math.round(parseFloat(el.style.left)),y:Math.round(parseFloat(el.style.top)),w:Math.round(parseFloat(el.style.width)),h:Math.round(parseFloat(el.style.height))};
let h=`<div class="pr"><span class="pl">ID</span><span class="pv">${id}</span></div><div class="pr"><span class="pl">Type</span><span class="pv">${d.visual_type}</span></div><div class="pr"><span class="pl">Title</span><span class="pv">${d.title||'-'}</span></div><div class="pr"><span class="pl">Hidden</span><span class="pv">${d.is_hidden?'Yes':'No'}</span></div><div class="pr"><span class="pl">Parent</span><span class="pv">${d.parent_group||'none'}</span></div><hr style="border-color:#3b4261;margin:4px 0"><div class="pr"><span class="pl">X</span><input class="pi" type="number" value="${pos.x}" onchange="uP('${id}','left',this.value)"></div><div class="pr"><span class="pl">Y</span><input class="pi" type="number" value="${pos.y}" onchange="uP('${id}','top',this.value)"></div><div class="pr"><span class="pl">Width</span><input class="pi" type="number" value="${pos.w}" onchange="uP('${id}','width',this.value)"></div><div class="pr"><span class="pl">Height</span><input class="pi" type="number" value="${pos.h}" onchange="uP('${id}','height',this.value)"></div>`;
const ms=d.fields.measures||[],cs=d.fields.columns||[];if(ms.length||cs.length){h+='<hr style="border-color:#3b4261;margin:4px 0"><div class="pl" style="margin-bottom:2px">Bindings</div>';ms.forEach(m=>{h+=`<div class="ft m">${m.table}.${m.measure}</div>`});cs.forEach(c=>{h+=`<div class="ft c">${c.table}.${c.column}</div>`})}
c.innerHTML=h;p.classList.remove('hide')}
function closeProps(){document.getElementById('props').classList.add('hide');selId=null;document.querySelectorAll('.v.selected').forEach(el=>el.classList.remove('selected'))}
function uP(id,p,v){const el=document.getElementById('v-'+id);if(el)el.style[p]=v+'px'}
function dragS(e,id){if(e.target.classList.contains('rh'))return;e.preventDefault();const el=document.getElementById('v-'+id);dS={id,el,sx:e.clientX,sy:e.clientY,ox:parseFloat(el.style.left),oy:parseFloat(el.style.top)};document.addEventListener('mousemove',dragM);document.addEventListener('mouseup',dragE)}
function dragM(e){if(!dS)return;dS.el.style.left=Math.max(0,dS.ox+(e.clientX-dS.sx))+'px';dS.el.style.top=Math.max(0,dS.oy+(e.clientY-dS.sy))+'px'}
function dragE(){dS=null;document.removeEventListener('mousemove',dragM);document.removeEventListener('mouseup',dragE);if(selId)showP(selId)}
function resS(e,id){e.preventDefault();e.stopPropagation();const el=document.getElementById('v-'+id);rS={id,el,sx:e.clientX,sy:e.clientY,ow:parseFloat(el.style.width),oh:parseFloat(el.style.height)};document.addEventListener('mousemove',resM);document.addEventListener('mouseup',resE)}
function resM(e){if(!rS)return;rS.el.style.width=Math.max(20,rS.ow+(e.clientX-rS.sx))+'px';rS.el.style.height=Math.max(15,rS.oh+(e.clientY-rS.sy))+'px'}
function resE(){rS=null;document.removeEventListener('mousemove',resM);document.removeEventListener('mouseup',resE);if(selId)showP(selId)}
function exportState(){const s=bldSt();document.getElementById('export-ta').value=JSON.stringify(s,null,2);document.getElementById('modal').classList.remove('hide')}
function copyState(){navigator.clipboard.writeText(JSON.stringify(bldSt(),null,2)).then(()=>{})}
function bldSt(){const vs=[];document.querySelectorAll('.v:not(.v-hidden)').forEach(el=>{if(el.style.display==='none')return;const id=el.dataset.vid,d=V.find(v=>v.id===id)||{};vs.push({id,visual_type:el.dataset.vtype,position:{x:Math.round(parseFloat(el.style.left)),y:Math.round(parseFloat(el.style.top)),width:Math.round(parseFloat(el.style.width)),height:Math.round(parseFloat(el.style.height))},title:d.title||'',fields:d.fields||{},parent_group:d.parent_group||''})});return{page_name:document.querySelector('.toolbar h2').textContent,visuals:vs}}
document.getElementById('canvas').addEventListener('click',function(e){if(e.target===this)closeProps()});
"""
