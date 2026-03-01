"""
AS trace event subscription for SE/FE profiling.

Manages Analysis Services trace subscriptions via AMO Server traces
for capturing query performance events (QueryEnd, VertiPaqSEQueryEnd,
DirectQueryEnd, etc.).

Thread-safe: trace events arrive on .NET callback threads and are
collected into a shared list protected by threading.RLock().
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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

# Default event types to capture for SE/FE profiling
DEFAULT_EVENT_IDS = [
    TRACE_EVENT_QUERY_BEGIN,
    TRACE_EVENT_QUERY_END,
    TRACE_EVENT_VERTIPAQ_SE_QUERY_END,
    TRACE_EVENT_VERTIPAQ_SE_QUERY_CACHE_MATCH,
    TRACE_EVENT_DIRECT_QUERY_END,
]

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
            logger.debug("Cannot start trace: AMO not available")
            return False

        with self._lock:
            if self._trace_active:
                logger.warning("Trace already active; stop it first")
                return False

            try:
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
                from Microsoft.AnalysisServices import (  # type: ignore
                    Trace,
                    TraceColumn,
                    TraceEvent as AMOTraceEvent,
                    TraceEventClass,
                    UpdateMode,
                    UpdateOptions,
                )

                # Create a unique trace name
                import uuid
                trace_name = (
                    f"PBIXRay_SE_FE_{uuid.uuid4().hex[:8]}"
                )

                trace = server.Traces.Add(trace_name)

                # Configure event types
                ids = event_types or DEFAULT_EVENT_IDS
                desired_columns = [
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

                trace.Events.Clear()
                for event_id in ids:
                    try:
                        evt_class = TraceEventClass(event_id)
                        te = AMOTraceEvent(evt_class)
                        for col in desired_columns:
                            try:
                                te.Columns.Add(col)
                            except Exception:
                                # Column not supported for this event
                                pass
                        trace.Events.Add(te)
                    except Exception as e:
                        logger.debug(
                            f"Skipping trace event {event_id}: {e}"
                        )

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

                # Auto-stop after 1 hour as safety net
                import datetime
                trace.StopTime = (
                    datetime.datetime.utcnow()
                    + datetime.timedelta(hours=1)
                )

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
                logger.debug(
                    f"Trace started: {trace_name} "
                    f"({len(ids)} event types)"
                )
                return True

            except Exception as e:
                logger.warning(f"Failed to start trace: {e}")
                self._cleanup_trace()
                return False

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
                    logger.debug(
                        "Cannot create AMO server; "
                        "returning empty trace"
                    )
                    # Fall through: execute without trace
                    rows = self._execute_query(connection, query)
                    return rows, []
                own_server = True

            # Start trace
            started = self.start_trace(
                amo_server, connection, event_types
            )
            if not started:
                logger.debug(
                    "Trace start failed; executing without trace"
                )
                rows = self._execute_query(connection, query)
                return rows, []

            # Execute the query
            start_time = time.monotonic()
            rows = self._execute_query(connection, query)
            execution_ms = (time.monotonic() - start_time) * 1000

            # Wait for trace events to arrive
            # (they come asynchronously on .NET callback threads)
            self._wait_for_events(execution_ms)

            # Stop and collect events
            events = self.stop_trace()
            return rows, events

        except Exception as e:
            logger.error(f"execute_with_trace failed: {e}")
            # Try to stop trace on error
            try:
                self.stop_trace()
            except Exception:
                pass
            return [], []

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
            except Exception:
                pass

            cpu_time = 0.0
            try:
                cpu_time = float(event_args.CpuTime)
            except Exception:
                pass

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

        Returns:
            Connected AMO Server or None if unavailable.
        """
        if not _check_amo():
            return None

        try:
            from Microsoft.AnalysisServices.Tabular import (  # type: ignore
                Server as AMOServer,
            )

            conn_str = getattr(connection, "ConnectionString", None)
            if not conn_str:
                return None

            srv = AMOServer()
            srv.Connect(conn_str)
            return srv

        except Exception as e:
            logger.debug(f"Failed to create AMO server: {e}")
            return None

    def _execute_query(
        self, connection: Any, query: str
    ) -> List[Dict[str, Any]]:
        """
        Execute a DAX query via ADOMD and return rows as dicts.

        This is a minimal execution path used by execute_with_trace.
        For full query execution with validation, use the
        OptimizedQueryExecutor instead.
        """
        rows: List[Dict[str, Any]] = []
        reader = None
        try:
            from Microsoft.AnalysisServices.AdomdClient import (  # type: ignore
                AdomdCommand,
            )

            cmd = AdomdCommand(query, connection)
            cmd.CommandTimeout = 120
            reader = cmd.ExecuteReader()

            # Read column names
            col_count = reader.FieldCount
            col_names = [reader.GetName(i) for i in range(col_count)]

            while reader.Read():
                row = {}
                for i in range(col_count):
                    try:
                        val = reader.GetValue(i)
                        # Convert .NET types to Python
                        if val is not None and str(type(val)) != "<class 'NoneType'>":
                            row[col_names[i]] = str(val)
                        else:
                            row[col_names[i]] = None
                    except Exception:
                        row[col_names[i]] = None
                rows.append(row)

        except Exception as e:
            logger.error(f"Query execution in trace context failed: {e}")
        finally:
            if reader is not None:
                try:
                    reader.Close()
                except Exception:
                    pass

        return rows

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
