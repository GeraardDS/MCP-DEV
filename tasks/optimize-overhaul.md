I# Task: Overhaul the `optimize` Operation in Debug Handler

## Background

The `optimize` operation in the debug tool (`server/handlers/debug_handler.py`, function `handle_optimize_measure`) analyzes a DAX measure for performance issues. It has been refactored to **not run its own SE/FE trace** — instead, the LLM must first run `operation=visual` with `trace=true` to get real SE/FE timing with filter context, then pass the timing values as **required** input params to `optimize`.

**Timing data is mandatory.** If no timing params are provided, optimize should return an error telling the caller to run `visual` with `trace=true` first.

This task adds deep SE event analysis, integrates two unused analyzers, extends callback/BPA/rewriter detections, and updates the schema/description.

## Current State of the Code (already changed)

The handler at `server/handlers/debug_handler.py` lines ~2869-3000 currently:

- Accepts `measure_name` + optional timing params (`total_ms`, `fe_ms`, `se_ms`, `se_cpu_ms`, `fe_pct`, `se_pct`, `se_queries`, `se_cache_hits`, `se_parallelism`)
- Runs: resolve expression → build perf dict → static callbacks → timing diagnosis (if provided) → BPA → code rewriter → synthesize → next steps → response
- Does NOT call `ContextAnalyzer` or `VertiPaqAnalyzer` (both exist and are unused)
- The input schema (lines ~3053-3079) does NOT yet include the timing input params
- The tool description (line ~3051) still mentions "cold-cache SE/FE trace"

## Implementation Plan

Execute all phases in order. Each phase builds on the previous.

---

### Phase 1: Make Timing Required + Integrate Existing Analyzers + SE Event Analyzer

#### 1A. Make timing params required in `handle_optimize_measure`

**File:** `server/handlers/debug_handler.py`

Change the timing param handling (around line 2913-2925) so that if NO timing params are provided, return an error:

```python
# After building perf dict from args
if not timing_provided:
    return {
        'success': False,
        'error': 'SE/FE timing data is required. Run operation=visual with trace=true first, '
                 'then pass fe_pct, se_queries, total_ms, fe_ms, se_ms to optimize.',
        'hint': 'Example: {"operation": "optimize", "measure_name": "Total Sales", '
                '"fe_pct": 75.2, "se_queries": 42, "total_ms": 1500, "fe_ms": 1130, "se_ms": 370}'
    }
```

Remove the `timing_hint` fallback in the response (lines ~2986-2991) — timing is always present now, so `timing` and `timing_diagnosis` are always in the response.

#### 1B. Add `se_events` as input param

The LLM should also be able to pass SE events from the visual trace. Add to the timing key reading:

```python
se_events_input = args.get('se_events', [])  # List of SE event dicts from visual trace
```

This enables the deep SE event analysis in optimize (when the LLM passes them through).

#### 1C. Wire in ContextAnalyzer

**File:** `server/handlers/debug_handler.py`

Add as new step after static callback detection:

```python
# ── Step N: Context transition analysis ──────────────────────────
context_result = None
try:
    from core.dax.context_analyzer import DaxContextAnalyzer
    ctx = DaxContextAnalyzer().analyze_context_transitions(expression)
    context_result = {
        'complexity_score': ctx.complexity_score,
        'max_nesting_level': ctx.max_nesting_level,
        'transition_count': len(ctx.transitions),
        'transitions': [
            {'type': t.transition_type, 'location': t.location,
             'function': t.function_name, 'nesting': t.nested_level}
            for t in ctx.transitions[:10]
        ],
        'warnings': [
            {'severity': w.severity, 'message': w.message}
            for w in ctx.warnings
        ],
    }
except Exception as ce:
    logger.warning(f'Context analysis failed: {ce}')
```

**Existing module:** `core/dax/context_analyzer.py` — `DaxContextAnalyzer` class, method `analyze_context_transitions(expression)` returns `ContextFlowExplanation` dataclass with fields: `transitions`, `warnings`, `summary`, `complexity_score`, `max_nesting_level`.

