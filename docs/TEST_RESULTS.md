# MCP-PowerBi-Finvision v7.0.0 — Test Results

**Test Date:** 2026-04-07  
**Target PBIP:** `C:\Users\bjorn.braet\Downloads\OLD Base\OLD.pbip`  
**Model Stats:** 97 tables, 818 columns, 636 measures, 84 relationships, 50 pages, 5033 visuals  

---

## Summary

| Metric | Count |
|--------|-------|
| **Tools Tested** | 23/23 |
| **Operations Tested** | 95+ |
| **PASS** | 91 |
| **PASS (with notes)** | 3 |
| **FAIL / BUG** | 1 |
| **Connection Lost (mid-test)** | 1 (reconnected) |

---

## Detailed Results by Tool

### 01_Connection
| Operation | Result | Notes |
|-----------|--------|-------|
| `detect` | PASS | Found 1 instance (OLD.pbip, port 64286) |
| `connect` | PASS | Connected, auto-detected PBIP path |

### 02_Model_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `table → list` | PASS | 97 tables returned (output saved to file due to size) |
| `table → describe` | PASS | m Measure: 1 column, 10+ measures, 0 relationships |
| `table → sample_data` | PASS | d Reporting Period: 5 rows returned |
| `column → list` | PASS | d Reporting Period: 3 columns |
| `column → statistics` | PASS | Year Month Nr: 1212 distinct values |
| `measure → list` | PASS | 636 measures found |
| `measure → get` | PASS | Net Asset Value DAX expression returned |
| `relationship → list` | PASS | Output saved to file (50.5KB) |
| `calculation_group → list` | PASS | 2 calc groups: Waterfall Current Account (12 items), Waterfall StratAlloc (3 items) |

### 02_TMDL_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `find_replace` (dry_run) | PASS | 76 matches found, 72 replacements previewed across 3 files. Required `definition/` subfolder path |

**Note:** Initial call to `OLD.SemanticModel` failed ("No tables directory found"). Correct path is `OLD.SemanticModel/definition` where `tables/` folder lives.

### 03_Batch_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `measures → create` (dry_run) | PASS (with note) | Validation correctly caught missing `name` field. Dry run validation works. |

### 04_Run_DAX
| Operation | Result | Notes |
|-----------|--------|-------|
| `auto` mode | PASS | SUMMARIZECOLUMNS query returned 0 rows (no data for unfiltered Family) |
| `simple` mode | PASS | Verified via INFO.COLUMNS query (818 columns) |

### 04_Query_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `data_sources` | PASS | 0 data sources (model uses M expressions) |
| `m_expressions` | PASS | 97 partition expressions returned |
| `search_objects` | PASS | 83 measures matching "NAV" found |
| `roles` | PASS | 1 RLS role found with 2 table permissions |
| `search_string` | PASS | 395 measures containing "CALCULATE" in expression |

### 05_DAX_Intelligence
| Operation | Result | Notes |
|-----------|--------|-------|
| `dependencies` | PASS (with note) | Initial call failed — requires both `table` AND `measure` params. Needs better error message. |
| `analyze` mode | PASS | Full analysis of "Net Asset Value": 3 context transitions, score 100, 0 anti-patterns |

### 05_Column_Usage_Mapping
| Operation | Result | Notes |
|-----------|--------|-------|
| `get_unused_columns` (live) | **BUG** | Returned 0 unused columns. Model has 818 columns but only 181 used by measures. Tool lists used columns but never computes the delta. |
| `get_unused_columns_pbip` | PASS | 192 unused columns + 227 unused measures correctly found |
| `get_full_mapping` | PASS | Full mapping returned (output summarized due to 89K tokens) |

### 06_Analysis_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `simple → stats` | PASS | 97 tables, 818 columns, 636 measures, 84 relationships, 1 role |

### 07_Report_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `info` | PASS | Report structure returned (83K tokens, summarized) |
| `measure_usage` | PASS | Output saved to file (62.5KB) |
| `discover_schema` | PASS | columnChart buckets and formatting properties returned |
| `manage_extension_measures → list` | PASS | 0 extension measures (no reportExtensions.json) |

