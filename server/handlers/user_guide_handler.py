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
2. Use `01_Detect_PBI_Instances` to find running instances
3. Use `01_Connect_To_Instance` (typically model_index=0)
4. Explore with `06_Simple_Analysis` or `02_Table_Operations` (operation='list')

---

## CATEGORY 01: CONNECTION (2 tools)

### 01_Detect_PBI_Instances
Detect running Power BI Desktop instances.
- **Parameters**: None
- **Returns**: List of instances with ports and model names

### 01_Connect_To_Instance
Connect to a Power BI Desktop instance (auto-detect or specify index).
- **Parameters**:
  - `model_index` (int, optional): Index of model to connect to (default: 0)
- **Returns**: Connection status and model information

---

## CATEGORY 02: MODEL OPERATIONS (7 tools)

### 02_Table_Operations
Unified table CRUD with 9 operations.
- **operation** (required): `list` | `describe` | `preview` | `sample_data` | `create` | `update` | `delete` | `rename` | `refresh`
- **Key parameters**:
  - `table_name` (str): Required for all except list
  - `new_name` (str): For rename
  - `description` (str): For create/update
  - `expression` (str): DAX expression for calculated tables (create/update)
  - `hidden` (bool): Hide from client tools (create/update)
  - `max_rows` (int, default 10): For preview/sample_data
  - `columns` (array): Column selection for sample_data
  - `order_by` / `order_direction`: Sorting for sample_data
  - `page_size` / `next_token`: Pagination for list

### 02_Column_Operations
Unified column CRUD with 8 operations.
- **operation** (required): `list` | `get` | `statistics` | `distribution` | `create` | `update` | `delete` | `rename`
- **Key parameters**:
  - `table_name` (str): Required for most operations
  - `column_name` (str): Required for get/statistics/distribution/update/delete/rename
  - `column_type` (str): Filter by 'all'|'data'|'calculated' (list)
  - `top_n` (int, default 10): For distribution
  - `data_type` (str): String|Int64|Double|Decimal|Boolean|DateTime|Binary|Variant (create)
  - `expression` (str): DAX for calculated columns (create/update)
  - `format_string` (str): e.g. '#,0' (create/update)
  - `new_name` (str): For rename

### 02_Measure_Operations
Unified measure CRUD with 7 operations.
- **operation** (required): `list` | `get` | `create` | `update` | `delete` | `rename` | `move`
- **Key parameters**:
  - `table_name` (str): Required for most operations
  - `measure_name` (str): Required for get/update/delete/rename/move
  - `expression` (str): DAX formula (create/update)
  - `format_string` (str): e.g. '#,0' or '0.0%' (create/update)
  - `display_folder` (str): Folder path (create/update)
  - `description` (str): Measure description (create/update)
  - `new_name` (str): For rename
  - `new_table` (str): Target table for move
- **Note**: `list` returns names only. Use `get` to see DAX expressions.

### 02_Relationship_Operations
Unified relationship CRUD with 8 operations.
- **operation** (required): `list` | `get` | `find` | `create` | `update` | `delete` | `activate` | `deactivate`
- **Key parameters**:
  - `relationship_name` (str): For get/update/delete/activate/deactivate
  - `table_name` (str): For find (finds relationships for a table)
  - `from_table`, `from_column`, `to_table`, `to_column` (str): For create
  - `from_cardinality` (str): 'One'|'Many' (default: Many)
  - `to_cardinality` (str): 'One'|'Many' (default: One)
  - `cross_filtering_behavior` (str): 'OneDirection'|'BothDirections'|'Automatic' (create/update)
  - `is_active` (bool): Active state (create/update)
  - `active_only` (bool): Filter active only (list)

### 02_Calculation_Group_Operations
Unified calculation group CRUD with 4 operations.
- **operation** (required): `list` | `list_items` | `create` | `delete`
- **Key parameters**:
  - `group_name` (str): Required for list_items/create/delete
  - `items` (array): Array of {name, expression, ordinal} for create
  - `description` (str): Optional for create
  - `precedence` (int): Optional for create

### 02_Role_Operations
RLS/OLS security role operations.
- **operation** (required): `list`
- **Returns**: All security roles with table permissions and DAX filters

