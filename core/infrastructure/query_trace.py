"""
Query Trace Runner for SE/FE timing analysis.

Captures Storage Engine and Formula Engine query timings via AMO server traces.
Python port of DaxTraceRunner.cs, following DAX Studio's trace setup patterns.
"""

import re
import time
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Trace configuration (aligned with DAX Studio)
_TRACE_PING_INTERVAL_S = 0.5
_TRACE_PING_COUNT = 5
_QUERY_END_TIMEOUT_S = 30
_STRAGGLER_WAIT_S = 2
_COMMAND_TIMEOUT_S = 300

# Compiled regexes for xmSQL cleaning
_RE_ALIAS = re.compile(r" AS\s*\[[^\]]*\]", re.IGNORECASE)
_RE_BRACKET = re.compile(r"(?<![\.0-9a-zA-Z'])\[([^\[)]*)\]")
_RE_DOT_BRACKET = re.compile(r"\.\[")
_RE_EST_SIZE = re.compile(r"Estimated size[^:]*:\s*(\d+),\s*(\d+)", re.IGNORECASE)
_RE_EST_ROWS = re.compile(r"rows\s*=\s*([\d,]+)", re.IGNORECASE)
_RE_EST_BYTES = re.compile(r"bytes\s*=\s*([\d,]+)", re.IGNORECASE)


@dataclass
class TraceEvent:
    """Single captured trace event."""
    event_class: str = ""
    event_subclass: str = ""
    duration: int = 0
    cpu_time: int = 0
    text_data: str = ""
    start_time: Any = None  # CLR DateTime
    end_time: Any = None


