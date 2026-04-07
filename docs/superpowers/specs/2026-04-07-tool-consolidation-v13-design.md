# Tool Consolidation v13 — Design Spec

**Date:** 2026-04-07
**Goal:** Streamline MCP tools from 38 to 23, surface all hidden capabilities, eliminate internal code duplication.

## Problem Statement

The MCP server has 38 registered tools plus 6 unregistered handler files containing unique functionality the AI cannot access. Key issues:

1. **Hidden capabilities** — `11_PBIP_Authoring` (clone/create/delete pages & visuals) and `07_Slicer_Operations` (visual interaction management) are defined but never registered
2. **Redundant tools** — 5 CRUD tools with identical dispatcher patterns, 3 query tools that could be 2, 6 debug tools that could be 4
3. **Dead handler files** — `role_operations_handler`, `report_info_handler`, `bookmark_theme_handler` duplicate functionality already in registered tools
4. **Internal code duplication** — DAX validation in 2 places, normalize_dax in 2 places, 150+ LOC copy-paste between context_analyzer and context_debugger, parallel batch systems
5. **Schema token cost** — ~8,000-10,000 tokens (5-7% of LLM context) for tool definitions

## Final Tool Map (23 tools)

### 01 — Core (2 tools)

| # | Tool | Operations | Change |
|---|---|---|---|
| 1 | `01_Connection` | `detect`, `connect` | **MERGE** `01_Detect_PBI_Instances` + `01_Connect_To_Instance` |
| 2 | `10_Show_User_Guide` | — | Keep as-is |

### 02 — Model CRUD (2 tools)

| # | Tool | Operations | Change |
|---|---|---|---|
| 3 | `02_Model_Operations` | `object_type` × `operation` dispatcher | **MERGE** 5 CRUD tools into 1 |
| 4 | `02_TMDL_Operations` | `export`, `find_replace`, `bulk_rename`, `generate_script`, `migrate_measures` | Keep as-is |

**`02_Model_Operations` dispatch matrix:**

| object_type | operations |
|---|---|
| `table` | list, describe, sample_data, create, update, delete, refresh, generate_calendar |
| `column` | list, get, statistics, distribution, create, update, delete |
| `measure` | list, get, create, update, delete, rename, move |
| `relationship` | list, get, find, create, update, delete, activate, deactivate |
| `calculation_group` | list, create, delete, list_items |

Schema uses `object_type` (required enum) + `operation` (required enum, valid values depend on object_type) + type-specific params. Invalid combos return a clear error with the valid operations for that object_type.

### 03 — Batch (1 tool)

| # | Tool | Operations | Change |
|---|---|---|---|
| 5 | `03_Batch_Operations` | measures, tables, columns, relationships | Keep as-is; `03_Manage_Transactions` becomes internal-only |

`03_Manage_Transactions` is not true ACID (in-memory tracking only) and is only used internally by batch operations. Remove from public tool registry, keep the handler code as internal infrastructure.

### 04 — Query (2 tools)

| # | Tool | Operations | Change |
|---|---|---|---|
| 6 | `04_Run_DAX` | auto, analyze, simple, trace modes | Keep as-is |
| 7 | `04_Query_Operations` | `data_sources`, `m_expressions`, `search_objects`, `roles`, `test_rls`, `search_string` | **ABSORB** `04_Search_String` as new operation |

### 05 — DAX Analysis (2 tools)

| # | Tool | Operations | Change |
|---|---|---|---|
| 8 | `05_DAX_Intelligence` | `analyze_context`, `debug_dax_context`, `dependencies`, `impact`, `export` | **ABSORB** `05_DAX_Operations` |
| 9 | `05_Column_Usage_Mapping` | `get_unused_columns`, `get_unused_columns_pbip`, `get_measures_for_tables`, `get_columns_for_measure`, `get_measures_for_column`, `get_full_mapping`, `export_to_csv`, `export_measures` | **ABSORB** `05_Export_DAX_Measures` as new operation |

### 06 — Model Analysis (1 tool)

| # | Tool | Operations | Change |
|---|---|---|---|
| 10 | `06_Analysis_Operations` | `simple`, `full`, `compare` | Keep as-is |

### 07 — PBIP/Report (6 tools)

