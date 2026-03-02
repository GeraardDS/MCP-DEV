# Task: Add `optimize` Operation to 09_Debug_Operations

## Background

Research was performed across three parallel agents covering:
1. Full codebase exploration of `server/handlers/debug_handler.py` and supporting modules
2. SE/FE DAX optimization theory (SQLBI, DAX Optimizer, Microsoft Learn)
3. DAX anti-pattern detection rules with regex patterns and fixes

This plan consolidates all findings into a concrete implementation spec.

---

## Goal

Add an `optimize` operation to the `09_Debug_Operations` MCP tool that:
- Accepts a **measure name** (not a pre-built query)
- Runs an SE/FE trace against that measure
- Analyzes the DAX expression for anti-patterns
- Detects `CallbackDataID` in SE events (the #1 performance enemy)
- Returns a prioritized, actionable list of optimization suggestions with before/after code

---

## Only File Modified

**`server/handlers/debug_handler.py`** — all changes live here.

---

## Step-by-Step Implementation

### Step 1 — Add `'optimize'` to the dispatch dict

Location: `handle_debug_operations()` function, approximately line 2566.

**Before:**
```python
dispatch = {
    'visual': handle_debug_visual,
    'compare': handle_compare_measures,
    'drill': handle_drill_to_detail,
    'analyze': handle_analyze_measure,
    'debug_variable': _handle_debug_variable,
    'step_variables': _handle_step_variables,
    'run_dax': _handle_run_dax,
}
```

**After:**
```python
dispatch = {
    'visual': handle_debug_visual,
    'compare': handle_compare_measures,
    'drill': handle_drill_to_detail,
    'analyze': handle_analyze_measure,
    'debug_variable': _handle_debug_variable,
    'step_variables': _handle_step_variables,
    'run_dax': _handle_run_dax,
    'optimize': handle_optimize_measure,
}
```

---

### Step 2 — Update the ToolDefinition schema

Location: The `ToolDefinition(name="09_Debug_Operations", ...)` call near the bottom of the file.

**a) Add `"optimize"` to the operation enum:**
```python
"operation": {
    "type": "string",
    "enum": ["visual", "compare", "drill", "analyze", "debug_variable", "step_variables", "run_dax", "optimize"],
    "default": "visual"
},
```

**b) Update the description string** — append to existing:
```
optimize (measure_name → SE/FE trace + DAX anti-pattern analysis + optimization suggestions with before/after code).
```

---

### Step 3 — Add four helper functions

Place all four functions together, just above or below `handle_analyze_measure`.

---

#### Helper A: `_analyze_se_callbacks`

Scans SE event list for `CallbackDataID` / `PFDATAID` strings — the clearest signal of FE-per-row invocation.

```python
def _analyze_se_callbacks(se_events: list) -> dict:
    """Detect CallbackDataID in SE events — the #1 performance anti-pattern."""
    callback_queries = []
    for evt in se_events:
        q = evt.get('query', '')
        if 'CallbackDataID' in q or 'PFDATAID' in q:
            callback_queries.append({
                'line': evt.get('line'),
                'duration_ms': evt.get('duration_ms'),
                'snippet': q[:300]
            })
    return {
        'detected': bool(callback_queries),
        'count': len(callback_queries),
        'queries': callback_queries
    }
```

---

#### Helper B: `_diagnose_timing`

Produces a plain-English timing profile from SE/FE percentages and query counts.