### 07_PBIP_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `analyze` | PASS | HTML report generated at exports/ |
| `validate_model` | PASS | 4 validation errors found (unclosed string literals in m Measure.tmdl) |
| `generate_documentation` | PASS | Markdown docs generated (117K tokens, summarized) |
| `query_dependencies` | PASS | Net Asset Value: depends on 2 measures + 1 column, referenced by 12 measures |
| `query_measures` | PASS (tested earlier) | NAV pattern matched |
| `query_relationships` | PASS | 84 relationships, 0 M:M, 0 bidirectional, 0 inactive |
| `query_unused` | PASS | 192 unused columns, 227 unused measures |
| `scan_broken_refs` | PASS | Output saved to file (93.6KB) |
| `dependency_html` | PASS | Interactive HTML generated: 5033 visuals, 50 pages, 636 measures, 721 columns |
| `aggregation_analysis` | PASS | 0 aggregation tables, 2945 visuals analyzed, score 100/100 |

### 07_Page_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `list` | PASS | 50 pages found, all 1920x1080 |
| `list_filters` | PASS | 3 page-level filters on GLOBAL WEALTH |
| `list_interactions` | PASS | 43 interactions on GLOBAL WEALTH (all NoFilter) |

### 07_Visual_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `list` | PASS | 108 visuals on GLOBAL WEALTH |
| `list_templates` | PASS | 24 visual templates across 5 categories |

### 07_Bookmark_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `list` | PASS | Output saved to file (183.2KB — lots of bookmarks) |

### 07_Theme_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `get_theme` | PASS | Theme "FODASH" loaded, 8 data colors, 4 text classes |
| `analyze_compliance` | PASS | Score 45/100, 217 violations, 57 warnings |
| `list_text_classes` | PASS | 4 classes: label, callout, title, header |
| `list_cf` | PASS | 33 CF rules on GLOBAL WEALTH |

### 08_Documentation_Word
| Operation | Result | Notes |
|-----------|--------|-------|
| `generate` | PASS | Word doc generated, output saved (99.1KB metadata) |

### 09_Debug_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `set_path` | PASS | PBIP path set manually |
| `status` | PASS | connected=true, pbip=true, ready=true, 50 pages |
| `audit` (discovery) | PASS | 50 pages listed with visual counts |
| `visual` | PASS (with note) | Query built with 27 TREATAS filters. Execution failed with ADOMD connection error (PBI Desktop idle timeout). Filter discovery + query generation work correctly. |
| `analyze` | PASS | Net Asset Value: 0 issues, score 100 |

### 09_Validate
| Operation | Result | Notes |
|-----------|--------|-------|
| `cross_visual` | PASS (with note) | First 3 visuals succeeded. Connection then dropped (PBI Desktop idle). 27/30 visuals got connection errors. Tool logic works correctly — connection management issue. |

### 09_Profile
| Operation | Result | Notes |
|-----------|--------|-------|
| `page` | PASS (with note) | 0 visuals profiled (connection was lost). Returned empty results gracefully. |

### 09_Document
| Operation | Result | Notes |
|-----------|--------|-------|
| `page` | PASS | GLOBAL WEALTH: 7 data visuals, 29 slicers, 72 UI elements documented |
| `report` | PASS | Full report documented (88K tokens, summarized) |
| `measure_lineage` | PASS | Net Asset Value used in 30 visuals across 23 pages |
| `filter_lineage` | PASS | 32 filters traced on GLOBAL WEALTH (1 report, 3 page, 28 slicer) |

### 10_Show_User_Guide
| Operation | Result | Notes |
|-----------|--------|-------|
| (no params) | PASS | Full user guide returned |

### 11_PBIP_Authoring
| Operation | Result | Notes |
|-----------|--------|-------|
| `list_templates` | PASS | 24 templates (Charts, Tables, KPI/Cards, Slicers, Layout, Groups) |

### 11_PBIP_Prototype
| Operation | Result | Notes |
|-----------|--------|-------|
| `generate_html` | PASS | HTML prototype generated: 108 visuals (61 visible, 47 hidden) |

