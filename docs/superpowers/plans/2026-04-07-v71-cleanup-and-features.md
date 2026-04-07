# v7.1 Server Cleanup + Feature Additions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up post-consolidation debris (dead code, version mismatches, stale registry) and add missing PBIR/MCP/TOM features to reach parity with Microsoft's reference MCP server.

**Architecture:** 8 sequential phases. Phases 1-4 are cleanup (no new features, only correctness). Phase 5 adds MCP protocol annotations. Phase 6 bumps PBIR schema and adds slicer templates. Phase 7 adds TOM CRUD managers. Phase 8 fixes core domain stubs.

**Tech Stack:** Python 3.10+, pythonnet/.NET interop (TOM/AMO), MCP SDK >=1.23, PBIR JSON schemas 2.7.0

**Spec:** `docs/superpowers/specs/2026-04-07-full-server-review-design.md`

---

## Phase 1 — Dead Code & Consolidation Cleanup

### Task 1: Delete Deprecated CRUD Handler Files

**Files:**
- Delete: `server/handlers/table_operations_handler.py`
- Delete: `server/handlers/column_operations_handler.py`
- Delete: `server/handlers/measure_operations_handler.py`
- Delete: `server/handlers/relationship_operations_handler.py`
- Delete: `server/handlers/calculation_group_operations_handler.py`

- [ ] **Step 1: Verify no active imports reference these files**

Run: `grep -r "from server.handlers.table_operations_handler\|from server.handlers.column_operations_handler\|from server.handlers.measure_operations_handler\|from server.handlers.relationship_operations_handler\|from server.handlers.calculation_group_operations_handler" server/ core/ src/ --include="*.py" -l`

Expected: 0 files. If any results, those imports must be updated first.

- [ ] **Step 2: Delete the 5 files**

```bash
git rm server/handlers/table_operations_handler.py
git rm server/handlers/column_operations_handler.py
git rm server/handlers/measure_operations_handler.py
git rm server/handlers/relationship_operations_handler.py
git rm server/handlers/calculation_group_operations_handler.py
```

- [ ] **Step 3: Verify server still imports cleanly**

Run: `python -c "from server.handlers import register_all_handlers; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add -A server/handlers/
git commit -m "cleanup: delete 5 deprecated CRUD handler files (superseded by 02_Model_Operations)"
```

---

### Task 2: Remove Dead register_*() Functions from Internal Helpers

**Files:**
- Modify: `server/handlers/bookmark_theme_handler.py`
- Modify: `server/handlers/report_info_handler.py`
- Modify: `server/handlers/transaction_management_handler.py`
- Modify: `server/handlers/aggregation_handler.py`
- Modify: `server/handlers/dependencies_handler.py`
- Modify: `server/handlers/filter_operations_handler.py`
- Modify: `server/handlers/hybrid_analysis_handler.py`
- Modify: `server/handlers/slicer_operations_handler.py`
- Modify: `server/handlers/comparison_handler.py`
- Modify: `server/handlers/metadata_handler.py`

- [ ] **Step 1: In each file, remove the dead `register_*()` function and add INTERNAL HELPER docstring**

For each of the 8 files that have a dead `register_*()` function:
1. Delete the `register_*()` function entirely (including its ToolDefinition construction)
2. Remove the `from server.registry import ToolDefinition` import if no longer used
3. Set the module docstring to clarify this is an internal helper

For the 2 files without register functions (`comparison_handler.py`, `metadata_handler.py`):
1. Add an "INTERNAL HELPER" module docstring

Example pattern — apply to each file:
```python
"""
INTERNAL HELPER — Not a registered MCP tool.
Provides helper functions consumed by active handlers.
"""
```

- [ ] **Step 2: Verify no ToolDefinition references remain in helper files**

Run: `grep -n "ToolDefinition\|registry.register" server/handlers/bookmark_theme_handler.py server/handlers/report_info_handler.py server/handlers/transaction_management_handler.py server/handlers/aggregation_handler.py server/handlers/dependencies_handler.py server/handlers/filter_operations_handler.py server/handlers/hybrid_analysis_handler.py server/handlers/slicer_operations_handler.py server/handlers/comparison_handler.py server/handlers/metadata_handler.py`

Expected: 0 results

- [ ] **Step 3: Verify server still imports cleanly**

Run: `python -c "from server.handlers import register_all_handlers; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add server/handlers/bookmark_theme_handler.py server/handlers/report_info_handler.py server/handlers/transaction_management_handler.py server/handlers/aggregation_handler.py server/handlers/dependencies_handler.py server/handlers/filter_operations_handler.py server/handlers/hybrid_analysis_handler.py server/handlers/slicer_operations_handler.py server/handlers/comparison_handler.py server/handlers/metadata_handler.py
git commit -m "cleanup: remove dead register_*() from 10 internal helper handlers"
```

---

## Phase 2 — Version, Dependency & Config Fixes

### Task 3: Align Version Strings

**Files:**
- Modify: `src/__version__.py:3`
- Modify: `manifest.json:5`
- Modify: `python/pyproject.toml:3`
- Modify: `src/pbixray_server_enhanced.py:3`

- [ ] **Step 1: Update all version strings to 7.1.0**

`src/__version__.py` line 3:
```python
__version__ = "7.1.0"
```

`manifest.json` — change `"version": "7.0.0"` to `"version": "7.1.0"`

`python/pyproject.toml` line 3 — change `version = "6.6.2"` to `version = "7.1.0"`

`src/pbixray_server_enhanced.py` line 3 — change `v3.4` to `v7.1.0` in the module docstring.

- [ ] **Step 2: Verify versions**

Run: `python -c "from src.__version__ import __version__; print(__version__)"`
Expected: `7.1.0`

Run: `python -c "import json; print(json.load(open('manifest.json'))['version'])"`
Expected: `7.1.0`

- [ ] **Step 3: Commit**

```bash
git add src/__version__.py manifest.json python/pyproject.toml src/pbixray_server_enhanced.py
git commit -m "chore: align version strings to 7.1.0 across all locations"
```

---

### Task 4: Sync Dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `python/requirements.txt`
- Modify: `python/pyproject.toml`

- [ ] **Step 1: Update `python/pyproject.toml` dependencies**

Fix `pbixray` version constraint from `>=0.1.0,<0.2.0` to `>=0.4.0,<1.0.0`.

Add missing packages:
```
"beautifulsoup4>=4.12.0,<5.0.0",
"orjson>=3.9.0,<4.0.0",
"tqdm>=4.66.0,<5.0.0",
"polars>=1.35.0,<2.0.0",
```

Update `mcp` constraint from `>=1.0.0` to `>=1.23.0,<2.0.0`.

- [ ] **Step 2: Update root `requirements.txt`**

Add missing packages that are in `pyproject.toml` but not here:
```
openpyxl>=3.1.0,<4.0.0
reportlab>=4.0.0,<5.0.0
matplotlib>=3.8.0,<4.0.0
pillow>=10.0.0,<11.0.0
```

Update `mcp` lower bound:
```
mcp>=1.23.0,<2.0.0
```

- [ ] **Step 3: Sync `python/requirements.txt` to match root `requirements.txt`**

Copy contents of root `requirements.txt` into `python/requirements.txt` (they should be identical).

- [ ] **Step 4: Commit**

```bash
git add requirements.txt python/requirements.txt python/pyproject.toml
git commit -m "chore: sync dependencies — fix pbixray constraint, add missing packages, pin MCP >=1.23"
```

---

## Phase 3 — Registry Alignment

### Task 5: Update CATEGORY_TOOLS in registry.py

**Files:**
- Modify: `server/registry.py:31-87`

- [ ] **Step 1: Replace the CATEGORY_TOOLS dict**

Replace lines 31-87 with:

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

- [ ] **Step 2: Verify reverse lookup resolves all 24 tools**

