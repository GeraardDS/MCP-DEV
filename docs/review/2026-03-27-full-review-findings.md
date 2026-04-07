# MCP-PowerBi-Finvision v6.6.2 — Full Review Findings

**Date:** 2026-03-27
**Audited by:** 6 parallel code review agents
**Codebase:** ~111K lines (95K core, 16K handlers, server layer)
**Tools:** 35 registered (manifest claims 47 — stale)

---

## Executive Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 12 | Thread safety (5), DAX parsing (2), facade APIs (2), resource leaks (1), BPA depth leak (1), stub validation (1) |
| HIGH | 25 | Duplication (7), security/injection (4), broken logic (5), dead code (3), performance (3), protocol gaps (3) |
| MEDIUM | 25 | Validation gaps, inconsistent patterns, stale references, config issues |
| LOW | 12 | Style, dead code, minor optimization |

**Top 3 systemic issues:**
1. **Thread safety** — ConnectionState, query cache, VQB cache, ConfigManager, ResourceManager all have unprotected shared mutable state. The server runs handlers in a thread pool.
2. **Code duplication** — Filter parsing regex 4x, SE event dedup 2x, `_resolve_definition_path` 3x, `_update_pages_json` 2x, `handle_run_dax_trace` 2x.
3. **Facade APIs** — Transaction rollback does nothing. Batch dry_run validates nothing. `_check_measure_references` is a stub. These APIs promise safety guarantees they don't deliver.

---

## CRITICAL FINDINGS (12)

### Thread Safety

**C-TS1: ConnectionState shared mutable state accessed without locks**
- File: `core/infrastructure/connection_state.py:161-215, 440-478, 611-624`
- `get_table_mappings()`, `invalidate_table_mappings()`, `cleanup()`, `store_trace_result()` all read/write shared dicts and timestamps outside any lock. Concurrent tool calls can see torn state.
- Fix: Extend `_init_lock` coverage to table-mapping cache, trace cache, and cleanup paths.

**C-TS2: OptimizedQueryExecutor query cache not thread-safe**
- File: `core/infrastructure/query_executor.py:603-632, 951-963`
- `OrderedDict` operations (`move_to_end`, `popitem`, `del`) in `_cache_get`/`_cache_set` are called from thread pool without any lock.
- Fix: Add `threading.RLock()` to `OptimizedQueryExecutor` for all cache operations.

**C-TS3: `_vqb_cache` module-level dict without threading lock**
- File: `server/handlers/debug_handler.py:34-35, 200-225`
- Module-level dict read/written/cleared by concurrent debug tool calls via thread pool.
- Fix: Add `threading.Lock()` and acquire for all cache access.

**C-TS4: Dynamic resource provider called while holding RLock — deadlock risk**
- File: `server/resources.py:147-151`
- `provider()` callback runs inside `self._lock`. If provider transitively acquires the same lock, deadlock.
- Fix: Copy provider reference out of lock, call outside.

**C-TS5: ConfigManager `reload()` not thread-safe**
- File: `core/config/config_manager.py:155-158`
- `self.config = {}` then rebuild while concurrent readers call `config.get()`.
- Fix: Add `threading.RLock()` around `_load_config()` and `get()`.

### Resource Leaks

**C-RL1: `execute_dmv_query` does not close ADOMD reader on exception**
- File: `core/infrastructure/query_executor.py:1961-2015`
- No `try/finally` around `cmd.ExecuteReader()`. CLR reader leaks server-side cursor.
- Fix: Wrap in `try/finally` matching the pattern in `_execute_dax_reader()`.

### DAX Parsing

**C-DAX1: `_validate_syntax` bracket scanner broken on `""` escaped quotes**
- File: `core/dax/code_rewriter.py:136-150`
- Simple `in_string = not in_string` toggle doesn't handle DAX's `""` escape. Bracket depth calculations wrong for expressions with escaped quotes.
- Fix: Use lookahead-for-doubled-quote pattern from `dax_utilities.py`.