```python
def _diagnose_timing(perf: dict) -> dict:
    """Convert raw SE/FE metrics into a human-readable diagnosis."""
    fe_pct = perf.get('fe_pct', 0)
    se_queries = perf.get('se_queries', 0)
    se_ms = perf.get('se_ms', 0)
    se_par = perf.get('se_parallelism', 0)
    notes = []

    if fe_pct > 80:
        profile = 'FE-bound'
        notes.append(
            f'Formula Engine consumed {fe_pct}% of total time. '
            'The FE is single-threaded and uncached — this is the bottleneck. '
            'Focus on reducing iterators, context transitions, and pushing work to SE.'
        )
    elif fe_pct > 50:
        profile = 'FE-heavy'
        notes.append(
            f'Formula Engine consumed {fe_pct}% of time. '
            'DAX complexity is dominant. Consider simplifying filter arguments and reducing iterator scope.'
        )
    elif fe_pct < 20:
        profile = 'SE-bound'
        notes.append(
            f'Storage Engine consumed {100 - fe_pct}% of time. '
            'Check for large table scans, high-cardinality DISTINCTCOUNT, or missing aggregation tables.'
        )
    else:
        profile = 'balanced'
        notes.append(
            f'Good FE/SE balance ({fe_pct}% FE, {100 - fe_pct:.0f}% SE). '
            'Query performance is likely acceptable at this complexity level.'
        )

    if se_queries > 256:
        notes.append(
            f'CRITICAL: SE query count ({se_queries}) exceeds the datacache limit of 256. '
            'Cache provides no benefit. Redesign required to reduce SE fan-out.'
        )
    elif se_queries > 50:
        notes.append(
            f'High SE query count ({se_queries}). Investigate iterator structure — '
            'repeated sub-expressions should be captured in VAR to avoid re-evaluation.'
        )

    if se_ms > 20 and se_par < 2.0:
        notes.append(
            f'Low SE parallelism ({se_par}x). SE queries are not scaling across CPU cores. '
            'This can indicate small result sets or FE serialization forcing sequential SE calls.'
        )

    return {'profile': profile, 'notes': notes}
```

---

#### Helper C: `_build_optimize_suggestions`

Merges findings from three sources into one prioritized list.

```python
def _build_optimize_suggestions(
    bpa_result: dict,
    rewriter_result: dict,
    callback_info: dict,
    perf: dict,
    expression: str
) -> list:
    """
    Merge CallbackDataID findings, BPA issues, and rewriter suggestions
    into a single prioritized optimization list.

    Priority order:
      1. CallbackDataID alerts (always critical)
      2. timing-correlated high/critical BPA issues
      3. non-timing-correlated high/critical BPA issues
      4. timing-correlated medium BPA issues
      5. high-confidence rewriter suggestions
      6. non-timing-correlated medium/low BPA issues
      7. medium-confidence rewriter suggestions
    """
    suggestions = []
    fe_pct = perf.get('fe_pct', 0) if perf else 0

    # --- Source 1: CallbackDataID alerts ---
    if callback_info.get('detected'):
        for cb in callback_info.get('queries', []):
            suggestions.append({
                'priority': 0,  # Always first
                'severity': 'critical',
                'category': 'callback_elimination',
                'title': 'CallbackDataID detected in Storage Engine query',
                'description': (
                    'A CallbackDataID forces the Formula Engine (single-threaded, uncached) '
                    'to be invoked for every row during SE scan. '
                    'This can increase query time by 100x–260x compared to a pure SE query. '
                    f"Triggered in SE event line {cb.get('line')} ({cb.get('duration_ms')}ms). "
                    'Common causes: ROUND/TRUNC/INT/CEILING/FLOOR inside SUMX, '
                    'DIVIDE() anywhere, IF() inside iterators, text functions in row context.'
                ),
                'code_before': cb.get('snippet', ''),
                'code_after': (
                    '-- Pre-group by distinct values to minimize callback invocations:\n'
                    'SUMX(\n'
                    '    SUMMARIZE(FactTable, FactTable[ColumnWithLowCardinality]),\n'
                    '    CALCULATE(SUM(FactTable[Qty])) * callback_function(FactTable[ColumnWithLowCardinality])\n'
                    ')'
                ),
                'estimated_improvement': '10x–260x reduction in SE CPU time',
                'confidence': 'high',
                'timing_correlated': True
            })

    # --- FE-bound timing context — which BPA categories to boost ---
    fe_correlated_categories = set()
    if fe_pct > 50:
        fe_correlated_categories = {
            'performance', 'anti_pattern'  # These map to FE-driven issues
        }

    # --- Source 2: BPA issues ---
    severity_rank = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}

    for issue in (bpa_result.get('issues') or []):
        sev = issue.get('severity', 'low')
        cat = issue.get('category', '')
        is_timing_correlated = (
            cat in fe_correlated_categories
            or sev in ('critical', 'high')
        )

        sev_rank = severity_rank.get(sev, 3)
        priority_base = sev_rank * 10
        if is_timing_correlated:
            priority_base -= 3  # Boost timing-correlated items

        suggestions.append({
            'priority': 10 + priority_base,  # Offset so callbacks stay at 0
            'severity': sev,
            'category': cat,
            'title': issue.get('title', ''),
            'description': issue.get('description', ''),
            'code_before': issue.get('code_example_before'),
            'code_after': issue.get('code_example_after'),
            'estimated_improvement': issue.get('estimated_improvement'),
            'confidence': 'high',
            'timing_correlated': is_timing_correlated
        })

    # --- Source 3: Code rewriter transformations ---
    confidence_rank = {'high': 0, 'medium': 1, 'low': 2}
    for t in (rewriter_result.get('transformations') or []):
        conf = t.get('confidence', 'low')
        if conf == 'low':
            continue  # Skip low-confidence rewrites
        suggestions.append({
            'priority': 50 + confidence_rank.get(conf, 2),
            'severity': 'medium' if conf == 'high' else 'low',
            'category': 'code_rewrite',
            'title': f"Code rewrite: {t.get('type', 'optimization')}",
            'description': t.get('explanation', ''),
            'code_before': t.get('original', ''),
            'code_after': t.get('transformed', ''),
            'estimated_improvement': t.get('estimated_improvement'),
            'confidence': conf,
            'timing_correlated': False
        })

    # Sort by priority (lower = higher priority)
    suggestions.sort(key=lambda x: x['priority'])

    # Remove internal priority key from output
    for s in suggestions:
        s.pop('priority', None)

    return suggestions
```