#### 1D. Wire in VertiPaqAnalyzer

**File:** `server/handlers/debug_handler.py`

Add as new step after context analysis:

```python
# ── Step N: VertiPaq column analysis ─────────────────────────────
vertipaq_result = None
try:
    from core.dax.vertipaq_analyzer import VertiPaqAnalyzer
    vpaq = VertiPaqAnalyzer(connection_state)
    vertipaq_result = vpaq.analyze_dax_columns(expression)
except Exception as ve:
    logger.warning(f'VertiPaq analysis failed: {ve}')
```

**Existing module:** `core/dax/vertipaq_analyzer.py` — `VertiPaqAnalyzer(connection_state)` class, method `analyze_dax_columns(expression)` returns dict with column metrics, cardinality impacts, high-cardinality warnings.

#### 1E. Pass both into BPA

Change the BPA call to pass context and vertipaq results (they were always accepted but never provided):

```python
bpa_result = DaxBestPracticesAnalyzer().analyze(
    expression,
    context_analysis=context_result,
    vertipaq_analysis=vertipaq_result,
)
```

#### 1F. Add SE event deep analysis if se_events provided

If the LLM passes `se_events` from the visual trace, run deep analysis:

```python
se_analysis = None
if se_events_input:
    try:
        from core.dax.se_event_analyzer import SeEventAnalyzer
        se_analysis = SeEventAnalyzer().analyze(se_events_input, perf)
    except Exception as se_err:
        logger.warning(f'SE event analysis failed: {se_err}')
```

#### 1G. Update response structure

Add new fields (backward compatible):

```python
if context_result:
    response['context_analysis'] = context_result
if vertipaq_result and vertipaq_result.get('success'):
    response['vertipaq_analysis'] = vertipaq_result
if se_analysis:
    response['se_analysis'] = se_analysis
```

Timing is always present now:

```python
response['timing'] = perf
response['timing_diagnosis'] = timing_diagnosis
```

#### 1H. Update input schema

**File:** `server/handlers/debug_handler.py`, in `register_debug_handlers` (lines ~3053-3079)

Add to the properties dict:

```python
"total_ms": {"type": "number", "description": "Total query time ms from visual trace (optimize, required)"},
"fe_ms": {"type": "number", "description": "Formula Engine time ms (optimize, required)"},
"se_ms": {"type": "number", "description": "Storage Engine time ms (optimize, required)"},
"se_cpu_ms": {"type": "number", "description": "SE CPU time ms (optimize)"},
"fe_pct": {"type": "number", "description": "FE % of total time (optimize, required)"},
"se_pct": {"type": "number", "description": "SE % of total time (optimize)"},
"se_queries": {"type": "integer", "description": "Number of SE queries (optimize, required)"},
"se_cache_hits": {"type": "integer", "description": "SE cache hits (optimize)"},
"se_parallelism": {"type": "number", "description": "SE parallelism ratio (optimize)"},
"se_events": {"type": "array", "items": {"type": "object"}, "description": "SE event list from visual trace (optimize, optional for deep SE analysis)"},
```

#### 1I. Update tool description

**File:** `server/handlers/debug_handler.py`, line ~3051

Change to:

```python
description="Visual debugger (visual), compare measures (compare), drill to detail (drill), analyze measure DAX (analyze), debug_variable (evaluate single VAR), step_variables (step through all VARs), run_dax (execute raw DEFINE…EVALUATE query), optimize (measure_name + SE/FE timing from prior visual trace → static CallbackDataID detection + context transition analysis + VertiPaq column cardinality + DAX anti-pattern analysis + prioritized optimization suggestions with before/after code. REQUIRES timing params: run visual with trace=true first, then pass fe_pct, se_queries, total_ms, fe_ms, se_ms. Optionally pass se_events for deep SE analysis.). Use trace=true on visual to get SE/FE timing analysis with the visual's real filter context; supply measures[] to override which measures are tested against that context.",
```

