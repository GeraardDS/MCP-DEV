"""Deep analysis of Storage Engine trace events from visual trace."""

import logging
import re
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Callback pattern in xmSQL WITH clauses
_CALLBACK_RE = re.compile(
    r'(CallbackDataID|EncodeCallback|RoundValueCallback|'
    r'MinMaxColumnPositionCallback|Cond)\s*\(',
    re.IGNORECASE,
)

# xmSQL WITH clause pattern: WITH $Expr0 := ( ... )
_WITH_CLAUSE_RE = re.compile(
    r'\$(\w+)\s*:=\s*\(\s*(CallbackDataID|EncodeCallback|RoundValueCallback|'
    r'MinMaxColumnPositionCallback|Cond)\s*\(([^)]*)\)',
    re.IGNORECASE,
)

# JOIN type patterns
_INNER_JOIN_RE = re.compile(r'\bINNER\s+JOIN\b', re.IGNORECASE)
_LEFT_OUTER_JOIN_RE = re.compile(r'\bLEFT\s+OUTER\s+JOIN\b', re.IGNORECASE)

# Aggregation function pattern for fusion analysis
_AGG_FUNC_RE = re.compile(
    r'\b(SUM|COUNT|MIN|MAX|AVG|DCOUNT|STDEV|VAR)\s*\(',
    re.IGNORECASE,
)


