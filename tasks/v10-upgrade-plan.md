# MCP-PowerBi-Finvision v10.0 — Major Upgrade Plan

## Context

After comprehensive research (4 parallel agents: tool audit, debug code review, online research, token analysis), we identified tool consolidation opportunities, critical debug bugs, and high-value missing features. This plan covers all findings organized into 5 phases.

**Key corrections from exploration:**
- `context_debugger.py` does NOT duplicate functions from `context_analyzer.py` — it uses composition via `self.analyzer`. Real duplication is between `context_analyzer.py` and `call_tree_builder.py`.
- SE/FE timing partially exists: `core/infrastructure/dax_executor_wrapper.py` wraps C# `DaxExecutor.exe` returning SE/FE/SE_CPU data. `core/performance/performance_analyzer.py` has AMO trace support.
- `core/dax/vertipaq_analyzer.py` already queries `$SYSTEM.DISCOVER_STORAGE_TABLE_COLUMNS`.
- `dax_context_handler.py` lines 18-47 manually loads DLLs instead of using centralized `dll_paths.py` (v9.2 regression).

---

## Phase 1: Bug Fixes & Quick Wins (2-3 days)

### 1.1 Fix nesting level calculation bug [CRITICAL]
**File:** `core/dax/context_analyzer.py` lines 504-514
- **Bug:** Counts ALL prior CALCULATE transitions, not just unclosed ones
- **Example:** `CALCULATE(X) + CALCULATE(Y)` — second gets nesting=1, should be 0
- **Fix:** Pass normalized DAX into method. For each CALCULATE transition, compute its scope (start to matching close-paren using fixed `_extract_function_body`). For each transition, count how many CALCULATE scopes contain its position.

### 1.2 Fix string literal handling in `_extract_function_body()` [CRITICAL]
**File:** `core/dax/context_analyzer.py` lines 490-502
- **Bug:** Simple paren counting without string literal awareness
- **Breaks on:** `FILTER(T, T[Col] = "(value)")` — the `)` inside string is counted
- **Fix:** Add `in_double_quote` / `in_single_quote` tracking with DAX escape handling (`""` for escaped double-quote, `''` for escaped single-quote)
- **Also fix:** `call_tree_builder.py` `_find_matching_paren()` lines 334-346 — same bug

### 1.3 Cache VisualQueryBuilder [12x perf improvement]
**File:** `server/handlers/debug_handler.py` lines 118-128
- **Issue:** `_get_visual_query_builder()` called 13+ times per request, rebuilds PBIP each time
- **Fix:** Module-level dict cache with TTL matching `PBIP_FRESHNESS_THRESHOLD_MINUTES` (5 min). Cache key = pbip_path, invalidate on path change or TTL expiry.

### 1.4 Extract shared DAX utilities
**New file:** `core/dax/dax_utilities.py`
- `normalize_dax(dax) -> str` — from `context_analyzer.py:236-244` and `call_tree_builder.py:171-177`
- `extract_function_body(dax, start) -> str` — FIXED version with string literal awareness
- `extract_variables(dax) -> Dict[str, str]` — from `context_analyzer.py:246-284`
- `get_line_column(text, position) -> Tuple[int, int]` — from `context_analyzer.py:604-609`
- `validate_dax_identifier(s) -> bool` — new, proper regex validation
- `find_matching_paren(expr, open_pos) -> int` — FIXED version from `call_tree_builder.py`
- **Update consumers:** `context_analyzer.py`, `call_tree_builder.py`, `dax_injector.py`

### 1.5 Extract `_get_database_name()` in dax_injector
**File:** `core/dax/dax_injector.py`
- 4 identical ~15-line blocks at lines 169-177, 360-368, 477-485, 609-617
- Extract to `_get_database_name(self, server) -> Tuple[str, Optional[dict]]`
- Update all 4 call sites

### 1.6 Fix weak identifier validation
**File:** `core/dax/dax_injector.py` lines 151-152, 344-345, 460-461, 585-586
- Current: allows spaces, special chars, injection patterns
- Fix: import `validate_dax_identifier` from `dax_utilities.py`, replace all 4 local definitions

### 1.7 Shorten tool descriptions (~250 tokens saved)
| Tool | Current | New |
|------|---------|-----|
| `05_DAX_Intelligence` | ~174 chars | ~85 chars |
| `05_Column_Usage_Mapping` | ~172 chars | ~95 chars |
| `02_TMDL_Operations` | ~118 chars | ~80 chars |
| `06_Analysis_Operations` | ~115 chars | ~80 chars |