#### 1J. Create `core/dax/se_event_analyzer.py` (NEW FILE, ~350 lines)

Stateless `SeEventAnalyzer` class for deep SE event analysis. Used by optimize (when se_events passed) and can also be wired into `visual` trace flow.

**Class structure:**

```python
class SeEventAnalyzer:
    """Deep analysis of Storage Engine trace events from visual trace."""

    def analyze(self, se_events: list, perf: dict) -> dict:
        """Main entry. Returns structured analysis dict."""
        callbacks = self._analyze_callbacks(se_events)
        datacache = self._analyze_datacache(se_events)
        timing_dist = self._analyze_timing_distribution(se_events, perf)
        fusion = self._detect_fusion_opportunities(se_events)
        joins = self._analyze_join_types(se_events)
        row_ratio = self._analyze_row_ratio(se_events)

        return {
            'callbacks': callbacks,
            'datacache': datacache,
            'timing_distribution': timing_dist,
            'fusion_opportunities': fusion,
            'join_analysis': joins,
            'row_ratio_analysis': row_ratio,
        }
```

**Methods to implement:**

1. `_analyze_callbacks(se_events)` — Parse xmSQL `WITH` clauses for ALL callback types: `CallbackDataID`, `EncodeCallback`, `RoundValueCallback`, `MinMaxColumnPositionCallback`, `Cond`. Use regex: `r'(CallbackDataID|EncodeCallback|RoundValueCallback|MinMaxColumnPositionCallback|Cond)\s*\('`. Return `{detected: bool, total_count: int, by_type: {type: [{line, duration_ms, snippet}]}, slowest_callback_query: {line, duration_ms, query}}`.

2. `_analyze_datacache(se_events)` — Sum `rows` and `kb` fields across all SE events. Flag individual queries with >100K rows or >10MB. Return `{total_rows, total_kb, largest_queries: [top 3 by rows], materialization_warnings: [str]}`.

3. `_analyze_timing_distribution(se_events, perf)` — Compute avg/median/max/p95 of SE query `duration_ms`. Identify outlier queries (>3x avg). Compute cache hit rate: `perf.se_cache_hits / perf.se_queries`. Assess parallelism: <1.0 = sequential, 1.0-2.0 = limited, >2.0 = good. Return `{avg_ms, max_ms, p95_ms, outlier_queries: [...], cache_hit_rate, parallelism_assessment: str}`.

4. `_detect_fusion_opportunities(se_events)` — **Key new capability.** Normalize each SE query by stripping the aggregation function (SUM/COUNT/MIN/MAX) to get the "filter context signature". Group by signature. If >1 query shares the same filter context = vertical fusion break (they should have been one query). Similarly, find queries that differ only in one column predicate value = horizontal fusion break. Return `{vertical_breaks: int, horizontal_breaks: int, estimated_saveable_queries: int, notes: [str]}`.

5. `_analyze_join_types(se_events)` — Scan each SE event's `query` field for `INNER JOIN` vs `LEFT OUTER JOIN`. INNER JOIN indicates Cartesian product (often from nested iterators or CROSSJOIN). Flag INNER JOINs where `rows` is high (>10K). Return `{inner_joins: int, left_outer_joins: int, cartesian_warnings: [str]}`.

6. `_parse_xmsql_with_clause(query)` — Helper. Parse `WITH $Expr0 := (CallbackDataID(...))` from xmSQL query text. Return list of `{expr_name, callback_type, arguments}`.

7. `_analyze_row_ratio(se_events)` — For each SE event, compute `duration_ms / max(rows, 1)`. High ratio (>0.01 ms/row) combined with callback presence = confirmed per-row FE overhead. Return `{queries_with_high_ratio: int, worst_ratio: float, worst_query_line: int}`.

**Imports needed:** `re`, `logging`, `statistics` (for median), `typing`.

**Location:** `core/dax/se_event_analyzer.py` — pure domain logic, no MCP awareness.