---

#### Helper D: `_build_next_steps`

```python
def _build_next_steps(
    optimizations: list,
    perf: dict,
    callback_info: dict
) -> list:
    """Generate 2–4 actionable next steps based on findings."""
    steps = []
    fe_pct = perf.get('fe_pct', 0) if perf else 0
    se_queries = perf.get('se_queries', 0) if perf else 0
    has_rewrites = any(o.get('category') == 'code_rewrite' for o in optimizations)

    if callback_info.get('detected'):
        steps.append(
            'PRIORITY: Eliminate CallbackDataID — open DAX Studio Server Timings, '
            'locate the SE query containing CallbackDataID, identify the triggering '
            'function (ROUND/IF/DIVIDE inside iterator), and restructure using SUMMARIZE '
            'to pre-group by distinct values.'
        )

    if fe_pct > 60:
        steps.append(
            'FE-bound query: focus on pushing filter predicates to SE. '
            'Replace FILTER(table, condition) with Boolean expression CALCULATE arguments. '
            'Use KEEPFILTERS instead of FILTER(VALUES(...), ...).'
        )

    if se_queries > 50:
        steps.append(
            f'High SE query count ({se_queries}): introduce VAR to capture repeated '
            'sub-expressions (e.g., prior-year CALCULATE blocks used in both numerator '
            'and denominator of DIVIDE).'
        )

    if has_rewrites:
        steps.append(
            'A recommended_rewrite is available. Test it using '
            'operation=compare with original_measure and optimized_expression '
            'to benchmark the improvement.'
        )

    if not steps:
        steps.append(
            'No critical issues detected. This measure has good SE/FE balance. '
            'Monitor performance if data volume increases significantly.'
        )

    return steps
```

---

### Step 4 — Add the main `handle_optimize_measure` function

