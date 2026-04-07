"""
Tool Input Schemas for Bridged Tools
Defines proper input schemas with required parameters.
"""

TOOL_SCHEMAS = {
    # DAX Intelligence (1 unified tool)
    'dax_intelligence': {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "DAX expression OR measure name (auto-detects). Not required for dependency operations."},
            "analysis_mode": {"type": "string", "enum": ["all", "analyze", "debug", "report"], "default": "all"},
            "skip_validation": {"type": "boolean", "default": False},
            "output_format": {"type": "string", "enum": ["friendly", "steps"], "default": "friendly"},
            "include_optimization": {"type": "boolean", "default": True},
            "include_profiling": {"type": "boolean", "default": True},
            "breakpoints": {"type": "array", "description": "Char positions for debugging", "items": {"type": "integer"}},
            "operation": {"type": "string", "enum": ["dependencies", "impact", "export"], "description": "Dependency operation. When set, analysis_mode is ignored."},
            "table": {"type": "string", "description": "Table name (for dependencies/impact)"},
            "measure": {"type": "string", "description": "Measure name (for dependencies/impact)"},
            "include_diagram": {"type": "boolean", "description": "Include Mermaid diagram (for dependencies)", "default": True},
            "output_path": {"type": "string", "description": "CSV output path (for export)"}
        },
        "required": []
    },

    # PBIP Dependency Analysis (1 tool)
    'pbip_dependency_analysis': {
        "type": "object",
        "properties": {
            "pbip_folder_path": {"type": "string", "description": "Path to .SemanticModel or PBIP folder"},
            "auto_open": {"type": "boolean", "default": True},
            "output_path": {"type": "string", "description": "Custom HTML output path"},
            "main_item": {"type": "string", "description": "Initial item (e.g. 'Table[Measure]')"}
        },
        "required": ["pbip_folder_path"]
    },

    # Report Operations (replaces report_info + new report-level ops)
    'report_operations': {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["info", "measure_usage", "rename", "rebind", "backup", "restore", "discover_schema", "manage_extension_measures"], "default": "info"},
            "pbip_path": {"type": "string", "description": "Path to PBIP project or .Report folder"},
            "include_visuals": {"type": "boolean", "default": True},
            "include_filters": {"type": "boolean", "default": True},
            "page_name": {"type": "string", "description": "Filter by page name"},
            "summary_only": {"type": "boolean", "default": True},
            "max_visuals_per_page": {"type": "integer", "default": 50},
            "measure_filter": {"type": "string", "description": "Filter by measure name"},
            "output_format": {"type": "string", "enum": ["text", "json"], "default": "text"},
            "export_path": {"type": "string", "description": "CSV export directory"},
            "new_name": {"type": "string", "description": "New report name (rename)"},
            "model_path": {"type": "string", "description": "Semantic model path (rebind)"},
            "model_id": {"type": "string", "description": "Semantic model GUID (rebind)"},
            "message": {"type": "string", "description": "Backup message"},
            "backup_path": {"type": "string", "description": "Backup path (restore)"},
            "visual_type": {"type": "string", "description": "Visual type to discover schema for"},
            "sub_operation": {"type": "string", "enum": ["list", "add", "update", "delete"], "description": "Extension measure sub-op"},
            "measure_name": {"type": "string", "description": "Extension measure name"},
            "expression": {"type": "string", "description": "DAX expression"},
            "table_ref": {"type": "string", "description": "Table reference for measure"},
            "data_type": {"type": "string", "default": "double"},
            "format_string": {"type": "string", "description": "Format string"},
            "description": {"type": "string", "description": "Measure description"}
        },
        "required": ["pbip_path"]
    },

    # Page Operations (new consolidated tool)
    'page_operations': {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["list", "create", "clone", "delete", "reorder", "resize", "set_display", "set_background", "set_wallpaper", "set_drillthrough", "set_tooltip", "hide", "show", "set_interaction", "bulk_set_interactions", "list_interactions"], "default": "list"},
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "page_name": {"type": "string", "description": "Page display name or ID"},
            "page_id": {"type": "string", "description": "Page ID (alternative to page_name)"},
            "width": {"type": "integer", "description": "Page width in pixels"},
            "height": {"type": "integer", "description": "Page height in pixels"},
            "insert_after": {"type": "string", "description": "Page ID to insert after"},
            "source_page": {"type": "string", "description": "Source page for clone"},
            "new_display_name": {"type": "string", "description": "New display name"},
            "page_order": {"type": "array", "items": {"type": "string"}, "description": "Ordered page IDs/names (reorder)"},
            "display_option": {"type": "string", "enum": ["FitToPage", "FitToWidth", "ActualSize"]},
            "color": {"type": "string", "description": "Color hex value (e.g. #E6E6E6)"},
            "transparency": {"type": "number", "description": "Transparency 0-100"},
            "table": {"type": "string", "description": "Table name (drillthrough filter)"},
            "field": {"type": "string", "description": "Field name (drillthrough filter)"},
            "clear": {"type": "boolean", "description": "Clear drillthrough filters"},
            "hidden": {"type": "boolean", "description": "Hide/show page"},
            "dry_run": {"type": "boolean", "default": False},
            "summary_only": {"type": "boolean", "default": True},
            "source_visual": {"type": "string", "description": "Source visual (interactions)"},
            "target_visual": {"type": "string", "description": "Target visual (interactions)"},
            "interaction_type": {"type": "string", "enum": ["NoFilter", "Filter", "Highlight"]},
            "include_visual_info": {"type": "boolean", "default": True},
            "interactions": {"type": "array", "description": "Bulk interactions [{source, target, type}]", "items": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "type": {"type": "string"}}, "required": ["source", "target", "type"]}},
            "replace_all": {"type": "boolean", "default": False}
        },
        "required": ["pbip_path"]
    },

    # Visual Operations (expanded - absorbs authoring create/delete + new ops)
    'visual_operations': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "operation": {"type": "string", "enum": ["list", "create", "create_group", "delete", "update_position", "update_visual_config", "update_formatting", "align", "add_field", "remove_field", "set_sort", "set_action", "inject_code", "manage_visual_calcs", "configure_slicer", "list_templates", "get_template"], "default": "list"},
            "display_title": {"type": "string", "description": "Filter by title"},
            "visual_type": {"type": "string", "description": "Filter/set visual type"},
            "visual_name": {"type": "string", "description": "Filter by visual ID"},
            "page_name": {"type": "string", "description": "Filter by page"},
            "page_id": {"type": "string", "description": "Page ID (alternative to page_name)"},
            "include_hidden": {"type": "boolean", "default": True},
            "x": {"type": "number"}, "y": {"type": "number"},
            "width": {"type": "number"}, "height": {"type": "number"},
            "z": {"type": "integer"},
            "dry_run": {"type": "boolean", "default": False},
            "summary_only": {"type": "boolean", "default": True},
            "config_type": {"type": "string", "description": "Config object to modify"},
            "property_name": {"type": "string", "description": "Property to update"},
            "property_value": {"type": ["string", "number", "boolean"]},
            "selector_metadata": {"type": "string", "description": "Per-series selector"},
            "value_type": {"type": "string", "enum": ["auto", "literal", "boolean", "number", "string"], "default": "auto"},
            "remove_property": {"type": "boolean", "default": False},
            "config_updates": {"type": "array", "description": "Batch config changes", "items": {"type": "object", "properties": {"config_type": {"type": "string"}, "property_name": {"type": "string"}, "property_value": {"type": ["string", "number", "boolean"]}, "selector_metadata": {"type": "string"}, "value_type": {"type": "string"}, "remove_property": {"type": "boolean"}}, "required": ["config_type", "property_name"]}},
            "title": {"type": "string", "description": "Visual title text (create)"},
            "position": {"type": "object", "description": "Position {x, y, width, height, z}", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "width": {"type": "number"}, "height": {"type": "number"}, "z": {"type": "integer"}}},
            "measures": {"type": "array", "description": "Measure bindings [{table, measure, bucket?, display_name?}]", "items": {"type": "object", "properties": {"table": {"type": "string"}, "measure": {"type": "string"}, "bucket": {"type": "string"}, "display_name": {"type": "string"}}, "required": ["table", "measure"]}},
            "columns": {"type": "array", "description": "Column bindings [{table, column, bucket?, display_name?}]", "items": {"type": "object", "properties": {"table": {"type": "string"}, "column": {"type": "string"}, "bucket": {"type": "string"}, "display_name": {"type": "string"}}, "required": ["table", "column"]}},
            "parent_group": {"type": "string", "description": "Parent visual group ID"},
            "group_name": {"type": "string", "description": "Display name for visual group"},
            "formatting": {"type": "array", "description": "Formatting overrides [{config_type, property_name, value}]", "items": {"type": "object"}},
            "delete_children": {"type": "boolean", "default": True},
            "visual_id": {"type": "string", "description": "Visual ID (for delete)"},
            "visual_names": {"type": "array", "items": {"type": "string"}, "description": "Visual names for alignment"},
            "alignment": {"type": "string", "enum": ["left", "right", "top", "bottom", "center_h", "center_v"], "description": "Alignment type"},
            "direction": {"type": "string", "enum": ["horizontal", "vertical"], "description": "Distribute direction"},
            "table": {"type": "string", "description": "Table name (field binding)"},
            "field": {"type": "string", "description": "Field name (field binding)"},
            "bucket": {"type": "string", "description": "Data role bucket"},
            "field_type": {"type": "string", "enum": ["Column", "Measure"], "default": "Column"},
            "display_name": {"type": "string", "description": "Display name override"},
            "sort_field": {"type": "string", "description": "Sort field (Table.Field)"},
            "sort_direction": {"type": "string", "enum": ["Ascending", "Descending"]},
            "action_type": {"type": "string", "enum": ["PageNavigation", "Bookmark", "Drillthrough", "WebUrl", "Back"], "description": "Action button type"},
            "action_target": {"type": "string", "description": "Action target (page/bookmark/URL)"},
            "code_type": {"type": "string", "enum": ["deneb", "python", "r"], "description": "Code injection type"},
            "code": {"type": "string", "description": "Code/spec content"},
            "provider": {"type": "string", "enum": ["vega", "vegaLite"], "description": "Deneb provider"},
            "sub_operation": {"type": "string", "enum": ["list", "add", "update", "delete"], "description": "Visual calc sub-op"},
            "calc_name": {"type": "string", "description": "Visual calculation name"},
            "expression": {"type": "string", "description": "DAX expression"},
            "display_name_filter": {"type": "string", "description": "Slicer display name filter"},
            "entity": {"type": "string", "description": "Slicer entity filter"},
            "property": {"type": "string", "description": "Slicer property filter"},
            "formatting_target": {"type": "string", "enum": ["title", "subtitle", "divider", "background", "border", "shadow", "padding", "spacing", "header", "tooltip", "legend", "categoryAxis", "valueAxis", "labels"], "description": "Formatting target (update_formatting)"},
            "formatting_properties": {"type": "object", "description": "Properties to set on target {show, text, fontSize, fontColor, ...}"}
        },
        "required": ["pbip_path"]
    },

    # Visual Sync (cross-visual operations, moved to pbip category)
    'visual_sync': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "operation": {"type": "string", "enum": ["replace_measure", "sync_visual", "sync_column_widths", "sync_formatting"]},
            "display_title": {"type": "string", "description": "Filter by title"},
            "visual_type": {"type": "string", "description": "Filter by type"},
            "visual_name": {"type": "string", "description": "Filter by visual ID"},
            "page_name": {"type": "string", "description": "Filter by page"},
            "dry_run": {"type": "boolean", "default": False},
            "summary_only": {"type": "boolean", "default": True},
            "source_entity": {"type": "string", "description": "Source table (replace_measure)"},
            "source_property": {"type": "string", "description": "Source measure (replace_measure)"},
            "target_entity": {"type": "string", "description": "Target table (replace_measure)"},
            "target_property": {"type": "string", "description": "Target measure (replace_measure)"},
            "new_display_name": {"type": "string", "description": "New display name (replace_measure)"},
            "source_visual_name": {"type": "string", "description": "Source visual ID (sync)"},
            "source_page": {"type": "string", "description": "Source page (sync)"},
            "target_display_title": {"type": "string", "description": "Target visual title (sync)"},
            "target_visual_type": {"type": "string", "description": "Target visual type (sync)"},
            "sync_position": {"type": "boolean", "default": True},
            "sync_children": {"type": "boolean", "default": True},
            "target_pages": {"type": "array", "items": {"type": "string"}, "description": "Target pages (sync)"},
            "formatting_types": {"type": "array", "items": {"type": "string"}, "description": "Formatting types to sync"}
        },
        "required": ["pbip_path", "operation"]
    },

    # Filter Operations (new)
    'filter_operations': {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["list", "add", "set", "clear", "hide", "unhide", "lock", "unlock"], "default": "list"},
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "level": {"type": "string", "enum": ["report", "page", "visual", "all"], "default": "all", "description": "Filter scope level"},
            "page_name": {"type": "string", "description": "Page name (for page/visual level)"},
            "visual_name": {"type": "string", "description": "Visual name/ID (for visual level)"},
            "filter_name": {"type": "string", "description": "Filter name/ID (for set/hide/lock)"},
            "table": {"type": "string", "description": "Table name (for add)"},
            "field": {"type": "string", "description": "Field name (for add)"},
            "filter_type": {"type": "string", "enum": ["Categorical", "Advanced", "TopN", "RelativeDate"], "default": "Categorical"},
            "values": {"type": "array", "items": {"type": "string"}, "description": "Filter values"},
            "operator": {"type": "string", "description": "Operator (Advanced: GreaterThan, LessThan, etc.)"},
            "top_n": {"type": "integer", "description": "TopN count"},
            "top_direction": {"type": "string", "enum": ["Top", "Bottom"]},
            "by_table": {"type": "string", "description": "TopN ranking table"},
            "by_field": {"type": "string", "description": "TopN ranking field"},
            "dry_run": {"type": "boolean", "default": False}
        },
        "required": ["pbip_path"]
    },

    # Bookmark Operations (replaces analyze_bookmarks)
    'bookmark_operations': {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["list", "create", "rename", "delete", "set_capture", "set_affected_visuals", "analyze"], "default": "list"},
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "bookmark_id": {"type": "string", "description": "Bookmark ID or display name"},
            "display_name": {"type": "string", "description": "Bookmark display name (create/rename)"},
            "new_name": {"type": "string", "description": "New name (rename)"},
            "page_name": {"type": "string", "description": "Target page (create)"},
            "capture_data": {"type": "boolean", "description": "Capture data state"},
            "capture_display": {"type": "boolean", "description": "Capture display state"},
            "capture_current_page": {"type": "boolean", "description": "Capture current page"},
            "visual_ids": {"type": "array", "items": {"type": "string"}, "description": "Affected visual IDs"},
            "all_visuals": {"type": "boolean", "description": "Affect all visuals"},
            "auto_open": {"type": "boolean", "default": True, "description": "Auto-open HTML (analyze)"},
            "output_path": {"type": "string", "description": "HTML output path (analyze)"}
        },
        "required": ["pbip_path"]
    },

    # Theme Operations (replaces analyze_theme_compliance + new theme ops)
    'theme_operations': {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["analyze_compliance", "get_theme", "set_colors", "set_formatting", "push_visual", "list_text_classes", "set_font", "list_cf", "add_cf", "remove_cf", "copy_cf"], "default": "get_theme"},
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "theme_path": {"type": "string", "description": "Custom theme JSON path"},
            "auto_open": {"type": "boolean", "default": True},
            "output_path": {"type": "string", "description": "HTML output path"},
            "colors": {"type": "object", "description": "Color map {dataColors, background, foreground, good, bad, ...}"},
            "visual_type_target": {"type": "string", "description": "Visual type for formatting defaults"},
            "formatting": {"type": "object", "description": "Formatting properties to set"},
            "page_name": {"type": "string", "description": "Page name (push_visual, CF ops)"},
            "visual_name": {"type": "string", "description": "Visual name (push_visual, CF ops)"},
            "text_class": {"type": "string", "description": "Text class name (title, label, callout, etc.)"},
            "font_family": {"type": "string", "description": "Font family name"},
            "font_size": {"type": "number", "description": "Font size"},
            "color": {"type": "string", "description": "Color hex value"},
            "bold": {"type": "boolean"},
            "container": {"type": "string", "description": "CF container (e.g. dataPoint)"},
            "property_name": {"type": "string", "description": "CF property (e.g. fill)"},
            "rule_type": {"type": "string", "enum": ["color_scale", "rules", "data_bars", "icons"], "description": "CF rule type"},
            "cf_config": {"type": "object", "description": "CF rule config {min_color, max_color, mid_color, etc.}"},
            "source_page": {"type": "string", "description": "Source page (copy_cf)"},
            "source_visual": {"type": "string", "description": "Source visual (copy_cf)"},
            "target_page": {"type": "string", "description": "Target page (copy_cf)"},
            "target_visual": {"type": "string", "description": "Target visual (copy_cf)"},
            "dry_run": {"type": "boolean", "default": False}
        },
        "required": ["pbip_path"]
    }
}