#### 1K. Enhance `_diagnose_timing` function

**File:** `server/handlers/debug_handler.py`, function `_diagnose_timing` (lines ~2593-2644)

Add these additional checks to the existing function:

```python
# Absolute time assessment
total_ms = perf.get('total_ms', 0)
if total_ms < 50:
    notes.append(f'Fast query ({total_ms}ms) — SE/FE ratios are less meaningful at this speed.')
elif total_ms > 2000:
    notes.append(f'Slow query ({total_ms}ms) — significant optimization opportunity.')

# SE/FE ratio benchmark
ideal_fe = 20  # ideal is ~20% FE / 80% SE
deviation = abs(fe_pct - ideal_fe)
if deviation > 40:
    notes.append(f'FE% ({fe_pct}%) is {deviation}% off ideal (20%). Major rebalancing needed.')
elif deviation > 20:
    notes.append(f'FE% ({fe_pct}%) is {deviation}% off ideal (20%). Room for improvement.')

# Datacache limit proximity
if se_queries > 200 and se_queries <= 256:
    notes.append(f'SE queries ({se_queries}) approaching datacache limit of 256. Performance cliff ahead.')

# Parallelism interpretation (enhance existing check)
if se_par < 1.0 and se_ms > 20:
    notes.append(f'SE parallelism ({se_par}x) is sequential — single-threaded SE execution.')
elif 1.0 <= se_par < 2.0 and se_ms > 50:
    notes.append(f'SE parallelism ({se_par}x) is limited — not fully utilizing CPU cores.')
```

#### 1L. Also wire SeEventAnalyzer into `visual` trace flow

**File:** `server/handlers/debug_handler.py`, in `handle_debug_visual` — after trace results are available and SE events are captured, add:

```python
if trace and se_events:
    try:
        from core.dax.se_event_analyzer import SeEventAnalyzer
        response['se_analysis'] = SeEventAnalyzer().analyze(se_events, perf)
    except Exception:
        pass
```

Find the exact location by searching for where `se_events` is built in the visual handler. The SE event analysis should be added to the trace response.

---

### Phase 2: Extend Callback Detector — 5 New Rules

**File:** `core/dax/callback_detector.py`

Add 5 new rule classes following the existing `_BaseRule` pattern (see CB001-CB006 for reference). Each rule class needs:
- `rule_id` and `severity` class attributes
- `check(self, dax: str) -> List[CallbackDetection]` method

Register all in `CallbackDetector.__init__` where `self._rules` is built (around line 524-532).

#### CB007: DIVIDE() inside iterators — severity: high

Detect `DIVIDE(` inside iterator expression body. Use `_ITERATOR_RE` to find iterators, `extract_function_body` to get the body, `_get_expression_arg` to get the expression argument, then check for `DIVIDE(`.

Fix suggestion: "Use VAR to pre-calculate the division result before the iterator, or use the / operator with a pre-filter to exclude zero denominators: `CALCULATE(SUMX(T, T[A] / T[B]), T[B] <> 0)`"

#### CB008: ROUND/TRUNC/INT/CEILING/FLOOR inside iterators — severity: high

Same pattern as CB007 but detect: `r'\b(ROUND|ROUNDUP|ROUNDDOWN|TRUNC|INT|CEILING|FLOOR|MROUND)\s*\('`

Fix suggestion: "Pre-group rows using SUMMARIZE to reduce callback invocations. Instead of `SUMX(Sales, Sales[Qty] * ROUND(Sales[Price], 2))`, use `SUMX(SUMMARIZE(Sales, Sales[Price]), CALCULATE(SUM(Sales[Qty])) * ROUND(Sales[Price], 2))`"

#### CB009: String functions inside iterators — severity: medium

Detect: `r'\b(LEFT|RIGHT|MID|SUBSTITUTE|REPLACE|CONCATENATE|UPPER|LOWER|TRIM|LEN|FIND|SEARCH|REPT|FORMAT)\s*\('` inside iterator expression body.