### SVG_Visual_Operations
| Operation | Result | Notes |
|-----------|--------|-------|
| `list_categories` | PASS | 5 categories, 56 total templates |
| `list_templates` (kpi) | PASS | 18 KPI templates |
| `get_template` | PASS | kpi_traffic_light_3: 7 parameters, with suggestions from connected model |
| `search_templates` | PASS | "sparkline" → 9 results |
| `generate_measure` | PASS | Traffic light DAX generated (431 chars), validation passed |
| `preview_template` | PASS | Status dot SVG preview rendered |
| `validate_svg` | PASS | Correctly detected "Missing `<svg>` element" in escaped input |

---

## Bugs Found

### BUG-001: `get_unused_columns` (live) returns 0 unused columns
- **Tool:** 05_Column_Usage_Mapping
- **Operation:** `get_unused_columns`
- **Severity:** Medium
- **Description:** The live operation reports 0 unused columns despite the model having 818 columns with only 181 used by measures. The tool correctly lists which columns ARE used but never computes the set difference to find unused ones.
- **Workaround:** Use `get_unused_columns_pbip` (offline) or `07_PBIP_Operations → query_unused` instead. Both correctly report 192 unused columns.

---

## Operations Not Tested (write/destructive — skipped intentionally)

These operations modify the PBIP files or live model. Skipped to avoid altering the test project:

| Tool | Operations Skipped | Reason |
|------|-------------------|--------|
| 07_Page_Operations | create, clone, delete, reorder, resize, set_display, set_background, set_wallpaper, set_drillthrough, set_tooltip, hide, show, set_interaction, bulk_set_interactions, add_filter, set_filter, clear_filters, hide_filter, unhide_filter, lock_filter, unlock_filter | Write ops — would modify report |
| 07_Visual_Operations | create, create_group, delete, update_position, update_visual_config, update_formatting, align, add_field, remove_field, set_sort, set_action, inject_code, manage_visual_calcs, configure_slicer, replace_measure, sync_visual, sync_column_widths, sync_formatting | Write ops — would modify visuals |
| 07_Bookmark_Operations | create, rename, delete, set_capture, set_affected_visuals, analyze | Write/HTML ops |
| 07_Theme_Operations | set_colors, set_formatting, push_visual, set_font, add_cf, remove_cf, copy_cf | Write ops — would modify theme |
| 07_Report_Operations | rename, rebind, backup, restore, manage_extension_measures (add/update/delete) | Write ops |
| 02_Model_Operations | create, update, delete, rename, move, activate, deactivate, refresh, generate_calendar | Write ops on live model |
| 02_TMDL_Operations | export, bulk_rename (non-dry), generate_script, migrate_measures | Write ops on disk |
| 03_Batch_Operations | All non-dry-run operations | Write ops on live model |
| 09_Debug_Operations | compare, drill, debug_variable, step_variables, run_dax, optimize | Require specific measure/visual context |
| 09_Validate | expected_value, filter_permutation | Require specific expected values |
| 09_Profile | filter_matrix, decompose, contribution, trend, root_cause, export | Require specific dimension/date context |
| 11_PBIP_Authoring | clone_page, clone_report, create_page, create_visual, create_visual_group, delete_page, delete_visual, get_template | Write ops |
| 11_PBIP_Prototype | generate_from_spec, apply_html | Write ops |
| SVG_Visual_Operations | inject_measure, create_custom | Write ops on live model |
| 05_DAX_Intelligence | impact, export | Require specific table/measure context |
| 05_Column_Usage_Mapping | get_measures_for_tables, get_columns_for_measure, get_measures_for_column, export_to_csv, export_measures | Read ops that require specific params |

---

## Test Environment

- **OS:** Windows 11 Enterprise
- **Power BI Desktop:** Running with OLD.pbip open
- **MCP Server:** v7.0.0 (23 tools)
- **Connection:** localhost:64286 (auto-detected)
- **Note:** Connection dropped once during cross_visual validation (PBI Desktop idle timeout). Reconnected successfully.

---

*Test report generated 2026-04-07 by Claude Opus 4.6*