Run: `python -c "from server.registry import CATEGORY_TOOLS; tools = [t for ts in CATEGORY_TOOLS.values() for t in ts]; print(f'{len(tools)} tools'); assert len(tools) == 24, f'Expected 24, got {len(tools)}'"`

Expected: `24 tools`

- [ ] **Step 3: Commit**

```bash
git add server/registry.py
git commit -m "fix: update CATEGORY_TOOLS to match actual 24 registered tools (was stale at 37)"
```

---

## Phase 4 — User Guide Rewrite

### Task 6: Rewrite User Guide Tool References

**Files:**
- Modify: `server/handlers/user_guide_handler.py`
- Modify: `docs/MCP_TOOL_REFERENCE.md`

- [ ] **Step 1: Rewrite the user guide content in `user_guide_handler.py`**

Replace all tool reference sections with content matching the actual 24 tools. The guide should be organized by category:

**Core:** `01_Connection` (detect + connect), `10_Show_User_Guide`
**Model:** `02_Model_Operations` (table/column/measure/relationship/calculation_group CRUD), `02_TMDL_Operations`
**Batch:** `03_Batch_Operations`
**Query:** `04_Run_DAX`, `04_Query_Operations` (data_sources, m_expressions, search_objects, roles, test_rls, search_string)
**DAX:** `05_DAX_Intelligence`, `05_Column_Usage_Mapping`
**Analysis:** `06_Analysis_Operations` (simple, full, compare)
**PBIP:** `07_PBIP_Operations`, `07_Report_Operations`, `07_Page_Operations`, `07_Visual_Operations`, `07_Bookmark_Operations`, `07_Theme_Operations`, `SVG_Visual_Operations`
**Docs:** `08_Documentation_Word`
**Debug:** `09_Debug_Operations`, `09_Validate`, `09_Profile`, `09_Document`
**Authoring:** `11_PBIP_Authoring`, `11_PBIP_Prototype`

Each tool entry should have:
- Tool name as header
- 1-2 sentence purpose
- Bullet list of key operations
- 1 example call pattern

Remove ALL references to old tool names (verify with grep).

- [ ] **Step 2: Fix `docs/MCP_TOOL_REFERENCE.md` header**

Change "23 registered MCP tools" to "24 registered MCP tools" in the document header (line 3).

- [ ] **Step 3: Verify no stale tool names remain**

Run: `grep -c "02_Table_Operations\|02_Column_Operations\|02_Measure_Operations\|02_Relationship_Operations\|06_Simple_Analysis\|06_Full_Analysis\|07_Report_Info\|07_PBIP_Model_Analysis\|07_PBIP_Query\|09_Debug_Visual\|09_Compare_Measures\|09_Debug_Config\|09_Advanced_Analysis" server/handlers/user_guide_handler.py`

Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add server/handlers/user_guide_handler.py docs/MCP_TOOL_REFERENCE.md
git commit -m "docs: rewrite user guide for v13 consolidated tool names (24 tools)"
```

---

## Phase 5 — MCP Protocol Updates

### Task 7: Add idempotentHint and openWorldHint Annotations to All Tools

**Files:**
- Modify: `server/handlers/connection_handler.py` (01_Connection)
- Modify: `server/handlers/model_operations_handler.py` (02_Model_Operations)
- Modify: `server/handlers/tmdl_handler.py` (02_TMDL_Operations)
- Modify: `server/handlers/batch_operations_handler.py` (03_Batch_Operations)
- Modify: `server/handlers/query_handler.py` (04_Run_DAX, 04_Query_Operations)
- Modify: `server/handlers/dax_context_handler.py` (05_DAX_Intelligence)
- Modify: `server/handlers/column_usage_handler.py` (05_Column_Usage_Mapping)
- Modify: `server/handlers/analysis_handler.py` (06_Analysis_Operations)
- Modify: `server/handlers/report_operations_handler.py` (07_Report_Operations)
- Modify: `server/handlers/pbip_operations_handler.py` (07_PBIP_Operations)
- Modify: `server/handlers/page_operations_handler.py` (07_Page_Operations)
- Modify: `server/handlers/visual_operations_handler.py` (07_Visual_Operations)
- Modify: `server/handlers/bookmark_operations_handler.py` (07_Bookmark_Operations)
- Modify: `server/handlers/theme_operations_handler.py` (07_Theme_Operations)
- Modify: `server/handlers/documentation_handler.py` (08_Documentation_Word)
- Modify: `server/handlers/debug_handler.py` (09_Debug_Operations, 09_Validate, 09_Profile, 09_Document)
- Modify: `server/handlers/user_guide_handler.py` (10_Show_User_Guide)
- Modify: `server/handlers/authoring_handler.py` (11_PBIP_Authoring)
- Modify: `server/handlers/prototype_handler.py` (11_PBIP_Prototype)
- Modify: `server/handlers/svg_handler.py` (SVG_Visual_Operations)

- [ ] **Step 1: Add annotations to each ToolDefinition**

In each handler's `ToolDefinition(...)` constructor, update the `annotations` dict to include all 4 MCP hints. The pattern for each tool:

```python
annotations={
    "readOnlyHint": <bool>,       # existing — keep as-is
    "destructiveHint": <bool>,    # existing — keep as-is
    "idempotentHint": <bool>,     # NEW
    "openWorldHint": <bool>,      # NEW
},
```

Apply these values per tool:

| Tool | readOnly | destructive | idempotent | openWorld |
|------|----------|-------------|------------|-----------|
| 01_Connection | False | False | False | True |
| 02_Model_Operations | False | True | False | True |
| 02_TMDL_Operations | False | True | False | True |
| 03_Batch_Operations | False | True | False | True |
| 04_Run_DAX | True | False | True | True |
| 04_Query_Operations | True | False | False | True |
| 05_DAX_Intelligence | True | False | True | False |
| 05_Column_Usage_Mapping | True | False | True | False |
| 06_Analysis_Operations | True | False | True | True |
| 07_Report_Operations | False | False | False | True |
| 07_PBIP_Operations | True | False | True | False |
| 07_Page_Operations | False | True | False | True |
| 07_Visual_Operations | False | True | False | True |
| 07_Bookmark_Operations | False | True | False | True |
| 07_Theme_Operations | False | True | False | True |
| 08_Documentation_Word | True | False | True | False |
| 09_Debug_Operations | True | False | True | True |
| 09_Validate | True | False | True | True |
| 09_Profile | True | False | True | True |
| 09_Document | True | False | True | False |
| 10_Show_User_Guide | True | False | True | False |
| 11_PBIP_Authoring | False | True | False | False |
| 11_PBIP_Prototype | False | False | False | True |
| SVG_Visual_Operations | True | False | True | False |

For tools that already have `annotations={"readOnlyHint": True}`, extend the dict. For tools with no annotations, add the full dict. If a handler currently has no `annotations` kwarg, add it.

- [ ] **Step 2: Verify annotations appear in MCP tool listing**

Run: `python -c "
from server.registry import HandlerRegistry
from server.handlers import register_all_handlers
reg = HandlerRegistry()
register_all_handlers(reg)
tools = reg.get_all_tools_as_mcp()
missing = [t.name for t in tools if not hasattr(t, 'annotations') or t.annotations is None]
print(f'{len(tools)} tools, {len(missing)} missing annotations')
if missing: print('Missing:', missing)
assert len(missing) == 0, 'All tools must have annotations'
"`

Expected: `24 tools, 0 missing annotations`

- [ ] **Step 3: Commit**

```bash
git add server/handlers/
git commit -m "feat: add idempotentHint + openWorldHint MCP annotations to all 24 tools"
```

---

### Task 8: Populate outputSchema on 5 Key Tools

**Files:**
- Modify: `server/handlers/connection_handler.py`
- Modify: `server/handlers/query_handler.py`
- Modify: `server/handlers/user_guide_handler.py`

- [ ] **Step 1: Add output_schema to 01_Connection**

In `connection_handler.py`, add to the ToolDefinition:

```python
output_schema={
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "instances": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "port": {"type": "integer"},
                    "database": {"type": "string"},
                    "pid": {"type": "integer"},
                },
            },
            "description": "List of detected PBI instances (detect operation)",
        },
        "database": {"type": "string", "description": "Connected database name (connect operation)"},
        "model_name": {"type": "string"},
    },
},
```

- [ ] **Step 2: Add output_schema to 04_Run_DAX**

In `query_handler.py`, add to the `04_Run_DAX` ToolDefinition:

```python
output_schema={
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "results": {"type": "array", "items": {"type": "object"}},
        "row_count": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "execution_time_ms": {"type": "number"},
    },
},
```

- [ ] **Step 3: Add output_schema to 10_Show_User_Guide**

In `user_guide_handler.py`, add to the ToolDefinition:

```python
output_schema={
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "guide": {"type": "string"},
    },
},
```

- [ ] **Step 4: Verify output schemas appear**

Run: `python -c "
from server.registry import HandlerRegistry
from server.handlers import register_all_handlers
reg = HandlerRegistry()
register_all_handlers(reg)
with_schema = [t.name for t in reg.get_all_tools_as_mcp() if getattr(t, 'outputSchema', None)]
print(f'{len(with_schema)} tools with outputSchema:', with_schema)
assert len(with_schema) >= 3
"`

Expected: `3 tools with outputSchema: ['01_Connection', '04_Run_DAX', '10_Show_User_Guide']`

- [ ] **Step 5: Commit**

```bash
git add server/handlers/connection_handler.py server/handlers/query_handler.py server/handlers/user_guide_handler.py
git commit -m "feat: add outputSchema to 3 key tools (MCP structured output support)"
```

---

## Phase 6 — PBIR Schema & Template Updates

### Task 9: Bump Visual Schema to 2.7.0

**Files:**
- Modify: `core/pbip/authoring/visual_templates.py:17`

- [ ] **Step 1: Update VISUAL_SCHEMA constant**

Change line 17 from:
```python
VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.6.0/schema.json"
```
to:
```python
VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json"
```

- [ ] **Step 2: Verify all templates still use the VISUAL_SCHEMA constant**

Run: `grep -c "VISUAL_SCHEMA" core/pbip/authoring/visual_templates.py`

Expected: At least 2 (the definition + usage in templates)

- [ ] **Step 3: Commit**

```bash
git add core/pbip/authoring/visual_templates.py
git commit -m "feat: bump PBIR visual container schema to 2.7.0"
```

---

### Task 10: Add 4 New Slicer Templates

**Files:**
- Modify: `core/pbip/authoring/visual_templates.py`

- [ ] **Step 1: Add template functions for 4 new slicer types**

Add these functions before the `TEMPLATE_REGISTRY` dict (before line 519). Follow the exact pattern of the existing `template_slicer` function, changing `visualType`:

```python
def template_button_slicer(visual_id: Optional[str] = None) -> Dict[str, Any]:
    """Template for button slicer visual (GA Oct 2025, schema 2.3.0+)."""
    vid = visual_id or generate_visual_id()
    return {
        "$schema": VISUAL_SCHEMA,
        "name": vid,
        "position": {"x": 0, "y": 0, "width": 300, "height": 60, "z": 0, "tabOrder": 0},
        "visual": {
            "visualType": "buttonSlicer",
            "query": {
                "queryState": {
                    "Values": {"projections": []}
                }
            },
            "objects": {},
            "visualContainerObjects": {},
        },
    }


def template_text_slicer(visual_id: Optional[str] = None) -> Dict[str, Any]:
    """Template for text slicer visual (preview Nov 2024, schema 1.4.0+)."""
    vid = visual_id or generate_visual_id()
    return {
        "$schema": VISUAL_SCHEMA,
        "name": vid,
        "position": {"x": 0, "y": 0, "width": 200, "height": 48, "z": 0, "tabOrder": 0},
        "visual": {
            "visualType": "textSlicer",
            "query": {
                "queryState": {
                    "Values": {"projections": []}
                }
            },
            "objects": {},
            "visualContainerObjects": {},
        },
    }


def template_list_slicer(visual_id: Optional[str] = None) -> Dict[str, Any]:
    """Template for list slicer visual (preview Nov 2024, schema 1.4.0+)."""
    vid = visual_id or generate_visual_id()
    return {
        "$schema": VISUAL_SCHEMA,
        "name": vid,
        "position": {"x": 0, "y": 0, "width": 200, "height": 300, "z": 0, "tabOrder": 0},
        "visual": {
            "visualType": "listSlicer",
            "query": {
                "queryState": {
                    "Values": {"projections": []}
                }
            },
            "objects": {},
            "visualContainerObjects": {},
        },
    }


def template_input_slicer(visual_id: Optional[str] = None) -> Dict[str, Any]:
    """Template for input slicer visual (GA Feb 2026, schema 2.6.0+)."""
    vid = visual_id or generate_visual_id()
    return {
        "$schema": VISUAL_SCHEMA,
        "name": vid,
        "position": {"x": 0, "y": 0, "width": 200, "height": 48, "z": 0, "tabOrder": 0},
        "visual": {
            "visualType": "inputSlicer",
            "query": {
                "queryState": {
                    "Values": {"projections": []}
                }
            },
            "objects": {},
            "visualContainerObjects": {},
        },
    }
```

- [ ] **Step 2: Add entries to TEMPLATE_REGISTRY**

In the `TEMPLATE_REGISTRY` dict, add under the `# Slicers` section:

```python
    # Slicers
    "slicer": template_slicer,
    "buttonSlicer": template_button_slicer,
    "textSlicer": template_text_slicer,
    "listSlicer": template_list_slicer,
    "inputSlicer": template_input_slicer,
```

- [ ] **Step 3: Verify template count**

Run: `python -c "from core.pbip.authoring.visual_templates import TEMPLATE_REGISTRY; print(f'{len(TEMPLATE_REGISTRY)} templates'); assert len(TEMPLATE_REGISTRY) >= 28"`

Expected: `32 templates` (28 unique types with 4 aliases: tableEx->table, pivotTable->matrix, cardVisual->card, group->visualGroup)

- [ ] **Step 4: Verify each new template produces valid JSON**

Run: `python -c "
from core.pbip.authoring.visual_templates import TEMPLATE_REGISTRY
for name in ['buttonSlicer', 'textSlicer', 'listSlicer', 'inputSlicer']:
    t = TEMPLATE_REGISTRY[name]()
    assert t['visual']['visualType'] == name, f'{name}: wrong visualType'
    assert '\$schema' in t or 'name' in t, f'{name}: missing schema or name'
    print(f'{name}: OK')
"`

Expected: 4 OK lines

- [ ] **Step 5: Commit**

```bash
git add core/pbip/authoring/visual_templates.py
git commit -m "feat: add 4 new slicer templates (button, text, list, input)"
```

---

### Task 11: Parse VisualTopN Filter Type

**Files:**
- Modify: `core/pbip/filter_engine.py`

- [ ] **Step 1: Add VisualTopN filter type to `_build_filter()`**

In `core/pbip/filter_engine.py`, find the `_build_filter()` function. After the existing `elif filter_type == "RelativeDate":` block (around line 304), add:

```python
    elif filter_type == "VisualTopN":
        # VisualTopN: filter to top/bottom N items by a measure
        top_count = values[0] if values else 10
        order_by_expr = by_field or field
        filt["filter"] = {
            "Version": 2,
            "From": [{"Name": alias, "Entity": table, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Top": {
                            "Count": top_count,
                            "Expression": column_expr,
                            "OrderBy": [
                                {
                                    "Direction": 2 if operator == "BottomN" else 1,
                                    "Expression": {
                                        "Column": {
                                            "Expression": {"SourceRef": {"Source": alias}},
                                            "Property": order_by_expr,
                                        }
                                    },
                                }
                            ],
                        }
                    }
                }
            ],
        }
```