### 02_TMDL_Operations
TMDL automation with 5 operations.
- **operation** (required): `export` | `find_replace` | `bulk_rename` | `generate_script` | `migrate_measures`
- **Operations**:
  - **export**: Export full TMDL to file. Optional: `output_dir`
  - **find_replace**: Find/replace in TMDL files. Requires: `tmdl_path`, `pattern`, `replacement`. Optional: `dry_run` (default true), `regex`, `case_sensitive`, `target`
  - **bulk_rename**: Rename objects with reference updates. Requires: `tmdl_path`, `renames` [{old_name, new_name, object_type?, table_name?}]. Optional: `dry_run` (default true), `update_references` (default true)
  - **generate_script**: Generate TMDL code. Requires: `definition`. Optional: `object_type` (table|measure|relationship|calc_group)
  - **migrate_measures**: Copy measures between TMDL files. Requires: `source_path`, `target_path`. Optional: `display_folder_filter`, `replace_target`, `skip_duplicates`
- **Safety**: Always run find_replace and bulk_rename with dry_run=true first!

---

## CATEGORY 03: BATCH & TRANSACTIONS (2 tools)

### 03_Batch_Operations
Execute batch operations on model objects (3-5x faster than individual operations).
- **Parameters** (all required):
  - `operation` (str): 'measures'|'tables'|'columns'|'relationships'
  - `batch_operation` (str): 'create'|'update'|'delete'|'rename'|'move'|'activate'|'deactivate'|'refresh'
  - `items` (array): List of object definitions
- **options** (optional):
  - `use_transaction` (bool, default true): Atomic all-or-nothing
  - `continue_on_error` (bool, default false): Continue on error (only with use_transaction=false)
  - `dry_run` (bool, default false): Validate without executing

### 03_Manage_Transactions
ACID transactions for atomic model changes with rollback.
- **operation** (required): `begin` | `commit` | `rollback` | `status` | `list_active`
- **Parameters**:
  - `transaction_id` (str): Required for commit/rollback/status
  - `connection_name` (str): Optional for begin

---

## CATEGORY 04: QUERY & SEARCH (5 tools)

### 04_Run_DAX
Execute DAX query with auto limits.
- **Parameters**:
  - `query` (str, required): DAX EVALUATE statement
  - `top_n` (int, default 100): Row limit
  - `mode` (str, default 'auto'): 'auto'|'analyze'|'simple'
    - auto: Smart mode selection
    - analyze: Include timing analysis
    - simple: Preview only

### 04_Get_Data_Sources
List all data sources. No parameters. Returns connection strings, types, credentials info.

### 04_Get_M_Expressions
List M/Power Query expressions.
- **Parameters**:
  - `limit` (int, optional): Max expressions to return

### 04_Search_Objects
Search tables/columns/measures by name pattern (wildcard).
- **Parameters**:
  - `pattern` (str): Search pattern
  - `types` (array): Filter by ['tables', 'columns', 'measures']
  - `page_size` / `next_token`: Pagination

### 04_Search_String
Search inside DAX expressions and measure names.
- **Parameters**:
  - `search_text` (str, required): Text to search for
  - `search_in_expression` (bool, default true): Search DAX code
  - `search_in_name` (bool, default true): Search measure names
  - `page_size` / `next_token`: Pagination

---

## CATEGORY 05: DAX INTELLIGENCE (5 tools)

### 05_DAX_Intelligence
Comprehensive DAX analysis with optimization recommendations.
- **Parameters**:
  - `expression` (str, required): DAX expression OR measure name (auto-detects and fetches)
  - `analysis_mode` (str, default 'all'): 'all'|'analyze'|'debug'|'report'
    - **all**: Complete analysis (context + anti-patterns + debug + report + best practices)
    - **analyze**: Context transition analysis with anti-patterns
    - **debug**: Step-by-step execution breakdown
    - **report**: Full analysis with optimization + profiling
  - `skip_validation` (bool, default false): Skip syntax check
  - `output_format` (str): 'friendly'|'steps' (debug mode)
  - `include_optimization` (bool, default true): Include suggestions
  - `include_profiling` (bool, default true): Include performance
  - `breakpoints` (array[int]): Char positions for debugging
