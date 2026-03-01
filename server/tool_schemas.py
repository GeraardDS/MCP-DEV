"""
Tool Input Schemas for Bridged Tools
Defines proper input schemas with required parameters.
"""

TOOL_SCHEMAS = {
    # DAX Intelligence (1 unified tool)
    'dax_intelligence': {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "DAX expression OR measure name (auto-detects)"},
            "analysis_mode": {"type": "string", "enum": ["all", "analyze", "debug", "report"], "default": "all"},
            "skip_validation": {"type": "boolean", "default": False},
            "output_format": {"type": "string", "enum": ["friendly", "steps"], "default": "friendly"},
            "include_optimization": {"type": "boolean", "default": True},
            "include_profiling": {"type": "boolean", "default": True},
            "breakpoints": {"type": "array", "description": "Char positions for debugging", "items": {"type": "integer"}}
        },
        "required": ["expression"]
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

    # Slicer Operations
    'slicer_operations': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "operation": {"type": "string", "enum": ["list", "configure_single_select", "list_interactions", "set_interaction", "bulk_set_interactions"], "default": "list"},
            "display_name": {"type": "string", "description": "Filter by slicer name"},
            "entity": {"type": "string", "description": "Filter by table/entity"},
            "property": {"type": "string", "description": "Filter by column"},
            "dry_run": {"type": "boolean", "default": False},
            "summary_only": {"type": "boolean", "default": True},
            "page_name": {"type": "string", "description": "Filter by page"},
            "source_visual": {"type": "string", "description": "Source visual (interactions)"},
            "target_visual": {"type": "string", "description": "Target visual (interactions)"},
            "interaction_type": {"type": "string", "enum": ["NoFilter", "Filter", "Highlight"]},
            "include_visual_info": {"type": "boolean", "default": True},
            "interactions": {"type": "array", "description": "Bulk interactions [{source, target, type}]", "items": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "type": {"type": "string", "enum": ["NoFilter", "Filter", "Highlight"]}}, "required": ["source", "target", "type"]}},
            "replace_all": {"type": "boolean", "default": False}
        },
        "required": ["pbip_path"]
    },

    # Visual Operations
    'visual_operations': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "operation": {"type": "string", "enum": ["list", "update_position", "replace_measure", "sync_visual", "sync_column_widths", "update_visual_config"], "default": "list"},
            "display_title": {"type": "string", "description": "Filter by title"},
            "visual_type": {"type": "string", "description": "Filter by type"},
            "visual_name": {"type": "string", "description": "Filter by visual ID"},
            "page_name": {"type": "string", "description": "Filter by page"},
            "include_hidden": {"type": "boolean", "default": True},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "width": {"type": "number"},
            "height": {"type": "number"},
            "z": {"type": "integer"},
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
            "config_type": {"type": "string", "description": "Config object (update_visual_config)"},
            "property_name": {"type": "string", "description": "Property to update"},
            "property_value": {"type": ["string", "number", "boolean"]},
            "selector_metadata": {"type": "string", "description": "Per-series selector"},
            "value_type": {"type": "string", "enum": ["auto", "literal", "boolean", "number", "string"], "default": "auto"},
            "remove_property": {"type": "boolean", "default": False},
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
                "default": "info"
            },
            "pbip_path": {"type": "string", "description": "Path to PBIP project or .Report folder"},
            "include_visuals": {"type": "boolean", "default": True},
            "include_filters": {"type": "boolean", "default": True},
            "page_name": {"type": "string", "description": "Filter by page name"},
            "summary_only": {"type": "boolean", "description": "Compact output", "default": True},
            "max_visuals_per_page": {"type": "integer", "default": 50},
            "measure_filter": {"type": "string", "description": "Filter by measure name (measure_usage)"},
            "output_format": {
                "type": "string",
                "enum": ["text", "json"],
                "default": "text"
            },
            "export_path": {"type": "string", "description": "CSV export directory (measure_usage)"}
        },
        "required": ["pbip_path"]
    },

    # Bookmark Analysis
    'analyze_bookmarks': {
        "type": "object",
        "properties": {
            "pbip_path": {"type": "string", "description": "Path to PBIP/Report folder"},
            "auto_open": {"type": "boolean", "default": True},
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
            "auto_open": {"type": "boolean", "default": True},
            "output_path": {"type": "string", "description": "Custom HTML output path"}
        },
        "required": ["pbip_path"]
    }
}
