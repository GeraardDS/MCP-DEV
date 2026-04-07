# Design Spec: v7.1 Server Cleanup + Feature Additions

**Date:** 2026-04-07
**Status:** Draft
**Scope:** Post-consolidation cleanup, version/dependency fixes, registry alignment, PBIR schema bump, MCP protocol updates, TOM feature parity

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [Phase 1 — Dead Code & Consolidation Cleanup](#2-phase-1--dead-code--consolidation-cleanup)
3. [Phase 2 — Version, Dependency & Config Fixes](#3-phase-2--version-dependency--config-fixes)
4. [Phase 3 — Registry Alignment](#4-phase-3--registry-alignment)
5. [Phase 4 — User Guide Rewrite](#5-phase-4--user-guide-rewrite)
6. [Phase 5 — MCP Protocol Updates](#6-phase-5--mcp-protocol-updates)
7. [Phase 6 — PBIR Schema & Template Updates](#7-phase-6--pbir-schema--template-updates)
8. [Phase 7 — TOM Feature Parity](#8-phase-7--tom-feature-parity)
9. [Phase 8 — Core Domain Fixes](#9-phase-8--core-domain-fixes)
10. [Out of Scope](#10-out-of-scope)
11. [Risk & Dependencies](#11-risk--dependencies)
12. [Verification Plan](#12-verification-plan)

---

## 1. Motivation

The v13 tool consolidation (38->23 tools) was completed at the `__init__.py` registration level but left significant debris:

- **15 orphaned handler files** with dead `register_*()` functions
- **registry.py lists 37 tools** when only 24 exist
- **Version strings diverge** across 4 locations (7.0.0 vs 6.6.2 vs 3.4)
- **Dependency specs conflict** between requirements.txt and pyproject.toml
- **User guide references 12+ dead tool names**
- **PBIR visual schema** is one version behind (2.6.0 vs 2.7.0)
- **MCP protocol** missing 2 tool annotations and structured output
- **8 TOM operations** missing vs Microsoft's reference MCP server

This spec addresses all findings in a single coordinated release (v7.1.0).

---

## 2. Phase 1 — Dead Code & Consolidation Cleanup

### 2.1 Delete Deprecated CRUD Handlers (5 files)

These files contain only dead `register_*()` functions and a deprecation header. No active handler imports anything from them.

| File | Dead Function |
|------|---------------|
| `server/handlers/table_operations_handler.py` | `register_table_operations_handler()` |
| `server/handlers/column_operations_handler.py` | `register_column_operations_handler()` |
| `server/handlers/measure_operations_handler.py` | `register_measure_operations_handler()` |
| `server/handlers/relationship_operations_handler.py` | `register_relationship_operations_handler()` |
| `server/handlers/calculation_group_operations_handler.py` | `register_calculation_group_operations_handler()` |

**Action:** Delete all 5 files. They are fully superseded by `model_operations_handler.py`.

### 2.2 Remove Dead register_*() from Internal Helpers (7 files)

These files are still imported by active handlers for their internal functions, but each contains a dead `register_*()` function that registers a phantom tool. Remove the register function and its `ToolDefinition` import/usage. Keep the internal helper functions intact.

| File | Dead Function | Line | Keep Functions |
|------|---------------|------|----------------|
| `bookmark_theme_handler.py` | `register_bookmark_theme_handlers()` | 201 | `_find_report_folder`, `handle_analyze_bookmarks`, `handle_theme_compliance` |
| `report_info_handler.py` | `register_report_info_handler()` | 857 | `handle_report_info`, `handle_report_measure_usage` |
| `transaction_management_handler.py` | `register_transaction_management_handler()` | 21 | Transaction helper functions |
| `aggregation_handler.py` | `register_aggregation_handler()` | 177 | `handle_aggregation_analysis` |
| `dependencies_handler.py` | `register_dependencies_handlers()` | 542 | `handle_dax_operations` |
| `filter_operations_handler.py` | `register_filter_operations_handler()` | 237 | `_op_list`, `_op_add`, `_op_set`, `_op_clear`, `_op_hide`, `_op_unhide`, `_op_lock`, `_op_unlock` |
| `hybrid_analysis_handler.py` | `register_hybrid_analysis_handlers()` | 104 | `handle_generate_pbip_dependency_diagram` |

**Action:** In each file, delete the `register_*()` function and the `ToolDefinition` import. Add a module docstring clarifying "INTERNAL HELPER — not a registered MCP tool".

### 2.3 Clean Up Remaining Orphaned Handlers (2 files)

| File | Dead Function | Line | Keep Functions |
|------|---------------|------|----------------|
| `slicer_operations_handler.py` | `register_slicer_operations_handler()` | 994 | `_op_set_interaction`, `_op_bulk_set_interactions`, `_op_list_interactions`, `_find_slicers`, `_configure_single_select_all` |
| `comparison_handler.py` | (no register function) | N/A | `handle_compare_pbi_models` |

**Action:** Remove the dead register function from `slicer_operations_handler.py`. `comparison_handler.py` has no register function — add "INTERNAL HELPER" docstring.

### 2.4 Add metadata_handler.py Docstring

`metadata_handler.py` has no register function and no deprecation header. Add "INTERNAL HELPER" module docstring for clarity.

### Summary: Phase 1 Deliverables

- **5 files deleted** (deprecated CRUD handlers)
- **7 files cleaned** (dead register functions removed)
- **2 files clarified** (docstrings added)
- **1 file documented** (metadata_handler)
- **Net result:** 0 phantom tool registrations remain outside `__init__.py`

---

## 3. Phase 2 — Version, Dependency & Config Fixes

### 3.1 Version Alignment

| File | Current | Target |
|------|---------|--------|
| `src/__version__.py` | 7.0.0 | 7.1.0 |
| `manifest.json` | 7.0.0 | 7.1.0 |
| `python/pyproject.toml` line 3 | **6.6.2** | 7.1.0 |
| `src/pbixray_server_enhanced.py` line 3 | **v3.4** | v7.1.0 |

### 3.2 Dependency Sync

**python/pyproject.toml dependencies** (align with requirements.txt):

| Package | pyproject.toml (current) | requirements.txt | Action |
|---------|--------------------------|-------------------|--------|
| `pbixray` | `>=0.1.0,<0.2.0` | `>=0.4.0,<1.0.0` | **Fix to >=0.4.0,<1.0.0** |
| `beautifulsoup4` | missing | `>=4.12.0,<5.0.0` | **Add** |
| `orjson` | missing | `>=3.9.0,<4.0.0` | **Add** |
| `tqdm` | missing | `>=4.66.0,<5.0.0` | **Add** |
| `polars` | missing | `>=1.35.0,<2.0.0` | **Add** |
| `mcp` | `>=1.0.0` | `>=1.0.0,<2.0.0` | **Add upper bound** |
| `openpyxl` | listed | not in requirements.txt | **Add to requirements.txt** (used by documentation handler) |
| `reportlab` | listed | not in requirements.txt | **Add to requirements.txt** (used by documentation handler) |
| `matplotlib` | listed | not in requirements.txt | **Add to requirements.txt** (used by visualization) |
| `pillow` | listed | not in requirements.txt | **Add to requirements.txt** (used by image processing) |

**MCP SDK pin:** Change `mcp>=1.0.0,<2.0.0` to `mcp>=1.23.0,<2.0.0` in both files to ensure Tasks, elicitation, and structured content support are available.

**Note:** `python/requirements.txt` is currently identical to root `requirements.txt`. After syncing, keep both files in lockstep. Consider making `python/requirements.txt` a symlink or deleting it in favor of a single source of truth.

### 3.3 Setup Script URLs

| File | Line | Current | Action |
|------|------|---------|--------|
| `MCP Server Setup.bat` | 311 | `https://dev.azure.com/finticx/...` | Replace with correct public/internal repo URL |
| `setup-dev.ps1` | 49 | `https://github.com/bibiibjorn/MCP-DEV.git` | Verify — update if repo was renamed |

**Note:** Confirm with user which repo URL is canonical before changing.

---

## 4. Phase 3 — Registry Alignment

### 4.1 Update CATEGORY_TOOLS in registry.py

Replace the current 37-tool mapping (lines 31-89) with the actual 24 tools:

```python
CATEGORY_TOOLS = {
    ToolCategory.CORE: [
        "01_Connection",
        "10_Show_User_Guide",
    ],
    ToolCategory.MODEL: [
        "02_Model_Operations",
        "02_TMDL_Operations",
    ],
    ToolCategory.BATCH: [
        "03_Batch_Operations",
    ],
    ToolCategory.QUERY: [
        "04_Run_DAX",
        "04_Query_Operations",
    ],
    ToolCategory.DAX: [
        "05_DAX_Intelligence",
        "05_Column_Usage_Mapping",
    ],
    ToolCategory.ANALYSIS: [
        "06_Analysis_Operations",
    ],
    ToolCategory.PBIP: [
        "07_PBIP_Operations",
        "07_Report_Operations",
        "07_Page_Operations",
        "07_Visual_Operations",
        "07_Bookmark_Operations",
        "07_Theme_Operations",
        "SVG_Visual_Operations",
    ],
    ToolCategory.DOCS: [
        "08_Documentation_Word",
    ],
    ToolCategory.DEBUG: [
        "09_Debug_Operations",
        "09_Validate",
        "09_Profile",
        "09_Document",
    ],
    ToolCategory.AUTHORING: [
        "11_PBIP_Authoring",
        "11_PBIP_Prototype",
    ],
}
```

### 4.2 Verify _TOOL_TO_CATEGORY

The reverse lookup is auto-computed from `CATEGORY_TOOLS` — fixing 4.1 automatically fixes this. After the change, verify all 24 tools resolve to the correct category. The 3 previously missing tools (`01_Connection`, `02_Model_Operations`, `11_PBIP_Authoring`) will now have correct lookups.

---

## 5. Phase 4 — User Guide Rewrite

### 5.1 Scope

`server/handlers/user_guide_handler.py` contains embedded documentation referencing **20+ dead tool names**. The entire tool reference section needs rewriting to match the 24 actual tools.

### 5.2 Tool Name Mapping (old -> new)

| Old Name (in user guide) | New Name | Notes |
|--------------------------|----------|-------|
| `01_Detect_PBI_Instances` | `01_Connection` | operation: `detect` |
| `01_Connect_To_Instance` | `01_Connection` | operation: `connect` |
| `02_Table_Operations` | `02_Model_Operations` | object_type: `table` |
| `02_Column_Operations` | `02_Model_Operations` | object_type: `column` |
| `02_Measure_Operations` | `02_Model_Operations` | object_type: `measure` |
| `02_Relationship_Operations` | `02_Model_Operations` | object_type: `relationship` |
| `02_Calculation_Group_Operations` | `02_Model_Operations` | object_type: `calculation_group` |
| `02_Role_Operations` | `04_Query_Operations` | operation: `roles` |
| `04_Search_String` | `04_Query_Operations` | operation: `search_string` |
| `05_DAX_Operations` | `05_DAX_Intelligence` | merged |
| `05_Export_DAX_Measures` | `05_Column_Usage_Mapping` | merged |
| `06_Simple_Analysis` | `06_Analysis_Operations` | operation: `simple` |
| `06_Full_Analysis` | `06_Analysis_Operations` | operation: `full` |
| `06_Compare_PBI_Models` | `06_Analysis_Operations` | operation: `compare` |
| `07_Report_Info` | `07_Report_Operations` | operation: `info` |
| `07_PBIP_Model_Analysis` | `07_PBIP_Operations` | operation: `model_analysis` |
| `07_PBIP_Query` | `07_PBIP_Operations` | operation: `query` |
| `07_PBIP_Dependency_Analysis` | `07_PBIP_Operations` | operation: `dependency_html` |
| `07_Analyze_Aggregation` | `07_PBIP_Operations` | operation: `aggregation` |
| `07_Filter_Operations` | `07_Page_Operations` | operation: `filters_*` |
| `07_Slicer_Operations` | `07_Page_Operations` / `07_Visual_Operations` | split |
| `07_Visual_Sync` | `07_Visual_Operations` | operation: `sync` |
| `07_Analyze_Bookmarks` | `07_Bookmark_Operations` | operation: `analyze` |
| `07_Analyze_Theme_Compliance` | `07_Theme_Operations` | operation: `compliance` |
| `08_Visual_Operations` | `07_Visual_Operations` | category renumbered |
| `09_Debug_Visual` | `09_Debug_Operations` | operation: `visual` |
| `09_Compare_Measures` | `09_Debug_Operations` | operation: `compare` |
| `09_Drill_To_Detail` | `09_Debug_Operations` | operation: `drill` |
| `09_Set_PBIP_Path` | `09_Debug_Operations` | operation: `set_pbip_path` |
| `09_Get_Debug_Status` | `09_Debug_Operations` | operation: `status` |
| `09_Analyze_Measure` | `09_Debug_Operations` | operation: `analyze_measure` |
| `09_Debug_Config` | `09_Debug_Operations` | operation: `config` |
| `09_Advanced_Analysis` | `09_Profile` | renamed |
| `03_Manage_Transactions` | (internal) | remove from guide |

### 5.3 Approach

Rewrite the user guide as a clean 24-tool reference organized by category. Each tool entry should list:
- Tool name
- Purpose (1-2 sentences)
- Key operations with brief descriptions
- Example usage pattern

Also update `docs/MCP_TOOL_REFERENCE.md` header from "23 registered" to "24 registered" (it lists 24 tools including SVG).

---

## 6. Phase 5 — MCP Protocol Updates

### 6.1 Add Missing Tool Annotations

The `ToolDefinition` dataclass already supports `annotations: Dict[str, Any]`. Two annotation types need adding to all 24 tools:

| Annotation | Type | Purpose |
|------------|------|---------|
| `idempotentHint` | bool | Can the tool be safely retried? |
| `openWorldHint` | bool | Does the tool interact with external systems? |

**Classification per tool:**

| Tool | idempotent | openWorld | Rationale |
|------|-----------|-----------|-----------|
| `01_Connection` | false | true | Connects to external PBI process |
| `02_Model_Operations` | false | true | CRUD includes writes; not safe to blindly retry |
| `02_TMDL_Operations` | false | true | File I/O + model writes |
| `03_Batch_Operations` | false | true | Transactional model writes |
| `04_Run_DAX` | true | true | Read-only query execution |
| `04_Query_Operations` | false | true | Includes write operations (roles) |
| `05_DAX_Intelligence` | true | false | Analysis only |
| `05_Column_Usage_Mapping` | true | false | Analysis only |
| `06_Analysis_Operations` | true | true | BPA reads live model |
| `07_Report_Operations` | false | true | Includes backup/restore/rename writes |
| `07_PBIP_Operations` | true | false | PBIP file analysis (read-only) |
| `07_Page_Operations` | false | true | Includes page CRUD + filter writes |
| `07_Visual_Operations` | false | true | Includes visual CRUD + formatting writes |
| `07_Bookmark_Operations` | false | true | Includes bookmark CRUD writes |
| `07_Theme_Operations` | false | true | Includes theme modification writes |
| `08_Documentation_Word` | true | false | Generates doc from model |
| `09_Debug_Operations` | true | true | Reads model + runs DAX |
| `09_Validate` | true | true | Validation queries |
| `09_Profile` | true | true | Profiling queries |
| `09_Document` | true | false | Documentation generation |
| `10_Show_User_Guide` | true | false | Static content |
| `11_PBIP_Authoring` | false | false | PBIR file writes |
| `11_PBIP_Prototype` | false | true | HTML generation + debug queries |
| `SVG_Visual_Operations` | true | false | Template retrieval |

**Implementation:** Add annotations in each handler's `ToolDefinition` constructor alongside existing `readOnlyHint`/`destructiveHint`.

### 6.2 Populate outputSchema on Tools

The `output_schema` field exists on `ToolDefinition` (line 125 of registry.py) but no tool populates it. For MCP spec 2025-06-18 structured output support:

**Phase 1 (this release):** Add `output_schema` to the 5 most commonly used tools:
- `01_Connection` — `{ type: "object", properties: { instances: {...}, connected: {...} } }`
- `04_Run_DAX` — `{ type: "object", properties: { results: {...}, row_count: {...} } }`
- `02_Model_Operations` — schema varies by operation (use `oneOf`)
- `09_Debug_Operations` — schema varies by operation
- `10_Show_User_Guide` — `{ type: "object", properties: { guide: { type: "string" } } }`

**Phase 2 (future):** Add schemas to remaining 19 tools incrementally.

### 6.3 MCP SDK Version Pin

Update both dependency files:
```
mcp>=1.23.0,<2.0.0
```

This ensures access to:
- Tool annotations (spec 2025-03-26)
- Structured output / outputSchema (spec 2025-06-18)
- Tasks primitive (spec 2025-11-25, experimental)

---

## 7. Phase 6 — PBIR Schema & Template Updates

### 7.1 Bump Visual Container Schema

In `core/pbip/authoring/visual_templates.py` line 17:

```python
# Before
VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.6.0/schema.json"

# After
VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json"
```

### 7.2 Add New Slicer Templates (4 types)

Add to `TEMPLATE_REGISTRY` in `visual_templates.py`:

| Template Key | Visual Type | Schema Since | Notes |
|-------------|-------------|--------------|-------|
| `input_slicer` | `inputSlicer` | 2.6.0 (GA Feb 2026) | Text input slicer for numeric/text parameters |
| `button_slicer` | `buttonSlicer` | 2.3.0 (GA Oct 2025) | Button-style single/multi-select |
| `text_slicer` | `textSlicer` | 1.4.0 (Nov 2024) | Free-text search slicer |
| `list_slicer` | `listSlicer` | 1.4.0 (Nov 2024) | Scrollable list selection |

Each template follows the existing pattern: base visual container structure with type-specific `config` and `dataTransforms`. Use existing `slicer` template as reference, adapting the `visualType` and `singleVisual.prototypeQuery` structure.

### 7.3 Parse VisualTopN Filter Type

In the filter parsing logic (`core/pbip/filter_engine.py` or equivalent):

- Add `VisualTopN` to the recognized filter types alongside `Basic`, `Advanced`, `RelativeDate`, `RelativeTime`, `TopN`
- Parse `topCount`, `orderBy`, `itemIdentity` properties
- Include in filter analysis output and dependency engine

### 7.4 Recognize SummarizeVisualContainer

In the PBIR visual type recognition logic:

- Add `SummarizeVisualContainer` as a known container type
- Parse its children (it wraps multiple visuals into a summary group)
- Include in page analysis, cloning operations, and dependency scanning

### 7.5 PBIR Annotation Support

Add read/write support for PBIR annotations (name-value pairs on visuals, pages, reports):

- **Read:** Parse `annotations` array from `visual.json`, `page.json`, `report.json`
- **Write:** Allow setting annotations via `07_Visual_Operations`, `07_Page_Operations`, `07_Report_Operations`
- **Use case:** Metadata tagging, version tracking, AI-generated provenance markers

### 7.6 Mobile Layout Handling

Add `mobile.json` awareness to visual/page operations:

- **Read:** Include mobile layout in visual/page info output
- **Clone:** Copy `mobile.json` alongside `visual.json` during clone operations
- **Delete:** Remove `mobile.json` when deleting visuals/pages

---

## 8. Phase 7 — TOM Feature Parity

Microsoft's `powerbi-modeling-mcp` (Nov 2025) exposes 8 TOM operation categories this server lacks. Add them as new operations within existing consolidated tools or as focused new tools.

### 8.1 Add to 02_Model_Operations (new object_type values)

| object_type | Operations | TOM Object |
|-------------|-----------|------------|
| `partition` | list, describe, create, update, delete, refresh | `Model.Tables[].Partitions[]` |
| `hierarchy` | list, describe, create, update, delete, reorder_levels | `Model.Tables[].Hierarchies[]` |
| `perspective` | list, describe, create, update, delete | `Model.Perspectives[]` |
| `culture` | list, describe, create, update, delete | `Model.Cultures[]` |
| `translation` | list, get, set, delete | `Model.Cultures[].ObjectTranslations[]` |
| `named_expression` | list, describe, create, update, delete | `Model.Expressions[]` (Power Query params) |
| `ols_rule` | list, describe, create, update, delete | `Model.Roles[].TablePermissions[].MetadataPermission` |
| `calendar` | list, describe, set | `Model.Tables[].Partitions[].Source` (M expressions for date tables) |

Each new `object_type` dispatches to a new CRUD manager in `core/operations/`.

### 8.2 New Core Operations Files

| File | Purpose |
|------|---------|
| `core/operations/partition_crud_manager.py` | Partition CRUD + targeted refresh |
| `core/operations/hierarchy_crud_manager.py` | Hierarchy CRUD |
| `core/operations/perspective_crud_manager.py` | Perspective CRUD |
| `core/operations/culture_crud_manager.py` | Culture + translation CRUD |
| `core/operations/named_expression_crud_manager.py` | Power Query parameter management |
| `core/operations/ols_crud_manager.py` | Object-level security rules |

### 8.3 DAX UDF Awareness

Add to `05_DAX_Intelligence`:

- **New operation: `list_udfs`** — calls `INFO.USERDEFINEDFUNCTIONS()` via DAX query
- **New operation: `describe_udf`** — returns UDF signature, parameters, documentation
- **Dependency engine update:** Recognize UDF calls in measure DAX expressions
- **DAX analysis update:** Recognize `NAMEOF()` and `TABLEOF()` functions

### 8.4 Visual Calculations CRUD

Currently the server reads visual calculations from PBIR but cannot create/edit them via TOM.

Add to `07_Visual_Operations`:
- **New operation: `create_visual_calculation`** — create visual calc on a visual
- **New operation: `update_visual_calculation`** — edit existing visual calc DAX
- **New operation: `delete_visual_calculation`** — remove visual calc

---

## 9. Phase 8 — Core Domain Fixes

### 9.1 Complete DAX Code Rewriter Stubs

In `core/dax/code_rewriter.py`:

**Line 697 — `_flatten_nested_calculate()`:**
- Implement proper DAX parsing to detect nested `CALCULATE(CALCULATE(...))` patterns
- Merge filter arguments from inner and outer CALCULATE
- Handle conflicting filters (outer wins)
- If implementation is too complex: replace TODO with a documented limitation comment and mark the optimization as "detected but not auto-applied"

**Line 827 — `_convert_summarize_to_summarizecolumns()`:**
- Parse SUMMARIZE arguments (table, groupBy columns, name/expression pairs)
- Rewrite to SUMMARIZECOLUMNS with ADDCOLUMNS wrapper for computed columns
- If implementation is too complex: same approach — document as detected-only

### 9.2 Complete Model Diff Engine

In `core/comparison/model_diff_engine.py`:

**Line 874 — Role comparison:**
- Compare role names, filter expressions, and member lists
- Detect added, removed, and modified roles
- For modified: diff the filter DAX per table

**Line 888 — Perspective comparison:**
- Compare perspective names and included objects (tables, columns, measures, hierarchies)
- Detect added, removed, and modified perspectives
- For modified: list added/removed objects

---

## 10. Out of Scope

The following items from the review are deferred to future releases:

| Item | Reason |
|------|--------|
| Streamable HTTP transport | Major architectural change; stdio is correct for Desktop |
| MCP Elicitation | Requires client support; not widely adopted yet |
| MCP Tasks primitive | Experimental in spec; wait for stabilization |
| Tool icons | Nice-to-have; no user impact |
| definition.pbir v2.0.0 schema | Only needed for Fabric deployment; not Desktop-relevant |
| PBIR size limit validation | Low priority; Desktop enforces limits itself |
| TMDL hot reload | Complex; requires AS engine refresh protocol |
| Monolithic file refactoring | Technical debt; split as files are touched, not proactively |
| Handler coupling refactoring | Working correctly; refactor when adding features to those handlers |
| Facade deprecation warnings | Low impact; add when facades are next modified |

---

## 11. Risk & Dependencies

| Risk | Mitigation |
|------|-----------|
| Deleting handler files breaks imports | Phase 1 only deletes files with zero imports; verified by agent review |
| Registry change breaks tool routing | `_TOOL_TO_CATEGORY` is auto-computed; verify all 24 tools resolve after change |
| PBIR 2.7.0 schema breaks existing templates | Schema is additive; existing visuals remain valid |
| MCP SDK 1.23+ has breaking changes | Pin `<2.0.0`; test with current client (Claude Desktop) |
| New TOM operations require .NET interop | Follow existing pattern in `core/operations/*_crud_manager.py`; reuse `connection_state` |
| New slicer templates produce invalid PBIR | Validate against Microsoft's JSON schemas; test round-trip in PBI Desktop |

---

## 12. Verification Plan

### Phase 1 (Dead code)
- `python -c "from server.handlers import register_all_handlers"` — no import errors
- `grep -r "register_table_operations_handler\|register_column_operations_handler\|register_measure_operations_handler\|register_relationship_operations_handler\|register_calculation_group_operations_handler" server/` — zero results
- Server starts and lists exactly 24 tools

### Phase 2 (Versions)
- `python -c "from src.__version__ import __version__; assert __version__ == '7.1.0'"`
- `python -c "import json; m=json.load(open('manifest.json')); assert m['version']=='7.1.0'"`
- `pip install -e . && pip show mcp-powerbi-finvision | grep Version` — shows 7.1.0

### Phase 3 (Registry)
- `python -c "from server.registry import _TOOL_TO_CATEGORY; assert len(_TOOL_TO_CATEGORY)==24, f'Expected 24, got {len(_TOOL_TO_CATEGORY)}'"`
- Verify each of the 24 tool names resolves to correct category

### Phase 4 (User guide)
- `grep -c "02_Table_Operations\|02_Column_Operations\|06_Simple_Analysis\|07_Report_Info\|09_Debug_Visual" server/handlers/user_guide_handler.py` — zero matches

### Phase 5 (MCP annotations)
- Server tool listing includes `idempotentHint` and `openWorldHint` for all 24 tools
- At least 5 tools have `output_schema` populated

### Phase 6 (PBIR)
- Visual templates reference schema 2.7.0
- 28 visual types in template registry (24 existing + 4 new slicers)
- Create a test page with each new slicer type, open in PBI Desktop — no errors

### Phase 7 (TOM)
- `02_Model_Operations` accepts `object_type: "partition"` and returns partition list
- Same for hierarchy, perspective, culture, named_expression, ols_rule
- `05_DAX_Intelligence` `list_udfs` operation returns UDF metadata

### Phase 8 (Core fixes)
- `_flatten_nested_calculate()` transforms `CALCULATE(CALCULATE(SUM(x), filter1), filter2)` into `CALCULATE(SUM(x), filter1, filter2)` or documents limitation
- `model_diff_engine` role comparison returns non-empty `modified` list when roles differ