- **Workflow**: Tool provides analysis recommendations -> AI writes optimized DAX

### 05_Analyze_Dependencies
Analyze measure dependencies with interactive diagram.
- **Parameters**:
  - `table` (str, required): Table name
  - `measure` (str, required): Measure name
  - `include_diagram` (bool, default true): Include Mermaid diagram
- **Returns**: Formatted dependency tree + interactive HTML diagram (auto-opens in browser)

### 05_Get_Measure_Impact
Get what depends on this measure (reverse dependencies).
- **Parameters**:
  - `table` (str, required): Table name
  - `measure` (str, required): Measure name
- **Returns**: List of measures that reference this measure

### 05_Export_DAX_Measures
Export all DAX measures to CSV.
- **Parameters**:
  - `output_path` (str, optional): Directory path (default: exports/)
- **Returns**: CSV with Table, Measure_Name, Display_Folder, DAX_Expression

### 05_Column_Usage_Mapping
Analyze column usage - find unused columns, check measure dependencies.
- **operation** (required): `get_unused_columns` | `get_measures_for_tables` | `get_columns_for_measure` | `get_measures_for_column` | `get_full_mapping` | `export_to_csv`
- **Key parameters**:
  - `tables` (array): Filter by table names
  - `table` / `measure` / `column` (str): For specific lookups
  - `group_by` (str): 'table'|'column'|'measure'|'flat' (for get_measures_for_tables)
  - `include_dax` (bool, default false): Include DAX expressions
  - `force_refresh` (bool, default false): Force cache refresh
- **Primary use**: `get_unused_columns` finds columns not used by measures OR relationships

---

## CATEGORY 06: ANALYSIS & COMPARISON (3 tools)

### 06_Simple_Analysis
Quick model analysis with expert insights (2-5 seconds).
- **Parameters**:
  - `mode` (str, default 'all'): 'all'|'tables'|'stats'|'measures'|'measure'|'columns'|'relationships'|'roles'|'database'|'calculation_groups'
  - `table` (str): Table filter (for measures/columns/measure modes)
  - `measure_name` (str): Required for mode=measure
  - `max_results` (int): Limit results
  - `active_only` (bool, default false): Active relationships only

### 06_Full_Analysis
Comprehensive analysis: Best practices (BPA 120+ rules), performance, integrity (10-180s).
- **Parameters**:
  - `scope` (str, default 'all'): 'all'|'best_practices'|'performance'|'integrity'
  - `depth` (str, default 'balanced'): 'fast'|'balanced'|'deep'
  - `include_bpa` (bool, default true): Include BPA rules
  - `include_performance` (bool, default true): Include performance analysis
  - `include_integrity` (bool, default true): Include integrity validation
  - `max_seconds` (int, 5-300): Max execution time

### 06_Compare_PBI_Models
Compare two live/open Power BI models.
- **Workflow**: Call without parameters first to detect instances, then call with ports.
- **Parameters**:
  - `old_port` (int): Port of OLD model
  - `new_port` (int): Port of NEW model
- **Returns**: Detailed diff of tables, measures, columns, relationships, DAX formulas

---

## CATEGORY 07: PBIP ANALYSIS (7 tools) - No live connection required

### 07_PBIP_Model_Analysis
Offline PBIP analysis and validation.
- **operation** (required): `analyze` | `validate_model` | `compare_models` | `generate_documentation`
- **Key parameters**:
  - `pbip_path` (str): Path to .pbip file or .SemanticModel folder
  - `source_path` / `target_path` (str): For compare_models
  - `output_path` (str): For analyze or generate_documentation
- **Operations**:
  - **analyze**: Full HTML report with model analysis
  - **validate_model**: TMDL validation and linting
  - **compare_models**: Compare two PBIP projects
  - **generate_documentation**: Markdown docs from TMDL metadata

### 07_PBIP_Query
Offline PBIP queries and git diff.
- **operation** (required): `query_dependencies` | `query_measures` | `query_relationships` | `query_unused` | `git_diff`
- **Key parameters**:
  - `pbip_path` (str): Path to .pbip file or .SemanticModel folder
  - `object_name` (str): For query_dependencies (e.g., '[Total Sales]')
  - `direction` (str): 'forward'|'reverse'|'both' (query_dependencies)
  - `table` / `display_folder` / `pattern` / `expression_search` (str): Filters for query_measures