```python
def handle_optimize_measure(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    SE/FE trace + DAX analysis + optimization suggestions for a single measure.

    Accepts a measure name, resolves its expression, runs a cold-cache
    SE/FE trace, detects anti-patterns, and returns prioritized
    optimization suggestions with before/after code examples.
    """
    try:
        measure_name = (args.get('measure_name') or '').strip()
        table_name = args.get('table_name')
        clear_cache = args.get('clear_cache', True)
        compact = args.get('compact', True)

        if not measure_name:
            return {
                'success': False,
                'error': 'measure_name is required for optimize operation',
                'hint': 'Example: {"operation": "optimize", "measure_name": "Net Asset Value"}'
            }

        if not connection_state.is_connected():
            return {
                'success': False,
                'error': 'Not connected to Power BI model. Use connect_to_powerbi first.'
            }

        qe = connection_state.query_executor
        if not qe:
            return ErrorHandler.handle_manager_unavailable('query_executor')

        # ── Step 1: Resolve measure expression ───────────────────────────────
        resolved = _resolve_measure_expression(measure_name, table_name, qe)
        if not resolved.get('success'):
            return resolved

        expression = resolved['expression']
        measure_details = resolved['measure_details']
        resolved_table = measure_details.get('table_name') or table_name or 'm Measure'
        expression_source = resolved.get('expression_source', 'unknown')

        # ── Step 2: SE/FE trace ───────────────────────────────────────────────
        perf: dict = {}
        se_events: list = []
        trace_error: Optional[str] = None
        trace_available = False

        try:
            from core.infrastructure.query_trace import NativeTraceRunner
            conn_str = connection_state.connection_manager.connection_string

            if not conn_str:
                trace_error = 'No connection string available'
            elif not NativeTraceRunner.is_available():
                trace_error = 'DaxExecutor.exe not found — DAX analysis will proceed without timing data'
            else:
                # Build minimal evaluation query
                clean_measure = measure_name.strip('[]')
                trace_query = f"EVALUATE ROW(\"Value\", '{resolved_table}'[{clean_measure}])"

                runner = NativeTraceRunner(conn_str)
                tr = runner.execute_with_trace(trace_query, clear_cache=clear_cache)

                if '_error' in tr:
                    trace_error = tr['_error']
                else:
                    perf = {
                        'total_ms': tr.get('total_ms', 0),
                        'fe_ms': tr.get('fe_ms', 0),
                        'se_ms': tr.get('se_ms', 0),
                        'se_cpu_ms': tr.get('se_cpu_ms', 0),
                        'se_parallelism': tr.get('se_parallelism', 0.0),
                        'se_queries': tr.get('se_queries', 0),
                        'se_cache_hits': tr.get('se_cache_hits', 0),
                        'fe_pct': tr.get('fe_pct', 0.0),
                        'se_pct': tr.get('se_pct', 0.0),
                        'cache_cleared': tr.get('cache_cleared', False),
                    }
                    se_events = tr.get('se_events', [])
                    trace_available = True

        except Exception as te:
            logger.warning(f'SE/FE trace failed for optimize: {te}')
            trace_error = str(te)

        # ── Step 3: Inspect SE events for CallbackDataID ─────────────────────
        callback_info = _analyze_se_callbacks(se_events)

        # ── Step 4: Timing diagnosis ──────────────────────────────────────────
        timing_diagnosis = _diagnose_timing(perf) if trace_available else None

        # ── Step 5: DAX anti-pattern analysis ────────────────────────────────
        from core.dax.dax_best_practices import DaxBestPracticesAnalyzer
        bpa_result = DaxBestPracticesAnalyzer().analyze(expression)

        # ── Step 6: Code rewriter ─────────────────────────────────────────────
        from core.dax.code_rewriter import DaxCodeRewriter
        rewriter_result = DaxCodeRewriter().rewrite_dax(expression)

        # ── Step 7: Synthesize suggestions ───────────────────────────────────
        optimizations = _build_optimize_suggestions(
            bpa_result, rewriter_result, callback_info, perf, expression
        )

        # ── Step 8: Next steps ────────────────────────────────────────────────
        next_steps = _build_next_steps(optimizations, perf, callback_info)

        # ── Step 9: Build response ────────────────────────────────────────────
        response: Dict[str, Any] = {
            'success': True,
            'measure': {
                'name': measure_name,
                'table': resolved_table,
                'expression': expression,
                'source': expression_source,
            },
            'dax_analysis': {
                'score': bpa_result.get('overall_score'),
                'complexity': bpa_result.get('complexity_level'),
                'total_issues': bpa_result.get('total_issues', 0),
                'critical': bpa_result.get('critical_issues', 0),
                'high': bpa_result.get('high_issues', 0),
                'medium': bpa_result.get('medium_issues', 0),
                'low': sum(1 for i in bpa_result.get('issues', [])
                           if i.get('severity') in ('low', 'info')),
            },
            'optimizations': optimizations,
            'next_steps': next_steps,
        }

        if trace_available:
            response['timing'] = perf
            response['timing_diagnosis'] = timing_diagnosis
            if not compact:
                response['se_events'] = se_events
        elif trace_error:
            response['trace_unavailable'] = trace_error

        if rewriter_result.get('has_changes'):
            response['recommended_rewrite'] = rewriter_result.get('rewritten_code')

        return _compact_response(response, compact)

    except Exception as e:
        logger.error(f'Error in handle_optimize_measure: {e}', exc_info=True)
        return ErrorHandler.handle_unexpected_error('optimize_measure', e)
```

---

## Existing Functions Reused (No Changes to These)

