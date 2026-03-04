# Debug Tool SE/FE Analysis & Optimization Improvements

## Context

The Debug tool's optimize operation has a mature 13-step pipeline combining runtime SE trace analysis, static DAX pattern detection, VertiPaq cardinality analysis, and code rewriting. After cross-referencing the codebase against latest SQLBI best practices, DAX Optimizer patterns, and professional tooling (DAX Studio, Tabular Editor BPA), we identified 11 concrete improvements across 3 phases — from quick bug fixes to advanced analysis features.

**What's already well-covered:** CB007 (DIVIDE-in-iterator), SUMX(T,T[Col])→SUM detection, ADDCOLUMNS(SUMMARIZE(...)) check, encoding capture from DMV, correct nesting calculation (primary path).

---

## Phase 1: Bug Fixes + Quick Wins (4 items, all independent)

### 1. Fix nesting level fallback bug
**File:** `core/dax/context_analyzer.py` (lines 585-591)
**Size:** S | **Risk:** LOW

**Problem:** Fallback (when `calc_scopes` unavailable) counts ALL prior CALCULATE transitions instead of tracking which are still open at each position. `CALCULATE(X) + CALCULATE(Y)` gives Y nesting=1 when it should be 0.

**Fix:** Replace naive count with paren-depth scope tracking:
- For each CALCULATE match before the transition position, track paren depth from match to transition
- Only count as "open" if paren depth hasn't returned to 0
- ~20 lines changed in one else-block

**Test:** Sequential non-nested CALCULATEs → both nesting=0; nested CALCULATE → inner nesting=1.

---

### 2. Add reverse join detection in xmSQL
**File:** `core/dax/se_event_analyzer.py` (extend `_analyze_join_types()`)
**Size:** S | **Risk:** LOW

**What:** Currently only detects INNER JOIN and LEFT OUTER JOIN. Missing REVERSE BITMAP JOIN and REVERSE HASH JOIN — expensive join reversals triggered when many-side >131K rows or unique values >16K.

**Changes:**
- Add 2 regex patterns: `_REVERSE_BITMAP_JOIN_RE`, `_REVERSE_HASH_JOIN_RE`
- Count occurrences in SE events, add warnings with row counts
- Return `reverse_bitmap_joins`, `reverse_hash_joins`, `reverse_join_warnings` in result dict

**Test:** Mock SE events with REVERSE BITMAP JOIN in xmSQL, verify counts and warnings.

---

### 3. Improve xmSQL normalization for fusion detection
**File:** `core/dax/se_event_analyzer.py` (method `_detect_fusion_opportunities`)
**Size:** S | **Risk:** LOW

**What:** Current normalization only strips aggregations and replaces literals. Misses fusion groups that differ only by case, whitespace, or alias naming.

**Changes:** Add `_normalize_xmsql()` helper:
1. Case normalization → `UPPER()`
2. Whitespace collapse → `re.sub(r'\s+', ' ')`
3. Alias normalization → strip `AS [ColName]` / `AS ColName` variations
4. Then apply existing aggregation stripping

**Test:** Queries differing only by case/whitespace/aliases produce same fusion signature.

---

### 4. Add SUMMARIZE with inline expressions check
**File:** `core/dax/dax_best_practices.py`
**Size:** S | **Risk:** LOW

**What:** `SUMMARIZE(Table, Col, "Name", <expr>)` with inline expressions is deprecated and can produce incorrect results. Currently only detected when wrapped in ADDCOLUMNS.

**Changes:**
- New check `_check_summarize_inline_expressions()`
- Detect SUMMARIZE with string literal args (indicating inline expressions)
- Skip if preceded by `ADDCOLUMNS(` (already covered)
- Severity: HIGH, Category: CORRECTNESS
- Reference: SQLBI best practices article

**Test:** `SUMMARIZE(Sales, Sales[Product], "Total", SUM(Sales[Amount]))` → triggers; plain `SUMMARIZE(Sales, Sales[Product])` → doesn't.

---

## Phase 2: Enhanced Analysis Capabilities (4 items)