- **Operations**:
  - **query_dependencies**: Dependency graph for an object
  - **query_measures**: Search/list measures by name, folder, or DAX expression
  - **query_relationships**: Relationships with quality analysis
  - **query_unused**: Find unused measures/columns
  - **git_diff**: Semantic analysis of git changes in TMDL files

### 07_Report_Info
Get report structure - pages, filters, visuals. measure_usage lists all measures per page.
- **Parameters**:
  - `operation` (str): 'info' (default) or 'measure_usage'
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `include_visuals` (bool, default true): [info] Include visual info
  - `include_filters` (bool, default true): [info] Include filter info
  - `page_name` (str): Filter by page name (substring match)
  - `summary_only` (bool, default true): [info] Compact output
  - `max_visuals_per_page` (int, default 50): [info] Limit visuals per page
  - `measure_filter` (str): [measure_usage] Filter by measure name
  - `output_format` (str): [measure_usage] 'text' (default) or 'json'
  - `export_path` (str): [measure_usage] Export to CSV at this directory path

### 07_PBIP_Dependency_Analysis
Generate interactive HTML dependency browser.
- **Parameters**:
  - `pbip_folder_path` (str, required): Path to .SemanticModel or PBIP folder
  - `auto_open` (bool, default true): Open HTML in browser
  - `output_path` (str): Custom HTML output path
  - `main_item` (str): Initial item to select (e.g., 'Table[Measure]')
- **Features**: Sidebar with ALL measures/columns, click to view upstream/downstream deps

### 07_Slicer_Operations
Configure Power BI slicers and visual interactions.
- **operation** (default 'list'): `list` | `configure_single_select` | `list_interactions` | `set_interaction` | `bulk_set_interactions`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `display_name` / `entity` / `property` (str): Slicer filters
  - `page_name` (str): Filter by page
  - `source_visual` / `target_visual` (str): For interaction operations
  - `interaction_type` (str): 'NoFilter'|'Filter'|'Highlight'
  - `interactions` (array): [{source, target, type}] for bulk operations
  - `dry_run` (bool, default false): Preview changes
  - `summary_only` (bool, default true): Compact output

### 07_Analyze_Aggregation
Analyze aggregation table usage and optimization opportunities.
- **Parameters**:
  - `pbip_path` (str, required): Path to PBIP project
  - `output_format` (str, default 'summary'): 'summary'|'detailed'|'html'|'json'
  - `output_path` (str): Output path for reports
  - `page_filter` (str): Filter by page name
  - `include_visual_details` (bool, default true): Per-visual analysis

### 07_Analyze_Bookmarks
Analyze bookmarks in a PBIP report with HTML output.
- **Parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `auto_open` (bool, default true): Open HTML in browser
  - `output_path` (str): Custom HTML output path

### 07_Analyze_Theme_Compliance
Analyze theme compliance in a PBIP report with HTML output.
- **Parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `theme_path` (str): Custom theme JSON path
  - `auto_open` (bool, default true): Open HTML in browser
  - `output_path` (str): Custom HTML output path

---

## CATEGORY 08: VISUALS & DOCS (2 tools)

### 08_Visual_Operations
Edit Power BI visual properties in PBIP files.
- **operation** (default 'list'): `list` | `update_position` | `replace_measure` | `sync_visual` | `sync_column_widths` | `update_visual_config`
- **Key parameters**:
  - `pbip_path` (str, required): Path to PBIP/Report folder
  - `page_name` / `visual_name` / `visual_type` / `display_title` (str): Filters
  - `x`, `y`, `width`, `height` (number): For update_position
  - `z` (int): Z-order for update_position
  - `source_entity`, `source_property`, `target_entity`, `target_property` (str): For replace_measure
  - `source_visual_name`, `source_page`, `target_pages` (str/array): For sync_visual
  - `sync_position` / `sync_children` (bool): Sync options
  - `config_type` / `property_name` / `property_value` (str): For update_visual_config
  - `config_updates` (array): Batch config changes
  - `dry_run` (bool, default false): Preview changes
  - `summary_only` (bool, default true): Compact output