| Function | Location | Purpose |
|---|---|---|
| `_resolve_measure_expression(name, table, qe)` | debug_handler.py ~line 1337 | 3-tier measure lookup: DMV → TMDL → fallback |
| `NativeTraceRunner(conn_str).execute_with_trace(query, clear_cache)` | core/infrastructure/query_trace.py | SE/FE timing trace via DaxExecutor.exe |
| `NativeTraceRunner.is_available()` | query_trace.py | Check if exe exists |
| `DaxBestPracticesAnalyzer().analyze(expression)` | core/dax/dax_best_practices.py | 15+ anti-pattern checks, returns issues[] with code_before/after |
| `DaxCodeRewriter().rewrite_dax(expression)` | core/dax/code_rewriter.py | Applies 5+ transformations, returns rewritten_code + transformations[] |
| `connection_state.is_connected()` | core/infrastructure/connection_state.py | Guard check |
| `connection_state.query_executor` | connection_state.py | QueryExecutor instance |
| `connection_state.connection_manager.connection_string` | connection_state.py | SSAS conn string for trace |
| `ErrorHandler.handle_unexpected_error()` | core/validation/error_handler.py | Exception handler |
| `_compact_response(data, compact)` | debug_handler.py | Token optimization |

---

## Key Design Decisions

### Why no new files?
All building blocks exist. The `optimize` operation is purely orchestration — it calls existing analyzers in sequence and synthesizes their output. Adding a new file would add unnecessary complexity.

### Why CallbackDataID gets priority 0?
It's the single most impactful SE performance issue. A measure with CallbackDataID in its SE trace is always a higher priority than any BPA issue regardless of severity. It's non-cacheable, runs per-row, and has documented 260x cost multipliers.

### Why is the trace query minimal (`EVALUATE ROW("Value", ...)`)?
We're measuring the measure's inherent DAX cost, not its cost in a specific visual. A minimal query with no filter context gives a reproducible baseline. Users who want real context timings should use `operation=visual` with `trace=true`.

### Graceful degradation
If `DaxExecutor.exe` isn't built (CI/CD environment, dev machine), the operation still returns full DAX analysis + suggestions — just without timing data. `trace_unavailable` key in response explains why.

### Timing correlation in suggestions
When the profile is `FE-bound`, BPA issues in `performance` and `anti_pattern` categories are boosted in priority because they are the likely cause of the FE bottleneck. This makes the suggestions order contextual rather than just severity-based.

---

## SE/FE Optimization Rules Embedded in Suggestions

The `_build_optimize_suggestions` function correlates timing profile with BPA categories. The underlying rules (already implemented in `DaxBestPracticesAnalyzer`) cover:

| Rule | BPA Detection | SE/FE Impact |
|---|---|---|
| FILTER(table, scalar) as CALCULATE arg | ✅ | FE: full table scan |
| SUMX over large unfiltered fact table | ✅ | FE: context transition per row |
| RELATED() inside fact-table iterator | ✅ | FE: per-row lookup |
| DISTINCTCOUNT on high-cardinality column | ✅ | SE: dictionary scan, no cache |
| Repeated sub-expression without VAR | ✅ | FE+SE: double evaluation |
| CROSSJOIN in measures | ✅ | FE: Cartesian explosion |
| Nested CALCULATE inside X-iterator | ✅ | FE: context transition per row |
| BLANK→0 forcing dense calculation | ✅ | SE: enumerate all groups |
| IF(HASONEVALUE) vs SELECTEDVALUE | ✅ | FE: count vs binary check |
| IFERROR/ISERROR wrapping | ✅ | SE: double scan |
| EARLIER() usage | ✅ | FE: stacked row contexts |
| CONCATENATEX over large sets | ✅ | FE: full materialization |
| CallbackDataID (new, timing-driven) | **NEW** | SE: per-row FE invocation |

---

## Verification Steps

1. **Connect** to R0101 Power BI instance
2. **Run**: `operation=optimize, measure_name="Net Asset Value"`
3. **Expect**:
   - `timing.fe_pct` populated
   - `timing_diagnosis.profile` = "balanced" (this is a clean SUM-based measure)
   - `dax_analysis.score` = high (few or no issues)
   - `optimizations` = small/empty list
   - `recommended_rewrite` = null (no rewrites needed)
4. **Test with a complex measure** that has FILTER/SUMX patterns → expect `optimizations` list with high-severity items
5. **Test graceful degradation**: pass unknown measure name → `success: false` with hint
6. **Test schema**: call with just `operation=optimize` (no measure_name) → clear error message