Fix suggestion: "String operations always force FE row-by-row evaluation. Move string logic to a calculated column in the data model, or pre-compute in a VAR outside the iterator."

#### CB010: SELECTEDVALUE/HASONEVALUE inside iterators — severity: medium

Detect `SELECTEDVALUE(` or `HASONEVALUE(` inside iterator expression body.

Fix suggestion: "These functions are re-evaluated per row but always return the same value within the iterator. Cache the result in a VAR before the iterator: `VAR _sel = SELECTEDVALUE(Table[Col]) RETURN SUMX(T, ... _sel ...)`"

#### CB011: Complex date functions inside iterators — severity: medium

Detect: `r'\b(DATEADD|DATESYTD|DATESQTD|DATESMTD|DATESBETWEEN|DATESINPERIOD|SAMEPERIODLASTYEAR|PARALLELPERIOD)\s*\('` inside iterator expression body.

Fix suggestion: "Date intelligence functions create complex filter contexts per row. Cache the date range in a VAR before the iterator: `VAR _dates = DATEADD(...) RETURN SUMX(T, CALCULATE([M], _dates))`"

---

### Phase 3: Extend DAX Best Practices — 8 New Checks

**File:** `core/dax/dax_best_practices.py`

Add 8 new check methods following the existing `_check_*` pattern. Each returns `List[DaxIssue]`. Register all in `_initialize_checks()` (lines 161-182).

#### `_check_filter_bare_table` — CRITICAL

This is the **highest impact** check (117x performance difference per SQLBI research "Filter columns, not tables").

Pattern: `CALCULATE` with `FILTER(BareTable, ...)` where BareTable is not wrapped in ALL/VALUES/DISTINCT/etc.

```python
def _check_filter_bare_table(self, dax: str) -> List[DaxIssue]:
    # Look for FILTER( followed by a bare table name (not a function call)
    # Pattern: FILTER(\s*TableName\s*,  or  FILTER(\s*'Table Name'\s*,
    # But NOT: FILTER(ALL(...), FILTER(VALUES(...), FILTER(DISTINCT(...), etc.
    pattern = r"FILTER\s*\(\s*(?!ALL\b|VALUES\b|DISTINCT\b|ALLSELECTED\b|KEEPFILTERS\b|CALCULATETABLE\b|TOPN\b|SUMMARIZE\b|ADDCOLUMNS\b|SELECTCOLUMNS\b|GENERATE\b|UNION\b|INTERSECT\b|EXCEPT\b|FILTER\b|DATATABLE\b|GENERATESERIES\b)(?:'[^']+'\s*,|[A-Za-z_]\w*\s*,)"
```

Severity: CRITICAL. Category: PERFORMANCE.
Code before: `CALCULATE([Sales], FILTER(Sales, Sales[Amount] > 100))`
Code after: `CALCULATE([Sales], Sales[Amount] > 100)` or `CALCULATE([Sales], KEEPFILTERS(Sales[Amount] > 100))`
Estimated improvement: "10-100x faster (filters expanded table including all related tables via relationships)"
Article: `https://www.sqlbi.com/articles/filter-columns-not-tables-in-dax/`

#### `_check_selectedvalue_over_hasonevalue` — MEDIUM

Pattern: `IF\s*\(\s*HASONEVALUE\s*\([^)]+\)\s*,\s*VALUES\s*\(`

Code before: `IF(HASONEVALUE(Table[Col]), VALUES(Table[Col]))`
Code after: `SELECTEDVALUE(Table[Col])`
Article: `https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue`

#### `_check_keepfilters_opportunity` — MEDIUM

Pattern: `FILTER\s*\(\s*VALUES\s*\(\s*[^)]+\)\s*,` — FILTER wrapping VALUES with a simple predicate.

Code before: `CALCULATE([M], FILTER(VALUES(Table[Col]), Table[Col] = "X"))`
Code after: `CALCULATE([M], KEEPFILTERS(Table[Col] = "X"))`
Article: `https://www.sqlbi.com/articles/using-keepfilters-in-dax/`