### 1.8 Remove operation context from parameter descriptions (~200 tokens)
- Pattern: `"Source table (replace_measure)"` → `"Source table"`
- Apply across: `tool_schemas.py` (visual_operations, slicer_operations), `pbip_operations_handler.py`, `debug_handler.py`
- ~30 parameters affected

### 1.9 Fix DLL loading centralization (v9.2 regression)
**File:** `server/handlers/dax_context_handler.py` lines 18-47
- Replace manual DLL path building with `from core.infrastructure.dll_paths import load_amo_assemblies, load_adomd_assembly`

---

## Phase 2: Refactoring (2-3 days)

### 2.1 Split `handle_debug_visual()` (427 LOC → ~100 LOC orchestrator)
**File:** `server/handlers/debug_handler.py` lines 131-557
- Extract: `_discover_visuals(args, builder, compact)` — handle discovery when page/visual not specified
- Extract: `_build_filter_context(builder, result, connection_state, compact)` — build and classify filters
- Extract: `_apply_manual_filters(args, result, builder, ...)` — manual filter overrides
- Extract: `_execute_visual_query(query, response, ...)` — query execution with retry

### 2.2 Split `handle_analyze_measure()` (263 LOC)
**File:** `server/handlers/debug_handler.py` lines 936-1198
- Extract: `_resolve_measure_expression(measure_name, table_name, qe)` — find expression
- Extract: `_analyze_measure_dax(expression)` — run DAX analysis
- Extract: `_get_visual_filter_context(page_name, visual_id, ...)` — get filter context
- Extract: `_execute_measure_with_context(measure_name, filters, qe)` — execute with context

### 2.3 Pre-compile regexes in context_analyzer
**File:** `core/dax/context_analyzer.py`
- Move to class-level compiled patterns in `__init__`:
  - `_SINGLE_LINE_COMMENT`, `_MULTI_LINE_COMMENT`, `_VAR_PATTERN`, `_MEASURE_PATTERN`, `_TABLE_COL_PATTERN`, `_SUMMARIZE_PATTERN`
- Update all `re.finditer()`/`re.search()`/`re.sub()` calls to use pre-compiled patterns

### 2.4 Move magic numbers to config
**File:** `config/default_config.json` — add `"debug"` section:
```json
"debug": {
    "pbip_freshness_minutes": 5,
    "vqb_cache_ttl_seconds": 300,
    "filter_truncation_chars": 50,
    "variable_truncation_chars": 100,
    "proximity_distance_chars": 50,
    "max_measures_shown": 3,
    "max_query_result_rows": 100
}
```
Update: `debug_handler.py` (lines 21, 44), `context_analyzer.py` (lines 279, 338, 749)

### 2.5 Split `07_PBIP_Operations` (9 ops → 2 tools)
**File:** `server/handlers/pbip_operations_handler.py`
- `07_PBIP_Model_Analysis` (sort_order=70): analyze, validate_model, compare_models, generate_documentation
  - Params: operation, pbip_path, output_path, source_path, target_path
- `07_PBIP_Query` (sort_order=71): query_dependencies, query_measures, query_relationships, query_unused, git_diff
  - Params: operation, pbip_path, object_name, direction, table, display_folder, pattern, expression_search
- Keep same handler file, add two dispatchers + two registration functions
- Update `server/handlers/__init__.py` and `server/registry.py` CATEGORY_TOOLS

### 2.6 Split `08_Visual_Operations` (20+ params → 2 tools)
**File:** `server/handlers/visual_operations_handler.py`, `server/tool_schemas.py`
- `08_Visual_Operations` (sort_order=80): list, update_position, update_visual_config
- `08_Visual_Sync` (sort_order=81): replace_measure, sync_visual, sync_column_widths
- Split schema in `tool_schemas.py`, add two dispatchers + registrations
- Update `__init__.py` and `registry.py`

### 2.7 Consolidate slicer schema (~50-80 tokens)
**File:** `server/tool_schemas.py`
- Remove redundant inner enum descriptions in nested `interactions` array items

---

## Phase 3: New Features — Foundation (3-4 days)