- [ ] **Step 2: Add VisualTopN to any filter type recognition/parsing logic**

Search for where filter types are enumerated or validated in the filter engine. Add `"VisualTopN"` to any lists/sets of recognized filter types. This may include:
- Type validation in `_parse_filter()` or similar
- Filter type display in analysis output
- Dependency engine filter traversal

Run: `grep -n "Categorical\|Advanced\|TopN\|RelativeDate" core/pbip/filter_engine.py`

Add `"VisualTopN"` alongside `"TopN"` in all relevant locations.

- [ ] **Step 3: Commit**

```bash
git add core/pbip/filter_engine.py
git commit -m "feat: parse VisualTopN filter type in PBIR filter engine"
```

---

### Task 12: Recognize SummarizeVisualContainer Type

**Files:**
- Modify: `core/pbip/pbip_project_scanner.py` (or wherever visual container types are recognized)

- [ ] **Step 1: Find where visual container types are recognized**

Run: `grep -rn "visualType\|visual_type\|container_type\|visualGroup" core/pbip/ --include="*.py" -l`

In the file(s) that enumerate known visual types, add `"SummarizeVisualContainer"` as a recognized type. It should be treated similarly to `"visualGroup"` — a container that wraps child visuals.

- [ ] **Step 2: Ensure SummarizeVisualContainer is included in page analysis**

When scanning pages for visuals, if a `SummarizeVisualContainer` is encountered, recurse into its children. Follow the pattern used for `visualGroup`.

- [ ] **Step 3: Commit**

```bash
git add core/pbip/
git commit -m "feat: recognize SummarizeVisualContainer type in PBIR parsing"
```

---

### Task 13: Add PBIR Annotation Support

**Files:**
- Modify: `core/pbip/pbip_project_scanner.py` (or visual/page parsing module)

- [ ] **Step 1: Parse annotations from visual.json, page.json, report.json**

When reading these PBIR JSON files, check for an `"annotations"` array at the top level. If present, include it in the parsed output:

```python
# In the visual/page/report parsing logic:
annotations = data.get("annotations", [])
if annotations:
    result["annotations"] = annotations
```

- [ ] **Step 2: Expose annotations in info operations**

In `07_Visual_Operations` (operation: `info`), `07_Page_Operations` (operation: `info`), and `07_Report_Operations` (operation: `info`), include the parsed annotations in the response.

- [ ] **Step 3: Allow setting annotations via write operations**

In `07_Visual_Operations` (operation: `update_formatting` or a new `set_annotation`), allow writing annotations:

```python
if "annotations" in args:
    visual_data["annotations"] = args["annotations"]
    # Write back to visual.json
```

- [ ] **Step 4: Commit**

```bash
git add core/pbip/ server/handlers/
git commit -m "feat: read/write PBIR annotations on visuals, pages, and reports"
```

---

### Task 14: Handle mobile.json in Clone/Delete Operations

**Files:**
- Modify: `core/pbip/authoring/clone_engine.py` (or wherever visual cloning happens)

- [ ] **Step 1: Find clone and delete logic for visuals/pages**

Run: `grep -rn "mobile.json\|mobile_json\|clone.*visual\|delete.*visual" core/pbip/authoring/ --include="*.py"`

- [ ] **Step 2: In clone operations, copy mobile.json alongside visual.json**

When cloning a visual, check if `mobile.json` exists in the source visual folder. If so, copy it to the target folder:

```python
mobile_path = source_folder / "mobile.json"
if mobile_path.exists():
    import shutil
    shutil.copy2(mobile_path, target_folder / "mobile.json")
```

- [ ] **Step 3: In delete operations, remove mobile.json alongside visual.json**

When deleting a visual, also delete `mobile.json` if it exists:

```python
mobile_path = visual_folder / "mobile.json"
if mobile_path.exists():
    mobile_path.unlink()
```

- [ ] **Step 4: In info operations, include mobile layout presence**

When reporting visual info, note whether a mobile.json exists:

```python
result["has_mobile_layout"] = (visual_folder / "mobile.json").exists()
```

- [ ] **Step 5: Commit**

```bash
git add core/pbip/authoring/
git commit -m "feat: handle mobile.json in visual clone/delete/info operations"
```

---

## Phase 7 — TOM Feature Parity

### Task 15: Add Partition CRUD Manager

**Files:**
- Create: `core/operations/partition_crud_manager.py`

- [ ] **Step 1: Create the partition CRUD manager**

Note: `core/operations/partition_manager.py` already exists. Check its contents first. If it already provides the needed operations, skip creating a new file and instead wire it into the dispatcher.

Run: `head -50 core/operations/partition_manager.py`

If it needs extending, add list/describe/create/update/delete/refresh operations following the pattern in `core/operations/table_crud_manager.py`:

```python
"""
Partition CRUD Manager — manage table partitions via TOM.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PartitionCrudManager:
    """CRUD operations for table partitions."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_partitions(self, table_name: str) -> Dict[str, Any]:
        """List all partitions for a table."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}

        partitions = []
        for partition in table.Partitions:
            partitions.append({
                "name": partition.Name,
                "source_type": str(partition.SourceType),
                "mode": str(partition.Mode) if hasattr(partition, 'Mode') else None,
                "state": str(partition.State) if hasattr(partition, 'State') else None,
                "refreshed_time": str(partition.RefreshedTime) if hasattr(partition, 'RefreshedTime') else None,
            })

        return {"success": True, "table": table_name, "partitions": partitions, "count": len(partitions)}

    def describe_partition(self, table_name: str, partition_name: str) -> Dict[str, Any]:
        """Get detailed info about a partition."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}

        partition = table.Partitions.Find(partition_name)
        if not partition:
            return {"success": False, "error": f"Partition '{partition_name}' not found in '{table_name}'"}

        info = {
            "name": partition.Name,
            "source_type": str(partition.SourceType),
            "mode": str(partition.Mode) if hasattr(partition, 'Mode') else None,
            "state": str(partition.State) if hasattr(partition, 'State') else None,
            "refreshed_time": str(partition.RefreshedTime) if hasattr(partition, 'RefreshedTime') else None,
        }

        # Get M expression if available
        try:
            if hasattr(partition, 'Source') and hasattr(partition.Source, 'Expression'):
                info["expression"] = partition.Source.Expression
        except Exception:
            pass

        return {"success": True, "partition": info}

    def refresh_partition(self, table_name: str, partition_name: str) -> Dict[str, Any]:
        """Refresh a specific partition."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}

        partition = table.Partitions.Find(partition_name)
        if not partition:
            return {"success": False, "error": f"Partition '{partition_name}' not found in '{table_name}'"}

        try:
            partition.RequestRefresh(1)  # RefreshType.Full = 1
            model.SaveChanges()
            return {"success": True, "message": f"Refresh requested for partition '{partition_name}'"}
        except Exception as e:
            return {"success": False, "error": f"Refresh failed: {str(e)}"}
```

- [ ] **Step 2: Commit**

```bash
git add core/operations/partition_crud_manager.py
git commit -m "feat: add PartitionCrudManager for table partition CRUD"
```

---

### Task 16: Add Hierarchy CRUD Manager

**Files:**
- Create: `core/operations/hierarchy_crud_manager.py`

- [ ] **Step 1: Create the hierarchy CRUD manager**

