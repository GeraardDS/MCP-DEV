"""
User Guide Handler
Shows comprehensive user guide with all tools, operations, and parameters.
"""
from typing import Dict, Any
import logging
from server.registry import ToolDefinition

logger = logging.getLogger(__name__)


def handle_show_user_guide(args: Dict[str, Any]) -> Dict[str, Any]:
    """Show comprehensive user guide"""
    return {
        'success': True,
        'guide': _get_user_guide(),
    }


def _get_user_guide() -> str:
    return """# MCP-PowerBi-Finvision User Guide

## QUICK START

1. Open Power BI Desktop with your model
2. Use `01_Connection` (operation='detect') to find running instances
3. Use `01_Connection` (operation='connect', model_index=0) to connect
4. Explore with `06_Analysis_Operations` (operation='simple') or `02_Model_Operations` (object_type='table', operation='list')

---

## CATEGORY 01: CONNECTION (2 tools)

### 01_Connection
Detect running Power BI Desktop instances and connect to one in a single tool.
- **Operations**: `detect` | `connect`
- **Key parameters**:
  - `operation` (str, required): 'detect' or 'connect'
  - `model_index` (int, default 0): Index of model to connect to (connect only)
- **Example**: `{"operation": "connect", "model_index": 0}`

### 10_Show_User_Guide
Show this comprehensive user guide with all tools, operations, and workflows.
- **Parameters**: None
- **Example**: `{}`

---

## CATEGORY 02: MODEL OPERATIONS (2 tools)

### 02_Model_Operations
Unified CRUD for all model objects: tables, columns, measures, relationships, calculation groups, and more.
- **object_type** (required): `table` | `column` | `measure` | `relationship` | `calculation_group` | `partition` | `hierarchy` | `perspective` | `culture` | `named_expression` | `ols_rule`
- **operation** (required): varies by object_type - typically `list` | `get` | `create` | `update` | `delete` | `rename` plus object-specific ops
- **Key parameters**:
  - `table_name` (str): Required for column/measure/partition/hierarchy operations
  - `measure_name` / `column_name` / `relationship_name` (str): For targeted operations
  - `expression` (str): DAX formula (measures/calculated columns/calculated tables)
  - `format_string` (str): e.g. '#,0' or '0.0%'
  - `display_folder` / `description` (str): Metadata
  - `new_name` / `new_table` (str): For rename/move
  - `from_table`, `from_column`, `to_table`, `to_column` (str): For relationship create
  - `is_active` (bool): Relationship active state
  - `items` (array): [{name, expression, ordinal}] for calculation_group create
- **Note**: Use operation='list' first to discover objects; use operation='get' to retrieve DAX expressions.
- **Example**: `{"object_type": "measure", "operation": "list", "table_name": "Sales"}`

### 02_TMDL_Operations
TMDL file automation: export, find/replace, bulk rename, script generation, and measure migration.
- **operation** (required): `export` | `find_replace` | `bulk_rename` | `generate_script` | `migrate_measures`
- **Key parameters**:
  - `tmdl_path` (str): Path to TMDL folder (find_replace, bulk_rename)
  - `pattern` / `replacement` (str): For find_replace
  - `renames` (array): [{old_name, new_name, object_type?, table_name?}] for bulk_rename
  - `source_path` / `target_path` (str): For migrate_measures
  - `dry_run` (bool, default true): Preview changes without writing
  - `regex` / `case_sensitive` (bool): find_replace options
- **Safety**: Always run find_replace and bulk_rename with dry_run=true first!
- **Example**: `{"operation": "export", "output_dir": "C:/backup/tmdl"}`

---

## CATEGORY 03: BATCH OPERATIONS (1 tool)

### 03_Batch_Operations
Execute bulk operations on model objects - 3-5x faster than individual calls.
- **Parameters** (all required):
  - `operation` (str): 'measures' | 'tables' | 'columns' | 'relationships'
  - `batch_operation` (str): 'create' | 'update' | 'delete' | 'rename' | 'move' | 'activate' | 'deactivate' | 'refresh'
  - `items` (array): List of object definitions
- **options** (optional):
  - `use_transaction` (bool, default true): Atomic all-or-nothing
  - `continue_on_error` (bool, default false): Continue past errors (requires use_transaction=false)
  - `dry_run` (bool, default false): Validate without executing
- **Example**: `{"operation": "measures", "batch_operation": "update", "items": [{"table_name": "Sales", "measure_name": "Revenue", "expression": "SUM(Sales[Amount])"}]}`

---

## CATEGORY 04: QUERY & SEARCH (2 tools)

### 04_Run_DAX
Execute a DAX query against the connected model with optional trace analysis.
- **Parameters**:
  - `query` (str, required): DAX EVALUATE statement
  - `top_n` (int, default 100): Row limit
  - `mode` (str, default 'auto'): 'auto' | 'analyze' | 'simple' | 'trace'
    - auto: Smart mode selection
    - analyze: Include timing analysis
    - simple: Preview only
    - trace: SE/FE timing analysis
  - `clear_cache` (bool, default true): Clear VertiPaq cache (trace mode only)
- **Example**: `{"query": "EVALUATE TOPN(10, Sales)", "mode": "simple"}`

### 04_Query_Operations
Query model metadata: data sources, M expressions, object search, security roles, and string search.
- **operation** (required): `data_sources` | `m_expressions` | `search_objects` | `roles` | `test_rls` | `search_string`
- **Key parameters**:
  - `pattern` (str): Search pattern (search_objects, search_string)
  - `types` (array): Filter by ['tables', 'columns', 'measures'] (search_objects)
  - `search_text` (str): Text to find in DAX or names (search_string)
  - `search_in_expression` / `search_in_name` (bool, default true): search_string scope
  - `role_name` (str): Role to test (test_rls)
  - `limit` (int): Max results
  - `page_size` / `next_token`: Pagination
- **Example**: `{"operation": "search_string", "search_text": "CALCULATE", "search_in_expression": true}`

---

## CATEGORY 05: DAX INTELLIGENCE (2 tools)

### 05_DAX_Intelligence
Comprehensive DAX analysis with optimization recommendations, dependency graphs, and impact analysis.
- **Parameters**:
  - `expression` (str, required): DAX expression OR measure name (auto-fetches from model)
  - `analysis_mode` (str, default 'all'): 'all' | 'analyze' | 'debug' | 'report'
    - **all**: Complete analysis (context + anti-patterns + debug + best practices + impact)
    - **analyze**: Context transition analysis with anti-patterns
    - **debug**: Step-by-step execution breakdown
    - **report**: Full analysis with optimization + profiling
  - `operation` (str): 'analyze_dependencies' | 'measure_impact' | 'export_dax' for graph/export ops
  - `table` / `measure` (str): For analyze_dependencies and measure_impact
  - `include_diagram` (bool, default true): Include Mermaid diagram
  - `output_path` (str): Directory path for export_dax
  - `skip_validation` (bool, default false): Skip syntax check
  - `include_optimization` / `include_profiling` (bool, default true)
  - `breakpoints` (array[int]): Char positions for debug mode
- **Workflow**: Tool provides analysis recommendations - AI writes optimized DAX based on output.
- **Example**: `{"expression": "Total Revenue", "analysis_mode": "all"}`

### 05_Column_Usage_Mapping
Analyze column and measure usage across the model - find unused columns and trace dependencies.
- **operation** (required): `get_unused_columns` | `get_measures_for_tables` | `get_columns_for_measure` | `get_measures_for_column` | `get_full_mapping` | `export_to_csv`
- **Key parameters**:
  - `tables` (array): Filter by table names
  - `table` / `measure` / `column` (str): For specific lookups
  - `group_by` (str): 'table' | 'column' | 'measure' | 'flat' (get_measures_for_tables)
  - `include_dax` (bool, default false): Include DAX expressions in output
  - `force_refresh` (bool, default false): Bypass cache
- **Primary use**: `get_unused_columns` finds columns not referenced by measures OR relationships.
- **Example**: `{"operation": "get_unused_columns", "tables": ["Sales", "Products"]}`

---

## CATEGORY 06: ANALYSIS & COMPARISON (1 tool)

### 06_Analysis_Operations
Model analysis from quick overview to comprehensive BPA, plus model comparison.
- **operation** (required): `simple` | `full` | `compare`
- **simple** - Quick model analysis with expert insights (2-5 seconds):
  - `mode` (str, default 'all'): 'all' | 'tables' | 'stats' | 'measures' | 'measure' | 'columns' | 'relationships' | 'roles' | 'database' | 'calculation_groups'
  - `table` (str): Table filter (measures/columns/measure modes)
  - `measure_name` (str): Required for mode=measure
  - `max_results` (int): Limit results
- **full** - BPA (120+ rules), performance, and integrity analysis (10-180s):
  - `scope` (str, default 'all'): 'all' | 'best_practices' | 'performance' | 'integrity'
  - `depth` (str, default 'balanced'): 'fast' | 'balanced' | 'deep'
  - `include_bpa` / `include_performance` / `include_integrity` (bool, default true)
  - `max_seconds` (int, 5-300): Max execution time
- **compare** - Diff two open Power BI Desktop models:
  - `old_port` / `new_port` (int): Ports of OLD and NEW models (call without ports first to detect)
- **Example**: `{"operation": "simple", "mode": "all"}`

---

## CATEGORY 07: PBIP ANALYSIS (6 tools) - No live connection required

### 07_PBIP_Operations
Offline PBIP model analysis, validation, comparison, documentation, git diff, dependency HTML, and aggregation analysis.
- **operation** (required): `analyze` | `validate_model` | `compare_models` | `generate_documentation` | `query_dependencies` | `query_measures` | `query_relationships` | `query_unused` | `git_diff` | `dependency_html` | `analyze_aggregation`
- **Key parameters**:
  - `pbip_path` (str): Path to .pbip file or .SemanticModel folder
  - `source_path` / `target_path` (str): For compare_models
  - `output_path` (str): Output path for reports/docs
  - `object_name` (str): For query_dependencies (e.g., '[Total Sales]')
  - `direction` (str): 'forward' | 'reverse' | 'both' (query_dependencies)
  - `table` / `display_folder` / `pattern` / `expression_search` (str): Filters for query_measures
  - `auto_open` (bool, default true): Open HTML in browser (dependency_html)
- **Example**: `{"operation": "query_unused", "pbip_path": "C:/project/model.SemanticModel"}`

### 07_Report_Operations
Get report structure, measure usage, schema, and manage extension measures. Supports rename and backup/restore.
- **operation** (str, default 'info'): `info` | `measure_usage` | `rename` | `rebind` | `backup` | `restore` | `schema` | `extension_measures`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `include_visuals` / `include_filters` (bool, default true): [info] Detail level
  - `page_name` (str): Filter by page (substring match)
  - `summary_only` (bool, default true): [info] Compact output
  - `measure_filter` (str): [measure_usage] Filter by measure name
  - `output_format` (str): [measure_usage] 'text' (default) or 'json'
  - `export_path` (str): [measure_usage] Export to CSV
- **Example**: `{"operation": "info", "pbip_path": "C:/project/report.Report", "summary_only": true}`

### 07_Page_Operations
CRUD for report pages, plus page-level filter management and interactions.
- **operation** (required): `list` | `get` | `create` | `delete` | `duplicate` | `reorder` | `list_filters` | `add_filter` | `remove_filter` | `list_interactions` | `set_interaction` | `bulk_set_interactions`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `page_name` (str): Target page
  - `display_name` (str): Page display name (create/duplicate)
  - `position` (int): Page order (reorder)
  - `filter` (object): DAX filter definition (add_filter)
  - `source_visual` / `target_visual` (str): For interaction operations
  - `interaction_type` (str): 'NoFilter' | 'Filter' | 'Highlight'
  - `dry_run` (bool, default false): Preview changes
- **Example**: `{"operation": "list", "pbip_path": "C:/project/report.Report"}`

### 07_Visual_Operations
CRUD for visuals, formatting, data binding, sync, and interactions within PBIP report pages.
- **operation** (required): `list` | `get` | `create` | `delete` | `update_position` | `replace_measure` | `sync_visual` | `sync_column_widths` | `update_visual_config` | `list_interactions` | `set_interaction` | `apply_template`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `page_name` / `visual_name` / `visual_type` / `display_title` (str): Filters/targets
  - `x`, `y`, `width`, `height` (number): Position for update_position
  - `z` (int): Z-order
  - `source_entity`, `source_property`, `target_entity`, `target_property` (str): For replace_measure
  - `source_visual_name`, `source_page`, `target_pages` (str/array): For sync_visual
  - `config_type` / `property_name` / `property_value` (str): For update_visual_config
  - `config_updates` (array): Batch config changes
  - `dry_run` (bool, default false): Preview changes
- **Example**: `{"operation": "list", "pbip_path": "C:/project/report.Report", "page_name": "Overview"}`

### 07_Bookmark_Operations
CRUD for report bookmarks plus interactive HTML bookmark analysis.
- **operation** (required): `list` | `get` | `create` | `update` | `delete` | `analyze_html`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `bookmark_name` (str): Target bookmark
  - `display_name` (str): Bookmark label (create/update)
  - `page_name` (str): Associated page
  - `auto_open` (bool, default true): Open HTML in browser (analyze_html)
  - `output_path` (str): Custom HTML output path
- **Example**: `{"operation": "list", "pbip_path": "C:/project/report.Report"}`

### 07_Theme_Operations
Analyze and update report theme: colors, fonts, text classes, formatting, and conditional formatting rules.
- **operation** (required): `get_colors` | `set_colors` | `get_fonts` | `set_fonts` | `get_text_classes` | `update_text_class` | `get_cf_rules` | `analyze_compliance`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `theme_path` (str): Custom theme JSON path
  - `colors` (object): Color palette updates
  - `font_family` (str): Font name
  - `text_class` (str): Text class to update (title, label, callout, etc.)
  - `auto_open` (bool, default true): Open compliance HTML in browser
- **Example**: `{"operation": "get_colors", "pbip_path": "C:/project/report.Report"}`

---

## CATEGORY 08: DOCUMENTATION (1 tool)

### 08_Documentation_Word
Generate or update a Word (.docx) documentation report from the connected model.
- **Parameters**:
  - `mode` (str, default 'generate'): 'generate' (new doc) | 'update' (detect changes)
  - `output_path` (str): Output Word file path
  - `input_path` (str): Existing doc path (required for mode='update')
- **Example**: `{"mode": "generate", "output_path": "C:/docs/model_docs.docx"}`

---

## CATEGORY 09: DEBUG (4 tools)

### 09_Debug_Operations
Visual debugger combining PBIP report layout with live model data. Discovers pages/visuals, captures full filter context (slicers, page filters, visual filters), executes queries, compares measures, drills to detail, and manages debug configuration.
- **operation** (required): `visual` | `compare` | `drill` | `audit` | `run_dax` | `set_pbip_path` | `get_status` | `analyze_measure` | `config`
- **Key parameters**:
  - `page_name` (str): Omit to list all pages
  - `visual_id` / `visual_name` (str): Target visual (omit to list all on page)
  - `measure_name` (str): Specific measure to query
  - `include_slicers` (bool, default true): Include slicer selections in filter context
  - `execute_query` (bool, default true): Execute query (false = filters only)
  - `filters` (array[str]): Manual DAX filter expressions
  - `skip_auto_filters` (bool, default false): Use only manual filters
  - `original_measure` / `optimized_expression` (str): For compare operation
  - `fact_table` (str): Fact table to drill into
  - `pbip_path` (str): For set_pbip_path if auto-detection failed
  - `compact` (bool, default true): Compact output
- **Example**: `{"operation": "visual", "page_name": "Overview", "visual_name": "Revenue Card"}`

### 09_Validate
Run validation tests against the live model: cross-visual consistency, expected value checks, and filter permutation testing.
- **operation** (required): `cross_visual` | `expected_value` | `filter_permutation`
- **Key parameters**:
  - `measure_name` (str): Measure to validate
  - `page_name` / `page_names` (str/array): Page context
  - `visual_id` / `visual_name` (str): Visual context
  - `expected_value` (number|str): For expected_value test
  - `filters` (array[str]): Additional DAX filters
  - `tolerance` (number, default 0.001): Numeric comparison tolerance
  - `max_permutations` (int, default 20): Max combinations for filter_permutation
- **Example**: `{"operation": "expected_value", "measure_name": "Total Revenue", "expected_value": 1000000}`

### 09_Profile
Performance profiling for report pages: per-visual timing and filter matrix analysis.
- **operation** (str, default 'page'): `page` | `filter_matrix`
- **Key parameters**:
  - `page_name` (str, required): Page to profile
  - `visual_id` / `visual_name` (str): Target for filter_matrix
  - `iterations` (int, default 3): Iterations per visual
  - `include_slicers` (bool, default true)
  - `filter_columns` (array[str]): Columns to vary (auto-detect if omitted)
  - `max_combinations` (int, default 15): Max filter combinations
- **Example**: `{"operation": "page", "page_name": "Overview", "iterations": 3}`

### 09_Document
Generate documentation from PBIP + live model: page docs, report docs, measure lineage, and filter lineage.
- **operation** (required): `page` | `report` | `measure_lineage` | `filter_lineage`
- **Key parameters**:
  - `page_name` (str): Required for page operation
  - `measure_name` (str): For measure_lineage
  - `lightweight` (bool, default true): Fast mode (skips DMV queries)
  - `include_ui_elements` (bool, default false): Include shapes/buttons
- **Example**: `{"operation": "measure_lineage", "measure_name": "Total Revenue"}`

---

## CATEGORY 10: SVG VISUALS

### SVG_Visual_Operations
40+ DAX measure templates for KPIs, sparklines, gauges, and data bars - injects directly into the model.
- **operation** (required): `list_templates` | `get_template` | `preview_template` | `generate_measure` | `inject_measure` | `list_categories` | `search_templates` | `validate_svg` | `create_custom`
- **Key parameters**:
  - `category` (str): 'kpi' | 'sparklines' | 'gauges' | 'databars' | 'advanced'
  - `complexity` (str): 'basic' | 'intermediate' | 'advanced' | 'complex'
  - `template_id` (str): For get/preview/generate/inject
  - `parameters` (object): Template params (measure_name, value_measure, thresholds, colors)
  - `table_name` (str): Target table for inject_measure
  - `search_query` (str): For search_templates
  - `svg_code` (str): For validate_svg/create_custom
  - `dynamic_vars` (object): Variable name -> DAX expression for create_custom
  - `context_aware` (bool, default true): Use connected model for suggestions
- **Example**: `{"operation": "list_categories"}`

---

## CATEGORY 11: PBIP AUTHORING (2 tools)

### 11_PBIP_Authoring
Create, clone, and manage pages and visuals in PBIP report files.
- **operation** (required): `clone_page` | `create_page` | `delete_page` | `clone_visual` | `create_visual` | `delete_visual` | `apply_template` | `list_templates` | `get_template`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `source_page` / `target_page` / `page_name` (str): Page targets
  - `visual_id` / `visual_name` (str): Visual targets
  - `display_name` (str): Name for created/cloned objects
  - `visual_type` (str): Type for create_visual (e.g., 'card', 'barChart', 'lineChart')
  - `template_id` (str): For apply_template/get_template
  - `position` (object): {x, y, width, height} for visual placement
  - `dry_run` (bool, default false): Preview changes without writing
- **Example**: `{"operation": "clone_page", "pbip_path": "C:/project/report.Report", "source_page": "Overview", "display_name": "Overview Copy"}`

### 11_PBIP_Prototype
Generate an HTML report prototype with real data from the live model.
- **operation** (required): `generate` | `preview` | `export`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `page_name` (str): Specific page to prototype (all pages if omitted)
  - `output_path` (str): Output HTML file path
  - `auto_open` (bool, default true): Open in browser after generation
  - `include_filters` (bool, default true): Include filter context in data
- **Example**: `{"operation": "generate", "pbip_path": "C:/project/report.Report", "page_name": "Overview"}`

---

## COMMON WORKFLOWS

### Model Health Check
1. `01_Connection` (operation='connect')
2. `06_Analysis_Operations` (operation='full', scope='all', depth='balanced')
3. Review best practices violations
4. Address critical/high priority issues

### Measure Development
1. `02_Model_Operations` (object_type='measure', operation='list') - study existing measures
2. `05_DAX_Intelligence` (analysis_mode='all') - analyze DAX
3. `02_Model_Operations` (object_type='measure', operation='create') - create new measure
4. `04_Run_DAX` - test with real data
5. `05_DAX_Intelligence` (operation='analyze_dependencies') - verify dependencies

### Model Documentation
1. `06_Analysis_Operations` (operation='simple', mode='all') - get model overview
2. `08_Documentation_Word` - generate Word doc
3. `07_PBIP_Operations` (operation='analyze') - HTML report
4. `02_TMDL_Operations` (operation='export') - TMDL backup

### DAX Debugging
1. `09_Debug_Operations` (operation='visual') - discover pages/visuals and capture filter context
2. `09_Debug_Operations` (operation='analyze_measure') - analyze anti-patterns
3. `05_DAX_Intelligence` (analysis_mode='all') - get optimization recommendations
4. AI writes optimized DAX based on recommendations
5. `09_Debug_Operations` (operation='compare') - validate original vs optimized
6. `02_Model_Operations` (object_type='measure', operation='update') - save optimized version

### Model Comparison
1. Open both Power BI files in separate Desktop instances
2. `06_Analysis_Operations` (operation='compare') - detect models (no ports needed)
3. Identify OLD vs NEW from returned list
4. `06_Analysis_Operations` (operation='compare', old_port=X, new_port=Y) - perform comparison

### Offline PBIP Analysis
1. `07_PBIP_Operations` (operation='analyze') - full offline analysis
2. `07_PBIP_Operations` (operation='validate_model') - TMDL linting
3. `07_PBIP_Operations` (operation='query_unused') - find dead code
4. `07_PBIP_Operations` (operation='dependency_html') - interactive dependency browser
5. `07_PBIP_Operations` (operation='analyze_aggregation') - aggregation optimization

---

## TIPS

- Always start with `01_Connection` (operation='connect') before using model or debug tools
- Use `06_Analysis_Operations` (operation='simple') for quick checks, operation='full' for thorough review
- Run `05_DAX_Intelligence` with analysis_mode='all' for complete analysis recommendations
- Always use dry_run=true first for TMDL find_replace and bulk_rename operations
- Check `05_DAX_Intelligence` (operation='analyze_dependencies' or 'measure_impact') before modifying/deleting measures
- PBIP tools (07_*) work offline without a Power BI Desktop connection
- Debug tools (09_*) combine PBIP report layout with live model data for accurate filter context
- Use `03_Batch_Operations` for bulk changes - 3-5x faster than individual operations
"""


def register_user_guide_handlers(registry):
    """Register user guide handler"""
    tool = ToolDefinition(
        name="10_Show_User_Guide",
        description="Show comprehensive user guide with all tools, operations, parameters, and workflows",
        handler=handle_show_user_guide,
        input_schema={
            "type": "object",
            "properties": {},
            "required": []
        },
        category="core",
        sort_order=110,
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    registry.register(tool)
    logger.info("Registered user guide handler")