class SeEventAnalyzer:
    """Deep analysis of Storage Engine trace events from visual trace."""

    def analyze(self, se_events: list, perf: dict) -> dict:
        """Main entry point. Returns structured analysis dict.

        Args:
            se_events: List of SE event dicts from NativeTraceRunner
            perf: Performance dict with timing aggregates
        """
        if not se_events:
            return {'note': 'No SE events provided'}

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

    def _analyze_callbacks(self, se_events: list) -> dict:
        """Parse xmSQL WITH clauses for all callback types.

        Returns dict with detected flag, counts by type, and slowest callback query.
        """
        by_type: Dict[str, list] = {}
        total_count = 0
        slowest_cb_query: Optional[dict] = None
        slowest_cb_duration = 0.0

        for idx, evt in enumerate(se_events):
            query = evt.get('query', '') or evt.get('xmSQL', '') or ''
            duration = evt.get('duration_ms', 0) or evt.get('duration', 0) or 0
            line = evt.get('line', idx + 1)

            for m in _CALLBACK_RE.finditer(query):
                cb_type = m.group(1)
                total_count += 1
                snippet = query[max(0, m.start() - 30):m.end() + 50].strip()

                entry = {'line': line, 'duration_ms': duration, 'snippet': snippet}
                by_type.setdefault(cb_type, []).append(entry)

                if duration > slowest_cb_duration:
                    slowest_cb_duration = duration
                    slowest_cb_query = {
                        'line': line,
                        'duration_ms': duration,
                        'query': query[:200],
                    }

        return {
            'detected': total_count > 0,
            'total_count': total_count,
            'by_type': {k: v[:5] for k, v in by_type.items()},  # Limit per type
            'slowest_callback_query': slowest_cb_query,
        }

    def _analyze_datacache(self, se_events: list) -> dict:
        """Sum rows and KB across all SE events. Flag large queries."""
        total_rows = 0
        total_kb = 0
        large_queries: list = []
        materialization_warnings: list = []

        for idx, evt in enumerate(se_events):
            rows = evt.get('rows', 0) or 0
            kb = evt.get('kb', 0) or evt.get('size_kb', 0) or 0
            line = evt.get('line', idx + 1)
            total_rows += rows
            total_kb += kb

            if rows > 100_000:
                large_queries.append({
                    'line': line,
                    'rows': rows,
                    'kb': kb,
                    'query': (evt.get('query', '') or '')[:150],
                })
                if rows > 1_000_000:
                    materialization_warnings.append(
                        f'SE query at line {line} materialized {rows:,} rows — '
                        f'consider reducing table scope or adding filters.'
                    )

            if kb > 10_240:  # >10MB
                materialization_warnings.append(
                    f'SE query at line {line} consumed {kb:,} KB — '
                    f'large datacache allocation.'
                )

        # Sort by rows descending, take top 3
        large_queries.sort(key=lambda q: q['rows'], reverse=True)

        return {
            'total_rows': total_rows,
            'total_kb': total_kb,
            'largest_queries': large_queries[:3],
            'materialization_warnings': materialization_warnings[:5],
        }

    def _analyze_timing_distribution(self, se_events: list, perf: dict) -> dict:
        """Compute avg/median/max/p95 of SE query durations. Identify outliers."""
        durations = []
        for evt in se_events:
            d = evt.get('duration_ms', 0) or evt.get('duration', 0) or 0
            durations.append(d)

        if not durations:
            return {'avg_ms': 0, 'max_ms': 0, 'p95_ms': 0, 'outlier_queries': []}

        avg_ms = statistics.mean(durations)
        max_ms = max(durations)
        median_ms = statistics.median(durations)

        # p95
        sorted_d = sorted(durations)
        p95_idx = int(len(sorted_d) * 0.95)
        p95_ms = sorted_d[min(p95_idx, len(sorted_d) - 1)]

        # Outliers: >3x average (only if avg is meaningful)
        outlier_queries = []
        threshold = max(avg_ms * 3, 5)  # At least 5ms to avoid noise
        for idx, evt in enumerate(se_events):
            d = evt.get('duration_ms', 0) or evt.get('duration', 0) or 0
            if d > threshold:
                outlier_queries.append({
                    'line': evt.get('line', idx + 1),
                    'duration_ms': d,
                    'query': (evt.get('query', '') or '')[:150],
                })

        outlier_queries.sort(key=lambda q: q['duration_ms'], reverse=True)

        # Cache hit rate
        se_queries = perf.get('se_queries', 0) or len(se_events)
        se_cache_hits = perf.get('se_cache_hits', 0) or 0
        cache_hit_rate = (se_cache_hits / se_queries) if se_queries > 0 else 0.0

        # Parallelism assessment
        se_par = perf.get('se_parallelism', 0) or 0
        if se_par < 1.0:
            parallelism_assessment = 'sequential'
        elif se_par < 2.0:
            parallelism_assessment = 'limited'
        else:
            parallelism_assessment = 'good'

        return {
            'avg_ms': round(avg_ms, 2),
            'median_ms': round(median_ms, 2),
            'max_ms': round(max_ms, 2),
            'p95_ms': round(p95_ms, 2),
            'outlier_queries': outlier_queries[:5],
            'cache_hit_rate': round(cache_hit_rate, 3),
            'parallelism_assessment': parallelism_assessment,
        }

    def _detect_fusion_opportunities(self, se_events: list) -> dict:
        """Detect vertical and horizontal fusion breaks.

        Vertical: Multiple SE queries with same filter context but different aggregations.
        Horizontal: SE queries differing only in one column predicate value.
        """
        # Normalize each query by stripping aggregation to get filter context signature
        signatures: Dict[str, list] = {}
        predicate_groups: Dict[str, list] = {}

        for idx, evt in enumerate(se_events):
            query = evt.get('query', '') or evt.get('xmSQL', '') or ''
            if not query:
                continue

            # Vertical fusion: strip aggregation function to get signature
            signature = _AGG_FUNC_RE.sub('AGG(', query.strip())
            signatures.setdefault(signature, []).append(idx)

            # Horizontal fusion: normalize column predicate values
            # Replace literal values (numbers, strings) with placeholder
            normalized = re.sub(r"'[^']*'", "'?'", query)
            normalized = re.sub(r'\b\d+(\.\d+)?\b', '?', normalized)
            predicate_groups.setdefault(normalized, []).append(idx)

        vertical_breaks = sum(1 for v in signatures.values() if len(v) > 1)
        horizontal_breaks = sum(1 for v in predicate_groups.values() if len(v) > 1)

        # Estimate saveable queries (conservative)
        estimated_saveable = sum(
            len(v) - 1 for v in signatures.values() if len(v) > 1
        )

        notes = []
        if vertical_breaks > 0:
            notes.append(
                f'{vertical_breaks} groups of SE queries share the same filter context '
                f'but use different aggregations — vertical fusion is broken. '
                f'This often happens with IF/SWITCH returning different measures.'
            )
        if horizontal_breaks > 0:
            notes.append(
                f'{horizontal_breaks} groups of SE queries differ only in predicate '
                f'values — horizontal fusion is broken. '
                f'Consider restructuring to allow VertiPaq to batch these.'
            )

        return {
            'vertical_breaks': vertical_breaks,
            'horizontal_breaks': horizontal_breaks,
            'estimated_saveable_queries': estimated_saveable,
            'notes': notes,
        }

    def _analyze_join_types(self, se_events: list) -> dict:
        """Scan SE events for INNER JOIN vs LEFT OUTER JOIN patterns."""
        inner_joins = 0
        left_outer_joins = 0
        cartesian_warnings: list = []

        for idx, evt in enumerate(se_events):
            query = evt.get('query', '') or evt.get('xmSQL', '') or ''
            rows = evt.get('rows', 0) or 0
            line = evt.get('line', idx + 1)

            inner_count = len(_INNER_JOIN_RE.findall(query))
            outer_count = len(_LEFT_OUTER_JOIN_RE.findall(query))
            inner_joins += inner_count
            left_outer_joins += outer_count

            if inner_count > 0 and rows > 10_000:
                cartesian_warnings.append(
                    f'INNER JOIN at line {line} produced {rows:,} rows — '
                    f'may indicate Cartesian product from nested iterators or CROSSJOIN.'
                )

        return {
            'inner_joins': inner_joins,
            'left_outer_joins': left_outer_joins,
            'cartesian_warnings': cartesian_warnings[:5],
        }

    def _parse_xmsql_with_clause(self, query: str) -> list:
        """Parse WITH $Expr := (CallbackType(...)) from xmSQL query text.

        Returns list of dicts with expr_name, callback_type, arguments.
        """
        results = []
        for m in _WITH_CLAUSE_RE.finditer(query):
            results.append({
                'expr_name': m.group(1),
                'callback_type': m.group(2),
                'arguments': m.group(3).strip(),
            })
        return results

    def _analyze_row_ratio(self, se_events: list) -> dict:
        """Compute duration_ms / rows ratio to identify per-row FE overhead.

        High ratio (>0.01 ms/row) with callback presence = confirmed per-row FE cost.
        """
        queries_with_high_ratio = 0
        worst_ratio = 0.0
        worst_query_line = 0

        for idx, evt in enumerate(se_events):
            duration = evt.get('duration_ms', 0) or evt.get('duration', 0) or 0
            rows = evt.get('rows', 0) or 0
            line = evt.get('line', idx + 1)

            if rows < 1:
                continue

            ratio = duration / rows
            if ratio > 0.01:
                queries_with_high_ratio += 1
                if ratio > worst_ratio:
                    worst_ratio = ratio
                    worst_query_line = line

        return {
            'queries_with_high_ratio': queries_with_high_ratio,
            'worst_ratio': round(worst_ratio, 4),
            'worst_query_line': worst_query_line,
        }
