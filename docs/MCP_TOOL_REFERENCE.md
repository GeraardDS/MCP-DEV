# MCP-PowerBi-Finvision v7.1.0 — Complete Tool Reference

> **23 registered MCP tools** across 10 categories, providing 150+ operations for Power BI Desktop analysis, DAX debugging, TMDL editing, PBIP report authoring, and offline model analysis.

---

## Table of Contents

1. [01_Connection](#01_connection)
2. [02_Model_Operations](#02_model_operations)
3. [02_TMDL_Operations](#02_tmdl_operations)
4. [03_Batch_Operations](#03_batch_operations)
5. [04_Run_DAX](#04_run_dax)
6. [04_Query_Operations](#04_query_operations)
7. [05_DAX_Intelligence](#05_dax_intelligence)
8. [05_Column_Usage_Mapping](#05_column_usage_mapping)
9. [06_Analysis_Operations](#06_analysis_operations)
10. [07_Report_Operations](#07_report_operations)
11. [07_PBIP_Operations](#07_pbip_operations)
12. [07_Page_Operations](#07_page_operations)
13. [07_Visual_Operations](#07_visual_operations)
14. [07_Bookmark_Operations](#07_bookmark_operations)
15. [07_Theme_Operations](#07_theme_operations)
16. [08_Documentation_Word](#08_documentation_word)
17. [09_Debug_Operations](#09_debug_operations)
18. [09_Validate](#09_validate)
19. [09_Profile](#09_profile)
20. [09_Document](#09_document)
21. [10_Show_User_Guide](#10_show_user_guide)
22. [11_PBIP_Authoring](#11_pbip_authoring)
23. [11_PBIP_Prototype](#11_pbip_prototype)
24. [SVG_Visual_Operations](#svg_visual_operations)

---

## Tool Categories

| Category | Tools | Requires Live Connection |
|----------|-------|--------------------------|
| **Core** | 01_Connection, 10_Show_User_Guide | No |
| **Model** | 02_Model_Operations, 02_TMDL_Operations | Yes (Model Ops), No (TMDL) |
| **Batch** | 03_Batch_Operations | Yes |
| **Query** | 04_Run_DAX, 04_Query_Operations | Yes |
| **DAX** | 05_DAX_Intelligence, 05_Column_Usage_Mapping | Yes (partial offline) |
| **Analysis** | 06_Analysis_Operations | Yes |
| **PBIP** | 07_Report/PBIP/Page/Visual/Bookmark/Theme_Operations, SVG_Visual_Operations | No |
| **Docs** | 08_Documentation_Word | Yes |
| **Debug** | 09_Debug/Validate/Profile/Document | Yes |
| **Authoring** | 11_PBIP_Authoring, 11_PBIP_Prototype | No (Prototype needs live for data) |

---

## 01_Connection

**Category:** Core | **Requires:** Power BI Desktop running

Detect running Power BI Desktop instances and establish a connection.

### Operations

| Operation | Description |
|-----------|-------------|
| `detect` | Scan for running Power BI Desktop instances (default) |
| `connect` | Connect to a specific Power BI Desktop instance |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | `"detect"` \| `"connect"` | `"detect"` | Operation to perform |
| `model_index` | integer | 0 | Index of the model to connect to (connect only) |

### Usage Examples

```json
// Detect instances
{"operation": "detect"}

// Connect to first instance
{"operation": "connect", "model_index": 0}

// Connect to second instance
{"operation": "connect", "model_index": 1}
```

### Returns
- **detect**: List of running PBI instances with port, PID, file name
- **connect**: Connection status, database name, model details, PBIP folder path

---

## 02_Model_Operations

**Category:** Model | **Requires:** Live connection

Unified CRUD for tables, columns, measures, relationships, and calculation groups. Specify `object_type` + `operation`.

### Object Types and Operations

#### `table`
| Operation | Description |
|-----------|-------------|
| `list` | List all tables with row counts |
| `describe` | Detailed table info (columns, measures, relationships) |
| `sample_data` | Preview table data |
| `create` | Create a calculated table |
| `update` | Update table properties |
| `delete` | Delete a table |
| `refresh` | Refresh table data |
| `generate_calendar` | Generate a date/calendar table |

#### `column`
| Operation | Description |
|-----------|-------------|
| `list` | List columns for a table |
| `get` | Get column details |
| `statistics` | Column statistics (min, max, distinct, nulls) |
| `distribution` | Value distribution (top N) |
| `create` | Create a calculated column |
| `update` | Update column properties |
| `delete` | Delete a column |

#### `measure`
| Operation | Description |
|-----------|-------------|
| `list` | List measures (optionally filtered by table) |
| `get` | Get measure details (expression, format string) |
| `create` | Create a new measure |
| `update` | Update measure expression/properties |
| `delete` | Delete a measure |
| `rename` | Rename a measure |
| `move` | Move a measure to a different table |

#### `relationship`
| Operation | Description |
|-----------|-------------|
| `list` | List all relationships |
| `get` | Get relationship details |
| `find` | Find relationships for a table |
| `create` | Create a new relationship |
| `update` | Update relationship properties |
| `delete` | Delete a relationship |
| `activate` | Activate a relationship |
| `deactivate` | Deactivate a relationship |

#### `calculation_group`
| Operation | Description |
|-----------|-------------|
| `list` | List calculation groups |
| `create` | Create a calculation group with items |
| `delete` | Delete a calculation group |
| `list_items` | List items in a calculation group |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `object_type` | `"table"` \| `"column"` \| `"measure"` \| `"relationship"` \| `"calculation_group"` | — | **Required.** Object type |
| `operation` | string | — | Operation (varies by object_type) |
| `table_name` | string | — | Table name |
| `column_name` | string | — | Column name |
| `measure_name` | string | — | Measure name |
| `expression` | string | — | DAX expression |
| `format_string` | string | — | Format string (e.g., `"#,##0.00"`) |
| `display_folder` | string | — | Display folder path |
| `hidden` | boolean | — | Hide object |
| `description` | string | — | Object description |
| `new_name` | string | — | New name (rename/update) |
| `new_table` | string | — | Target table (measure move) |
| `max_rows` | integer | 10 | Max rows for sample_data (max 1000) |
| `columns` | string[] | — | Columns to include (sample_data) |
| `order_by` | string | — | Order by column (sample_data) |
| `order_direction` | `"asc"` \| `"desc"` | `"asc"` | Sort direction |
| `data_type` | `"String"` \| `"Int64"` \| `"Double"` \| `"Decimal"` \| `"Boolean"` \| `"DateTime"` \| `"Binary"` \| `"Variant"` | `"String"` | Column data type |
| `source_column` | string | — | Source column (data column create) |
| `from_table` | string | — | Source table (relationship) |
| `from_column` | string | — | Source column (relationship) |
| `to_table` | string | — | Target table (relationship) |
| `to_column` | string | — | Target column (relationship) |
| `from_cardinality` | `"One"` \| `"Many"` | `"Many"` | Source cardinality |
| `to_cardinality` | `"One"` \| `"Many"` | `"One"` | Target cardinality |
| `cross_filtering_behavior` | `"OneDirection"` \| `"BothDirections"` \| `"Automatic"` | `"OneDirection"` | Cross-filter direction |
| `is_active` | boolean | — | Active state |
| `start_year` | integer | current-5 | Calendar start year |
| `end_year` | integer | current+2 | Calendar end year |
| `include_fiscal` | boolean | false | Include fiscal year columns |
| `fiscal_start_month` | integer | 7 | Fiscal year start month (1-12) |
| `items` | array | — | Calculation items `[{name, expression, ordinal}]` |
| `precedence` | integer | — | Calculation group precedence |

### Usage Examples

```json
// List all tables
{"object_type": "table", "operation": "list"}

// Describe a table
{"object_type": "table", "operation": "describe", "table_name": "Sales"}

// Preview data
{"object_type": "table", "operation": "sample_data", "table_name": "Sales", "max_rows": 20}

// Create a measure
{"object_type": "measure", "operation": "create", "table_name": "Sales", "measure_name": "Total Sales", "expression": "SUM(Sales[Amount])", "format_string": "#,##0.00"}

// Create a relationship
{"object_type": "relationship", "operation": "create", "from_table": "Sales", "from_column": "ProductKey", "to_table": "Products", "to_column": "ProductKey"}
```

---

## 02_TMDL_Operations

**Category:** Model | **Requires:** TMDL files on disk (no live connection needed)

TMDL automation: export from live model, find/replace, bulk rename with reference updates, script generation, and measure migration between files.

### Operations

| Operation | Description |
|-----------|-------------|
| `export` | Export TMDL definition from connected model |
| `find_replace` | Find and replace text in TMDL files (regex supported) |
| `bulk_rename` | Bulk rename objects with automatic reference updates |
| `generate_script` | Generate TMDL script from a definition object |
| `migrate_measures` | Migrate measures between TMDL table files |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | — | **Required.** Operation to perform |
| `output_dir` | string | — | Output directory (export) |
| `tmdl_path` | string | — | TMDL export folder path |
| `pattern` | string | — | Find pattern |
| `replacement` | string | — | Replacement text |
| `regex` | boolean | false | Use regex patterns |
| `case_sensitive` | boolean | true | Case-sensitive matching |
| `dry_run` | boolean | true | Preview only (no changes) |
| `target` | string | `"all"` | Target objects filter |
| `renames` | array | — | `[{object_type, old_name, new_name, table_name?}]` |
| `update_references` | boolean | true | Update DAX references when renaming |
| `definition` | object | — | Object definition (generate_script) |
| `object_type` | `"table"` \| `"measure"` \| `"relationship"` \| `"calc_group"` | `"table"` | Object type (generate_script) |
| `source_path` | string | — | Source TMDL file (migrate) |
| `target_path` | string | — | Target TMDL file (migrate) |
| `display_folder_filter` | string | — | Folder prefix filter (migrate) |
| `replace_target` | boolean | false | Replace target entirely |
| `skip_duplicates` | boolean | true | Skip existing measures |

### Usage Examples

```json
// Export TMDL
{"operation": "export", "output_dir": "C:/export/model"}

// Find and replace (dry run)
{"operation": "find_replace", "tmdl_path": "C:/project/model.SemanticModel", "pattern": "OldTable", "replacement": "NewTable", "dry_run": true}

// Bulk rename with reference updates
{"operation": "bulk_rename", "tmdl_path": "C:/project/model.SemanticModel", "renames": [{"old_name": "Total Sales", "new_name": "Revenue", "object_type": "measure", "table_name": "Sales"}], "dry_run": false}
```

---

## 03_Batch_Operations

**Category:** Batch | **Requires:** Live connection

Execute batch operations on model objects with ACID transaction support. 3-5x faster than individual operations.

### Operations

| Object Type | Batch Operations |
|-------------|-----------------|
| `measures` | create, update, delete, rename, move |
| `tables` | create, update, delete, refresh |
| `columns` | create, update, delete |
| `relationships` | create, update, delete, activate, deactivate |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | `"measures"` \| `"tables"` \| `"columns"` \| `"relationships"` | — | **Required.** Object type |
| `batch_operation` | `"create"` \| `"update"` \| `"delete"` \| `"rename"` \| `"move"` \| `"activate"` \| `"deactivate"` \| `"refresh"` | — | **Required.** Batch operation |
| `items` | array | — | **Required.** List of object definitions (min 1) |
| `options.use_transaction` | boolean | true | Atomic all-or-nothing execution |
| `options.continue_on_error` | boolean | false | Continue on error (only if use_transaction=false) |
| `options.dry_run` | boolean | false | Validate without executing |

### Usage Examples

```json
// Batch create measures
{
  "operation": "measures",
  "batch_operation": "create",
  "items": [
    {"table_name": "Sales", "measure_name": "Total Sales", "expression": "SUM(Sales[Amount])"},
    {"table_name": "Sales", "measure_name": "Avg Price", "expression": "AVERAGE(Sales[Price])"}
  ],
  "options": {"use_transaction": true}
}

// Batch rename with dry run
{
  "operation": "measures",
  "batch_operation": "rename",
  "items": [
    {"table_name": "Sales", "measure_name": "Total Sales", "new_name": "Revenue"}
  ],
  "options": {"dry_run": true}
}
```

---

## 04_Run_DAX

**Category:** Query | **Requires:** Live connection

Execute DAX queries with automatic row limits and optional SE/FE trace analysis.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | — | **Required.** DAX query (EVALUATE statement) |
| `top_n` | integer | 100 | Maximum rows to return |
| `mode` | `"auto"` \| `"simple"` \| `"analyze"` \| `"trace"` | `"auto"` | Execution mode |
| `clear_cache` | boolean | true | Clear VertiPaq cache before execution (trace mode only) |

### Execution Modes

| Mode | Description |
|------|-------------|
| `auto` / `simple` | Execute and return preview results |
| `analyze` | Multi-run benchmark with timing statistics |
| `trace` | SE/FE timing analysis with query events |

### Usage Examples

```json
// Simple query
{"query": "EVALUATE SUMMARIZECOLUMNS('Date'[Year], \"Total\", [Total Sales])"}

// With trace analysis
{"query": "EVALUATE SUMMARIZECOLUMNS('Date'[Year], \"Total\", [Total Sales])", "mode": "trace", "clear_cache": true}

// Large result set
{"query": "EVALUATE Sales", "top_n": 500}
```

---

## 04_Query_Operations

**Category:** Query | **Requires:** Live connection

Query model metadata: data sources, M expressions, object search, RLS roles and testing, text search.

### Operations

| Operation | Description |
|-----------|-------------|
| `data_sources` | List all data sources |
| `m_expressions` | List M/Power Query expressions |
| `search_objects` | Search for tables, columns, measures by pattern |
| `roles` | List RLS/OLS security roles |
| `test_rls` | Test RLS role filter (compare with/without) |
| `search_string` | Search text in object names and DAX expressions |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | — | **Required.** Operation |
| `pattern` | string | — | Search pattern (search_objects) |
| `types` | `["tables", "columns", "measures"]` | all | Object types to search |
| `role_name` | string | — | RLS role name (test_rls) |
| `test_query` | string | — | DAX query to test with RLS |
| `test_table` | string | — | Table for auto-generated count query |
| `search_text` | string | — | Text to search for (search_string) |
| `search_in_expression` | boolean | true | Search in DAX expressions |
| `search_in_name` | boolean | true | Search in object names |
| `limit` | integer | — | Max results (m_expressions) |

### Usage Examples

```json
// List data sources
{"operation": "data_sources"}

// Search for objects
{"operation": "search_objects", "pattern": "Sales", "types": ["tables", "measures"]}

// Test RLS
{"operation": "test_rls", "role_name": "RegionalManager", "test_table": "Sales"}

// Search in DAX expressions
{"operation": "search_string", "search_text": "CALCULATE", "search_in_expression": true, "search_in_name": false}
```

---

## 05_DAX_Intelligence

**Category:** DAX | **Requires:** Live connection (for dependency/impact ops)

DAX analysis engine: context transitions, anti-patterns, optimization suggestions, dependency trees, impact analysis, and CSV export.

### Modes

| Mode | Description |
|------|-------------|
| `all` | Full analysis (default) |
| `analyze` | Pattern analysis and anti-pattern detection |
| `debug` | Debug with breakpoints |
| `report` | Formatted report output |

### Dependency Operations

When `operation` is set, `analysis_mode` is ignored:

| Operation | Description |
|-----------|-------------|
| `dependencies` | Dependency graph for a measure/table |
| `impact` | Impact analysis (what breaks if I change X?) |
| `export` | Export dependency graph to CSV |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | string | — | DAX expression OR measure name (auto-detects) |
| `analysis_mode` | `"all"` \| `"analyze"` \| `"debug"` \| `"report"` | `"all"` | Analysis mode |
| `skip_validation` | boolean | false | Skip validation step |
| `output_format` | `"friendly"` \| `"steps"` | `"friendly"` | Output format |
| `include_optimization` | boolean | true | Include optimization suggestions |
| `include_profiling` | boolean | true | Include profiling data |
| `breakpoints` | integer[] | — | Character positions for debugging |
| `operation` | `"dependencies"` \| `"impact"` \| `"export"` | — | Dependency operation |
| `table` | string | — | Table name (dependency/impact) |
| `measure` | string | — | Measure name (dependency/impact) |
| `include_diagram` | boolean | true | Include Mermaid diagram |
| `output_path` | string | — | CSV output path (export) |

### Usage Examples

```json
// Analyze a DAX expression
{"expression": "CALCULATE(SUM(Sales[Amount]), FILTER(ALL(Date), Date[Year] = 2024))"}

// Get dependencies for a measure
{"operation": "dependencies", "measure": "Total Sales", "include_diagram": true}

// Impact analysis
{"operation": "impact", "table": "Sales", "measure": "Total Sales"}

// Export to CSV
{"operation": "export", "output_path": "C:/export/dependencies.csv"}
```

---

## 05_Column_Usage_Mapping

**Category:** DAX | **Requires:** Live connection (partial offline with PBIP)

Bidirectional column-measure mapping. Find unused columns, trace measure dependencies, export to CSV.

### Operations

| Operation | Description |
|-----------|-------------|
| `get_unused_columns` | Find unused columns (live model) |
| `get_unused_columns_pbip` | Find unused columns (offline, multi-report support) |
| `get_measures_for_tables` | Get measures using columns from specified tables |
| `get_columns_for_measure` | Get columns used by a specific measure |
| `get_measures_for_column` | Get measures using a specific column |
| `get_full_mapping` | Complete bidirectional mapping |
| `export_to_csv` | Export mapping to CSV files |
| `export_measures` | Export all DAX measures to CSV |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | `"get_unused_columns"` | Operation |
| `pbip_path` | string | — | PBIP path (offline ops) |
| `report_paths` | string[] | — | Multiple report folders |
| `tables` | string[] | — | Table name filter |
| `table` | string | — | Single table filter |
| `measure` | string | — | Measure name |
| `column` | string | — | Column name |
| `group_by` | `"table"` \| `"column"` \| `"measure"` \| `"flat"` | `"flat"` | Grouping |
| `output_path` | string | `"exports/"` | CSV output directory |
| `include_dax` | boolean | false | Include DAX expressions in output |
| `force_refresh` | boolean | false | Force cache refresh |

### Usage Examples

```json
// Find unused columns
{"operation": "get_unused_columns"}

// Find unused columns across multiple reports (offline)
{"operation": "get_unused_columns_pbip", "pbip_path": "C:/project/Model.SemanticModel", "report_paths": ["C:/project/Report1.Report", "C:/project/Report2.Report"]}

// What columns does a measure use?
{"operation": "get_columns_for_measure", "measure": "Total Sales"}

// Export measures to CSV
{"operation": "export_measures", "output_path": "C:/export", "include_dax": true}
```

---

## 06_Analysis_Operations

**Category:** Analysis | **Requires:** Live connection

Model analysis: quick overview, full BPA analysis, and model comparison.

### Operations

| Operation | Description | Duration |
|-----------|-------------|----------|
| `simple` | Quick analysis (8 modes + insights) | 2-5s |
| `full` | Complete BPA + performance analysis | 10-180s |
| `compare` | Compare two open models | 5-30s |

### Simple Analysis Modes

| Mode | Description |
|------|-------------|
| `all` | All modes combined |
| `tables` | Table overview |
| `stats` | Model statistics |
| `measures` | Measure listing |
| `measure` | Specific measure detail |
| `columns` | Column overview |
| `relationships` | Relationship analysis |
| `roles` | RLS/OLS roles |
| `database` | Database info |
| `calculation_groups` | Calculation group listing |
| `storage` | Storage/VertiPaq info |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | `"simple"` \| `"full"` \| `"compare"` | `"simple"` | Operation |
| `mode` | enum (see above) | `"all"` | Simple analysis mode |
| `table` | string | — | Table filter |
| `measure_name` | string | — | Required for mode=measure |
| `scope` | `"all"` \| `"best_practices"` \| `"performance"` \| `"integrity"` | `"all"` | Full analysis scope |
| `depth` | `"fast"` \| `"balanced"` \| `"deep"` | `"balanced"` | Analysis depth |
| `include_bpa` | boolean | true | Include Best Practice Analyzer |
| `include_performance` | boolean | true | Include performance analysis |
| `include_integrity` | boolean | true | Include integrity checks |
| `max_seconds` | integer | — | Timeout (5-300s) |
| `old_port` | integer | — | Port of OLD model (compare) |
| `new_port` | integer | — | Port of NEW model (compare) |

### Usage Examples

```json
// Quick overview
{"operation": "simple", "mode": "all"}

// Measure detail
{"operation": "simple", "mode": "measure", "measure_name": "Total Sales"}

// Full BPA analysis
{"operation": "full", "scope": "best_practices", "depth": "deep"}

// Compare two models
{"operation": "compare", "old_port": 52345, "new_port": 52678}
```

---

## 07_Report_Operations

**Category:** PBIP | **Requires:** PBIP files on disk

Report-level operations: structure info, measure usage tracking, rename, rebind, backup/restore, schema discovery, extension measures.

### Operations

| Operation | Description |
|-----------|-------------|
| `info` | Get report structure (pages, visuals, filters) |
| `measure_usage` | Find which measures are used on which pages |
| `rename` | Rename a report |
| `rebind` | Rebind report to a different semantic model |
| `backup` | Create a timestamped backup |
| `restore` | Restore from a backup |
| `discover_schema` | Discover visual type property schemas |
| `manage_extension_measures` | CRUD for extension measures (list/add/update/delete) |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pbip_path` | string | — | **Required.** PBIP project or .Report folder |
| `operation` | enum | `"info"` | Operation |
| `include_visuals` | boolean | true | Include visual details (info) |
| `include_filters` | boolean | true | Include filter details (info) |
| `page_name` | string | — | Filter by page name |
| `summary_only` | boolean | true | Summary vs full detail |
| `measure_filter` | string | — | Filter by measure name |
| `output_format` | `"text"` \| `"json"` | `"text"` | Output format |
| `export_path` | string | — | CSV export directory |
| `new_name` | string | — | New report name (rename) |
| `model_path` | string | — | Semantic model path (rebind) |
| `model_id` | string | — | Semantic model GUID (rebind) |
| `message` | string | — | Backup message |
| `backup_path` | string | — | Backup path (restore) |
| `visual_type` | string | — | Visual type (discover_schema) |
| `sub_operation` | `"list"` \| `"add"` \| `"update"` \| `"delete"` | — | Extension measure sub-op |
| `measure_name` | string | — | Extension measure name |
| `expression` | string | — | DAX expression |
| `table_ref` | string | — | Table reference |
| `data_type` | string | `"double"` | Data type |
| `format_string` | string | — | Format string |
| `description` | string | — | Description |

### Usage Examples

```json
// Get report info
{"pbip_path": "C:/project/Report.Report", "operation": "info"}

// Find measure usage
{"pbip_path": "C:/project/Report.Report", "operation": "measure_usage"}

// Backup report
{"pbip_path": "C:/project/Report.Report", "operation": "backup", "message": "Before refactor"}

// Add extension measure
{"pbip_path": "C:/project/Report.Report", "operation": "manage_extension_measures", "sub_operation": "add", "measure_name": "Running Total", "expression": "CALCULATE([Total], FILTER(ALL(Date), Date[Date] <= MAX(Date[Date])))", "table_ref": "Sales"}
```

---

## 07_PBIP_Operations

**Category:** PBIP | **Requires:** PBIP files on disk (no live connection)

Offline PBIP analysis: model validation, comparison, documentation, dependency analysis, unused object detection, broken reference scanning, git diff analysis.

### Operations

| Operation | Description |
|-----------|-------------|
| `analyze` | Full analysis with HTML report |
| `validate_model` | TMDL validation |
| `compare_models` | Compare two PBIP models offline |
| `generate_documentation` | Generate Markdown documentation |
| `query_dependencies` | Dependency graph queries |
| `query_measures` | List/search measures with filtering |
| `query_relationships` | Relationship quality analysis |
| `query_unused` | Find unused measures/columns |
| `scan_broken_refs` | Scan for broken field references in visuals |
| `git_diff` | Git change analysis for TMDL files |
| `dependency_html` | Interactive HTML dependency diagram |
| `aggregation_analysis` | Aggregation table analysis |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | — | **Required.** Operation |
| `pbip_path` | string | — | PBIP path / .SemanticModel folder |
| `output_path` | string | — | Output path |
| `source_path` | string | — | Source PBIP (compare_models) |
| `target_path` | string | — | Target PBIP (compare_models) |
| `object_name` | string | — | Object name (query_dependencies, e.g. `[Total Sales]`) |
| `direction` | `"forward"` \| `"reverse"` \| `"both"` | — | Dependency direction |
| `table` | string | — | Table filter (query_measures) |
| `display_folder` | string | — | Display folder filter |
| `pattern` | string | — | Name regex (query_measures) |
| `expression_search` | string | — | DAX expression regex |
| `main_item` | string | — | Initial selected item (dependency_html) |
| `auto_open` | boolean | — | Auto-open HTML in browser |
| `output_format` | `"summary"` \| `"detailed"` \| `"html"` \| `"json"` | — | Report format (aggregation) |
| `include_visual_details` | boolean | — | Per-visual details (aggregation) |
| `page_filter` | string | — | Page name filter (aggregation) |

### Usage Examples

```json
// Full analysis
{"operation": "analyze", "pbip_path": "C:/project/Model.SemanticModel"}

// Find unused objects
{"operation": "query_unused", "pbip_path": "C:/project/Model.SemanticModel"}

// Search measures by expression
{"operation": "query_measures", "pbip_path": "C:/project/Model.SemanticModel", "expression_search": "CALCULATE"}

// Interactive dependency diagram
{"operation": "dependency_html", "pbip_path": "C:/project/Model.SemanticModel", "auto_open": true}

// Scan broken references
{"operation": "scan_broken_refs", "pbip_path": "C:/project/Report.Report"}
```

---

## 07_Page_Operations

**Category:** PBIP | **Requires:** PBIP files on disk

Page CRUD, display settings, drillthrough/tooltip configuration, visual interactions, and filter management.

### Operations

| Group | Operations |
|-------|-----------|
| **CRUD** | `list`, `create`, `clone`, `delete`, `reorder` |
| **Display** | `resize`, `set_display`, `set_background`, `set_wallpaper`, `hide`, `show` |
| **Special Pages** | `set_drillthrough`, `set_tooltip` |
| **Interactions** | `set_interaction`, `bulk_set_interactions`, `list_interactions` |
| **Filters** | `list_filters`, `add_filter`, `set_filter`, `clear_filters`, `hide_filter`, `unhide_filter`, `lock_filter`, `unlock_filter` |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pbip_path` | string | — | **Required.** PBIP/Report folder |
| `operation` | enum | `"list"` | Operation |
| `page_name` | string | — | Page display name or ID |
| `page_id` | string | — | Page ID (alternative) |
| `width` | integer | — | Page width in pixels |
| `height` | integer | — | Page height in pixels |
| `insert_after` | string | — | Insert after page ID |
| `source_page` | string | — | Source page (clone) |
| `new_display_name` | string | — | New display name |
| `page_order` | string[] | — | Ordered page IDs/names (reorder) |
| `display_option` | `"FitToPage"` \| `"FitToWidth"` \| `"ActualSize"` | — | Display option |
| `color` | string | — | Hex color (e.g. `#E6E6E6`) |
| `transparency` | number | — | Transparency 0-100 |
| `table` | string | — | Table name (drillthrough filter) |
| `field` | string | — | Field name (drillthrough/filter) |
| `clear` | boolean | — | Clear drillthrough filters |
| `dry_run` | boolean | false | Preview only |
| `source_visual` | string | — | Source visual (interactions) |
| `target_visual` | string | — | Target visual (interactions) |
| `interaction_type` | `"NoFilter"` \| `"Filter"` \| `"Highlight"` | — | Interaction type |
| `interactions` | array | — | Bulk `[{source, target, type}]` |
| `level` | `"report"` \| `"page"` \| `"visual"` \| `"all"` | `"all"` | Filter scope level |
| `visual_name` | string | — | Visual name (filter visual level) |
| `filter_name` | string | — | Filter name/ID |
| `filter_type` | `"Categorical"` \| `"Advanced"` \| `"TopN"` \| `"RelativeDate"` | `"Categorical"` | Filter type |
| `values` | string[] | — | Filter values |
| `operator` | string | — | Advanced operator |
| `top_n` | integer | — | TopN count |
| `top_direction` | `"Top"` \| `"Bottom"` | — | TopN direction |

### Usage Examples

```json
// List pages
{"pbip_path": "C:/project/Report.Report", "operation": "list"}

// Create a page
{"pbip_path": "C:/project/Report.Report", "operation": "create", "page_name": "Sales Overview", "width": 1920, "height": 1080}

// Clone a page
{"pbip_path": "C:/project/Report.Report", "operation": "clone", "source_page": "Sales Overview", "new_display_name": "Sales Overview Copy"}

// Add a page filter
{"pbip_path": "C:/project/Report.Report", "operation": "add_filter", "page_name": "Sales Overview", "table": "Date", "field": "Year", "values": ["2024"], "level": "page"}

// Set visual interaction
{"pbip_path": "C:/project/Report.Report", "operation": "set_interaction", "page_name": "Sales Overview", "source_visual": "slicer1", "target_visual": "chart1", "interaction_type": "Filter"}
```

---

## 07_Visual_Operations

**Category:** PBIP | **Requires:** PBIP files on disk

Visual CRUD, positioning, formatting, field binding, sorting, actions, code injection, slicer configuration, visual calculations, templates, measure replacement, and cross-visual sync.

### Operations

| Group | Operations |
|-------|-----------|
| **CRUD** | `list`, `create`, `create_group`, `delete` |
| **Layout** | `update_position`, `align` |
| **Config** | `update_visual_config`, `update_formatting` |
| **Data** | `add_field`, `remove_field`, `set_sort`, `replace_measure` |
| **Actions** | `set_action` |
| **Code** | `inject_code` (Deneb/Python/R) |
| **Visual Calcs** | `manage_visual_calcs` (list/add/update/delete) |
| **Slicers** | `configure_slicer` |
| **Templates** | `list_templates`, `get_template` |
| **Sync** | `sync_visual`, `sync_column_widths`, `sync_formatting` |

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `pbip_path` | string | **Required.** PBIP/Report folder |
| `operation` | enum | Operation (default: `list`) |
| `page_name` | string | Page filter |
| `visual_name` | string | Visual ID filter |
| `display_title` | string | Filter by visual title |
| `visual_type` | string | Visual type (e.g., `columnChart`, `card`, `table`) |
| `x`, `y`, `width`, `height`, `z` | number | Position/size |
| `position` | object | `{x, y, width, height, z}` |
| `title` | string | Visual title (create) |
| `measures` | array | `[{table, measure, bucket?, display_name?}]` |
| `columns` | array | `[{table, column, bucket?, display_name?}]` |
| `config_type` | string | Config object to modify |
| `property_name` | string | Property to update |
| `property_value` | string/number/boolean | Property value |
| `config_updates` | array | Batch config changes |
| `formatting_target` | enum | `title`, `subtitle`, `background`, `border`, etc. |
| `formatting_properties` | object | `{show, text, fontSize, fontColor, ...}` |
| `table`, `field`, `bucket` | string | Field binding params |
| `field_type` | `"Column"` \| `"Measure"` | Field type |
| `sort_field`, `sort_direction` | string | Sort config |
| `action_type` | enum | `PageNavigation`, `Bookmark`, `WebUrl`, etc. |
| `code_type` | `"deneb"` \| `"python"` \| `"r"` | Code injection type |
| `code` | string | Code/spec content |
| `provider` | `"vega"` \| `"vegaLite"` | Deneb provider |
| `alignment` | enum | `left`, `right`, `top`, `bottom`, `center_h`, `center_v` |
| `source_visual_name`, `source_page` | string | Sync source |
| `dry_run` | boolean | Preview only |

### Usage Examples

```json
// List visuals on a page
{"pbip_path": "C:/project/Report.Report", "operation": "list", "page_name": "Sales Overview"}

// Create a column chart
{"pbip_path": "C:/project/Report.Report", "operation": "create", "page_name": "Sales Overview", "visual_type": "columnChart", "title": "Monthly Sales", "position": {"x": 100, "y": 100, "width": 600, "height": 400}, "measures": [{"table": "Sales", "measure": "Total Sales", "bucket": "Values"}], "columns": [{"table": "Date", "column": "Month", "bucket": "Category"}]}

// Update formatting
{"pbip_path": "C:/project/Report.Report", "operation": "update_formatting", "page_name": "Sales Overview", "visual_name": "abc123", "formatting_target": "title", "formatting_properties": {"show": true, "text": "Revenue by Month", "fontSize": 14, "fontColor": "#333333"}}

// Inject Deneb spec
{"pbip_path": "C:/project/Report.Report", "operation": "inject_code", "page_name": "Sales Overview", "visual_name": "abc123", "code_type": "deneb", "provider": "vegaLite", "code": "{\"mark\": \"bar\", ...}"}

// Sync formatting across visuals
{"pbip_path": "C:/project/Report.Report", "operation": "sync_formatting", "source_visual_name": "abc123", "source_page": "Sales Overview", "target_visual_name": "def456", "target_page": "Sales Detail"}
```

---

## 07_Bookmark_Operations

**Category:** PBIP | **Requires:** PBIP files on disk

Bookmark CRUD, capture settings, affected visuals, and HTML analysis.

### Operations

| Operation | Description |
|-----------|-------------|
| `list` | List all bookmarks |
| `create` | Create a new bookmark |
| `rename` | Rename a bookmark |
| `delete` | Delete a bookmark |
| `set_capture` | Configure capture settings (data/display/page) |
| `set_affected_visuals` | Set which visuals are affected |
| `analyze` | Generate HTML bookmark analysis |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pbip_path` | string | — | **Required.** PBIP/Report folder |
| `operation` | enum | `"list"` | Operation |
| `bookmark_id` | string | — | Bookmark ID or display name |
| `display_name` | string | — | Display name (create/rename) |
| `new_name` | string | — | New name (rename) |
| `page_name` | string | — | Target page (create) |
| `capture_data` | boolean | — | Capture data state |
| `capture_display` | boolean | — | Capture display state |
| `capture_current_page` | boolean | — | Capture current page |
| `visual_ids` | string[] | — | Affected visual IDs |
| `all_visuals` | boolean | — | Affect all visuals |
| `auto_open` | boolean | true | Auto-open HTML (analyze) |
| `output_path` | string | — | HTML output path (analyze) |

---

## 07_Theme_Operations

**Category:** PBIP | **Requires:** PBIP files on disk

Theme management and conditional formatting: compliance analysis, color management, formatting defaults, font settings, text classes, CF rule CRUD.

### Operations

| Operation | Description |
|-----------|-------------|
| `analyze_compliance` | Theme compliance analysis (HTML report) |
| `get_theme` | Load and display current theme |
| `set_colors` | Set theme colors |
| `set_formatting` | Set formatting defaults for visual types |
| `push_visual` | Push visual formatting to theme |
| `list_text_classes` | List text classes |
| `set_font` | Set font properties for a text class |
| `list_cf` | List conditional formatting rules |
| `add_cf` | Add a CF rule |
| `remove_cf` | Remove a CF rule |
| `copy_cf` | Copy CF rules between visuals |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pbip_path` | string | — | **Required.** PBIP/Report folder |
| `operation` | enum | `"get_theme"` | Operation |
| `theme_path` | string | — | Custom theme JSON path |
| `colors` | object | — | `{dataColors, background, foreground, good, bad, ...}` |
| `visual_type_target` | string | — | Visual type for formatting defaults |
| `formatting` | object | — | Formatting properties |
| `page_name` | string | — | Page name |
| `visual_name` | string | — | Visual name |
| `text_class` | string | — | Text class name |
| `font_family` | string | — | Font family |
| `font_size` | number | — | Font size |
| `color` | string | — | Hex color |
| `bold` | boolean | — | Bold |
| `container` | string | — | CF container (e.g., `dataPoint`) |
| `property_name` | string | — | CF property (e.g., `fill`) |
| `rule_type` | `"color_scale"` \| `"rules"` \| `"data_bars"` \| `"icons"` | — | CF rule type |
| `cf_config` | object | — | CF rule config |
| `source_page/visual`, `target_page/visual` | string | — | Copy CF source/target |
| `dry_run` | boolean | false | Preview only |

---

## 08_Documentation_Word

**Category:** Docs | **Requires:** Live connection

Generate or update Word (.docx) documentation for the connected model.

### Operations

| Operation | Description |
|-----------|-------------|
| `generate` | Generate new Word documentation |
| `update` | Update existing Word documentation |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | `"generate"` \| `"update"` | — | Operation mode |
| `output_path` | string | — | Output Word file path |
| `input_path` | string | — | Existing doc path (required for update) |

---

## 09_Debug_Operations

**Category:** Debug | **Requires:** Live connection + PBIP path

Visual debugger with SE/FE trace analysis, measure comparison, drill-to-detail, DAX analysis, variable debugging, optimization suggestions, and page audit.

### Operations

| Operation | Description |
|-----------|-------------|
| `visual` | Debug a visual (discover filters, execute query, SE/FE trace) |
| `compare` | Compare original vs optimized measure |
| `drill` | Drill to detail data |
| `analyze` | Analyze a DAX expression |
| `debug_variable` | Debug a specific variable in a measure |
| `step_variables` | Step through all variables in a measure |
| `run_dax` | Run raw DAX with debug context |
| `optimize` | Performance optimization suggestions based on trace data |
| `audit` | Audit all visuals on page(s) |
| `set_path` | Set PBIP path context |
| `status` | Get current debug status |

### Key Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | `"visual"` | **Required.** Operation |
| `page_name` | string | — | Page name |
| `visual_id` / `visual_name` | string | — | Visual identifier |
| `measure_name` | string | — | Measure to debug |
| `measures` | string[] | — | Explicit measure names (overrides auto-discovery) |
| `pbip_path` | string | — | PBIP folder path (set_path) |
| `query` | string | — | Raw DAX query (run_dax) |
| `execute_query` | boolean | — | Execute and return rows (visual) |
| `trace` | boolean | false | Run SE/FE trace analysis |
| `clear_cache` | boolean | true | Clear VertiPaq cache before trace |
| `filters` | string[] | — | Manual DAX filters |
| `skip_auto_filters` | boolean | — | Skip auto-discovered filters |
| `include_slicers` | boolean | — | Include slicer context |
| `compact` | boolean | — | Compact output |
| `original_measure` | string | — | Original measure (compare) |
| `optimized_expression` | string | — | Optimized DAX (compare) |
| `fact_table` | string | — | Fact table (drill) |
| `limit` | integer | 100 | Max rows (drill) |
| `variable_name` | string | — | Variable name (debug_variable) |
| `max_rows` | integer | 100 | Max rows (debug_variable/step_variables) |
| `total_ms`, `fe_ms`, `se_ms`, `fe_pct`, `se_queries` | number | — | Trace metrics (optimize, required) |
| `se_events` | array | — | SE event list (optimize, for deep analysis) |
| `cache_comparison` | boolean | false | Cold+warm cache comparison (optimize) |
| `per_measure_trace` | boolean | false | Per-measure traces (optimize, slow) |
| `pages` | string[] | — | Pages to audit (default: all) |
| `include_data` | boolean | false | Include row data in audit |
| `skip_types` | string[] | — | Additional visual types to skip (audit) |

### Usage Examples

```json
// Debug a visual with trace
{"operation": "visual", "page_name": "Sales Overview", "visual_name": "chart1", "trace": true, "execute_query": true}

// Audit all pages
{"operation": "audit", "include_data": false}

// Step through measure variables
{"operation": "step_variables", "measure_name": "Total Sales", "page_name": "Sales Overview", "visual_name": "chart1"}

// Optimize based on trace data
{"operation": "optimize", "measure_name": "Total Sales", "total_ms": 2500, "fe_ms": 2100, "se_ms": 400, "fe_pct": 84, "se_queries": 12}
```

---

## 09_Validate

**Category:** Debug | **Requires:** Live connection

Cross-visual validation, expected value testing, and filter permutation analysis.

### Operations

| Operation | Description |
|-----------|-------------|
| `cross_visual` | Validate measure consistency across visuals/pages |
| `expected_value` | Validate a measure returns an expected value |
| `filter_permutation` | Test measure under different filter combinations |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | — | **Required.** Operation |
| `measure_name` | string | — | Measure to validate |
| `page_name` / `page_names` | string/array | — | Page(s) to validate |
| `visual_id` / `visual_name` | string | — | Visual identifier |
| `expected_value` | number/string | — | Expected result |
| `filters` | string[] | — | DAX filters |
| `tolerance` | number | — | Numeric tolerance |
| `max_permutations` | integer | — | Max filter combinations |

---

## 09_Profile

**Category:** Debug | **Requires:** Live connection

Performance profiling, filter matrix analysis, measure decomposition, contribution and trend analysis, root cause analysis.

### Operations

| Operation | Description |
|-----------|-------------|
| `page` | Page performance profiling |
| `filter_matrix` | Filter matrix analysis |
| `decompose` | Measure decomposition by dimensions |
| `contribution` | Contribution analysis |
| `trend` | Trend analysis over time |
| `root_cause` | Root cause analysis |
| `export` | Export profiling results |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | — | **Required.** Operation |
| `page_name` | string | — | Page name |
| `visual_id` / `visual_name` | string | — | Visual identifier |
| `iterations` | integer | — | Benchmark iterations |
| `include_slicers` | boolean | — | Include slicer context |
| `filter_columns` | string[] | — | Filter columns |
| `max_combinations` | integer | — | Max filter combinations |
| `dimension` / `dimensions` | string/array | — | Decomposition dimensions |
| `date_column` | string | — | Date column (trend) |
| `granularity` | `"day"` \| `"week"` \| `"month"` \| `"quarter"` \| `"year"` | — | Time granularity |
| `baseline_filters` / `comparison_filters` | string[] | — | Comparison filters (root_cause) |
| `top_n` | integer | — | Top N results |
| `format` | `"markdown"` \| `"json"` | — | Output format |

---

## 09_Document

**Category:** Debug | **Requires:** Live connection

Documentation generation: page documentation, report documentation, measure lineage, filter lineage.

### Operations

| Operation | Description |
|-----------|-------------|
| `page` | Document a specific page (visuals, measures, filters) |
| `report` | Document the entire report |
| `measure_lineage` | Trace measure lineage (dependencies + dependents) |
| `filter_lineage` | Trace filter lineage across pages/visuals |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | enum | — | **Required.** Operation |
| `page_name` | string | — | Page name |
| `measure_name` | string | — | Measure name (lineage) |
| `lightweight` | boolean | — | Lightweight output |
| `include_ui_elements` | boolean | — | Include UI-only elements |

---

## 10_Show_User_Guide

**Category:** Core | **Requires:** Nothing

Display the comprehensive user guide with all tools, operations, parameters, and workflows.

### Parameters

None.

---

## 11_PBIP_Authoring

**Category:** Authoring | **Requires:** PBIP files on disk

Create, clone, and delete pages/visuals in PBIP reports. Includes visual templates.

### Operations

| Operation | Description |
|-----------|-------------|
| `clone_page` | Clone a page with all visuals |
| `clone_report` | Clone an entire report |
| `create_page` | Create an empty page |
| `create_visual` | Create a visual from template |
| `create_visual_group` | Create a visual group |
| `delete_page` | Delete a page |
| `delete_visual` | Delete a visual |
| `list_templates` | List available visual templates |
| `get_template` | Get template structure |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pbip_path` | string | — | **Required.** PBIP/Report folder |
| `operation` | string | — | **Required.** Operation |
| `source_page` | string | — | Source page (clone_page) |
| `new_display_name` | string | — | New display name |
| `target_path` | string | — | Target path (clone_report) |
| `new_report_name` | string | — | New report name |
| `page_name` | string | — | Page name |
| `page_id` | string | — | Page ID |
| `width` | integer | 1280 | Page width |
| `height` | integer | 720 | Page height |
| `insert_after` | string | — | Insert after page ID |
| `visual_type` | string | — | Visual type |
| `visual_id` / `visual_name` | string | — | Visual identifier (delete) |
| `title` | string | — | Visual title |
| `position` | object | — | `{x, y, width, height, z}` |
| `measures` | array | — | `[{table, measure, bucket?, display_name?}]` |
| `columns` | array | — | `[{table, column, bucket?, display_name?}]` |
| `parent_group` | string | — | Parent group ID |
| `group_name` | string | — | Group display name |
| `formatting` | array | — | `[{config_type, property_name, value}]` |
| `delete_children` | boolean | true | Delete group children |

---

## 11_PBIP_Prototype

**Category:** Authoring | **Requires:** PBIP files + optional live connection for data

Generate and prototype Power BI report pages: spec-based generation, interactive HTML prototype, and HTML-to-PBIP translation.

### Operations

| Operation | Description |
|-----------|-------------|
| `generate_from_spec` | Create a PBIP page from a structured JSON specification |
| `generate_html` | Generate an interactive HTML prototype from a PBIP page |
| `apply_html` | Apply HTML prototype changes back to PBIP files |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pbip_path` | string | — | **Required.** PBIP path |
| `operation` | string | — | **Required.** Operation |
| `spec` | object | — | Page specification (generate_from_spec) |
| `page_name` | string | — | Page name (generate_html) |
| `output_path` | string | — | Custom HTML output path |
| `auto_open` | boolean | true | Auto-open in browser |
| `include_data` | boolean | false | Include live data from PBI |
| `state` | object | — | Exported state JSON (apply_html) |
| `dry_run` | boolean | false | Preview changes |

---

## SVG_Visual_Operations

**Category:** PBIP | **Requires:** Optional live connection for context-aware suggestions

SVG visual generation: 40+ DAX measure templates for KPIs, sparklines, gauges, and data bars. List, preview, generate, inject, validate, and create custom.

### Operations

| Operation | Description |
|-----------|-------------|
| `list_templates` | List available SVG templates |
| `get_template` | Get template details |
| `preview_template` | Preview template rendering |
| `generate_measure` | Generate a DAX measure from template |
| `inject_measure` | Inject generated measure into live model |
| `list_categories` | List template categories |
| `search_templates` | Search templates by keyword |
| `validate_svg` | Validate SVG code |
| `create_custom` | Create a custom SVG template |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | string | — | **Required.** Operation |
| `category` | `"kpi"` \| `"sparklines"` \| `"gauges"` \| `"databars"` \| `"advanced"` | — | Category filter |
| `complexity` | `"basic"` \| `"intermediate"` \| `"advanced"` \| `"complex"` | — | Complexity filter |
| `template_id` | string | — | Template ID |
| `parameters` | object | — | Template params: `measure_name`, `value_measure`, thresholds, colors (`%23RRGGBB`) |
| `table_name` | string | — | Target table (inject) |
| `measure_name` | string | — | Measure name |
| `search_query` | string | — | Search term |
| `svg_code` | string | — | SVG code (validate/create_custom) |
| `dynamic_vars` | object | — | DAX variable mappings (create_custom) |
| `context_aware` | boolean | true | Use connected model for suggestions |

### Usage Examples

```json
// List KPI templates
{"operation": "list_templates", "category": "kpi"}

// Generate a gauge measure
{"operation": "generate_measure", "template_id": "gauge_basic", "parameters": {"measure_name": "Revenue Gauge", "value_measure": "[Total Sales]", "threshold_low": 1000, "threshold_high": 5000}}

// Inject into model
{"operation": "inject_measure", "template_id": "sparkline_basic", "table_name": "Sales", "measure_name": "Sales Trend", "parameters": {"value_measure": "[Total Sales]"}}
```

---

## Quick Reference: Requires Connection vs Offline

| Offline (PBIP only) | Live Connection Required |
|---------------------|------------------------|
| 02_TMDL_Operations | 01_Connection |
| 05_Column_Usage_Mapping (pbip ops) | 02_Model_Operations |
| 07_Report_Operations | 03_Batch_Operations |
| 07_PBIP_Operations | 04_Run_DAX |
| 07_Page_Operations | 04_Query_Operations |
| 07_Visual_Operations | 05_DAX_Intelligence |
| 07_Bookmark_Operations | 05_Column_Usage_Mapping (live ops) |
| 07_Theme_Operations | 06_Analysis_Operations |
| 11_PBIP_Authoring | 08_Documentation_Word |
| 11_PBIP_Prototype (no data) | 09_Debug_Operations |
| SVG_Visual_Operations (templates) | 09_Validate |
| 10_Show_User_Guide | 09_Profile |
| | 09_Document |

---

*Generated for MCP-PowerBi-Finvision v7.0.0 — 23 tools, 150+ operations*