### 08_Documentation_Word
Generate or update Word documentation report.
- **Parameters**:
  - `mode` (str, default 'generate'): 'generate' (new doc) | 'update' (detect changes)
  - `output_path` (str): Output Word file path
  - `input_path` (str): Existing doc path (required for mode='update')

---

## CATEGORY 09: DEBUG (10 tools)

### 09_Debug_Visual
Visual debugger - discover pages/visuals, show filter context, execute queries.
- **Parameters**:
  - `page_name` (str): Omit to list all pages
  - `visual_id` / `visual_name` (str): Omit to list all visuals on page
  - `measure_name` (str): Specific measure to query
  - `include_slicers` (bool, default true): Include slicer selections
  - `execute_query` (bool, default true): Execute query (false = filters only)
  - `filters` (array[str]): Manual DAX filter expressions
  - `skip_auto_filters` (bool, default false): Use only manual filters
  - `compact` (bool, default true): Compact output

### 09_Compare_Measures
Compare original vs optimized measure with the same filter context.
- **Parameters**:
  - `original_measure` (str, required): Original measure name (e.g., '[Total Sales]')
  - `optimized_expression` (str, required): Optimized DAX expression
  - `page_name` / `visual_id` / `visual_name` (str): Filter context source
  - `filters` (array[str]): Manual DAX filters
  - `include_slicers` (bool, default true)

### 09_Drill_To_Detail
Show underlying rows for an aggregated value using visual filter context.
- **Parameters**:
  - `page_name` / `visual_id` / `visual_name` (str): Filter context source
  - `fact_table` (str): Fact table to query (if visual not specified)
  - `limit` (int, default 100): Max rows
  - `include_slicers` (bool, default true)

### 09_Set_PBIP_Path
Manually set PBIP folder path for visual debugging if auto-detection failed.
- **Parameters**:
  - `pbip_path` (str, required): Full path to PBIP project folder

### 09_Get_Debug_Status
Get current debug capabilities status (PBIP and model connection).
- **Parameters**:
  - `compact` (bool, default true): Compact output

### 09_Analyze_Measure
Analyze measure DAX for anti-patterns and get fix suggestions.
- **Parameters**:
  - `measure_name` (str, required): Measure name
  - `table_name` (str): Table containing measure (optional, searches all)
  - `page_name` / `visual_id` / `visual_name` (str): Filter context
  - `include_slicers` (bool, default true)
  - `execute_measure` (bool, default true): Execute to see current value
  - `compact` (bool, default true)

### 09_Validate
Validation tests: cross_visual, expected_value, filter_permutation.
- **operation** (required): `cross_visual` | `expected_value` | `filter_permutation`
- **Parameters**:
  - `measure_name` (str): For cross_visual
  - `page_name` / `page_names` (str/array): Page context
  - `visual_id` / `visual_name` (str): Visual context
  - `expected_value` (number|str): For expected_value test
  - `filters` (array[str]): Additional DAX filters
  - `tolerance` (number, default 0.001): Numeric comparison tolerance
  - `max_permutations` (int, default 20): Max combinations for filter_permutation

### 09_Profile
Performance profiling.
- **operation** (default 'page'): `page` | `filter_matrix`
- **Parameters**:
  - `page_name` (str, required): Page to profile
  - `visual_id` / `visual_name` (str): For filter_matrix
  - `iterations` (int, default 3): Iterations per visual
  - `include_slicers` (bool, default true)
  - `filter_columns` (array[str]): Columns to vary (auto-detect if not set)
  - `max_combinations` (int, default 15): Max filter combinations

### 09_Document
Documentation generation from PBIP + live model.
- **operation** (required): `page` | `report` | `measure_lineage` | `filter_lineage`
- **Parameters**:
  - `page_name` (str): Required for page operation
  - `measure_name` (str): For measure_lineage
  - `lightweight` (bool, default true): Fast mode (skips DMV queries)
  - `include_ui_elements` (bool, default false): Include shapes/buttons