**C-DAX2: `_find_top_level_return` string literal scanner doesn't handle escaped quotes**
- File: `core/dax/code_rewriter.py:474-479`
- `while i < length and dax[i] != '"'` exits on first `""` escape. RETURN detection broken.
- Fix: Same escaped-quote handling pattern.

### Facade APIs

**C-FACADE1: Transaction management is a facade — rollback does nothing**
- File: `core/operations/transaction_management.py:79-163`
- `_rollback_transaction` updates in-memory status flag only. Zero actual model operation reversal. `operations` list is never populated during actual model changes. API claims "ACID transactions" but delivers none of A, C, I, or D.
- Fix: Either implement real TOM-level transactions or clearly document as "operation tracking only" and remove "rollback" operation.

**C-FACADE2: `_check_measure_references` is a stub — validation chain reports success while checking nothing**
- File: `core/model/model_validator.py:293-315`
- Method fetches measures, builds name set, then returns empty list. "Check 4: Invalid measure references" always passes.
- Fix: Implement actual `[MeasureRef]` cross-check or remove from validation chain.

### BPA Engine

**C-BPA1: `_evaluate_expression_impl` — `_eval_depth` not decremented in finally block**
- File: `core/analysis/bpa_analyzer.py:800-804`
- No `try/finally` for depth counter across ~450 lines of evaluation logic. Internal exceptions that are swallowed by nested try/except blocks permanently increment depth. After enough leaks, evaluator returns `False` for all rules.
- Fix: Wrap method body in `try/finally: self._eval_depth -= 1`.

### Documentation

**C-DOC1: `_collect_table_previews` iterates ALL tables with no cap**
- File: `core/documentation/interactive_explorer.py:683-754`
- Issues one DAX query per table. 60+ table model = 60+ queries, multi-MB HTML, potential thread pool starvation.
- Fix: Cap at 25 tables for preview.

---

## HIGH FINDINGS (25)

### Security / Injection

**H-SEC1: Fast-path validation bypass includes write-capable tools**
- File: `src/pbixray_server_enhanced.py:141-147`
- `02_Table_Operations`, `02_Column_Operations`, `02_Measure_Operations` in `fast_path_tools` bypass `DANGEROUS_DAX_PATTERNS` check. These tools support create/update/delete.
- Fix: Remove from `fast_path_tools`, keep only detection tools.

**H-SEC2: DAX injection in `_describe_table_sequential`**
- File: `core/infrastructure/query_executor.py:1554-1558`
- `table_name` embedded directly in DAX without escaping. Inconsistent with `_describe_table_consolidated` which does escape.
- Fix: Apply `_escape_dax_string(table_name)` consistently.

**H-SEC3: DAX injection in `search_measures_dax`/`search_objects_dax`**
- File: `core/infrastructure/query_executor.py:1276-1286, 1300-1368`
- `search_text` escaped for single quotes but embedded in double-quoted DAX `SEARCH("...")` literals.
- Fix: Add `.replace('"', '""')` for double-quote contexts.

**H-SEC4: `model_diff_report_v2.py` — TMDL data in `<script>` tag without `</script>` sanitization**
- File: `core/comparison/model_diff_report_v2.py:102-105`
- DAX expression containing `</script>` breaks out of script block. Interactive explorer already has the fix.
- Fix: Add `tmdl_data_json.replace('</', '<\\/')`.

### Broken Logic

**H-BUG1: `_extract_filter_arguments` drops last filter when it's the only filter**
- File: `core/dax/context_analyzer.py:380-391`
- Guard `and filters` on last-argument append means single-filter CALCULATE gets empty filter list.
- Fix: Remove `and filters` guard.

**H-BUG2: BPA OR/AND split corrupts expressions with those words inside quoted strings**
- File: `core/analysis/bpa_analyzer.py:1036-1049`
- `str.split(' or ')` splits everywhere including inside regex pattern strings.
- Fix: Respect parenthesis depth and quoted strings when splitting.

**H-BUG3: `_check_circular_relationships` — cycle detection only reports first cycle**
- File: `core/model/model_validator.py:352-361`
- Single `break` after finding any cycle. Fresh `rec_stack` per DFS root.
- Fix: Continue iteration after first cycle, accumulate all cycles.