class QueryTraceRunner:
    """Captures SE/FE query timings via AMO server traces."""

    def __init__(self, adomd_connection, connection_string: str):
        self._adomd_conn = adomd_connection
        self._connection_string = connection_string
        self._events: List[TraceEvent] = []
        self._events_lock = threading.Lock()
        self._query_end_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_with_trace(self, query: str, clear_cache: bool = False) -> dict:
        """Execute a DAX query while capturing SE/FE trace events.

        Args:
            query: DAX query (EVALUATE statement).
            clear_cache: If True, clear VertiPaq cache before execution.

        Returns:
            Dict with total_ms, fe_ms, se_ms, se_cpu_ms, se_events, etc.
        """
        from Microsoft.AnalysisServices import (  # type: ignore
            Server as AMOServer,
            TraceColumn,
            TraceEventClass,
            UpdateOptions,
            UpdateMode,
        )
        from Microsoft.AnalysisServices.AdomdClient import AdomdCommand  # type: ignore
        import System  # type: ignore

        session_id = str(self._adomd_conn.SessionID)
        col_map, table_map = self._get_id_mappings()

        self._events.clear()
        self._query_end_event.clear()

        server = AMOServer()
        server.Connect(self._connection_string)
        trace = None

        try:
            trace_name = f"MCP_Trace_{session_id}_{int(time.time())}"
            trace = server.Traces.Add(trace_name)

            # Session filter
            filter_xml = (
                '<Or xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">'
                f"<Equal><ColumnID>{int(TraceColumn.SessionID)}</ColumnID>"
                f"<Value>{session_id}</Value></Equal>"
                f"<Equal><ColumnID>{int(TraceColumn.ApplicationName)}</ColumnID>"
                "<Value>MCP_Trace</Value></Equal>"
                "</Or>"
            )
            doc = System.Xml.XmlDocument()
            doc.LoadXml(filter_xml)
            trace.Filter = doc

            # Desired columns
            desired_cols = [
                TraceColumn.EventClass,
                TraceColumn.EventSubclass,
                TraceColumn.Duration,
                TraceColumn.CpuTime,
                TraceColumn.TextData,
                TraceColumn.StartTime,
                TraceColumn.EndTime,
                TraceColumn.SessionID,
                TraceColumn.CurrentTime,
                TraceColumn.ApplicationName,
                TraceColumn.DatabaseName,
            ]

            # Discover supported event/column combos via DMV
            supported = self._get_supported_events()

            # Heartbeat events (for trace activation)
            heartbeat = [
                TraceEventClass.DiscoverBegin,
                TraceEventClass.CommandBegin,
                TraceEventClass.QueryEnd,
            ]
            # Analysis events
            analysis = [
                TraceEventClass.QueryBegin,
                TraceEventClass.VertiPaqSEQueryEnd,
                TraceEventClass.VertiPaqSEQueryCacheMatch,
                TraceEventClass.DirectQueryEnd,
            ]

            trace.Events.Clear()
            from Microsoft.AnalysisServices import TraceEvent as AmoTraceEvent  # type: ignore
            for evt_class in heartbeat + analysis:
                evt_id = int(evt_class)
                if evt_id not in supported:
                    continue
                te = AmoTraceEvent(evt_class)
                sup_cols = supported[evt_id]
                for col in desired_cols:
                    if int(col) in sup_cols:
                        te.Columns.Add(col)
                trace.Events.Add(te)

            trace.OnEvent += self._on_trace_event
            trace.Update(UpdateOptions.Default, UpdateMode.CreateOrReplace)
            trace.Start()

            # Ping trace to activate event subscription (DAX Studio pattern)
            for _ in range(_TRACE_PING_COUNT):
                self._ping_trace()
                time.sleep(_TRACE_PING_INTERVAL_S)

            # Optionally clear cache
            cache_cleared = False
            if clear_cache:
                cache_cleared = self._clear_cache()

            # Execute DAX query
            row_count = 0
            cmd = AdomdCommand(query, self._adomd_conn)
            cmd.CommandTimeout = _COMMAND_TIMEOUT_S
            reader = cmd.ExecuteReader()
            try:
                while reader.Read():
                    row_count += 1
            finally:
                reader.Close()

            # Wait for QueryEnd event + stragglers
            self._query_end_event.wait(timeout=_QUERY_END_TIMEOUT_S)
            time.sleep(_STRAGGLER_WAIT_S)

        finally:
            if trace is not None:
                try:
                    trace.Stop()
                except Exception:
                    pass
                try:
                    trace.Drop()
                except Exception:
                    pass
            try:
                server.Disconnect()
            except Exception:
                pass

        return self._compute_timings(col_map, table_map, row_count, cache_cleared)

    # ------------------------------------------------------------------
    # CLR event callback (fires on .NET background thread)
    # ------------------------------------------------------------------

    def _on_trace_event(self, sender, e):
        """CLR callback. Must not throw."""
        try:
            text = str(e.TextData or "")
            if "$SYSTEM.DISCOVER_SESSIONS" in text or text.startswith("/* PING */"):
                return

            evt = TraceEvent(event_class=str(e.EventClass))
            try:
                evt.event_subclass = str(e.EventSubclass)
            except:
                pass
            try:
                evt.duration = int(e.Duration)
            except:
                pass
            try:
                evt.cpu_time = int(e.CpuTime)
            except:
                pass
            try:
                evt.start_time = e.StartTime
            except:
                try:
                    evt.start_time = e.CurrentTime
                except:
                    pass
            try:
                evt.end_time = e.EndTime
            except:
                pass
            evt.text_data = text

            with self._events_lock:
                self._events.append(evt)

            if evt.event_class == "QueryEnd":
                self._query_end_event.set()
        except:
            pass  # CLR callback must never throw

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ping_trace(self):
        """Ping the connection to activate trace subscription."""
        try:
            sid = str(self._adomd_conn.SessionID)
            cmd = self._adomd_conn.CreateCommand()
            cmd.CommandText = (
                f"SELECT * FROM $SYSTEM.DISCOVER_SESSIONS "
                f"WHERE SESSION_ID = '{sid}'"
            )
            reader = cmd.ExecuteReader()
            try:
                while reader.Read():
                    pass
            finally:
                reader.Close()
        except Exception:
            pass

    def _clear_cache(self) -> bool:
        """Clear VertiPaq cache via XMLA command."""
        try:
            db_name = self._get_database_name()
            if not db_name:
                return False
            xmla = (
                '<Batch xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">'
                "<ClearCache><Object>"
                f"<DatabaseID>{db_name}</DatabaseID>"
                "</Object></ClearCache></Batch>"
            )
            cmd = self._adomd_conn.CreateCommand()
            cmd.CommandText = xmla
            cmd.ExecuteNonQuery()
            logger.debug("VertiPaq cache cleared")
            return True
        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")
            return False

    def _get_database_name(self) -> Optional[str]:
        """Get current database name via DMV."""
        try:
            from Microsoft.AnalysisServices.AdomdClient import AdomdCommand  # type: ignore
            cmd = AdomdCommand(
                "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS",
                self._adomd_conn,
            )
            reader = cmd.ExecuteReader()
            try:
                if reader.Read():
                    return str(reader.GetValue(0))
            finally:
                reader.Close()
        except Exception:
            pass
        return None

    def _get_id_mappings(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Get column ID->name and table ID->name mappings via DMVs."""
        col_map: Dict[str, str] = {}
        table_map: Dict[str, str] = {}
        try:
            from Microsoft.AnalysisServices.AdomdClient import AdomdCommand  # type: ignore
            # Column mappings
            cmd = AdomdCommand(
                "SELECT COLUMN_ID, ATTRIBUTE_NAME FROM $SYSTEM.DISCOVER_STORAGE_TABLE_COLUMNS "
                "WHERE COLUMN_TYPE = 'BASIC_DATA'",
                self._adomd_conn,
            )
            reader = cmd.ExecuteReader()
            try:
                while reader.Read():
                    cid = str(reader.GetValue(0))
                    cname = str(reader.GetValue(1))
                    if cid not in col_map:
                        col_map[cid] = cname
            finally:
                reader.Close()

            # Table mappings
            cmd = AdomdCommand(
                "SELECT TABLE_ID, DIMENSION_NAME FROM $SYSTEM.DISCOVER_STORAGE_TABLES "
                "WHERE RIGHT(LEFT(TABLE_ID, 2), 1) <> '$'",
                self._adomd_conn,
            )
            reader = cmd.ExecuteReader()
            try:
                while reader.Read():
                    tid = str(reader.GetValue(0))
                    tname = str(reader.GetValue(1))
                    if tid not in table_map:
                        table_map[tid] = tname
            finally:
                reader.Close()
        except Exception as e:
            logger.debug(f"ID mapping lookup failed: {e}")
        return col_map, table_map

    def _get_supported_events(self) -> Dict[int, set]:
        """Discover supported trace event classes and columns via DMV."""
        result: Dict[int, set] = {}
        try:
            import xml.etree.ElementTree as ET
            from Microsoft.AnalysisServices.AdomdClient import AdomdCommand  # type: ignore
            cmd = AdomdCommand(
                "SELECT * FROM $SYSTEM.DISCOVER_TRACE_EVENT_CATEGORIES",
                self._adomd_conn,
            )
            reader = cmd.ExecuteReader()
            try:
                while reader.Read():
                    xml_str = str(reader.GetString(0))
                    root = ET.fromstring(xml_str)
                    for event_el in root.iter("EVENT"):
                        eid_el = event_el.find("ID")
                        if eid_el is None or eid_el.text is None:
                            continue
                        eid = int(eid_el.text)
                        cols = set()
                        for col_el in event_el.iter("EVENTCOLUMN"):
                            cid_el = col_el.find("ID")
                            if cid_el is not None and cid_el.text is not None:
                                cols.add(int(cid_el.text))
                        result[eid] = cols
            finally:
                reader.Close()
        except Exception as e:
            logger.debug(f"Trace event discovery failed, using fallback: {e}")
            # Fallback: common events with standard columns
            std = {0, 1, 2, 3, 5, 6, 8, 15, 16, 25, 36, 39, 40, 42, 43, 44, 45}
            result = {9: std, 10: std, 83: std, 85: std, 99: std, 15: std, 25: std}
        return result

    # ------------------------------------------------------------------
    # Timings computation
    # ------------------------------------------------------------------

    def _compute_timings(
        self,
        col_map: Dict[str, str],
        table_map: Dict[str, str],
        row_count: int,
        cache_cleared: bool,
    ) -> dict:
        """Compute SE/FE timings from collected trace events."""
        with self._events_lock:
            events = list(self._events)

        query_end = next((e for e in events if e.event_class == "QueryEnd"), None)
        se_events = [
            e
            for e in events
            if e.event_class == "VertiPaqSEQueryEnd"
            and e.event_subclass != "VertiPaqScanInternal"
        ]
        dq_events = [e for e in events if e.event_class == "DirectQueryEnd"]
        cache_events = [e for e in events if e.event_class == "VertiPaqSEQueryCacheMatch"]

        # Total duration from QueryEnd
        total_ms = query_end.duration if query_end else 0

        # SE parallel duration (merged overlapping intervals)
        all_se = se_events + dq_events
        se_parallel_ms = self._merge_intervals(all_se)

        # SE CPU
        se_cpu_ms = sum(e.cpu_time for e in all_se)

        # FE = Total - SE (never negative)
        fe_ms = max(0, total_ms - se_parallel_ms)

        # Parallelism
        se_parallelism = round(se_cpu_ms / se_parallel_ms, 1) if se_parallel_ms > 0 else 0.0

        # Percentages
        fe_pct = round(fe_ms / total_ms * 100, 1) if total_ms > 0 else 0.0
        se_pct = round(se_parallel_ms / total_ms * 100, 1) if total_ms > 0 else 0.0

        # Individual SE event details
        se_details = []
        for i, e in enumerate(se_events, 1):
            par = round(e.cpu_time / e.duration, 1) if e.duration > 0 else 1.0
            rows, kb = _parse_estimated_size(e.text_data)
            se_details.append(
                {
                    "line": i,
                    "duration_ms": e.duration,
                    "cpu_ms": e.cpu_time,
                    "parallelism": par,
                    "rows": rows,
                    "kb": kb,
                    "query": _clean_xmsql(e.text_data, col_map, table_map),
                }
            )

        return {
            "total_ms": int(total_ms),
            "fe_ms": int(fe_ms),
            "se_ms": int(se_parallel_ms),
            "se_cpu_ms": int(se_cpu_ms),
            "se_parallelism": se_parallelism,
            "se_queries": len(se_events),
            "se_cache_hits": len(cache_events),
            "fe_pct": fe_pct,
            "se_pct": se_pct,
            "se_events": se_details,
            "query_rows": row_count,
            "cache_cleared": cache_cleared,
        }

    @staticmethod
    def _merge_intervals(se_events: List[TraceEvent]) -> float:
        """Merge overlapping SE time intervals to get true parallel duration."""
        intervals = []
        for e in se_events:
            if e.start_time is not None and e.end_time is not None:
                intervals.append((e.start_time, e.end_time))
            elif e.start_time is not None and e.duration > 0:
                # Synthesize end from start + duration (CLR DateTime + TimeSpan)
                try:
                    import System  # type: ignore
                    end = e.start_time.Add(System.TimeSpan.FromMilliseconds(e.duration))
                    intervals.append((e.start_time, end))
                except Exception:
                    pass

        if not intervals:
            return sum(e.duration for e in se_events)

        intervals.sort(key=lambda x: x[0])
        merged_ms = 0.0
        current_end = None
        for start, end in intervals:
            if current_end is None or start > current_end:
                merged_ms += (end - start).TotalMilliseconds
                current_end = end
            elif end > current_end:
                merged_ms += (end - current_end).TotalMilliseconds
                current_end = end
        return merged_ms


# ======================================================================
# Module-level helpers (xmSQL cleaning, size parsing)
# ======================================================================


def _clean_xmsql(
    text: str, col_map: Dict[str, str], table_map: Dict[str, str]
) -> str:
    """Replace hex IDs with human-readable names, strip aliases and brackets."""
    if not text:
        return ""
    for cid, cname in col_map.items():
        if cid in text:
            text = text.replace(cid, cname)
    for tid, tname in table_map.items():
        if tid in text:
            text = text.replace(tid, tname)
    # Remove aliases like  AS [alias]
    text = _RE_ALIAS.sub("", text)
    # Replace standalone [Name] with 'Name'
    text = _RE_BRACKET.sub(lambda m: f"'{m.group(1)}'", text)
    # Fix .[col] -> [col]
    text = _RE_DOT_BRACKET.sub("[", text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text.strip()


def _parse_estimated_size(text: str) -> Tuple[int, int]:
    """Extract estimated rows and KB from xmSQL text."""
    rows, kb = 0, 0
    if not text:
        return rows, kb
    m = _RE_EST_SIZE.search(text)
    if m:
        rows = int(m.group(1))
        kb = max(1, int(m.group(2)) // 1024)
        return rows, kb
    m = _RE_EST_ROWS.search(text)
    if m:
        rows = int(m.group(1).replace(",", ""))
    m = _RE_EST_BYTES.search(text)
    if m:
        kb = max(1, int(m.group(1).replace(",", "")) // 1024)
    return rows, kb