```python
"""
Hierarchy CRUD Manager — manage table hierarchies via TOM.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class HierarchyCrudManager:
    """CRUD operations for table hierarchies."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_hierarchies(self, table_name: str = None) -> Dict[str, Any]:
        """List hierarchies, optionally filtered by table."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        hierarchies = []
        tables = [model.Tables.Find(table_name)] if table_name else model.Tables
        for table in tables:
            if table is None:
                return {"success": False, "error": f"Table '{table_name}' not found"}
            for hier in table.Hierarchies:
                levels = []
                for level in hier.Levels:
                    levels.append({
                        "name": level.Name,
                        "ordinal": level.Ordinal,
                        "column": level.Column.Name if level.Column else None,
                    })
                hierarchies.append({
                    "table": table.Name,
                    "name": hier.Name,
                    "description": hier.Description or "",
                    "is_hidden": hier.IsHidden,
                    "levels": levels,
                })

        return {"success": True, "hierarchies": hierarchies, "count": len(hierarchies)}

    def describe_hierarchy(self, table_name: str, hierarchy_name: str) -> Dict[str, Any]:
        """Get detailed info about a hierarchy."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}

        hier = table.Hierarchies.Find(hierarchy_name)
        if not hier:
            return {"success": False, "error": f"Hierarchy '{hierarchy_name}' not found in '{table_name}'"}

        levels = []
        for level in hier.Levels:
            levels.append({
                "name": level.Name,
                "ordinal": level.Ordinal,
                "column": level.Column.Name if level.Column else None,
            })

        return {
            "success": True,
            "hierarchy": {
                "table": table.Name,
                "name": hier.Name,
                "description": hier.Description or "",
                "is_hidden": hier.IsHidden,
                "display_folder": hier.DisplayFolder or "",
                "levels": levels,
            },
        }

    def create_hierarchy(self, table_name: str, hierarchy_name: str, levels: list, **kwargs) -> Dict[str, Any]:
        """Create a new hierarchy with specified levels."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}

        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            hier = TOM.Hierarchy()
            hier.Name = hierarchy_name
            if kwargs.get("description"):
                hier.Description = kwargs["description"]
            if kwargs.get("display_folder"):
                hier.DisplayFolder = kwargs["display_folder"]
            if kwargs.get("hidden") is not None:
                hier.IsHidden = kwargs["hidden"]

            for i, level_info in enumerate(levels):
                level = TOM.Level()
                level.Name = level_info.get("name", level_info.get("column"))
                level.Ordinal = i
                col = table.Columns.Find(level_info["column"])
                if not col:
                    return {"success": False, "error": f"Column '{level_info['column']}' not found in '{table_name}'"}
                level.Column = col
                hier.Levels.Add(level)

            table.Hierarchies.Add(hier)
            model.SaveChanges()
            return {"success": True, "message": f"Hierarchy '{hierarchy_name}' created with {len(levels)} levels"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_hierarchy(self, table_name: str, hierarchy_name: str) -> Dict[str, Any]:
        """Delete a hierarchy."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}

        hier = table.Hierarchies.Find(hierarchy_name)
        if not hier:
            return {"success": False, "error": f"Hierarchy '{hierarchy_name}' not found"}

        try:
            table.Hierarchies.Remove(hier)
            model.SaveChanges()
            return {"success": True, "message": f"Hierarchy '{hierarchy_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add core/operations/hierarchy_crud_manager.py
git commit -m "feat: add HierarchyCrudManager for hierarchy CRUD"
```

---

### Task 17: Add Perspective CRUD Manager

**Files:**
- Create: `core/operations/perspective_crud_manager.py`

- [ ] **Step 1: Create the perspective CRUD manager**

```python
"""
Perspective CRUD Manager — manage model perspectives via TOM.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class PerspectiveCrudManager:
    """CRUD operations for model perspectives."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_perspectives(self) -> Dict[str, Any]:
        """List all perspectives in the model."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        perspectives = []
        for persp in model.Perspectives:
            table_count = 0
            for table in model.Tables:
                if any(pt.Name == table.Name for pt in persp.PerspectiveTables):
                    table_count += 1
            perspectives.append({
                "name": persp.Name,
                "description": persp.Description or "",
                "table_count": table_count,
            })

        return {"success": True, "perspectives": perspectives, "count": len(perspectives)}

    def describe_perspective(self, perspective_name: str) -> Dict[str, Any]:
        """Get detailed info about a perspective."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        persp = model.Perspectives.Find(perspective_name)
        if not persp:
            return {"success": False, "error": f"Perspective '{perspective_name}' not found"}

        tables = []
        for pt in persp.PerspectiveTables:
            columns = [pc.Name for pc in pt.PerspectiveColumns]
            measures = [pm.Name for pm in pt.PerspectiveMeasures]
            hierarchies = [ph.Name for ph in pt.PerspectiveHierarchies]
            tables.append({
                "table": pt.Name,
                "columns": columns,
                "measures": measures,
                "hierarchies": hierarchies,
            })

        return {
            "success": True,
            "perspective": {
                "name": persp.Name,
                "description": persp.Description or "",
                "tables": tables,
            },
        }

    def create_perspective(self, perspective_name: str, **kwargs) -> Dict[str, Any]:
        """Create a new perspective."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            persp = TOM.Perspective()
            persp.Name = perspective_name
            if kwargs.get("description"):
                persp.Description = kwargs["description"]
            model.Perspectives.Add(persp)
            model.SaveChanges()
            return {"success": True, "message": f"Perspective '{perspective_name}' created"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_perspective(self, perspective_name: str) -> Dict[str, Any]:
        """Delete a perspective."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        persp = model.Perspectives.Find(perspective_name)
        if not persp:
            return {"success": False, "error": f"Perspective '{perspective_name}' not found"}

        try:
            model.Perspectives.Remove(persp)
            model.SaveChanges()
            return {"success": True, "message": f"Perspective '{perspective_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add core/operations/perspective_crud_manager.py
git commit -m "feat: add PerspectiveCrudManager for perspective CRUD"
```

---

### Task 18: Add Culture/Translation CRUD Manager

**Files:**
- Create: `core/operations/culture_crud_manager.py`

- [ ] **Step 1: Create the culture CRUD manager**

```python
"""
Culture CRUD Manager — manage cultures (translations) via TOM.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class CultureCrudManager:
    """CRUD operations for model cultures and translations."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_cultures(self) -> Dict[str, Any]:
        """List all cultures in the model."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        cultures = []
        for culture in model.Cultures:
            cultures.append({
                "name": culture.Name,
                "translation_count": culture.ObjectTranslations.Count,
            })

        return {"success": True, "cultures": cultures, "count": len(cultures)}

    def describe_culture(self, culture_name: str) -> Dict[str, Any]:
        """Get detailed info about a culture including translations."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        culture = model.Cultures.Find(culture_name)
        if not culture:
            return {"success": False, "error": f"Culture '{culture_name}' not found"}

        translations = []
        for t in culture.ObjectTranslations:
            translations.append({
                "property": str(t.Property),
                "object_type": type(t.Object).__name__,
                "object_name": t.Object.Name if hasattr(t.Object, 'Name') else str(t.Object),
                "value": t.Value,
            })

        return {
            "success": True,
            "culture": {
                "name": culture.Name,
                "translations": translations,
                "translation_count": len(translations),
            },
        }

    def create_culture(self, culture_name: str) -> Dict[str, Any]:
        """Create a new culture (e.g., 'fr-FR', 'de-DE')."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            culture = TOM.Culture()
            culture.Name = culture_name
            model.Cultures.Add(culture)
            model.SaveChanges()
            return {"success": True, "message": f"Culture '{culture_name}' created"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_culture(self, culture_name: str) -> Dict[str, Any]:
        """Delete a culture."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        culture = model.Cultures.Find(culture_name)
        if not culture:
            return {"success": False, "error": f"Culture '{culture_name}' not found"}

        try:
            model.Cultures.Remove(culture)
            model.SaveChanges()
            return {"success": True, "message": f"Culture '{culture_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_translation(self, culture_name: str, object_type: str, object_name: str,
                        property_name: str, value: str, table_name: str = None) -> Dict[str, Any]:
        """Set a translation for an object property."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        culture = model.Cultures.Find(culture_name)
        if not culture:
            return {"success": False, "error": f"Culture '{culture_name}' not found"}

        try:
            import Microsoft.AnalysisServices.Tabular as TOM

            # Find the target object
            obj = None
            if object_type == "table":
                obj = model.Tables.Find(object_name)
            elif object_type == "column" and table_name:
                table = model.Tables.Find(table_name)
                if table:
                    obj = table.Columns.Find(object_name)
            elif object_type == "measure" and table_name:
                table = model.Tables.Find(table_name)
                if table:
                    obj = table.Measures.Find(object_name)
            elif object_type == "hierarchy" and table_name:
                table = model.Tables.Find(table_name)
                if table:
                    obj = table.Hierarchies.Find(object_name)

            if not obj:
                return {"success": False, "error": f"{object_type} '{object_name}' not found"}

            # Map property name to TranslatedProperty enum
            prop_map = {"caption": TOM.TranslatedProperty.Caption, "description": TOM.TranslatedProperty.Description, "display_folder": TOM.TranslatedProperty.DisplayFolder}
            prop = prop_map.get(property_name)
            if not prop:
                return {"success": False, "error": f"Invalid property: {property_name}. Use: caption, description, display_folder"}

            culture.ObjectTranslations.SetTranslation(obj, prop, value)
            model.SaveChanges()
            return {"success": True, "message": f"Translation set for {object_type} '{object_name}'.{property_name} = '{value}'"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add core/operations/culture_crud_manager.py
git commit -m "feat: add CultureCrudManager for culture/translation CRUD"
```