### 5. Fusion break detection for IF/SWITCH branches
**File:** `core/dax/dax_best_practices.py`
**Size:** M | **Risk:** MEDIUM (false positive risk on simple IF)

**What:** IF/SWITCH returning different measures in branches breaks vertical fusion — can cause billions of FE combinations. Time intelligence functions in branches also break it. NOT currently detected.

**Changes:**
- New check `_check_if_switch_fusion_break()`
- Detect IF/SWITCH where body contains 2+ different measure references OR time intelligence functions (DATESYTD, DATEADD, TOTALYTD, SAMEPERIODLASTYEAR, etc.)
- Severity: HIGH (time intelligence) / MEDIUM (different measures)
- Suggest: pre-compute both branches with VAR to enable fusion
- Reference: SQLBI "Optimizing fusion optimization for DAX measures"

**Mitigation:** Require 2+ different measure refs OR time intelligence to avoid flagging simple `IF(cond, 1, 0)`.

**Test:** `IF(cond, [MeasureA], [MeasureB])` → triggers; `IF(cond, 1, 0)` → doesn't; `SWITCH(TRUE(), cond, TOTALYTD([Sales], D[Date]))` → triggers.

---

### 6. Encoding-aware VertiPaq recommendations
**File:** `core/dax/vertipaq_analyzer.py`
**Size:** M | **Risk:** LOW

**What:** Encoding type IS captured from DMV (Encoding field) but NOT used in recommendations. Hash-encoded columns with high cardinality are silently expensive.

**Changes:** Enhance `_get_optimization_suggestions()`:
- **Hash + >500K cardinality** → CRITICAL: flag for review/splitting
- **Numeric column with hash encoding** → MEDIUM: suggest reducing distinct values for value encoding
- **Cardinality >1M + >50MB column size** → HIGH: recommend column splitting (can reduce 93%+ per SQLBI research)
- Add `optimization_type` field to suggestions: `'encoding'`, `'column_splitting'`

**Test:** Mock column with HASH encoding + 600K cardinality → critical suggestion; low-cardinality column → no false suggestion.

---

### 7. Cardinality-weighted priority scoring
**File:** `server/handlers/debug_handler.py` (`_build_optimize_suggestions`, ~line 2783)
**Size:** M | **Risk:** MEDIUM (changes suggestion ordering)

**What:** Current priority is flat `sev_rank × 10` with optional -3 boost. Same anti-pattern on 100M row table ranks identical to 1K row table.

**Changes:**
- Add `vertipaq_result` parameter to `_build_optimize_suggestions()`
- Priority formula: `sev_rank × 10 - cardinality_boost - fe_boost - timing_correlation`
  - `cardinality_boost`: min(5, log10(max_cardinality) - 2) → 0-5 range
  - `fe_boost`: (fe_pct - 50) / 10 when FE-bound and category is performance → 0-5 range
- Callback findings (priority 0-1) remain undisplaced
- Update call site to pass vertipaq_result

**Test:** HIGH issue on 10M-row table ranks above same issue on 1K-row table; callbacks always stay priority 0-1.

---

### 8. Datacache threshold with fusion awareness
**File:** `server/handlers/debug_handler.py` (`_diagnose_timing`, ~line 2640)
**Size:** M | **Risk:** LOW

**What:** Hard 256-query warning. Doesn't account for whether fusion is working or broken.

**Changes:**
- Add `se_analysis` parameter to `_diagnose_timing()`
- If se_analysis shows >5 vertical fusion breaks → tighten threshold to 128
- Adjust warning messages to include fusion context
- **Reorder** optimize pipeline: move `_diagnose_timing()` call to AFTER SE analysis (step 9) so fusion data is available

**Test:** 150 queries + 8 fusion breaks → warning (128 limit); 150 queries + 0 breaks → no warning (256 limit).

---

## Phase 3: Advanced Features (3 items)

### 9. Cold/warm cache comparison mode
**Files:** `core/dax/se_event_analyzer.py` (new method) + `server/handlers/debug_handler.py` (orchestration)
**Size:** L | **Risk:** MEDIUM