### 09_Advanced_Analysis
Advanced analysis operations.
- **operation** (required): `decompose` | `contribution` | `trend` | `root_cause` | `export`
- **Parameters**:
  - `page_name` (str): Required for decompose/contribution/trend/root_cause
  - `visual_id` / `visual_name` (str): Visual target
  - `dimension` (str): Dimension column for decompose/contribution
  - `date_column` (str): For trend analysis
  - `granularity` (str, default 'month'): day|week|month|quarter|year
  - `baseline_filters` / `comparison_filters` (array[str]): For root_cause
  - `dimensions` (array[str]): Dimensions for root_cause
  - `top_n` (int): Top results
  - `format` (str, default 'markdown'): For export

---

## SVG VISUAL GENERATION

### SVG_Visual_Operations
40+ DAX templates for KPIs, sparklines, gauges, data bars.
- **operation** (required): `list_templates` | `get_template` | `preview_template` | `generate_measure` | `inject_measure` | `list_categories` | `search_templates` | `validate_svg` | `create_custom`
- **Key parameters**:
  - `category` (str): 'kpi'|'sparklines'|'gauges'|'databars'|'advanced'
  - `complexity` (str): 'basic'|'intermediate'|'advanced'|'complex'
  - `template_id` (str): For get/preview/generate/inject
  - `parameters` (object): Template params (measure_name, value_measure, thresholds, colors)
  - `table_name` (str): Target table for inject_measure
  - `search_query` (str): For search_templates
  - `svg_code` (str): For validate_svg/create_custom
  - `dynamic_vars` (object): Variable name -> DAX expression for create_custom
  - `context_aware` (bool, default true): Use connected model for suggestions

---

## COMMON WORKFLOWS

### Model Health Check
1. `01_Detect_PBI_Instances`
2. `01_Connect_To_Instance`
3. `06_Full_Analysis` (scope='all', depth='balanced')
4. Review best practices violations
5. Address critical/high priority issues

### Measure Development
1. `02_Measure_Operations` (operation='list') - study existing measures
2. `05_DAX_Intelligence` (mode='all') - analyze DAX
3. `02_Measure_Operations` (operation='create') - create new measure
4. `04_Run_DAX` - test with real data
5. `05_Analyze_Dependencies` - verify dependencies

### Model Documentation
1. `06_Simple_Analysis` (mode='all') - get model overview
2. `08_Documentation_Word` - generate Word doc
3. `07_PBIP_Model_Analysis` (operation='analyze') - HTML report
4. `02_TMDL_Operations` (operation='export') - TMDL backup

### DAX Debugging
1. `09_Debug_Visual` - discover pages/visuals and filter context
2. `09_Analyze_Measure` - analyze anti-patterns
3. `05_DAX_Intelligence` (mode='all') - get optimization recommendations
4. AI writes optimized DAX based on recommendations
5. `09_Compare_Measures` - validate original vs optimized
6. `02_Measure_Operations` (operation='update') - save optimized version

### Model Comparison
1. Open both Power BI files in separate Desktop instances
2. `06_Compare_PBI_Models` (no parameters) - detect models
3. Identify OLD vs NEW from returned list
4. `06_Compare_PBI_Models` (old_port, new_port) - perform comparison

### Offline PBIP Analysis
1. `07_PBIP_Model_Analysis` (operation='analyze') - full offline analysis
2. `07_PBIP_Model_Analysis` (operation='validate_model') - TMDL linting
3. `07_PBIP_Query` (operation='query_unused') - find dead code
4. `07_PBIP_Dependency_Analysis` - interactive dependency browser
5. `07_Analyze_Aggregation` - aggregation optimization

---

## TIPS

- Always start with `01_Detect_PBI_Instances` then `01_Connect_To_Instance`
- Use `06_Simple_Analysis` for quick checks, `06_Full_Analysis` for thorough review
- Run `05_DAX_Intelligence` with mode='all' for complete analysis recommendations
- Always use dry_run=true first for find_replace and bulk_rename operations
- Check `05_Analyze_Dependencies` and `05_Get_Measure_Impact` before modifying/deleting measures
- PBIP tools (07_*) work offline without Power BI Desktop connection
- Debug tools (09_*) combine PBIP report layout with live model data
- Use `03_Batch_Operations` for bulk changes (3-5x faster than individual operations)
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
        sort_order=110
    )
    registry.register(tool)
    logger.info("Registered user guide handler")