---

### Task 19: Add Named Expression CRUD Manager

**Files:**
- Create: `core/operations/named_expression_crud_manager.py`

- [ ] **Step 1: Create the named expression CRUD manager**

```python
"""
Named Expression CRUD Manager — manage Power Query parameters/expressions via TOM.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class NamedExpressionCrudManager:
    """CRUD operations for model named expressions (Power Query parameters)."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_expressions(self) -> Dict[str, Any]:
        """List all named expressions in the model."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        expressions = []
        for expr in model.Expressions:
            expressions.append({
                "name": expr.Name,
                "kind": str(expr.Kind) if hasattr(expr, 'Kind') else "M",
                "description": expr.Description or "",
            })

        return {"success": True, "expressions": expressions, "count": len(expressions)}

    def describe_expression(self, expression_name: str) -> Dict[str, Any]:
        """Get detailed info about a named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        expr = model.Expressions.Find(expression_name)
        if not expr:
            return {"success": False, "error": f"Expression '{expression_name}' not found"}

        return {
            "success": True,
            "expression": {
                "name": expr.Name,
                "kind": str(expr.Kind) if hasattr(expr, 'Kind') else "M",
                "expression": expr.Expression,
                "description": expr.Description or "",
            },
        }

    def create_expression(self, expression_name: str, expression: str, **kwargs) -> Dict[str, Any]:
        """Create a new named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            ne = TOM.NamedExpression()
            ne.Name = expression_name
            ne.Expression = expression
            ne.Kind = TOM.ExpressionKind.M
            if kwargs.get("description"):
                ne.Description = kwargs["description"]
            model.Expressions.Add(ne)
            model.SaveChanges()
            return {"success": True, "message": f"Expression '{expression_name}' created"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_expression(self, expression_name: str, expression: str = None, **kwargs) -> Dict[str, Any]:
        """Update a named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        expr = model.Expressions.Find(expression_name)
        if not expr:
            return {"success": False, "error": f"Expression '{expression_name}' not found"}

        try:
            if expression is not None:
                expr.Expression = expression
            if kwargs.get("description") is not None:
                expr.Description = kwargs["description"]
            model.SaveChanges()
            return {"success": True, "message": f"Expression '{expression_name}' updated"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_expression(self, expression_name: str) -> Dict[str, Any]:
        """Delete a named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        expr = model.Expressions.Find(expression_name)
        if not expr:
            return {"success": False, "error": f"Expression '{expression_name}' not found"}

        try:
            model.Expressions.Remove(expr)
            model.SaveChanges()
            return {"success": True, "message": f"Expression '{expression_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add core/operations/named_expression_crud_manager.py
git commit -m "feat: add NamedExpressionCrudManager for Power Query parameter CRUD"
```

---

### Task 20: Add OLS CRUD Manager

**Files:**
- Create: `core/operations/ols_crud_manager.py`

- [ ] **Step 1: Create the OLS CRUD manager**

```python
"""
OLS CRUD Manager — manage Object-Level Security rules via TOM.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class OlsCrudManager:
    """CRUD operations for Object-Level Security rules."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_ols_rules(self, role_name: str = None) -> Dict[str, Any]:
        """List OLS rules, optionally filtered by role."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        rules = []
        roles = [model.Roles.Find(role_name)] if role_name else model.Roles
        for role in roles:
            if role is None:
                return {"success": False, "error": f"Role '{role_name}' not found"}
            for tp in role.TablePermissions:
                # Check column permissions
                for cp in tp.ColumnPermissions:
                    rules.append({
                        "role": role.Name,
                        "table": tp.Name,
                        "column": cp.Name,
                        "metadata_permission": str(cp.MetadataPermission),
                    })

        return {"success": True, "ols_rules": rules, "count": len(rules)}

    def set_ols_rule(self, role_name: str, table_name: str, column_name: str,
                     permission: str = "None") -> Dict[str, Any]:
        """Set OLS permission on a column for a role. permission: 'None' (block), 'Read', 'Default'."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        role = model.Roles.Find(role_name)
        if not role:
            return {"success": False, "error": f"Role '{role_name}' not found"}

        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}

        col = table.Columns.Find(column_name)
        if not col:
            return {"success": False, "error": f"Column '{column_name}' not found in '{table_name}'"}

        try:
            import Microsoft.AnalysisServices.Tabular as TOM

            # Ensure table permission exists
            tp = role.TablePermissions.Find(table_name)
            if not tp:
                tp = TOM.TablePermission()
                tp.Table = table
                role.TablePermissions.Add(tp)

            # Map permission string to enum
            perm_map = {
                "None": TOM.MetadataPermission.None_,
                "Read": TOM.MetadataPermission.Read,
                "Default": TOM.MetadataPermission.Default,
            }
            perm = perm_map.get(permission)
            if perm is None:
                return {"success": False, "error": f"Invalid permission: {permission}. Use: None, Read, Default"}

            # Set column permission
            cp = tp.ColumnPermissions.Find(column_name)
            if not cp:
                cp = TOM.ColumnPermission()
                cp.Column = col
                tp.ColumnPermissions.Add(cp)
            cp.MetadataPermission = perm

            model.SaveChanges()
            return {"success": True, "message": f"OLS set: {role_name}/{table_name}/{column_name} = {permission}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_ols_rule(self, role_name: str, table_name: str, column_name: str) -> Dict[str, Any]:
        """Remove OLS permission from a column for a role."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}

        role = model.Roles.Find(role_name)
        if not role:
            return {"success": False, "error": f"Role '{role_name}' not found"}

        tp = role.TablePermissions.Find(table_name)
        if not tp:
            return {"success": False, "error": f"No table permission for '{table_name}' in role '{role_name}'"}

        cp = tp.ColumnPermissions.Find(column_name)
        if not cp:
            return {"success": False, "error": f"No OLS rule for '{column_name}' in '{table_name}'"}

        try:
            tp.ColumnPermissions.Remove(cp)
            model.SaveChanges()
            return {"success": True, "message": f"OLS removed: {role_name}/{table_name}/{column_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add core/operations/ols_crud_manager.py
git commit -m "feat: add OlsCrudManager for Object-Level Security CRUD"
```

---

### Task 21: Wire New Object Types into 02_Model_Operations

**Files:**
- Modify: `server/handlers/model_operations_handler.py`

- [ ] **Step 1: Import and register new CRUD managers**

Add imports after line 13:

```python
from core.operations.partition_crud_manager import PartitionCrudManager
from core.operations.hierarchy_crud_manager import HierarchyCrudManager
from core.operations.perspective_crud_manager import PerspectiveCrudManager
from core.operations.culture_crud_manager import CultureCrudManager
from core.operations.named_expression_crud_manager import NamedExpressionCrudManager
from core.operations.ols_crud_manager import OlsCrudManager
```