| # | Tool | Operations | Change |
|---|---|---|---|
| 11 | `07_Report_Operations` | info, measure_usage, rename, rebind, backup, restore, discover_schema, manage_extension_measures | Keep as-is |
| 12 | `07_PBIP_Operations` | analyze, validate_model, compare_models, generate_documentation, query_dependencies, query_measures, query_relationships, query_unused, scan_broken_refs, git_diff, `dependency_html`, `aggregation_analysis` | **ABSORB** `07_PBIP_Dependency_Analysis` + `07_Analyze_Aggregation` |
| 13 | `07_Page_Operations` | list, create, clone, delete, reorder, resize, display, background, drillthrough, tooltip, hide, show, interactions + all filter ops (`list_filters`, `add_filter`, `set_filter`, `clear_filters`, `hide_filter`, `unhide_filter`, `lock_filter`, `unlock_filter`) | **ABSORB** `07_Filter_Operations` |
| 14 | `07_Visual_Operations` | list, create, delete, position, config, formatting, align, field binding, sort, actions, code injection, slicer config, visual calcs, templates, `sync_visual`, `sync_formatting`, `sync_column_widths`, `replace_measure`, `list_interactions`, `set_interaction`, `bulk_set_interactions` | **ABSORB** `07_Visual_Sync` + slicer interaction ops from `slicer_operations_handler` |
| 15 | `07_Bookmark_Operations` | list, create, rename, delete, set_capture, set_affected_visuals, analyze | Keep as-is |
| 16 | `07_Theme_Operations` | analyze_compliance, colors, formatting, fonts, text_classes, cf_rules | Keep as-is |

### 08 — Documentation (1 tool)

| # | Tool | Operations | Change |
|---|---|---|---|
| 17 | `08_Documentation_Word` | generate, update | Keep as-is |

### 09 — Debug (4 tools)

| # | Tool | Operations | Change |
|---|---|---|---|
| 18 | `09_Debug_Operations` | visual, compare, drill, analyze, debug_variable, step_variables, run_dax, optimize, audit, `set_path`, `status` | **ABSORB** `09_Debug_Config` |
| 19 | `09_Validate` | cross_visual, expected_value, filter_permutation | Keep as-is |
| 20 | `09_Profile` | page, filter_matrix, `decompose`, `contribution`, `trend`, `root_cause`, `export` | **ABSORB** `09_Advanced_Analysis` |
| 21 | `09_Document` | page, report, measure_lineage, filter_lineage | Keep as-is |

### 11 — Authoring (2 tools)

| # | Tool | Operations | Change |
|---|---|---|---|
| 22 | `11_PBIP_Authoring` | clone_page, clone_report, create_page, create_visual, create_visual_group, delete_page, delete_visual, list_templates, get_template | **NEWLY REGISTERED** — was hidden |
| 23 | `11_PBIP_Prototype` | generate_from_spec, generate_html, apply_html | Keep as-is |

### SVG (1 tool)

| # | Tool | Operations | Change |
|---|---|---|---|
| 23 | `SVG_Visual_Operations` | list_templates, get_template, preview_template, generate_measure, inject_measure, list_categories, search_templates, validate_svg, create_custom | Keep as-is |

SVG is a specialized domain (DAX-based SVG generation) distinct from PBIR visual manipulation. Absorbing 9 SVG ops into an already-large `07_Visual_Operations` would create a 33-operation mega-tool. Keep separate.

**Final total: 23 tools.**

---

## Dead Handler Cleanup

### Files to delete (pure duplicates)

| File | Reason |
|---|---|
| `role_operations_handler.py` | Duplicate of `04_Query_Operations.roles` |
| `report_info_handler.py` | Duplicate of `07_Report_Operations.info` + `.measure_usage` |
| `bookmark_theme_handler.py` | Duplicate of `07_Bookmark_Operations.analyze` + `07_Theme_Operations.analyze_compliance` |

### Files to keep as internal helpers (add docstring noting they're not standalone tools)

| File | Used by |
|---|---|
| `comparison_handler.py` | `06_Analysis_Operations.compare` |
| `metadata_handler.py` | `04_Query_Operations.search_objects` + `.search_string` |

### Files to archive (functionality moved into registered tools)

| File | Moved to |
|---|---|
| `slicer_operations_handler.py` | Interaction ops → `07_Visual_Operations`; slicer config already in visual_ops |
| `transaction_management_handler.py` | Internalized into `03_Batch_Operations` infrastructure |

### Handler files that disappear via CRUD merge

| File | Replaced by |
|---|---|
| `table_operations_handler.py` | `02_Model_Operations` |
| `column_operations_handler.py` | `02_Model_Operations` |
| `measure_operations_handler.py` | `02_Model_Operations` |
| `relationship_operations_handler.py` | `02_Model_Operations` |
| `calculation_group_operations_handler.py` | `02_Model_Operations` |

These files can be kept as internal modules (the CRUD managers they delegate to stay), but their `register_*` functions and `ToolDefinition` registrations are removed. The new `model_operations_handler.py` dispatches to them.

