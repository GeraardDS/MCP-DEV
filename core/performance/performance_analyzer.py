"""
Enhanced Performance Analyzer with SE/FE trace profiling.

Uses TraceManager to capture AMO trace events (VertiPaqSEQueryEnd,
QueryEnd, etc.) for Storage Engine / Formula Engine timing breakdown.
Falls back to basic wall-clock timing when traces are unavailable.
"""
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EnhancedAMOTraceAnalyzer:
    """
    Performance analyzer for DAX query timing with SE/FE breakdown.

    Uses TraceManager (AMO trace events) for detailed SE/FE profiling.
    Falls back to basic wall-clock timing when AMO traces fail.
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.amo_available = False
        self._trace_manager = None

        logger.debug(f"Performance analyzer initialized with connection: {connection_string[:50]}...")

    def connect_amo(self) -> bool:
        """
        Attempt to load AMO assemblies and create TraceManager.

        Returns:
            True if AMO is available and TraceManager is ready.
        """
        try:
            from core.infrastructure.dll_paths import load_amo_assemblies
            if load_amo_assemblies():
                self.amo_available = True
                from core.performance.trace_manager import TraceManager
                self._trace_manager = TraceManager()
                logger.info("AMO libraries loaded; TraceManager ready for SE/FE profiling")
                return True
            else:
                logger.debug("AMO assemblies not available")
                self.amo_available = False
                return False
        except Exception as e:
            logger.debug(f"AMO setup failed: {e}")
            self.amo_available = False
            return False

    def analyze_query(
        self,
        query_executor,
        query: str,
        runs: int = 3,
        clear_cache: bool = True,
        include_event_counts: bool = False,
    ) -> Dict[str, Any]:
        """
        Analyze query performance with SE/FE breakdown.

        Tries AMO trace profiling first for real SE/FE timing split.
        Falls back to basic wall-clock timing if traces fail.

        Args:
            query_executor: Query executor instance (used for fallback).
            query: DAX query to analyze.
            runs: Number of benchmark runs (used in fallback mode).
            clear_cache: Whether to clear cache between runs.
            include_event_counts: Include detailed event counts.

        Returns:
            Performance analysis results with SE/FE timing breakdown.
        """
        if not query_executor:
            return {"success": False, "error": "Query executor not available"}

        # Try SE/FE trace profiling
        if self.amo_available and self._trace_manager:
            try:
                result = self._profile_with_trace(query)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"Trace profiling failed, falling back to basic: {e}")

        # Fallback: basic wall-clock timing
        return self._analyze_basic(query_executor, query, runs, clear_cache)

    def _profile_with_trace(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Profile query using AMO trace events for SE/FE breakdown.

        Creates a temporary ADOMD connection, runs the query with
        trace events active, and parses the results.

        Returns:
            Dict with SE/FE breakdown, or None if tracing failed.
        """
        try:
            from Microsoft.AnalysisServices.AdomdClient import (  # type: ignore
                AdomdConnection,
            )
        except ImportError:
            logger.debug("ADOMD.NET not available for trace profiling")
            return None

        conn = None
        try:
            conn = AdomdConnection(self.connection_string)
            conn.Open()

            rows, events = self._trace_manager.execute_with_trace(conn, query)

            if not events:
                logger.debug("Trace returned no events")
                return None

            return self._parse_se_fe_events(events, rows)

        except Exception as e:
            logger.debug(f"Trace profiling error: {e}")
            return None
        finally:
            if conn is not None:
                try:
                    conn.Close()
                    conn.Dispose()
                except Exception:
                    pass

    def _parse_se_fe_events(
        self, events: List[Any], rows: List[Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Parse trace events into SE/FE timing breakdown.

        Mirrors DAX Studio's calculation:
        - Total = QueryEnd.Duration
        - SE = sum of VertiPaqSEQueryEnd durations (with interval merging)
        - FE = Total - SE
        """
        query_end = None
        se_events = []
        cache_hits = 0

        for evt in events:
            ec = evt.event_class
            if ec in ("QueryEnd", "10"):
                query_end = evt
            elif ec in ("VertiPaqSEQueryEnd", "83"):
                if evt.event_subclass == "VertiPaqScanInternal":
                    continue
                se_events.append(evt)
            elif ec in ("VertiPaqSEQueryCacheMatch", "85"):
                cache_hits += 1
            elif ec in ("DirectQueryEnd", "99"):
                se_events.append(evt)

        if query_end is None:
            logger.debug("No QueryEnd event in trace — cannot compute SE/FE split")
            return None

        # Total from QueryEnd
        total_ms = query_end.duration_ms
        if total_ms <= 0 and query_end.start_time and query_end.end_time:
            total_ms = (query_end.end_time - query_end.start_time) * 1000.0

        # SE timing: try interval merging for parallel SE queries
        se_sum_ms = 0.0
        se_cpu_ms = 0.0
        se_query_details = []

        for se_evt in se_events:
            dur = se_evt.duration_ms
            cpu = se_evt.cpu_time_ms
            se_sum_ms += dur
            se_cpu_ms += cpu
            se_query_details.append({
                "xmsql": (se_evt.text or "")[:500],
                "duration_ms": round(dur, 1),
                "cpu_ms": round(cpu, 1),
            })

        # Try net parallel duration via interval merging
        net_se_ms = self._calculate_net_parallel_se(se_events)
        if net_se_ms is None or net_se_ms <= 0:
            net_se_ms = se_sum_ms

        fe_ms = max(0.0, total_ms - net_se_ms)

        # SE parallelism ratio
        se_parallelism = round(se_cpu_ms / net_se_ms, 1) if net_se_ms > 0 else 0.0

        return {
            "success": True,
            "profiling_method": "AMO_TRACE",
            "summary": {
                "total_ms": round(total_ms, 1),
                "se_ms": round(net_se_ms, 1),
                "fe_ms": round(fe_ms, 1),
                "se_cpu_ms": round(se_cpu_ms, 1),
                "se_pct": round(net_se_ms / total_ms * 100, 1) if total_ms > 0 else 0.0,
                "fe_pct": round(fe_ms / total_ms * 100, 1) if total_ms > 0 else 0.0,
                "se_query_count": len(se_events),
                "se_cache_hits": cache_hits,
                "se_parallelism": se_parallelism,
            },
            "se_queries": se_query_details,
            "row_count": len(rows) if rows else 0,
        }

    def _calculate_net_parallel_se(self, se_events: List[Any]) -> Optional[float]:
        """Merge overlapping SE query time intervals for net parallel duration."""
        intervals = []
        for evt in se_events:
            start = evt.start_time
            end = evt.end_time
            if start is not None and end is not None:
                intervals.append((start, end))
            elif start is not None and evt.duration_ms > 0:
                intervals.append((start, start + evt.duration_ms / 1000.0))

        if not intervals:
            return None

        intervals.sort(key=lambda x: x[0])
        merged = [intervals[0]]
        for start, end in intervals[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

        return sum(end - start for start, end in merged) * 1000.0

    def _analyze_basic(
        self,
        query_executor,
        query: str,
        runs: int = 3,
        clear_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Fallback: basic wall-clock timing without SE/FE breakdown.
        """
        try:
            logger.info(f"Basic performance analysis: {runs} runs")

            # Warm-up run
            result = query_executor.validate_and_execute_dax(query, top_n=0)
            if not result.get("success"):
                return {
                    "success": False,
                    "error": f"Warm-up run failed: {result.get('error', 'Unknown error')}",
                }

            timings = []
            for i in range(runs):
                if clear_cache and i > 0:
                    try:
                        query_executor.execute_xmla_command(
                            '<ClearCache xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">'
                            "<Object><DatabaseID>"
                            + query_executor.connection_string.split("=")[-1].split(";")[0]
                            + "</DatabaseID></Object>"
                            "</ClearCache>"
                        )
                    except Exception:
                        pass

                start_time = time.time()
                result = query_executor.validate_and_execute_dax(query, top_n=0)
                end_time = time.time()

                if not result.get("success"):
                    continue

                timings.append((end_time - start_time) * 1000)

            if not timings:
                return {"success": False, "error": "All benchmark runs failed"}

            avg_total = sum(timings) / len(timings)

            return {
                "success": True,
                "profiling_method": "BASIC_TIMING",
                "summary": {
                    "total_ms": round(avg_total, 2),
                    "avg_execution_ms": round(avg_total, 2),
                    "min_execution_ms": round(min(timings), 2),
                    "max_execution_ms": round(max(timings), 2),
                    "runs_completed": len(timings),
                },
                "notes": ["SE/FE breakdown unavailable; showing wall-clock timing only"],
            }

        except Exception as e:
            logger.error(f"Basic performance analysis failed: {e}", exc_info=True)
            return {"success": False, "error": f"Performance analysis failed: {str(e)}"}