**H-BUG4: `handle_audit` returns `{"ok":, "err":}` — wrong response format**
- File: `server/handlers/debug_handler.py:~3490-3629`
- All other handlers return `{"success":, "error":}`. Middleware wraps this creating double nesting.
- Fix: Replace `ok/err` with `success/error` in ~10 return statements.

**H-BUG5: `FILTER(VALUES) -> KEEPFILTERS` transformation is semantically incorrect**
- File: `core/dax/code_rewriter.py:891-924`
- `FILTER(VALUES(Col), pred)` is a table expression; `KEEPFILTERS(pred)` is a CALCULATE modifier. Not equivalent outside CALCULATE filter context. Marked `confidence: "high"`.
- Fix: Only apply inside CALCULATE filter arguments, or remove transformation.

### Duplication

**H-DUP1: `handle_run_dax_trace` verbatim duplicate**
- Files: `server/handlers/query_handler.py:15-97` and `server/handlers/query_trace_handler.py:14-97`
- Fix: Delete `query_trace_handler.py`.

**H-DUP2: SE event deduplication duplicated**
- Files: `server/handlers/debug_handler.py:84-141` and `server/handlers/query_handler.py:45-87`
- Fix: Extract to `core/infrastructure/query_trace.py`.

**H-DUP3: `_resolve_definition_path` triplicated**
- Files: `authoring_handler.py:17`, `prototype_handler.py:17`, `visual_operations_handler.py:~1612`
- Fix: Move to `core/utilities/pbip_utils.py`.

**H-DUP4: `_update_pages_json` duplicated**
- Files: `core/pbip/authoring/clone_engine.py:466-487` and `page_builder.py:182-202`
- Fix: Extract to shared utility.

### Dead Code

**H-DEAD1: `query_trace_handler.py` — entire file dead**
- Never called from `__init__.py`. Contains duplicate of `handle_run_dax_trace`.
- Fix: Delete file.

**H-DEAD2: `role_operations_handler.py` — ghost tool**
- Comment says "merged into query_handler" but file still exists with register function.
- Fix: Verify not called, delete file.

**H-DEAD3: `tool_schemas.py` — unused schema definitions**
- 153-line file defining schemas for old bridge-tool names. No importer.
- Fix: Delete file.

### Performance

**H-PERF1: `dax_context_handler` analysis_mode='report' runs full pipeline twice**
- File: `server/handlers/dax_context_handler.py:~1196-1270`
- `generate_debug_report()` runs all analyzers, then handler re-runs them.
- Fix: Return intermediate results from `generate_debug_report()`.

**H-PERF2: `execute_info_query` hard-capped at `top_n=100` — silently truncates enterprise models**
- Files: `core/documentation/interactive_explorer.py:77-90`, `core/model/model_validator.py`, `core/performance/performance_optimizer.py`
- 100-row cap on INFO.TABLES/COLUMNS/MEASURES. Enterprise models have 400-2000 measures.
- Fix: Remove or raise cap to 10000 for model-wide analytics.

**H-PERF3: Double key-compaction corrupts debug handler responses**
- File: `src/pbixray_server_enhanced.py:274-277`
- Debug handler applies compaction internally, server layer applies again.
- Fix: Add `_compacted` sentinel or apply only at server layer.

### Other HIGH

**H-MISC1: Stale `_is_connected` flag after PBI Desktop crash**
- File: `core/infrastructure/connection_state.py:80-84, 146-149`
- Cached `_is_connected = True` not updated when PBI crashes.
- Fix: Derive from `connection_manager.is_connected()` always.

**H-MISC2: `ConnectionManager.connect()` not atomic — three non-atomic assignments**
- File: `core/infrastructure/connection_manager.py:217-298`
- `active_connection`, `active_instance`, `connection_string` set separately without lock.
- Fix: Add `threading.RLock()` to ConnectionManager.

**H-MISC3: Batch `dry_run` does no actual validation**
- File: `core/operations/batch_operations.py:51-59`
- Returns `success: True` without validating items.
- Fix: Validate required fields, table existence, expression syntax.