---

## Internal Code Deduplication

### 1. DAX Utilities Consolidation

**What:** `validate_dax_identifier()` exists in both `core/dax/dax_utilities.py` and `core/dax/dax_validator.py`. `normalize_dax()` exists in both `core/dax/dax_utilities.py` and `core/dax/context_analyzer.py`. VAR/RETURN extraction regex in 3+ modules.

**Action:** 
- Keep `core/dax/dax_utilities.py` as the canonical home
- Remove duplicates from `dax_validator.py` and `context_analyzer.py`, import from `dax_utilities`
- Extract common regex patterns (qualified token, unqualified token, var pattern) into constants in `dax_utilities.py`

### 2. Context Analyzer / Context Debugger Dedup

**What:** `context_debugger.py` has 150+ LOC copy-pasted from `context_analyzer.py` (identical `_normalize_dax`, `_extract_variables`, `_extract_function_body`).

**Action:**
- Move shared functions to `core/dax/dax_utilities.py`
- Both `context_analyzer.py` and `context_debugger.py` import from there

### 3. Batch/Bulk Operations Merge

**What:** `core/operations/batch_operations.py` (handler-based) and `core/operations/bulk_operations.py` (manager-based) implement batch operations with different error handling patterns.

**Action:**
- Merge `bulk_operations.py` logic into `batch_operations.py`
- Single batch system with consistent error handling and transaction support

### 4. Thin Wrapper Removal

**What:** `core/operations/measure_operations.py`, `column_operations.py`, `relationship_operations.py`, `table_operations.py` are thin pass-through wrappers that just extract params and call CRUD managers.

**Action:**
- New `model_operations_handler.py` dispatches directly to CRUD managers
- Remove the operations.py intermediary layer
- CRUD managers (`*_crud_manager.py`) remain untouched — they're the real logic

---

## Schema Design Standards

Apply across all 22 tools for consistency:

1. **Dispatcher param**: Always `operation` (never `action` or `mode` as primary dispatcher)
2. **Path params**: Always `pbip_path` (not `pbip_folder_path`)
3. **Name params**: `name` for the primary object, `new_name` for renames, `display_name` only when distinct from object name
4. **Position**: Always nested `{x, y, width, height}` object
5. **Dry run**: All destructive operations support `dry_run: boolean`
6. **All schemas externalized** to `server/tool_schemas.py` for central management

---

## Migration Strategy

### Phase 1: Surface hidden capabilities (no breaking changes)
- Register `11_PBIP_Authoring` in `__init__.py`
- Absorb slicer interaction ops into `07_Visual_Operations`

### Phase 2: Absorb small merges
- `04_Search_String` → `04_Query_Operations`
- `05_Export_DAX_Measures` → `05_Column_Usage_Mapping`
- `05_DAX_Operations` → `05_DAX_Intelligence`
- `09_Debug_Config` → `09_Debug_Operations`
- `09_Advanced_Analysis` → `09_Profile`
- `07_PBIP_Dependency_Analysis` + `07_Analyze_Aggregation` → `07_PBIP_Operations`
- `07_Filter_Operations` → `07_Page_Operations`
- `07_Visual_Sync` → `07_Visual_Operations`
- `SVG_Visual_Operations` → `07_Visual_Operations`
- `01_Detect/Connect` → `01_Connection`
- Internalize `03_Manage_Transactions`

### Phase 3: Structural merges
- 5 CRUD tools → `02_Model_Operations`
- Internal code dedup (DAX utilities, context analyzer, batch/bulk, thin wrappers)

### Phase 4: Cleanup
- Delete dead handler files
- Move all schemas to `tool_schemas.py`
- Standardize param naming
- Update CLAUDE.md tool references

---

## Risk Mitigation

- **Each phase is independently deployable** — if Phase 3 has issues, Phases 1-2 still deliver value
- **Old tool names can be aliased** temporarily if external consumers depend on them
- **CRUD merge validation**: test every object_type × operation combination
- **Debug tools kept separate** to avoid confusing the AI with a 25-operation mega-tool

---

## Success Criteria

- [ ] All 22 tools registered and callable
- [ ] Zero hidden capabilities (every operation from unregistered handlers is reachable)
- [ ] Zero duplicate handler files (dead files deleted or archived)
- [ ] `validate_dax_identifier()` exists in exactly 1 place
- [ ] `normalize_dax()` exists in exactly 1 place
- [ ] No copy-paste blocks > 20 LOC between files
- [ ] All schemas in `tool_schemas.py`
- [ ] Consistent `operation` dispatcher across all multi-op tools
- [ ] Schema token cost reduced by ~40%