**What:** Confirms CallbackDataID impact empirically. If warm cache ≈ cold cache timing, SE cache is busted.

**Changes:**
- New `SeEventAnalyzer.compare_cache_impact(cold_events, warm_events)` method
- Returns: cold_total_ms, warm_total_ms, speedup_ratio, cache_effective (>1.5x = effective), diagnosis text
- Opt-in via new `cache_comparison: bool` parameter on optimize operation
- When True: run trace twice (cold then warm), include comparison in response
- Add to input schema with description

**Test:** Unit test compare_cache_impact with mock events; integration test manual.

---

### 10. Basic DAX syntax validation for code rewriter
**File:** `core/dax/code_rewriter.py`
**Size:** S | **Risk:** LOW

**What:** Rewriter has zero validation. Rewritten DAX may have broken parentheses, missing RETURN, etc.

**Changes:**
- New `_validate_syntax(dax)` method: checks parenthesis balance, bracket balance, VAR-without-RETURN
- Called after all transformations applied
- If validation fails: downgrade ALL transformation confidences to 'low', add `validation_warnings` to result
- Does NOT block rewriting — advisory only

**Test:** Balanced DAX → no errors; missing closing paren → error; VAR without RETURN → error; existing rewrites pass validation.

---

### 11. Per-measure timing via sequential traces
**File:** `server/handlers/debug_handler.py` (new helper + schema update)
**Size:** L | **Risk:** HIGH (slow, timing may not match visual context)

**What:** Currently only visual-level timing. Can't tell which measure is slow in multi-measure visuals.

**Changes:**
- New `_trace_measures_individually(measures, connection_state, clear_cache)` helper
- For each measure, runs `EVALUATE ROW("Result", [MeasureName])` with NativeTraceRunner
- Opt-in via `per_measure_trace: bool` parameter on optimize operation
- Returns `per_measure_timing: {measure_name: {total_ms, se_ms, fe_ms, se_queries}}`
- Clear caveat in docs: individual traces lack visual's combined filter context

**Test:** Unit test with mocked trace runner; verify opt-in behavior (default=False).

---

## Dependency Graph

```
Phase 1 (all independent, can be done in parallel):
  Item 1 (nesting bug)     ── no deps
  Item 2 (reverse joins)   ── no deps
  Item 3 (xmSQL normalize) ── no deps
  Item 4 (SUMMARIZE check) ── no deps

Phase 2:
  Item 5 (fusion break)   ── no deps
  Item 6 (encoding VP)    ── no deps
  Item 7 (weighted score) ── soft dep on Item 6 (richer vertipaq data)
  Item 8 (datacache flex)  ── soft dep on Item 3 (better fusion detection)
                           ── requires reordering steps 6↔9 in optimize flow

Phase 3:
  Item 9  (cache compare)  ── no hard deps
  Item 10 (syntax validate)── no hard deps
  Item 11 (per-measure)    ── no hard deps
```

## Files Modified

| File | Items | Changes |
|------|-------|---------|
| `core/dax/context_analyzer.py` | 1 | Fix fallback nesting (~20 lines) |
| `core/dax/se_event_analyzer.py` | 2, 3, 9 | Reverse joins, xmSQL normalize, cache compare |
| `core/dax/dax_best_practices.py` | 4, 5 | 2 new check methods (~80 lines total) |
| `core/dax/vertipaq_analyzer.py` | 6 | Encoding-aware suggestions (~40 lines) |
| `core/dax/code_rewriter.py` | 10 | Syntax validation (~40 lines) |
| `server/handlers/debug_handler.py` | 7, 8, 11 | Priority scoring, datacache flex, per-measure trace |

## Verification

After each phase:
1. `pytest` — all existing tests must pass
2. `black --check --line-length 100 core/ server/` — formatting
3. Manual test: connect to Power BI Desktop, run `optimize` on a real measure, verify new suggestions appear correctly
4. For Phase 2 Item 8: verify step reorder doesn't break optimize flow by testing with and without SE events
5. For Phase 3 Items 9, 11: verify opt-in parameters default to False and don't affect existing behavior