**H-MISC4: BPA `analyze_model_fast` silently swallows all rule exceptions**
- File: `core/analysis/bpa_analyzer.py:1526`
- `except Exception: pass` — no logging, no diagnostic context.
- Fix: Add `logger.debug(...)` at minimum.

**H-MISC5: Manifest `manifest.json` lists 47 tools, only 35 registered**
- File: `manifest.json`
- 12+ stale tool names from pre-consolidation. MCP clients see phantom tools.
- Fix: Regenerate from `CATEGORY_TOOLS` in registry.py.

### Protocol

**H-PROTO1: `isError` never set on `CallToolResult` for error responses**
- File: `src/pbixray_server_enhanced.py:134-281`
- All errors return as normal `TextContent`. Clients can't programmatically detect failures.
- Fix: Set `isError=True` when result contains `success: False`.

**H-PROTO2: No tool annotations on any of 35 tools**
- File: `server/registry.py:114-122, 227`
- `ToolAnnotations` (readOnlyHint, destructiveHint, idempotentHint) never passed.
- Fix: Add `annotations` field to `ToolDefinition`, pass through to `Tool()`.

---

## MEDIUM FINDINGS (25)

| ID | File | Issue |
|----|------|-------|
| M1 | `core/infrastructure/dll_paths.py:41-55` | `load_amo_assemblies()` returns `True` when no DLLs loaded |
| M2 | `core/infrastructure/cache_manager.py:151-162` | Off-by-one allows `max_entries + 1` items |
| M3 | `core/infrastructure/multi_instance_manager.py:196-217` | `get_all_instances()` releases lock before iterating snapshot |
| M4 | `core/validation/input_validator.py:186-188` | Path traversal check bypassable on Windows after `normpath` |
| M5 | `core/infrastructure/connection_state.py:299-303` | `_history_logger` registration silently swallows exceptions |
| M6 | `core/validation/pagination_helpers.py:56,110` | Layering violation: `core/` imports from `server/` |
| M7 | `server/resources.py:191-195` | `get_resource_info` reads cache without lock |
| M8 | `server/pbip_cache.py:50-63` | TOCTOU race in `get_or_parse` |
| M9 | `src/pbixray_server_enhanced.py:154-176` | Validation error responses use uncompacted keys |
| M10 | `server/handlers/debug_handler.py:613,633` | Private method access on VisualQueryBuilder |
| M11 | `server/handlers/comparison_handler.py:~43` | Dead `pass` branch — misleading code |
| M12 | `server/handlers/aggregation_handler.py:~74` | HTML always generated regardless of output_format |
| M13 | `server/handlers/user_guide_handler.py` | Stale tool names in user guide |
| M14 | `server/handlers/dax_context_handler.py:~779` | LLM instructions embedded in tool response data |
| M15 | `server/handlers/debug_handler.py:~2395` | `top_n=0` — no row limit on DAX execution |
| M16 | `server/handlers/debug_handler.py:~981` | Tolerance hardcoded to 0.001, ignores schema param |
| M17 | `server/handlers/query_handler.py:~165` | `RoleOperationsHandler` instantiated per call |
| M18 | `core/analysis/m_practices.py:36-37` | M003 rule only detects Excel.Workbook, misses Csv/Json/Xml |
| M19 | `core/debug/anomaly_detector.py:78,241-263` | IQR 1.5x on financial data = high false-positive rate |
| M20 | `core/analysis/bpa_analyzer.py:497-512` | `CALCGROUP_ORDINAL_GAPS` fires on every calc group |
| M21 | `core/svg/svg_validator.py:75-83` | XSS check misses whitespace variants of `<script` |
| M22 | `core/comparison/model_narrative.py:39-44` | Q3 quartile off-by-one for small lists |
| M23 | `core/documentation/word_generator.py:20-30` | Bookmark ID hash collisions likely at 100+ objects |
| M24 | `core/analysis/column_usage_analyzer.py:141` | `include_dax` parameter has no effect |
| M25 | `MCP Server Setup.bat:110-111` | Hardcoded Python 3.13.0 installer URL |