### 3.1 Trace Event Subscription [foundation for SE/FE]
**New file:** `core/performance/trace_manager.py`
- `TraceManager` class managing AS trace subscriptions via AMO `Server.SessionTrace`
- Event types: `QueryEnd` (ID=10), `VertiPaqSEQueryEnd` (ID=89), `DirectQueryEnd`
- Thread-safe event collection (events arrive on .NET callback thread → `threading.RLock`)
- Methods: `start_trace(connection, event_types)`, `stop_trace()`, `execute_with_trace(query, events)`
- Auto-cleanup on connection loss
- ADOMD.NET already loaded via `dll_paths.py`

### 3.2 SE/FE Timing Breakdown [multi-layer with fallback]
**New file:** `core/performance/se_fe_profiler.py`

Three layers with automatic fallback:

**Layer 1 — ADOMD Trace Events (preferred):**
- Use `TraceManager` (3.1) to subscribe to `QueryEnd` + `VertiPaqSEQueryEnd`
- Parse: total_ms from QueryEnd, individual SE queries with xmSQL text + duration + CPU
- Calculate: SE_total = sum(SE_query_durations), FE = total - SE_total
- Capture: xmSQL text, cache hits, SE query count

**Layer 2 — C# DaxExecutor (fallback):**
- Already exists: `core/infrastructure/dax_executor_wrapper.py`
- Returns: `{Total, FE, SE, SE_CPU, SE_Par, SE_Queries, SE_Cache}`
- Wire `SEFEProfiler._profile_via_executor()` to call this

**Layer 3 — Basic timing (last resort):**
- Simple before/after timing, no SE/FE split
- Always works, used when neither trace nor C# available

**Data model:**
```python
@dataclass
class SEQuery:
    xmsql: str; duration_ms: float; cpu_ms: float; cache_hit: bool

@dataclass
class SEFEResult:
    total_ms: float; se_ms: float; fe_ms: float; se_cpu_ms: float
    se_queries: List[SEQuery]; se_cache_hits: int
    profiling_method: str  # "trace" | "executor" | "basic"
```

**Surface via:**
- `04_Run_DAX` mode `"profile"` → return SE/FE breakdown
- `09_Profile` page profiling → SE/FE per visual
- `09_Debug_Operations` analyze → SE/FE in measure analysis

### 3.3 CallbackDataID Detection
**New file:** `core/dax/callback_detector.py`
- `CallbackDetector` class with static analysis rules:
  - CB001: IF/SWITCH inside SUMX/AVERAGEX/COUNTX (critical)
  - CB002: IFERROR/ISERROR in iterators (high)
  - CB003: Nested iterators creating Cartesian products (critical)
  - CB004: FILTER on entire table vs column filter (high)
  - CB005: FORMAT() preventing SE optimization (medium)
  - CB006: LASTDATE vs MAX for dates (medium)
- Each rule: regex pattern, description, severity, fix suggestion
- Integrate into `05_DAX_Intelligence` pipeline in `dax_context_handler.py`

### 3.4 TOJSON/TOCSV Variable Debugging
**New operation in `09_Debug_Operations`:** `debug_variable`
**File:** `server/handlers/debug_handler.py`
- Input: measure_name, variable_name, table_name (optional), max_rows (default 100)
- Flow:
  1. Get measure expression, parse VARs via `extract_variables()`
  2. Generate modified DAX: replace RETURN with `TOJSON(varName)` or `TOPN(max_rows, varName)` for tables
  3. Inject temp measure via `DAXInjector.upsert_measure()`
  4. Execute and capture
  5. **CRITICAL: Restore original in `try/finally`**
  6. Return structured variable contents
- Add `debug_variable` to operation enum, add `variable_name` and `max_rows` params to schema

---

## Phase 4: New Features — Enhancement (3-4 days)

### 4.1 VertiPaq Storage Analysis Enhancement
**New file:** `core/dax/vertipaq_storage_report.py`
- `VertiPaqStorageReport` class using existing `VertiPaqAnalyzer`
- Additional DMV: `$SYSTEM.DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS` for segment-level data
- Additional INFO: `INFO.STORAGETABLECOLUMNS()` as fallback
- Report: per-column cardinality/size/encoding, per-table totals, compression ratios, recommendations
- Surface via: `06_Analysis_Operations` new mode `"storage"` in `analysis_handler.py`