#### `_check_var_defeating_shortcircuit` — HIGH

Pattern: Detect VAR definitions containing expensive operations (CALCULATE, SUMX, AVERAGEX, COUNTX, MAXX, MINX) that appear before IF/SWITCH. This is complex — look for VAR ... = CALCULATE/SUMX/... followed later by IF( or SWITCH(.

Code before: `VAR _sales = CALCULATE([Sales], ...) VAR _salesLY = CALCULATE([Sales LY], ...) RETURN IF(condition, _sales, _salesLY)`
Code after: `IF(condition, CALCULATE([Sales], ...), CALCULATE([Sales LY], ...))`
Estimated improvement: "50% faster when one branch is unused (VAR forces eager evaluation of all branches)"
Article: `https://www.sqlbi.com/articles/optimizing-if-and-switch-expressions-using-variables/`

#### `_check_count_vs_countrows` — LOW

Pattern: `COUNT\s*\(\s*[^)]*\[` — COUNT with a column reference.

Code before: `COUNT(Sales[OrderID])`
Code after: `COUNTROWS(Sales)`

#### `_check_all_table_vs_column` — MEDIUM

Pattern: `ALL\s*\(\s*(?:'[^']+'|[A-Za-z_]\w*)\s*\)` — ALL with just a table name (no column).

Code before: `CALCULATE([M], ALL(Sales))`
Code after: `CALCULATE([M], ALL(Sales[Region], Sales[Category]))` (only remove specific column filters)
Note: Only flag if the expression also references specific columns from that table.

#### `_check_addcolumns_summarize` — MEDIUM

Pattern: `ADDCOLUMNS\s*\(\s*SUMMARIZE\s*\(`

Code before: `ADDCOLUMNS(SUMMARIZE(Sales, Sales[Product]), "Total", [Total Sales])`
Code after: `SUMMARIZECOLUMNS(Sales[Product], "Total", [Total Sales])`
Estimated improvement: "2-5x faster — SUMMARIZECOLUMNS produces optimal query plans"
Article: `https://www.sqlbi.com/articles/introducing-summarizecolumns/`

#### `_check_divide_in_iterator` — HIGH

Pattern: `DIVIDE\s*\(` found inside an iterator body (SUMX, AVERAGEX, etc.). Uses same iterator detection as callback detector.

Code before: `SUMX(Sales, DIVIDE(Sales[Revenue], Sales[Cost]))`
Code after: `CALCULATE(SUMX(Sales, Sales[Revenue] / Sales[Cost]), Sales[Cost] <> 0)`
Estimated improvement: "DIVIDE always creates CallbackDataID in iterators. / operator can execute in SE."
Article: `https://www.sqlbi.com/articles/divide-performance/`

---

### Phase 4: Extend Code Rewriter — 4 New Transforms

**File:** `core/dax/code_rewriter.py`

Add 4 new transform methods to the `DaxCodeRewriter` class. Add them to the `rewrite_dax()` pipeline after the existing 5 transforms (after `_optimize_distinct_values`).

#### `_rewrite_iterator_to_calculate`

Pattern: `SUMX(FILTER(Table, condition), Table[Column])` or other X-functions with FILTER as first arg.
Transform to: `CALCULATE(SUM(Table[Column]), condition)`
Confidence: high
Estimated improvement: "5-10x faster"

Use regex to match `(SUMX|AVERAGEX|COUNTX|MAXX|MINX)\s*\(\s*FILTER\s*\(`. Extract the FILTER body to get table, condition, and expression. Map SUMX→SUM, AVERAGEX→AVERAGE, etc.

#### `_rewrite_filter_to_keepfilters`

Pattern: `FILTER(VALUES(Col), Col = value)` or `FILTER(ALL(Col), Col = value)` where predicate is simple equality/comparison.
Transform to: `KEEPFILTERS(Col = value)`
Confidence: high
Estimated improvement: "3-10x faster"

#### `_rewrite_hasonevalue_to_selectedvalue`

Pattern: `IF(HASONEVALUE(Table[Col]), VALUES(Table[Col]))` with optional third argument.
Transform to: `SELECTEDVALUE(Table[Col])` or `SELECTEDVALUE(Table[Col], alternate)`
Confidence: high

#### `_rewrite_callback_reduction`

Pattern: `SUMX(Table, expression_containing_ROUND_or_DIVIDE)`
Transform to: Template showing SUMMARIZE pre-grouping pattern.
Confidence: medium (template guidance, not exact rewrite — depends on available low-cardinality columns)

```
-- Template: reduce callbacks via pre-grouping
SUMX(
    SUMMARIZE(Table, Table[LowCardinalityColumn]),
    CALCULATE(SUM(Table[Quantity])) * ROUND(Table[LowCardinalityColumn], 2)
)
```

---

### Phase 5: Polish

#### 5A. Add `tl_dr` to response

In `handle_optimize_measure`, after building all results, generate a one-sentence summary:

```python
# Build tl;dr
tl_dr_parts = []
if static_callbacks.get('summary', {}).get('critical', 0):
    tl_dr_parts.append(f"{static_callbacks['summary']['critical']} critical callback patterns")
if bpa_result.get('critical_issues', 0):
    tl_dr_parts.append(f"{bpa_result['critical_issues']} critical DAX anti-patterns")
fe_pct_val = perf.get('fe_pct', 0)
if fe_pct_val > 60:
    tl_dr_parts.append(f"FE-bound at {fe_pct_val}%")
if tl_dr_parts:
    response['tl_dr'] = f"Key issues: {'; '.join(tl_dr_parts)}. See optimizations for fixes."
else:
    response['tl_dr'] = "No critical issues. Measure has acceptable performance characteristics."
```

#### 5B. Compact mode enhancements

When `compact=True`:
- Limit `optimizations` list to top 5 by priority
- Collapse `context_analysis` to just `{complexity_score, max_nesting_level, transition_count}`
- Omit empty `se_analysis` sub-sections

#### 5C. Update `_build_next_steps`

Add guidance for new analysis sources:

```python
# Context transition guidance
if context_result and context_result.get('max_nesting_level', 0) > 3:
    steps.append(
        f"Deep CALCULATE nesting detected (depth {context_result['max_nesting_level']}). "
        "Flatten nested CALCULATE into single CALCULATE with multiple filter arguments."
    )

# VertiPaq cardinality guidance
if vertipaq_result and vertipaq_result.get('high_cardinality_columns'):
    high_card = vertipaq_result['high_cardinality_columns']
    steps.append(
        f"High-cardinality columns in DAX: {', '.join(c.get('column', '') for c in high_card[:3])}. "
        "If these appear in iterators, reduce scope using SUMMARIZE or filter to subset."
    )

# SE event deep analysis guidance
if se_analysis:
    fusion = se_analysis.get('fusion_opportunities', {})
    if fusion.get('vertical_breaks', 0) > 2:
        steps.append(
            f"Vertical fusion broken ({fusion['vertical_breaks']} SE queries could be fused). "
            "Check for IF/SWITCH returning different measures — restructure to CALCULATE pattern."
        )
    if se_analysis.get('callbacks', {}).get('detected'):
        cb = se_analysis['callbacks']
        steps.append(
            f"Runtime CallbackDataID confirmed ({cb['total_count']} occurrences in SE events). "
            "This is the #1 priority — eliminate callbacks via SUMMARIZE pre-grouping."
        )
```

---

## Files Summary

| File | Action | Description |
| ---- | ------ | ----------- |
| `server/handlers/debug_handler.py` | Modify | Make timing required, wire ContextAnalyzer + VertiPaqAnalyzer + SeEventAnalyzer, update schema, update description, enhance `_diagnose_timing`, enhance `_build_next_steps`, add tl_dr, wire SE analysis into visual trace |
| `core/dax/se_event_analyzer.py` | **NEW** | Deep SE event analysis: callback type classification, datacache sizing, timing distribution, fusion detection, join type analysis, row ratio |
| `core/dax/callback_detector.py` | Extend | 5 new rules: CB007 (DIVIDE), CB008 (ROUND/TRUNC/INT), CB009 (strings), CB010 (SELECTEDVALUE), CB011 (date functions) |
| `core/dax/dax_best_practices.py` | Extend | 8 new checks: filter_bare_table, selectedvalue_over_hasonevalue, keepfilters_opportunity, var_defeating_shortcircuit, count_vs_countrows, all_table_vs_column, addcolumns_summarize, divide_in_iterator |
| `core/dax/code_rewriter.py` | Extend | 4 new transforms: iterator_to_calculate, filter_to_keepfilters, hasonevalue_to_selectedvalue, callback_reduction |

## Verification

1. Run `optimize` WITHOUT timing params → should get error message requiring timing
2. Run `optimize` WITH timing params (`fe_pct=75, se_queries=120, total_ms=3000, fe_ms=2250, se_ms=750`) → verify timing_diagnosis always present, timing-correlated suggestions boosted
3. Run `optimize` WITH `se_events` list → verify `se_analysis` field with deep analysis
4. Test new callback rules: write DAX with `SUMX(T, DIVIDE(T[A], T[B]))` → verify CB007 fires
5. Test new BPA checks: write DAX with `CALCULATE([M], FILTER(Sales, Sales[X] > 5))` → verify `_check_filter_bare_table` fires as CRITICAL
6. Test new code rewrites: write DAX with `SUMX(FILTER(T, cond), T[Col])` → verify rewrite to CALCULATE
7. Run `visual` with `trace=true` → verify `se_analysis` field appears in response
8. Verify schema: timing params visible in tool schema for MCP discovery

## Key Modules to Reuse (DO NOT RECREATE)

- `core/dax/context_analyzer.py` → `DaxContextAnalyzer.analyze_context_transitions(expression)` returns `ContextFlowExplanation`
- `core/dax/vertipaq_analyzer.py` → `VertiPaqAnalyzer(connection_state).analyze_dax_columns(expression)` returns dict
- `core/dax/dax_utilities.py` → `normalize_dax()`, `extract_function_body()`, `get_line_column()`
- `core/dax/callback_detector.py` → `_BaseRule` pattern, `_ITERATOR_RE`, `_get_expression_arg()`
- `core/dax/dax_best_practices.py` → `DaxIssue` dataclass, `IssueSeverity`, `IssueCategory` enums
- `core/dax/code_rewriter.py` → `Transformation` dataclass, pipeline pattern in `rewrite_dax()`

## Research Sources (for understanding fixes)

- SQLBI "Filter columns, not tables" — 117x improvement: https://www.sqlbi.com/articles/filter-columns-not-tables-in-dax/
- SQLBI "Optimizing callbacks in SUMX iterator" — SUMMARIZE pre-grouping: https://www.sqlbi.com/articles/optimizing-callbacks-in-a-sumx-iterator/
- SQLBI "DIVIDE performance" — / operator vs DIVIDE in iterators: https://www.sqlbi.com/articles/divide-performance/
- SQLBI "Vertical fusion" — how measures break fusion: https://docs.sqlbi.com/dax-internals/optimization-notes/vertical-fusion
- SQLBI "Horizontal fusion" — column predicate fusion: https://docs.sqlbi.com/dax-internals/optimization-notes/horizontal-fusion
- SQLBI "SWITCH optimization" — VAR defeating short-circuit: https://www.sqlbi.com/articles/optimizing-if-and-switch-expressions-using-variables/
- SQLBI "KEEPFILTERS best practices": https://www.sqlbi.com/articles/using-keepfilters-in-dax/
- Microsoft Learn "SELECTEDVALUE over HASONEVALUE": https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue
- Microsoft Learn "Avoid FILTER as filter argument": https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-avoid-filter-as-filter-argument