---

## LOW FINDINGS (12)

| ID | File | Issue |
|----|------|-------|
| L1 | `core/utilities/json_utils.py:90` | Missing `encoding='utf-8'` in stdlib fallback |
| L2 | `core/infrastructure/connection_state.py:157,205` | `import time` inside function bodies |
| L3 | `core/infrastructure/rate_limiter.py:102-139` | `time.sleep()` held inside lock |
| L4 | `server/registry.py:101-111` | `CATEGORY_INFO` tool counts stale |
| L5 | `server/handlers/bookmark_theme_handler.py:~15` | `_find_report_folder` duplicates pbip_utils |
| L6 | `server/handlers/debug_handler.py` schema | `"required": []` on 9-operation tool |
| L7 | `server/handlers/dax_context_handler.py:~18` | AMO failure silently degrades capability |
| L8 | `core/analysis/bpa_analyzer.py:146-154` | Custom rule path resolution fragile for installed packages |
| L9 | `core/debug/filter_to_dax.py:64-78` | Project-specific field parameter patterns hardcoded |
| L10 | `core/orchestration/analysis_orchestrator.py:40-41` | Dead `pass` branch unreachable |
| L11 | `core/aggregation/aggregation_hit_rate_analyzer.py:24-29` | TYPE_CHECKING forward refs break at runtime hints |
| L12 | `core/pbip/authoring/visual_templates.py:32-34` | `_number_literal` int/float branch dead code |

---

## MCP PROTOCOL COMPLIANCE

| Feature | Status | Priority |
|---------|--------|----------|
| Tools — listing/calling | Implemented | - |
| Tool error reporting (`isError`) | Not implemented | HIGH |
| Tool annotations | Not implemented | HIGH |
| Prompts | Not implemented | HIGH |
| Resources — listing/reading | Implemented | - |
| Resource templates | Not implemented | MEDIUM |
| Structured output (`outputSchema`) | Not implemented | MEDIUM |
| Progress tracking | Not implemented | MEDIUM |
| MCP logging (`setLevel`, notifications) | Not implemented | MEDIUM |
| Cancellation | Not implemented | LOW |
| Pagination (MCP cursor protocol) | Not implemented (proprietary only) | LOW |
| Completion/auto-complete | Not implemented | LOW |
| Tasks (async) | Not implemented | LOW |
| Sampling | Not implemented | LOW |
| Roots | Not implemented | LOW |
| Elicitation | Not implemented | LOW |

---

## FEATURE GAPS VS COMPETITION

### vs Microsoft Official (23 tools)
| Feature | Priority |
|---------|----------|
| Partition management | HIGH |
| Calendar table generation | HIGH |
| Read-only mode | HIGH |
| Built-in prompts (6) | HIGH |
| Confirmation prompts for writes | HIGH |
| Hierarchy management | MEDIUM |
| Named expression management | MEDIUM |
| Perspective management | LOW |
| Culture/translation | LOW |
| Query group management | LOW |

### vs Community Servers
| Feature | Source | Priority |
|---------|--------|----------|
| PII detection/masking | sulaiman013 | MEDIUM |
| Security audit logging | sulaiman013 | LOW |
| RLS testing | sulaiman013 | MEDIUM |
| PBIP diagnostics (broken visual scan) | sulaiman013 | MEDIUM |
| Rollback/undo | MCP Engine | MEDIUM |

---

## TEST COVERAGE

Current state: **1 test file** (`tests/test_code_rewriter.py`) covering a single DAX rewriter rule.

Estimated coverage: <1% of codebase.

Priority test targets:
1. Thread safety — concurrent tool call tests
2. DAX parsing — escaped quotes, nested CALCULATE, edge cases
3. TMDL parsing — multiline expressions, roles, perspectives
4. BPA evaluation — depth counter, OR/AND split, custom rules
5. Input validation — path traversal, DAX injection, parameter bounds
6. Transaction management — document actual behavior vs API contract