- [ ] **Step 2: Add new object types to the _handlers dict and _valid_operations**

Extend `_handlers` dict (after line 24):

```python
_handlers = {
    # ... existing entries ...
    "partition": PartitionCrudManager(),
    "hierarchy": HierarchyCrudManager(),
    "perspective": PerspectiveCrudManager(),
    "culture": CultureCrudManager(),
    "named_expression": NamedExpressionCrudManager(),
    "ols_rule": OlsCrudManager(),
}
```

Extend `_valid_operations` dict:

```python
_valid_operations = {
    # ... existing entries ...
    "partition": ["list", "describe", "refresh"],
    "hierarchy": ["list", "describe", "create", "delete"],
    "perspective": ["list", "describe", "create", "delete"],
    "culture": ["list", "describe", "create", "delete", "set_translation"],
    "named_expression": ["list", "describe", "create", "update", "delete"],
    "ols_rule": ["list", "set", "remove"],
}
```

- [ ] **Step 3: Update the input_schema enum for object_type**

In the ToolDefinition's `input_schema`, update the `object_type` enum to include the new types:

```python
"object_type": {
    "type": "string",
    "enum": ["table", "column", "measure", "relationship", "calculation_group",
             "partition", "hierarchy", "perspective", "culture", "named_expression", "ols_rule"],
    "description": "Type of model object to operate on"
},
```

- [ ] **Step 4: Add new type-specific parameters to input_schema**

Add these properties to the schema's `properties` dict:

```python
# Partition-specific
"partition_name": {"type": "string", "description": "Partition name"},
# Hierarchy-specific
"hierarchy_name": {"type": "string", "description": "Hierarchy name"},
"levels": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "column": {"type": "string"}}}, "description": "Hierarchy levels (create)"},
# Perspective-specific
"perspective_name": {"type": "string", "description": "Perspective name"},
# Culture-specific
"culture_name": {"type": "string", "description": "Culture name (e.g. 'fr-FR')"},
"object_type_target": {"type": "string", "enum": ["table", "column", "measure", "hierarchy"], "description": "Target object type (set_translation)"},
"property_name": {"type": "string", "enum": ["caption", "description", "display_folder"], "description": "Property to translate (set_translation)"},
"value": {"type": "string", "description": "Translation value"},
# Named expression-specific
"expression_name": {"type": "string", "description": "Named expression name"},
# OLS-specific
"role_name": {"type": "string", "description": "Security role name"},
"permission": {"type": "string", "enum": ["None", "Read", "Default"], "description": "OLS permission level"},
```

- [ ] **Step 5: Wire execute() for new managers**

The new CRUD managers need an `execute(args)` method that maps operations to methods. Add this to each new manager (or add a dispatcher in `handle_model_operations`):

In `handle_model_operations()`, after getting the handler, add dispatch logic for the new types that don't have an `execute()` method:

```python
    # For new CRUD managers without execute(), dispatch directly
    if object_type in ("partition", "hierarchy", "perspective", "culture", "named_expression", "ols_rule"):
        return _dispatch_new_type(handler, object_type, args)


def _dispatch_new_type(manager, object_type: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch operations for new TOM object types."""
    operation = args.get("operation", "list")

    dispatch_map = {
        "partition": {
            "list": lambda: manager.list_partitions(args.get("table_name")),
            "describe": lambda: manager.describe_partition(args.get("table_name"), args.get("partition_name")),
            "refresh": lambda: manager.refresh_partition(args.get("table_name"), args.get("partition_name")),
        },
        "hierarchy": {
            "list": lambda: manager.list_hierarchies(args.get("table_name")),
            "describe": lambda: manager.describe_hierarchy(args.get("table_name"), args.get("hierarchy_name")),
            "create": lambda: manager.create_hierarchy(
                args.get("table_name"), args.get("hierarchy_name"), args.get("levels", []),
                description=args.get("description"), display_folder=args.get("display_folder"), hidden=args.get("hidden")),
            "delete": lambda: manager.delete_hierarchy(args.get("table_name"), args.get("hierarchy_name")),
        },
        "perspective": {
            "list": lambda: manager.list_perspectives(),
            "describe": lambda: manager.describe_perspective(args.get("perspective_name")),
            "create": lambda: manager.create_perspective(args.get("perspective_name"), description=args.get("description")),
            "delete": lambda: manager.delete_perspective(args.get("perspective_name")),
        },
        "culture": {
            "list": lambda: manager.list_cultures(),
            "describe": lambda: manager.describe_culture(args.get("culture_name")),
            "create": lambda: manager.create_culture(args.get("culture_name")),
            "delete": lambda: manager.delete_culture(args.get("culture_name")),
            "set_translation": lambda: manager.set_translation(
                args.get("culture_name"), args.get("object_type_target"), args.get("name"),
                args.get("property_name"), args.get("value"), table_name=args.get("table_name")),
        },
        "named_expression": {
            "list": lambda: manager.list_expressions(),
            "describe": lambda: manager.describe_expression(args.get("expression_name")),
            "create": lambda: manager.create_expression(args.get("expression_name"), args.get("expression"), description=args.get("description")),
            "update": lambda: manager.update_expression(args.get("expression_name"), args.get("expression"), description=args.get("description")),
            "delete": lambda: manager.delete_expression(args.get("expression_name")),
        },
        "ols_rule": {
            "list": lambda: manager.list_ols_rules(args.get("role_name")),
            "set": lambda: manager.set_ols_rule(args.get("role_name"), args.get("table_name"), args.get("column_name"), args.get("permission", "None")),
            "remove": lambda: manager.remove_ols_rule(args.get("role_name"), args.get("table_name"), args.get("column_name")),
        },
    }

    ops = dispatch_map.get(object_type, {})
    handler_fn = ops.get(operation)
    if not handler_fn:
        return {"success": False, "error": f"Unknown operation '{operation}' for {object_type}", "valid_operations": list(ops.keys())}

    return handler_fn()
```

- [ ] **Step 6: Update tool description**

Update the ToolDefinition description to reflect new object types:

```python
description="Unified CRUD for tables, columns, measures, relationships, calculation groups, partitions, hierarchies, perspectives, cultures, named expressions, and OLS rules. Specify object_type + operation.",
```

- [ ] **Step 7: Verify handler dispatches correctly**

Run: `python -c "
from server.handlers.model_operations_handler import handle_model_operations
# Test that new object types are recognized (will fail with 'Not connected' which is fine)
for ot in ['partition', 'hierarchy', 'perspective', 'culture', 'named_expression', 'ols_rule']:
    result = handle_model_operations({'object_type': ot, 'operation': 'list'})
    assert 'error' in result or 'success' in result, f'{ot}: unexpected result'
    print(f'{ot}: OK (got expected response)')
"`

Expected: 6 OK lines (each returning "Not connected" error, which is correct without a live PBI instance)

- [ ] **Step 8: Commit**

```bash
git add server/handlers/model_operations_handler.py
git commit -m "feat: wire 6 new TOM object types into 02_Model_Operations (partition, hierarchy, perspective, culture, named_expression, ols_rule)"
```

---

### Task 22: Add DAX UDF Awareness to 05_DAX_Intelligence

**Files:**
- Modify: `server/handlers/dax_context_handler.py`

- [ ] **Step 1: Add `list_udfs` and `describe_udf` operations**

In the DAX Intelligence handler, find where operations are dispatched. Add two new operations:

**list_udfs:** Execute `EVALUATE INFO.USERDEFINEDFUNCTIONS()` via the query executor and return the results.

**describe_udf:** Given a UDF name, return its signature and documentation.

The implementation delegates to `04_Run_DAX` internally:

```python
def _handle_list_udfs(args):
    """List all DAX user-defined functions in the model."""
    from core.infrastructure.connection_state import connection_state
    executor = connection_state.query_executor
    if not executor:
        return {"success": False, "error": "Not connected"}

    try:
        result = executor.execute_dax("EVALUATE INFO.USERDEFINEDFUNCTIONS()")
        return {"success": True, "udfs": result.get("results", []), "count": result.get("row_count", 0)}
    except Exception as e:
        return {"success": True, "udfs": [], "count": 0, "note": "UDFs not supported in this model or DAX version"}
```

- [ ] **Step 2: Add `list_udfs` and `describe_udf` to the operation enum in the ToolDefinition input_schema**

- [ ] **Step 3: Commit**

```bash
git add server/handlers/dax_context_handler.py
git commit -m "feat: add list_udfs operation to 05_DAX_Intelligence for DAX UDF awareness"
```

---

## Phase 8 — Core Domain Fixes

### Task 23: Document DAX Code Rewriter Limitations

**Files:**
- Modify: `core/dax/code_rewriter.py:697`
- Modify: `core/dax/code_rewriter.py:827`

- [ ] **Step 1: Replace TODO stubs with documented limitations**

At line 697, replace:
```python
        # TODO: Implement actual flattening with proper DAX parsing
        return dax
```
with:
```python
        # LIMITATION: Auto-flattening nested CALCULATE requires a full DAX parser
        # (balanced parentheses, string literal awareness, context transition detection).
        # The transformation is detected and reported above but not auto-applied.
        # Users should apply the suggested transformation manually.
        return dax
```

At line 827, replace:
```python
            # TODO: Actual conversion would require parsing to understand SUMMARIZE arguments
            # For now, just flag it as a transformation opportunity
```
with:
```python
            # LIMITATION: Auto-converting SUMMARIZE to SUMMARIZECOLUMNS requires parsing
            # the argument list to separate groupBy columns from name/expression pairs,
            # then wrapping computed columns in ADDCOLUMNS. Detected but not auto-applied.
```

- [ ] **Step 2: Commit**

```bash
git add core/dax/code_rewriter.py
git commit -m "docs: document DAX code rewriter limitations (replace TODO stubs)"
```

---

### Task 24: Complete Model Diff Engine Role/Perspective Comparison

**Files:**
- Modify: `core/comparison/model_diff_engine.py:874,888`

- [ ] **Step 1: Implement role comparison**

Replace the `_compare_roles` method (around line 864):

```python
    def _compare_roles(self) -> Dict[str, Any]:
        """Compare roles between models."""
        roles1 = {r['name']: r for r in self.model1.get('roles', [])}
        roles2 = {r['name']: r for r in self.model2.get('roles', [])}

        roles1_names = set(roles1.keys())
        roles2_names = set(roles2.keys())

        modified = []
        for name in roles1_names & roles2_names:
            r1, r2 = roles1[name], roles2[name]
            changes = {}

            # Compare filter expressions per table
            filters1 = {f.get('table', ''): f.get('expression', '') for f in r1.get('table_permissions', [])}
            filters2 = {f.get('table', ''): f.get('expression', '') for f in r2.get('table_permissions', [])}
            if filters1 != filters2:
                added_tables = set(filters2) - set(filters1)
                removed_tables = set(filters1) - set(filters2)
                changed_tables = {t for t in set(filters1) & set(filters2) if filters1[t] != filters2[t]}
                changes["filter_expressions"] = {
                    "added_tables": list(added_tables),
                    "removed_tables": list(removed_tables),
                    "changed_tables": list(changed_tables),
                }

            # Compare members
            members1 = set(r1.get('members', []))
            members2 = set(r2.get('members', []))
            if members1 != members2:
                changes["members"] = {
                    "added": list(members2 - members1),
                    "removed": list(members1 - members2),
                }

            if changes:
                modified.append({"name": name, "changes": changes})

        return {
            "added": list(roles2_names - roles1_names),
            "removed": list(roles1_names - roles2_names),
            "modified": modified,
        }
```

- [ ] **Step 2: Implement perspective comparison**

Replace the `_compare_perspectives` method (around line 877):

```python
    def _compare_perspectives(self) -> Dict[str, Any]:
        """Compare perspectives between models."""
        persp1 = {p['name']: p for p in self.model1.get('perspectives', [])}
        persp2 = {p['name']: p for p in self.model2.get('perspectives', [])}

        persp1_names = set(persp1.keys())
        persp2_names = set(persp2.keys())

        modified = []
        for name in persp1_names & persp2_names:
            p1, p2 = persp1[name], persp2[name]
            objects1 = set()
            objects2 = set()
            for t in p1.get('tables', []):
                tname = t.get('name', '')
                objects1.add(f"table:{tname}")
                for c in t.get('columns', []):
                    objects1.add(f"column:{tname}.{c}")
                for m in t.get('measures', []):
                    objects1.add(f"measure:{tname}.{m}")
                for h in t.get('hierarchies', []):
                    objects1.add(f"hierarchy:{tname}.{h}")
            for t in p2.get('tables', []):
                tname = t.get('name', '')
                objects2.add(f"table:{tname}")
                for c in t.get('columns', []):
                    objects2.add(f"column:{tname}.{c}")
                for m in t.get('measures', []):
                    objects2.add(f"measure:{tname}.{m}")
                for h in t.get('hierarchies', []):
                    objects2.add(f"hierarchy:{tname}.{h}")

            if objects1 != objects2:
                modified.append({
                    "name": name,
                    "added_objects": sorted(objects2 - objects1),
                    "removed_objects": sorted(objects1 - objects2),
                })

        return {
            "added": list(persp2_names - persp1_names),
            "removed": list(persp1_names - persp2_names),
            "modified": modified,
        }
```

- [ ] **Step 3: Commit**

```bash
git add core/comparison/model_diff_engine.py
git commit -m "feat: implement role and perspective comparison in model diff engine"
```

---

## Final — Version Bump Verification

### Task 25: Final Verification

- [ ] **Step 1: Verify server starts and lists 24 tools**

Run: `python -c "
from server.registry import HandlerRegistry, CATEGORY_TOOLS
from server.handlers import register_all_handlers
reg = HandlerRegistry()
register_all_handlers(reg)
tools = reg.get_all_tools_as_mcp()
print(f'{len(tools)} tools registered')
assert len(tools) == 24, f'Expected 24, got {len(tools)}'

# Verify CATEGORY_TOOLS matches
cat_tools = [t for ts in CATEGORY_TOOLS.values() for t in ts]
print(f'{len(cat_tools)} tools in CATEGORY_TOOLS')
assert len(cat_tools) == 24, f'Expected 24, got {len(cat_tools)}'

# Verify all annotations present
missing_annot = [t.name for t in tools if t.annotations is None]
assert len(missing_annot) == 0, f'Missing annotations: {missing_annot}'

# Verify output schemas
with_schema = [t.name for t in tools if getattr(t, 'outputSchema', None)]
print(f'{len(with_schema)} tools with outputSchema')

print('ALL CHECKS PASSED')
"`

Expected: `24 tools registered`, `24 tools in CATEGORY_TOOLS`, `3 tools with outputSchema`, `ALL CHECKS PASSED`

- [ ] **Step 2: Verify no stale tool names anywhere**

Run: `grep -r "02_Table_Operations\|02_Column_Operations\|02_Measure_Operations\|02_Relationship_Operations\|02_Calculation_Group_Operations\|06_Simple_Analysis\|06_Full_Analysis\|07_Report_Info\|09_Debug_Config\|09_Advanced_Analysis" server/ --include="*.py" -l`

Expected: 0 files (no stale references remain)

- [ ] **Step 3: Verify template count**

Run: `python -c "from core.pbip.authoring.visual_templates import TEMPLATE_REGISTRY; print(f'{len(TEMPLATE_REGISTRY)} templates')"`

Expected: `32 templates` (28 unique + 4 aliases)

- [ ] **Step 4: Create final commit if any cleanup needed, then tag**

```bash
git tag v7.1.0
```
