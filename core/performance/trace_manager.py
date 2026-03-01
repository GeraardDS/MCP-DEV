"""
AS trace event subscription for SE/FE profiling.

Manages Analysis Services trace subscriptions via AMO Server traces
for capturing query performance events (QueryEnd, VertiPaqSEQueryEnd,
DirectQueryEnd, etc.).

Thread-safe: trace events arrive on .NET callback threads and are
collected into a shared list protected by threading.RLock().
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Trace event class IDs (AS trace protocol)
# Reference: Microsoft.AnalysisServices.TraceEventClass enum
TRACE_EVENT_QUERY_BEGIN = 9
TRACE_EVENT_QUERY_END = 10
TRACE_EVENT_VERTIPAQ_SE_QUERY_BEGIN = 82
TRACE_EVENT_VERTIPAQ_SE_QUERY_END = 83
TRACE_EVENT_VERTIPAQ_SE_QUERY_CACHE_MATCH = 85
TRACE_EVENT_DIRECT_QUERY_END = 99
TRACE_EVENT_EXECUTION_METRICS = 136
TRACE_EVENT_AGGREGATE_TABLE_REWRITE = 131

# Default event types to capture for SE/FE profiling.
# QueryBegin (9) excluded: begin events don't support Duration/CpuTime.
# DirectQueryEnd (99) excluded: rejects EventSubclass (col Id=1) at
# trace.Update() time on the AS engine used by Power BI Desktop.
# DQ events are also irrelevant for VertiPaq/import models.
# ExecutionMetrics (136) excluded: rejects SessionID (col 39) and
# EventSubclass (col 1) — breaks the entire trace.Update() call.
DEFAULT_EVENT_IDS = [
    TRACE_EVENT_QUERY_END,
    TRACE_EVENT_VERTIPAQ_SE_QUERY_END,
    TRACE_EVENT_VERTIPAQ_SE_QUERY_CACHE_MATCH,
]

# Events that use minimal columns (no Duration/CpuTime/StartTime/EndTime).
# Cache-match events have no computation, so timing columns are unsupported.
# The AS engine rejects the entire trace.Update() call if any event gets
# an unsupported column — so these must be exact.
# All other events in DEFAULT_EVENT_IDS use full timing columns.
_MINIMAL_COLUMNS_IDS = [
    TRACE_EVENT_VERTIPAQ_SE_QUERY_CACHE_MATCH,
]

# Reverse lookup for readable log messages.
# Values are TraceColumn enum integers used by the AS trace protocol.
_COLUMN_ID_NAMES = {
    0: "EventClass", 1: "EventSubclass", 3: "Duration",
    4: "CpuTime", 5: "StartTime", 6: "EndTime",
    39: "SessionID", 42: "TextData", 43: "DatabaseName",
}

_EVENT_ID_NAMES = {
    9: "QueryBegin", 10: "QueryEnd",
    82: "VertiPaqSEQueryBegin", 83: "VertiPaqSEQueryEnd",
    85: "VertiPaqSEQueryCacheMatch", 99: "DirectQueryEnd",
    131: "AggregateTableRewriteQuery", 136: "ExecutionMetrics",
}

# Max retry attempts when trace.Update() rejects an event/column combo.
_MAX_TRACE_RETRIES = 4

# AMO availability (lazy-loaded)
_amo_checked = False
_amo_available = False


def _check_amo() -> bool:
    """Check if AMO/TOM assemblies are available. Cached after first call."""
    global _amo_checked, _amo_available
    if _amo_checked:
        return _amo_available
    try:
        from core.infrastructure.dll_paths import load_amo_assemblies
        _amo_available = load_amo_assemblies()
    except Exception as e:
        logger.debug(f"AMO assemblies not available: {e}")
        _amo_available = False
    _amo_checked = True
    return _amo_available


@dataclass
class TraceEvent:
    """A single captured trace event from the AS engine."""

    event_class: str        # "QueryEnd", "VertiPaqSEQueryEnd", etc.
    event_subclass: str = ""
    duration_ms: float = 0.0
    cpu_time_ms: float = 0.0
    text: str = ""          # xmSQL or DAX text
    timestamp: float = 0.0  # Python time.time() when captured
    start_time: Optional[float] = None  # Event start (epoch seconds)
    end_time: Optional[float] = None    # Event end (epoch seconds)
    additional_data: Dict[str, Any] = field(default_factory=dict)


class TraceManager:
    """
    Manages AS trace subscriptions via AMO Server traces.

    Provides thread-safe trace event collection for SE/FE profiling.
    Events arrive on .NET callback threads and are collected into a
    shared list protected by an RLock.

    Usage:
        tm = TraceManager()
        result, events = tm.execute_with_trace(connection, query)
    """

    # Timeout for waiting for trace events after query execution
    _EVENT_WAIT_TIMEOUT_S = 5.0
    # Poll interval while waiting for trace events
    _EVENT_POLL_INTERVAL_S = 0.1

    def __init__(self):
        self._lock = threading.RLock()
        self._events: List[TraceEvent] = []
        self._trace_active = False
        self._server = None
        self._trace = None
        self._event_handler = None
        self._session_id: Optional[str] = None

    @property
    def is_active(self) -> bool:
        """Whether a trace is currently active."""
        with self._lock:
            return self._trace_active

    @property
    def event_count(self) -> int:
        """Number of events collected so far."""
        with self._lock:
            return len(self._events)

    def start_trace(
        self,
        server: Any,
        connection: Any = None,
        event_types: Optional[List[int]] = None,
    ) -> bool:
        """
        Start collecting trace events on an AMO server.

        Includes automatic retry logic: if trace.Update() fails because
        the AS engine rejects a specific event/column combination, the
        offending column is excluded and the trace is rebuilt and retried
        (up to _MAX_TRACE_RETRIES attempts).

        Args:
            server: AMO Tabular.Server instance (already connected).
            connection: Optional ADOMD connection for session ID
                filtering. If provided, only events for this
                session are captured.
            event_types: List of trace event class IDs to capture.
                Defaults to DEFAULT_EVENT_IDS.

        Returns:
            True if the trace was started successfully.
        """
        if not _check_amo():
            logger.warning("Cannot start trace: AMO not available")
            return False

        with self._lock:
            if self._trace_active:
                logger.warning("Trace already active; stop it first")
                return False

            self._events.clear()
            self._server = server

            # Determine session ID for filtering
            self._session_id = None
            if connection is not None:
                try:
                    self._session_id = getattr(
                        connection, "SessionID", None
                    )
                except Exception:
                    pass

            # Import .NET trace types
            try:
                from Microsoft.AnalysisServices import (  # type: ignore
                    Trace,
                    TraceColumn,
                    TraceEvent as AMOTraceEvent,
                    TraceEventClass,
                    UpdateMode,
                    UpdateOptions,
                )
            except ImportError as e:
                logger.warning(f"Cannot import AMO trace types: {e}")
                return False

            ids = event_types or DEFAULT_EVENT_IDS

            # Track columns excluded by the AS engine across retries.
            # Key: event_id, Value: set of column_ids to skip.
            excluded_columns: Dict[int, Set[int]] = {}

            for attempt in range(_MAX_TRACE_RETRIES):
                trace = None
                try:
                    import uuid
                    trace_name = (
                        f"PBIXRay_SE_FE_{uuid.uuid4().hex[:8]}"
                    )
                    trace = server.Traces.Add(trace_name)

                    # Access trace.Events via .NET reflection to bypass a
                    # pythonnet name-collision: accessing trace.Events
                    # directly returns EventHandlerList (the OnEvent
                    # delegate store) rather than TraceEventCollection.
                    events_collection = None
                    try:
                        _prop = trace.GetType().GetProperty("Events")
                        if _prop is not None:
                            events_collection = _prop.GetValue(trace)
                    except Exception as e:
                        logger.warning(
                            f"Reflection access to trace.Events failed: {e}"
                        )

                    if events_collection is None:
                        logger.warning(
                            "trace.Events (TraceEventCollection) not "
                            "accessible; cannot configure trace events"
                        )
                        self._cleanup_trace()
                        return False

                    # Add events with column exclusions applied
                    events_added = self._add_trace_events(
                        events_collection, ids, excluded_columns,
                        TraceEventClass, AMOTraceEvent, TraceColumn,
                    )

                    if events_added == 0:
                        logger.warning(
                            "No trace events registered "
                            f"(tried {len(ids)} IDs); aborting"
                        )
                        try:
                            trace.Drop()
                        except Exception:
                            pass
                        self._cleanup_trace()
                        return False

                    # Apply session filter if available
                    if self._session_id:
                        try:
                            self._apply_session_filter(
                                trace, self._session_id, TraceColumn
                            )
                        except Exception as e:
                            logger.debug(
                                f"Could not apply session filter: {e}"
                            )

                    # Auto-stop after 1 hour as safety net.
                    # Must use System.DateTime — pythonnet cannot
                    # auto-convert Python datetime to .NET DateTime.
                    try:
                        import System  # type: ignore
                        trace.StopTime = (
                            System.DateTime.UtcNow.AddHours(1)
                        )
                    except Exception:
                        pass

                    # Subscribe to OnEvent callback
                    trace.OnEvent += self._on_trace_event
                    self._event_handler = self._on_trace_event

                    # Commit trace definition and start
                    trace.Update(
                        UpdateOptions.Default,
                        UpdateMode.CreateOrReplace,
                    )
                    trace.Start()

                    self._trace = trace
                    self._trace_active = True

                    retry_note = (
                        f" (after {attempt} retries, "
                        f"excluded: {self._format_exclusions(excluded_columns)})"
                        if attempt > 0 else ""
                    )
                    logger.info(
                        f"Trace started: {trace_name} "
                        f"({events_added}/{len(ids)} events)"
                        f"{retry_note}"
                    )
                    return True

                except Exception as e:
                    error_msg = str(e)

                    # Parse "event Id=X does not contain column Id=Y"
                    match = re.search(
                        r"event Id=(\d+).*?column Id=(\d+)",
                        error_msg,
                    )
                    if match and attempt < _MAX_TRACE_RETRIES - 1:
                        bad_event = int(match.group(1))
                        bad_col = int(match.group(2))
                        excluded_columns.setdefault(
                            bad_event, set()
                        ).add(bad_col)

                        evt_name = _EVENT_ID_NAMES.get(
                            bad_event, str(bad_event)
                        )
                        col_name = _COLUMN_ID_NAMES.get(
                            bad_col, str(bad_col)
                        )
                        logger.warning(
                            f"Trace retry {attempt + 1}/"
                            f"{_MAX_TRACE_RETRIES}: "
                            f"{evt_name} (id={bad_event}) rejected "
                            f"column {col_name} (id={bad_col}); "
                            f"rebuilding without it"
                        )

                        # Drop the failed trace before retry
                        if trace is not None:
                            try:
                                trace.OnEvent -= self._on_trace_event
                            except Exception:
                                pass
                            try:
                                trace.Drop()
                            except Exception:
                                pass
                        continue

                    # Non-retryable error or retries exhausted
                    logger.warning(f"Failed to start trace: {error_msg}")
                    if trace is not None:
                        try:
                            trace.Drop()
                        except Exception:
                            pass
                    self._cleanup_trace()
                    return False

            # Exhausted all retries
            logger.warning(
                f"Trace failed after {_MAX_TRACE_RETRIES} attempts; "
                f"excluded: {self._format_exclusions(excluded_columns)}"
            )
            self._cleanup_trace()
            return False

    def _add_trace_events(
        self,
        events_collection: Any,
        event_ids: List[int],
        excluded_columns: Dict[int, Set[int]],
        TraceEventClass: Any,
        AMOTraceEvent: Any,
        TraceColumn: Any,
    ) -> int:
        """
        Add trace events to the collection, respecting column exclusions.

        Returns the number of events successfully added.
        """
        # Full columns for end-events (they have Duration/CpuTime).
        # Minimal columns for cache-match / begin events — the AS
        # engine rejects the whole trace.Update() if any event is
        # given an unsupported column.
        full_columns = [
            TraceColumn.EventClass,
            TraceColumn.EventSubclass,
            TraceColumn.Duration,
            TraceColumn.CpuTime,
            TraceColumn.TextData,
            TraceColumn.StartTime,
            TraceColumn.EndTime,
            TraceColumn.SessionID,
            TraceColumn.ActivityID,
            TraceColumn.DatabaseName,
        ]
        minimal_columns = [
            TraceColumn.EventClass,
            TraceColumn.TextData,
            TraceColumn.SessionID,
        ]

        events_added = 0
        for event_id in event_ids:
            try:
                evt_class = TraceEventClass(event_id)
                te = AMOTraceEvent(evt_class)

                cols = (
                    minimal_columns
                    if event_id in _MINIMAL_COLUMNS_IDS
                    else full_columns
                )

                # Apply exclusions for this event
                excluded = excluded_columns.get(event_id, set())
                cols_added = 0
                cols_skipped = []

                for col in cols:
                    col_id = int(col)
                    if col_id in excluded:
                        cols_skipped.append(
                            _COLUMN_ID_NAMES.get(col_id, str(col_id))
                        )
                        continue
                    try:
                        te.Columns.Add(col)
                        cols_added += 1
                    except Exception as e:
                        logger.debug(
                            f"Column {col} add failed for "
                            f"event {event_id}: {e}"
                        )

                if cols_skipped:
                    evt_name = _EVENT_ID_NAMES.get(
                        event_id, str(event_id)
                    )
                    logger.debug(
                        f"Event {evt_name}: excluded columns "
                        f"{cols_skipped}"
                    )

                events_collection.Add(te)
                events_added += 1

            except Exception as e:
                evt_name = _EVENT_ID_NAMES.get(
                    event_id, str(event_id)
                )
                logger.warning(
                    f"Skipping trace event {evt_name} "
                    f"(id={event_id}): {e}"
                )

        return events_added

    @staticmethod
    def _format_exclusions(
        excluded: Dict[int, Set[int]]
    ) -> str:
        """Format excluded columns map for logging."""
        if not excluded:
            return "none"
        parts = []
        for eid, cids in excluded.items():
            evt = _EVENT_ID_NAMES.get(eid, str(eid))
            cols = [_COLUMN_ID_NAMES.get(c, str(c)) for c in cids]
            parts.append(f"{evt}:[{','.join(cols)}]")
        return " ".join(parts)

    def stop_trace(self) -> List[TraceEvent]:
        """
        Stop the active trace and return collected events.

        Returns:
            List of TraceEvent objects collected during the trace.
            Returns empty list if no trace was active.
        """
        with self._lock:
            if not self._trace_active:
                return list(self._events)

            try:
                self._stop_and_cleanup()
            except Exception as e:
                logger.debug(f"Error stopping trace: {e}")
                self._cleanup_trace()

            return list(self._events)

    def execute_with_trace(
        self,
        connection: Any,
        query: str,
        server: Optional[Any] = None,
        event_types: Optional[List[int]] = None,
    ) -> tuple:
        """
        Execute a DAX query while collecting trace events.

        This is the primary convenience method. It:
        1. Connects to AMO server if needed
        2. Starts a trace
        3. Executes the query via ADOMD
        4. Waits for trace events to arrive
        5. Stops the trace
        6. Returns (query_result_rows, trace_events)

        Args:
            connection: ADOMD connection (open, with SessionID).
            query: DAX query string (EVALUATE ...).
            server: Optional pre-connected AMO Server. If None,
                a new server connection is created from the ADOMD
                connection string.
            event_types: Optional list of trace event IDs.

        Returns:
            Tuple of (result_rows: List[Dict], events: List[TraceEvent]).
            result_rows may be empty if execution fails.
        """
        amo_server = server
        own_server = False

        try:
            # Create AMO server if not provided
            if amo_server is None:
                amo_server = self._create_amo_server(connection)
                if amo_server is None:
                    logger.warning(
                        "Cannot create AMO server; "
                        "returning empty trace"
                    )
                    # Fall through: execute without trace
                    t0 = time.monotonic()
                    rows = self._execute_query(connection, query)
                    ms = (time.monotonic() - t0) * 1000
                    return rows, [], ms
                own_server = True

            # Start trace
            started = self.start_trace(
                amo_server, connection, event_types
            )
            if not started:
                logger.warning(
                    "Trace start failed; executing without trace"
                )
                t0 = time.monotonic()
                rows = self._execute_query(connection, query)
                ms = (time.monotonic() - t0) * 1000
                return rows, [], ms

            # Execute the query
            start_time = time.monotonic()
            rows = self._execute_query(connection, query)
            execution_ms = (time.monotonic() - start_time) * 1000

            # Wait for trace events to arrive
            # (they come asynchronously on .NET callback threads)
            self._wait_for_events(execution_ms)

            # Stop and collect events
            events = self.stop_trace()
            return rows, events, execution_ms

        except Exception as e:
            logger.error(f"execute_with_trace failed: {e}")
            # Try to stop trace on error
            try:
                self.stop_trace()
            except Exception:
                pass
            return [], [], 0.0

        finally:
            if own_server and amo_server is not None:
                try:
                    amo_server.Disconnect()
                except Exception:
                    pass

    def clear_events(self):
        """Clear collected events."""
        with self._lock:
            self._events.clear()

    def get_events(self) -> List[TraceEvent]:
        """Return a copy of collected events."""
        with self._lock:
            return list(self._events)

    # ---- Internal helpers ----

    def _on_trace_event(self, sender: Any, event_args: Any):
        """
        Callback for trace events. Called from .NET thread.

        Thread-safe: appends to self._events under RLock.
        """
        try:
            # Extract event data from AMO TraceEventArgs
            text_data = ""
            try:
                text_data = str(event_args.TextData or "")
            except Exception:
                pass

            # Skip internal/ping events
            if (
                "$SYSTEM.DISCOVER_SESSIONS" in text_data
                or text_data.startswith("/* PING */")
            ):
                return

            event_class_str = ""
            try:
                event_class_str = str(event_args.EventClass)
            except Exception:
                pass

            event_subclass_str = ""
            try:
                event_subclass_str = str(event_args.EventSubclass)
            except Exception:
                pass

            duration = 0.0
            try:
                duration = float(event_args.Duration)
            except Exception as e:
                logger.debug(
                    f"Duration extraction failed for {event_class_str}: {e}"
                )

            cpu_time = 0.0
            try:
                raw_cpu = event_args.CpuTime
                cpu_time = float(raw_cpu)
            except Exception as e:
                logger.debug(
                    f"CpuTime extraction failed for {event_class_str}: "
                    f"{type(e).__name__}: {e}"
                )

            start_epoch = None
            try:
                st = event_args.StartTime
                if st is not None:
                    start_epoch = self._dotnet_datetime_to_epoch(st)
            except Exception:
                try:
                    ct = event_args.CurrentTime
                    if ct is not None:
                        start_epoch = self._dotnet_datetime_to_epoch(ct)
                except Exception:
                    pass

            end_epoch = None
            try:
                et = event_args.EndTime
                if et is not None:
                    end_epoch = self._dotnet_datetime_to_epoch(et)
            except Exception:
                pass

            evt = TraceEvent(
                event_class=event_class_str,
                event_subclass=event_subclass_str,
                duration_ms=duration,
                cpu_time_ms=cpu_time,
                text=text_data,
                timestamp=time.time(),
                start_time=start_epoch,
                end_time=end_epoch,
                additional_data={},
            )

            with self._lock:
                self._events.append(evt)

        except Exception as e:
            # Never let callback exceptions propagate to .NET
            logger.debug(f"Trace event callback error: {e}")

    def _wait_for_events(self, execution_ms: float):
        """
        Wait for trace events to arrive after query execution.

        Trace events are delivered asynchronously by the AS engine.
        We wait a bounded amount of time for the QueryEnd event
        to appear, which signals that all SE events have been sent.
        """
        # Minimum wait: proportional to execution time
        # Maximum wait: capped at _EVENT_WAIT_TIMEOUT_S
        min_wait = min(execution_ms / 1000.0 * 0.5, 1.0)
        max_wait = self._EVENT_WAIT_TIMEOUT_S
        deadline = time.monotonic() + max_wait

        # Always wait at least a small amount for events to arrive
        time.sleep(max(min_wait, 0.1))

        # Poll until we see a QueryEnd event or timeout
        while time.monotonic() < deadline:
            with self._lock:
                has_query_end = any(
                    e.event_class in ("QueryEnd", "10")
                    for e in self._events
                )
            if has_query_end:
                # Give a small buffer for trailing events
                time.sleep(0.1)
                break
            time.sleep(self._EVENT_POLL_INTERVAL_S)

    def _create_amo_server(self, connection: Any) -> Optional[Any]:
        """
        Create and connect an AMO Server from an ADOMD connection.

        Tries Microsoft.AnalysisServices.Server (has Traces collection)
        first, then falls back to Tabular.Server for connect-only.

        Returns:
            Connected AMO Server or None if unavailable.
        """
        if not _check_amo():
            logger.warning("_create_amo_server: AMO not available")
            return None

        conn_str = getattr(connection, "ConnectionString", None)
        if not conn_str:
            logger.warning("_create_amo_server: connection has no ConnectionString")
            return None

        # Try non-Tabular Server first — it has the Traces collection
        try:
            from Microsoft.AnalysisServices import (  # type: ignore
                Server as AMOServer,
            )
            srv = AMOServer()
            srv.Connect(conn_str)
            logger.debug("AMO Server connected (Microsoft.AnalysisServices)")
            return srv
        except Exception as e:
            logger.warning(
                f"_create_amo_server: Microsoft.AnalysisServices.Server.Connect failed: {e}"
            )

        return None

    def _execute_query(
        self, connection: Any, query: str
    ) -> List[Dict[str, Any]]:
        """
        Execute a DAX query via ADOMD, draining results fast.

        This is the profiling execution path used by execute_with_trace.
        It does NOT materialize rows — it only drains the reader to let
        the AS engine complete. Materializing rows through pythonnet is
        extremely slow (~500ms for 20K rows) and inflates QueryEnd.Duration
        via backpressure on the AS engine.

        For full query execution with data, use OptimizedQueryExecutor.
        """
        reader = None
        try:
            from Microsoft.AnalysisServices.AdomdClient import (  # type: ignore
                AdomdCommand,
            )

            cmd = AdomdCommand(query, connection)
            cmd.CommandTimeout = 120
            reader = cmd.ExecuteReader()

            # Drain the reader as fast as possible without extracting
            # values. Each Read() is a single .NET interop call vs
            # N×GetValue+str() calls per row when materializing.
            while reader.Read():
                pass

        except Exception as e:
            logger.error(f"Query execution in trace context failed: {e}")
        finally:
            if reader is not None:
                try:
                    reader.Close()
                except Exception:
                    pass

        return []

    def _apply_session_filter(
        self, trace: Any, session_id: str, TraceColumn: Any
    ):
        """Apply a session ID filter to a trace via XML."""
        import System.Xml  # type: ignore

        filter_xml = (
            '<Equal xmlns='
            '"http://schemas.microsoft.com/analysisservices/2003/engine">'
            f'<ColumnID>{int(TraceColumn.SessionID)}</ColumnID>'
            f'<Value>{session_id}</Value>'
            '</Equal>'
        )

        doc = System.Xml.XmlDocument()
        doc.LoadXml(filter_xml)
        trace.Filter = doc

    def _stop_and_cleanup(self):
        """Stop trace and clean up resources. Called under lock."""
        if self._trace is not None:
            try:
                self._trace.Stop()
            except Exception as e:
                logger.debug(f"Trace stop error: {e}")

            try:
                if self._event_handler is not None:
                    self._trace.OnEvent -= self._event_handler
            except Exception:
                pass

            try:
                self._trace.Drop()
            except Exception as e:
                logger.debug(f"Trace drop error: {e}")

        self._trace = None
        self._trace_active = False
        self._event_handler = None

    def _cleanup_trace(self):
        """Force-cleanup trace state without raising."""
        self._trace = None
        self._trace_active = False
        self._event_handler = None
        self._server = None

    @staticmethod
    def _dotnet_datetime_to_epoch(dt: Any) -> Optional[float]:
        """
        Convert a .NET DateTime to Python epoch seconds.

        Returns None if conversion fails.
        """
        try:
            # .NET DateTime.Ticks: 100ns intervals since 0001-01-01
            # Python epoch: seconds since 1970-01-01
            ticks = dt.Ticks
            # .NET epoch offset: ticks from 0001-01-01 to 1970-01-01
            EPOCH_TICKS = 621355968000000000
            return (ticks - EPOCH_TICKS) / 10_000_000.0
        except Exception:
            return None
