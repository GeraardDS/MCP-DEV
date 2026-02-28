"""
Tool Input Schemas for Bridged Tools
Defines proper input schemas with required parameters.
"""

TOOL_SCHEMAS = {
    # DAX Intelligence (1 unified tool)
    'dax_intelligence': {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "DAX expression OR measure name (auto-detects and fetches)"},
            "analysis_mode": {"type": "string", "description": "all|analyze|debug|report (default: all)", "enum": ["all", "analyze", "debug", "report"], "default": "all"},
            "skip_validation": {"type": "boolean", "description": "Skip syntax validation", "default": False},
            "output_format": {"type": "string", "description": "friendly|steps (debug mode)", "enum": ["friendly", "steps"], "default": "friendly"},
            "include_optimization": {"type": "boolean", "description": "Include optimization suggestions", "default": True},
            "include_profiling": {"type": "boolean", "description": "Include profiling", "default": True},
            "breakpoints": {"type": "array", "description": "Char positions for debugging", "items": {"type": "integer"}}
        },
        "required": ["expression"]
    },

    # PBIP Dependency Analysis (1 tool)
    'pbip_dependency_analysis': {
        "type": "object",
        "properties": {
            "pbip_folder_path": {"type": "string", "description": "Path to .SemanticModel or PBIP folder"},
            "auto_open": {"type": "boolean", "description": "Open HTML in browser", "default": True},
            "output_path": {"type": "string", "description": "Custom HTML output path"},
            "main_item": {"type": "string", "description": "Initial item to select (e.g., 'Table[Measure]')"}
        },
        "required": ["pbip_folder_path"]
    },

    # Slicer Operations
    'slicer_operations': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "operation": {"type": "string", "enum": ["list", "configure_single_select", "list_interactions", "set_interaction", "bulk_set_interactions"], "description": "list|configure_single_select|list_interactions|set_interaction|bulk_set_interactions", "default": "list"},
            "display_name": {"type": "string", "description": "Filter by slicer display name"},
            "entity": {"type": "string", "description": "Filter by table/entity"},
            "property": {"type": "string", "description": "Filter by column/property"},
            "dry_run": {"type": "boolean", "description": "Preview changes only", "default": False},
            "summary_only": {"type": "boolean", "description": "Condensed output", "default": True},
            "page_name": {"type": "string", "description": "Filter by page name"},
            "source_visual": {"type": "string", "description": "Source visual for interactions"},
            "target_visual": {"type": "string", "description": "Target visual for interactions"},
            "interaction_type": {"type": "string", "enum": ["NoFilter", "Filter", "Highlight"], "description": "Interaction type"},
            "include_visual_info": {"type": "boolean", "description": "Include visual titles", "default": True},
            "interactions": {"type": "array", "description": "Bulk interactions [{source, target, type}]", "items": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "type": {"type": "string", "enum": ["NoFilter", "Filter", "Highlight"]}}, "required": ["source", "target", "type"]}},
            "replace_all": {"type": "boolean", "description": "Replace all interactions", "default": False}
        },
        "required": ["pbip_path"]
    },

    # Visual Operations
    'visual_operations': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "operation": {"type": "string", "enum": ["list", "update_position", "replace_measure", "sync_visual", "sync_column_widths", "update_visual_config"], "description": "list|update_position|replace_measure|sync_visual|sync_column_widths|update_visual_config", "default": "list"},
            "display_title": {"type": "string", "description": "Filter by visual title"},
            "visual_type": {"type": "string", "description": "Filter by type (slicer, barChart, etc.)"},
            "visual_name": {"type": "string", "description": "Filter by visual ID"},
            "page_name": {"type": "string", "description": "Filter by page name"},
            "include_hidden": {"type": "boolean", "description": "Include hidden visuals", "default": True},
            "x": {"type": "number", "description": "Horizontal position"},
            "y": {"type": "number", "description": "Vertical position"},
            "width": {"type": "number", "description": "Width"},
            "height": {"type": "number", "description": "Height"},
            "z": {"type": "integer", "description": "Z-order"},
            "dry_run": {"type": "boolean", "description": "Preview changes", "default": False},
            "summary_only": {"type": "boolean", "description": "Condensed output", "default": True},
            "source_entity": {"type": "string", "description": "Source table for replace_measure"},
            "source_property": {"type": "string", "description": "Source measure for replace_measure"},
            "target_entity": {"type": "string", "description": "Target table for replace_measure"},
            "target_property": {"type": "string", "description": "Target measure for replace_measure"},
            "new_display_name": {"type": "string", "description": "New display name for replaced measure"},
            "source_visual_name": {"type": "string", "description": "Source visual ID for sync"},
            "source_page": {"type": "string", "description": "Source page for sync"},
            "target_display_title": {"type": "string", "description": "Target visual title for sync"},
            "target_visual_type": {"type": "string", "description": "Target visual type for sync"},
            "sync_position": {"type": "boolean", "description": "Sync position/size", "default": True},
            "sync_children": {"type": "boolean", "description": "Sync child visuals", "default": True},
            "target_pages": {"type": "array", "items": {"type": "string"}, "description": "Target pages for sync"},
            "config_type": {"type": "string", "description": "Config object (categoryAxis, valueAxis, labels, etc.)"},
            "property_name": {"type": "string", "description": "Property to update"},
            "property_value": {"type": ["string", "number", "boolean"], "description": "New value"},
            "selector_metadata": {"type": "string", "description": "Selector for per-series formatting"},
            "value_type": {"type": "string", "enum": ["auto", "literal", "boolean", "number", "string"], "description": "Value format type", "default": "auto"},
            "remove_property": {"type": "boolean", "description": "Remove property to reset", "default": False},
            "config_updates": {"type": "array", "description": "Batch config changes", "items": {"type": "object", "properties": {"config_type": {"type": "string"}, "property_name": {"type": "string"}, "property_value": {"type": ["string", "number", "boolean"]}, "selector_metadata": {"type": "string"}, "value_type": {"type": "string"}, "remove_property": {"type": "boolean"}}, "required": ["config_type", "property_name"]}}
        },
        "required": ["pbip_path"]
    },

    # Report Info
    'report_info': {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["info", "measure_usage"],
                "description": (
                    "Operation:\n"
                    "• 'info' - Report structure (pages, visuals, filters) [default]\n"
                    "• 'measure_usage' - All measures used across report(s): which page, visual, and context (bucket/filter/objects). Supports multiple .Report folders."
                ),
                "default": "info"
            },
            "pbip_path": {"type": "string", "description": "Path to PBIP project, .Report folder, or definition folder"},
            "include_visuals": {"type": "boolean", "description": "[info] Include visual info", "default": True},
            "include_filters": {"type": "boolean", "description": "[info] Include filter info", "default": True},
            "page_name": {"type": "string", "description": "Filter by page name (substring match)"},
            "summary_only": {"type": "boolean", "description": "[info] Compact output - visual types/titles/field refs only, no positions/nested objects.", "default": True},
            "max_visuals_per_page": {"type": "integer", "description": "[info] Max visuals returned per page (0=unlimited)", "default": 50},
            "measure_filter": {"type": "string", "description": "[measure_usage] Filter by measure name (substring match)"},
            "output_format": {
                "type": "string",
                "enum": ["text", "json"],
                "description": "[measure_usage] Output format: 'text' (simple readable list, default) or 'json' (structured data)",
                "default": "text"
            },
            "export_path": {"type": "string", "description": "[measure_usage] Export to CSV file at this directory path. Returns file path instead of inline data."}
        },
        "required": ["pbip_path"]
    },

    # Bookmark Analysis
    'analyze_bookmarks': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "auto_open": {"type": "boolean", "description": "Open HTML in browser", "default": True},
            "output_path": {"type": "string", "description": "Custom HTML output path"}
        },
        "required": ["pbip_path"]
    },

    # Theme Compliance Analysis
    'analyze_theme_compliance': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "theme_path": {"type": "string", "description": "Custom theme JSON path"},
            "auto_open": {"type": "boolean", "description": "Open HTML in browser", "default": True},
            "output_path": {"type": "string", "description": "Custom HTML output path"}
        },
        "required": ["pbip_path"]
    }
}