### 4.2 Expanded DAX Static Analysis Rules
**New file:** `core/dax/dax_rules_engine.py`
- `DaxRulesEngine` class with comprehensive rule library:
  - Performance: SUMX+IF, nested iterators, FILTER vs CALCULATE, FORMAT(), DISTINCTCOUNT vs COUNTROWS(VALUES()), bidirectional relationships
  - Readability: unused variables, deeply nested expressions (>4 levels)
  - Correctness: division without DIVIDE(), SWITCH without default
- DAX health score (0-100) per measure
- Integrate with `05_DAX_Intelligence` alongside existing `detect_dax_anti_patterns()`

### 4.3 Variable-by-Variable Stepping
**New operation in `09_Debug_Operations`:** `step_variables`
- Input: measure_name, page_name (optional for filter context), max_rows
- For each VAR: determine type (scalar/table), build eval query, execute, collect timing
- Scalar: `EVALUATE ROW("value", <expression>)`
- Table: `EVALUATE TOPN(10, <expression>)`
- Return ordered list: `[{var_name, type, value, execution_time_ms}]`

### 4.4 Enhanced BPA Rules [DONE]

**File:** `core/analysis/bpa_analyzer.py`

- [x] Custom rule loading from `config/bpa_rules/*.json`
- [x] 13 built-in enhanced rules across 6 categories
- [x] Rule categories: DAX Expressions, Naming, Formatting, Relationships, Calculation Groups, Performance
- [x] `get_violations_by_category()` and `get_rule_categories()` methods
- [x] Fixed expression cache key collision bug
- [x] Fixed `(?i)` flag handling for third-arg regex flags
- [x] Added `.Any()` pre-paren handler, numeric comparison handler, `Columns`/`Measures`/`AllRelationships` path support
- [x] Sample custom rule in `config/bpa_rules/sample_custom_rule.json`

---

## Phase 5: Verification (1-2 days)

| Check | Command/Approach |
|-------|-----------------|
| No regressions | `pytest` |
| Formatting | `black --check --line-length 100 core/ server/ src/` |
| Type checking | `mypy core/` |
| Tool splits work | Test each split tool via MCP client |
| Token footprint | Compare schema sizes before/after |
| SE/FE accuracy | Compare results with DAX Studio on same query |
| CallbackDataID | Test against known anti-pattern measures |
| TOJSON debugging | Test on multi-VAR measure, verify restore |
| VertiPaq | Compare with DAX Studio VertiPaq Analyzer |
| BPA rules | Run against model with known violations |

---

## Critical Files

| File | Changes |
|------|---------|
| `core/dax/context_analyzer.py` | Fix nesting (504-514), fix string literals (490-502), pre-compile regexes, delegate to dax_utilities |
| `server/handlers/debug_handler.py` | Cache VQB (118-128), split handle_debug_visual (131-557), split handle_analyze_measure (936-1198), add debug_variable + step_variables ops |
| `core/dax/dax_injector.py` | Extract _get_database_name (4 sites), fix validation (4 sites) |
| `core/dax/call_tree_builder.py` | Fix _find_matching_paren (334-346), delegate to dax_utilities |
| `server/handlers/pbip_operations_handler.py` | Split into 2 tools with 2 dispatchers |
| `server/handlers/visual_operations_handler.py` | Split into 2 tools with 2 dispatchers |
| `server/tool_schemas.py` | Split visual schema, consolidate slicer schema |
| `server/handlers/__init__.py` | Update registrations for split tools |
| `server/registry.py` | Update CATEGORY_TOOLS for split tools |
| `server/handlers/dax_context_handler.py` | Fix DLL loading, integrate CallbackDetector + DaxRulesEngine |
| `server/handlers/analysis_handler.py` | Add storage mode for VertiPaq |
| `config/default_config.json` | Add debug section with magic numbers |

## New Files

| File | Purpose |
|------|---------|
| `core/dax/dax_utilities.py` | Shared DAX parsing utilities |
| `core/dax/callback_detector.py` | CallbackDataID pattern detection |
| `core/dax/dax_rules_engine.py` | Comprehensive DAX static analysis |
| `core/dax/vertipaq_storage_report.py` | Enhanced VertiPaq storage reporting |
| `core/performance/trace_manager.py` | AS trace event subscription |
| `core/performance/se_fe_profiler.py` | SE/FE timing with 3-layer fallback |
