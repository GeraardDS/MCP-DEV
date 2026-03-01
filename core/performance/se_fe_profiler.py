"""
SE/FE timing breakdown with 3-layer fallback.

Provides Storage Engine (SE) and Formula Engine (FE) timing
analysis for DAX queries using the best available method:

Layer 1 (trace):    AMO trace events via TraceManager (preferred)
Layer 2 (executor): C# DaxExecutor subprocess (fallback)
Layer 3 (basic):    Simple wall-clock timing (last resort)

The profiler automatically falls through layers when a method
is unavailable or fails, ensuring a result is always returned.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from core.performance.se_fe_analyzer import SEFEAnalysis

logger = logging.getLogger(__name__)


@dataclass
class SEQuery:
    """A single Storage Engine query captured during profiling."""

    xmsql: str
    duration_ms: float
    cpu_ms: float
    cache_hit: bool
    dc_kind: str = ""           # "AUTO", "DENSE", etc. from xmSQL header


@dataclass
class SEFEResult:
    """
    SE/FE profiling result.

    Attributes:
        total_ms: Total query execution time in milliseconds.
        se_ms: Total Storage Engine time (sum of SE query durations,
            or net parallel duration if overlapping).
        fe_ms: Formula Engine time (total - se_ms).
        se_cpu_ms: Total CPU time consumed by SE queries.
        se_queries: Individual SE query details.
        se_cache_hits: Number of SE queries served from cache.
        profiling_method: Which layer produced this result:
            "trace", "executor", or "basic".
    """

    total_ms: float = 0.0
    se_ms: float = 0.0
    fe_ms: float = 0.0
    se_cpu_ms: float = 0.0
    fe_cpu_ms: float = 0.0          # FE CPU from ExecutionMetrics
    peak_memory_kb: int = 0         # Peak memory from ExecutionMetrics
    result_rows: int = 0            # Query result row count
    execution_delay_ms: float = 0.0 # Queue wait before execution started
    se_start_offset_ms: float = 0.0 # How long FE ran before first SE scan
    se_queries: List[SEQuery] = field(default_factory=list)
    se_cache_hits: int = 0
    profiling_method: str = "basic"

    @property
    def se_query_count(self) -> int:
        """Number of SE queries (excluding cache hits)."""
        return len(self.se_queries)

    @property
    def se_parallelism(self) -> float:
        """SE CPU/duration ratio indicating parallelism."""
        if self.se_ms > 0:
            return round(self.se_cpu_ms / self.se_ms, 1)
        return 0.0

    def analyze(self) -> "SEFEAnalysis":
        """Return structured optimization analysis for this result."""
        from core.performance.se_fe_analyzer import (
            SEFEAnalysis,
            analyze_se_fe,
        )
        return analyze_se_fe(self)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d: Dict[str, Any] = {
            "total_ms": round(self.total_ms, 1),
            "se_ms": round(self.se_ms, 1),
            "fe_ms": round(self.fe_ms, 1),
            "se_cpu_ms": round(self.se_cpu_ms, 1),
            "se_query_count": self.se_query_count,
            "se_cache_hits": self.se_cache_hits,
            "se_parallelism": self.se_parallelism,
            "profiling_method": self.profiling_method,
            "se_queries": [
                {
                    "xmsql": q.xmsql[:500],  # Truncate long xmSQL
                    "duration_ms": round(q.duration_ms, 1),
                    "cpu_ms": round(q.cpu_ms, 1),
                    "cache_hit": q.cache_hit,
                    **({"dc_kind": q.dc_kind} if q.dc_kind else {}),
                }
                for q in self.se_queries
            ],
        }
        # Include ExecutionMetrics extras only when available (non-zero)
        if self.fe_cpu_ms:
            d["fe_cpu_ms"] = round(self.fe_cpu_ms, 1)
        if self.peak_memory_kb:
            d["peak_memory_kb"] = self.peak_memory_kb
        if self.result_rows:
            d["result_rows"] = self.result_rows
        if self.execution_delay_ms:
            d["execution_delay_ms"] = round(self.execution_delay_ms, 1)
        if self.se_start_offset_ms:
            d["se_start_offset_ms"] = round(self.se_start_offset_ms, 1)
        # Always include analysis when we have trace-level data
        if self.profiling_method == "trace":
            d["analysis"] = self.analyze().to_dict()
        return d


class SEFEProfiler:
    """
    SE/FE profiling with automatic fallback.

    Tries three progressively simpler profiling methods:
    1. AMO trace events (richest data: xmSQL, per-query timing)
    2. C# DaxExecutor subprocess (good data: aggregate SE/FE)
    3. Basic wall-clock timing (minimal: total time only)

    Args:
        trace_manager: Optional TraceManager instance for Layer 1.
        executor_wrapper: Optional DaxExecutorWrapper for Layer 2.
    """

    def __init__(
        self,
        trace_manager: Optional[Any] = None,
        executor_wrapper: Optional[Any] = None,
    ):
        self._trace_manager = trace_manager
        self._executor = executor_wrapper

    def profile_query(
        self,
        connection: Any,
        query: str,
        server: Optional[Any] = None,
        connection_string: Optional[str] = None,
        dataset_name: Optional[str] = None,
    ) -> SEFEResult:
        """
        Profile a DAX query with the best available method.

        Tries Layer 1 (trace), falls back to Layer 2 (executor),
        then Layer 3 (basic timing).

        Args:
            connection: Open ADOMD connection for query execution.
            query: DAX query string (EVALUATE ...).
            server: Optional pre-connected AMO Server for Layer 1.
            connection_string: XMLA endpoint string for Layer 2.
                Required only if executor_wrapper is provided.
            dataset_name: Dataset/database name for Layer 2.
                Required only if executor_wrapper is provided.

        Returns:
            SEFEResult with profiling data from whichever layer
            succeeded.
        """
        # Layer 1: AMO trace events (preferred)
        if self._trace_manager is not None:
            result = self._profile_via_trace(
                connection, query, server
            )
            if result is not None:
                return result
            logger.warning(
                "Layer 1 (trace) failed; trying Layer 2"
            )

        # Layer 2: C# DaxExecutor
        if self._executor is not None:
            result = self._profile_via_executor(
                query, connection_string, dataset_name
            )
            if result is not None:
                return result
            logger.debug(
                "Layer 2 (executor) failed; trying Layer 3"
            )

        # Layer 3: Basic timing (always works)
        return self._profile_basic(connection, query)

    def _profile_via_trace(
        self,
        connection: Any,
        query: str,
        server: Optional[Any] = None,
    ) -> Optional[SEFEResult]:
        """
        Layer 1: Profile using AMO trace events.

        Subscribes to QueryEnd + VertiPaqSEQueryEnd + cache match
        events, executes the query, and parses the collected events
        into an SEFEResult.

        Returns:
            SEFEResult with profiling_method="trace", or None if
            trace is unavailable or failed.
        """
        from core.performance.trace_manager import TraceEvent

        try:
            rows, events = self._trace_manager.execute_with_trace(
                connection, query, server=server
            )
        except Exception as e:
            logger.debug(f"Trace execution failed: {e}")
            return None

        if not events:
            logger.warning("No trace events captured")
            return None

        return self._parse_trace_events(events)

    def _parse_trace_events(
        self, events: List[Any]
    ) -> Optional[SEFEResult]:
        """
        Parse trace events into an SEFEResult.

        Extracts QueryEnd for total time, VertiPaqSEQueryEnd for
        individual SE queries, ExecutionMetrics for FE CPU / peak
        memory / result rows, and cache match events.
        """
        query_end_event = None
        se_events = []
        cache_hits = 0
        exec_metrics: Dict[str, Any] = {}

        for evt in events:
            ec = evt.event_class
            if ec in ("QueryEnd", "10"):
                query_end_event = evt
            elif ec in ("VertiPaqSEQueryEnd", "83"):
                # Skip internal scan subclass (cardinality probe)
                if evt.event_subclass == "VertiPaqScanInternal":
                    continue
                se_events.append(evt)
            elif ec in ("VertiPaqSEQueryCacheMatch", "85"):
                cache_hits += 1
            elif ec in ("DirectQueryEnd", "99"):
                se_events.append(evt)
            elif ec in ("ExecutionMetrics", "136"):
                try:
                    exec_metrics = json.loads(evt.text or "{}")
                except Exception:
                    pass

        if query_end_event is None:
            logger.warning("No QueryEnd event found in trace")
            return None

        # Total duration from QueryEnd
        total_ms = query_end_event.duration_ms
        if total_ms <= 0:
            if (
                query_end_event.start_time is not None
                and query_end_event.end_time is not None
            ):
                total_ms = (
                    (query_end_event.end_time
                     - query_end_event.start_time)
                    * 1000.0
                )

        # Parse individual SE queries
        se_query_list: List[SEQuery] = []
        se_total_ms = 0.0
        se_cpu_total = 0.0

        for se_evt in se_events:
            dur = se_evt.duration_ms
            cpu = se_evt.cpu_time_ms
            xmsql = se_evt.text or ""
            dc_kind = self._extract_dc_kind(xmsql)

            se_query_list.append(
                SEQuery(
                    xmsql=xmsql,
                    duration_ms=dur,
                    cpu_ms=cpu,
                    cache_hit=False,
                    dc_kind=dc_kind,
                )
            )
            se_total_ms += dur
            se_cpu_total += cpu

        # Calculate net parallel SE duration via interval merging
        net_se_ms = self._calculate_net_parallel_duration(se_events)
        if net_se_ms is None or net_se_ms <= 0:
            net_se_ms = se_total_ms

        # FE = total - SE (clamped to 0)
        fe_ms = max(0.0, total_ms - net_se_ms)

        # SE start offset: how long FE ran alone before first SE scan
        se_start_offset_ms = self._calculate_se_start_offset(
            query_end_event, se_events
        )

        # ExecutionMetrics extras
        fe_cpu_ms = float(
            exec_metrics.get("queryProcessingCpuTimeMs", 0)
        )
        peak_memory_kb = int(
            exec_metrics.get("approximatePeakMemConsumptionKB", 0)
        )
        result_rows = int(
            exec_metrics.get("queryResultRows", 0)
        )
        execution_delay_ms = float(
            exec_metrics.get("executionDelayMs", 0)
        )

        return SEFEResult(
            total_ms=total_ms,
            se_ms=net_se_ms,
            fe_ms=fe_ms,
            se_cpu_ms=se_cpu_total,
            fe_cpu_ms=fe_cpu_ms,
            peak_memory_kb=peak_memory_kb,
            result_rows=result_rows,
            execution_delay_ms=execution_delay_ms,
            se_start_offset_ms=se_start_offset_ms,
            se_queries=se_query_list,
            se_cache_hits=cache_hits,
            profiling_method="trace",
        )

    @staticmethod
    def _extract_dc_kind(xmsql: str) -> str:
        """Extract DC_KIND value from an xmSQL string."""
        m = re.search(r'DC_KIND="([^"]+)"', xmsql)
        return m.group(1) if m else ""

    @staticmethod
    def _calculate_se_start_offset(
        query_end_event: Any, se_events: List[Any]
    ) -> float:
        """
        Calculate how many ms the FE ran before the first SE scan.

        Returns 0.0 if timestamps are unavailable.
        """
        if not se_events:
            return 0.0
        query_start = query_end_event.start_time
        if query_start is None:
            return 0.0
        se_starts = [
            e.start_time for e in se_events if e.start_time is not None
        ]
        if not se_starts:
            return 0.0
        return max(0.0, (min(se_starts) - query_start) * 1000.0)

    def _calculate_net_parallel_duration(
        self, se_events: List[Any]
    ) -> Optional[float]:
        """
        Calculate net parallel SE duration by merging overlapping
        time intervals.

        If SE queries run in parallel, their individual durations
        would overcount. This method merges overlapping intervals
        to get the actual wall-clock SE time.

        Returns:
            Net parallel duration in ms, or None if timestamps
            are not available.
        """
        # Collect (start, end) intervals
        intervals = []
        for evt in se_events:
            start = evt.start_time
            end = evt.end_time

            if start is not None and end is not None:
                intervals.append((start, end))
            elif start is not None and evt.duration_ms > 0:
                # Reconstruct end from start + duration
                end_est = start + (evt.duration_ms / 1000.0)
                intervals.append((start, end_est))

        if not intervals:
            return None

        # Sort by start time and merge overlapping intervals
        intervals.sort(key=lambda x: x[0])
        merged = [intervals[0]]

        for start, end in intervals[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                # Overlapping: extend the previous interval
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

        # Sum merged interval durations (in seconds -> ms)
        total_seconds = sum(end - start for start, end in merged)
        return total_seconds * 1000.0

    def _profile_via_executor(
        self,
        query: str,
        connection_string: Optional[str] = None,
        dataset_name: Optional[str] = None,
    ) -> Optional[SEFEResult]:
        """
        Layer 2: Profile using C# DaxExecutor subprocess.

        The executor returns a JSON response with Performance
        metrics: {Total, FE, SE, SE_CPU, SE_Par, SE_Queries,
        SE_Cache} and EventDetails for individual SE queries.

        Returns:
            SEFEResult with profiling_method="executor", or None
            if executor is unavailable or failed.
        """
        if not connection_string or not dataset_name:
            logger.debug(
                "Executor profiling requires connection_string "
                "and dataset_name"
            )
            return None

        try:
            success, result_data, error = (
                self._executor.execute_with_profiling(
                    query=query,
                    xmla_endpoint=connection_string,
                    dataset_name=dataset_name,
                )
            )

            if not success:
                logger.debug(f"Executor profiling failed: {error}")
                return None

            return self._parse_executor_result(result_data)

        except Exception as e:
            logger.debug(f"Executor profiling error: {e}")
            return None

    def _parse_executor_result(
        self, result_data: Dict[str, Any]
    ) -> Optional[SEFEResult]:
        """
        Parse DaxExecutor JSON output into an SEFEResult.

        Expected structure from DaxTraceRunner.cs:
        {
            "Performance": {
                "Total": 150.0, "FE": 80.0, "SE": 70.0,
                "SE_CPU": 120.0, "SE_Par": 1.7,
                "SE_Queries": 5, "SE_Cache": 1
            },
            "EventDetails": [
                {"Class": "SE", "Duration": 14.0, "CPU": 25.0,
                 "Query": "SET DC ...", ...},
                ...
            ]
        }
        """
        perf = result_data.get("Performance")
        if not perf:
            # Try lowercase keys (different serialization)
            perf = result_data.get("performance")
        if not perf:
            return None

        total_ms = float(perf.get("Total", 0))
        fe_ms = float(perf.get("FE", 0))
        se_ms = float(perf.get("SE", 0))
        se_cpu_ms = float(perf.get("SE_CPU", 0))
        se_query_count = int(perf.get("SE_Queries", 0))
        se_cache = int(perf.get("SE_Cache", 0))

        # Parse individual SE query details if available
        se_query_list: List[SEQuery] = []
        event_details = (
            result_data.get("EventDetails")
            or result_data.get("eventDetails")
            or []
        )

        for detail in event_details:
            evt_class = detail.get("Class", "")
            if evt_class in ("SE", "VertiPaqSEQueryEnd", "DQ"):
                se_query_list.append(
                    SEQuery(
                        xmsql=detail.get("Query", ""),
                        duration_ms=float(
                            detail.get("Duration", 0)
                        ),
                        cpu_ms=float(detail.get("CPU", 0)),
                        cache_hit=False,
                    )
                )

        return SEFEResult(
            total_ms=total_ms,
            se_ms=se_ms,
            fe_ms=fe_ms,
            se_cpu_ms=se_cpu_ms,
            se_queries=se_query_list,
            se_cache_hits=se_cache,
            profiling_method="executor",
        )

    def _profile_basic(
        self, connection: Any, query: str
    ) -> SEFEResult:
        """
        Layer 3: Simple wall-clock timing (last resort).

        Executes the query and measures total wall-clock time.
        No SE/FE breakdown is possible; se_ms and fe_ms remain 0.

        This always succeeds (unless the query itself fails,
        in which case total_ms reflects the time until failure).
        """
        reader = None
        start = time.monotonic()
        try:
            from Microsoft.AnalysisServices.AdomdClient import (  # type: ignore
                AdomdCommand,
            )

            cmd = AdomdCommand(query, connection)
            cmd.CommandTimeout = 120
            reader = cmd.ExecuteReader()

            # Drain the reader to ensure full execution
            while reader.Read():
                pass

        except Exception as e:
            logger.debug(f"Basic profiling query error: {e}")
        finally:
            if reader is not None:
                try:
                    reader.Close()
                except Exception:
                    pass

        total_ms = (time.monotonic() - start) * 1000.0

        return SEFEResult(
            total_ms=total_ms,
            se_ms=0.0,
            fe_ms=0.0,
            se_cpu_ms=0.0,
            se_queries=[],
            se_cache_hits=0,
            profiling_method="basic",
        )
