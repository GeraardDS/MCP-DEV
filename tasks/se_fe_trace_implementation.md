# SE/FE Query Trace Analysis — Full Implementation Plan

> **Status**: Ready to implement. All research complete. Start a new session and reference this file.

## What We're Building

DAX Studio-style SE/FE (Storage Engine / Formula Engine) query analysis for the MCP server, working on live/open Power BI Desktop models. Captures server timings via AMO traces to show how query time is split between VertiPaq SE and the FE, plus individual xmSQL queries.

## Approach Decision

**Pure Python via pythonnet AMO traces** — no external .exe, no build step, uses existing loaded AMO DLLs.

Why not the C# DaxTraceRunner:
- The C# exe (`core/infrastructure/dax_executor/DaxExecutor.exe`) is NOT built — needs .NET 8 SDK
- The pure Python approach uses already-loaded DLLs and existing infrastructure
- Simpler, fewer moving parts

## Architecture

```
MCP Tool Call → query_trace_handler.py → QueryTraceRunner (query_trace.py)
                                              ↓
                                    AMO Server.Traces (trace management)
                                    + existing ADOMD connection (query execution)
                                              ↓
                                    Collect events → Compute SE/FE → Return results
```

---

## Files to Create

### 1. `core/infrastructure/query_trace.py` (~200 lines)

Core trace engine. No MCP awareness. Pure domain logic.

**Class `QueryTraceRunner`**:
- Constructor: `__init__(self, adomd_connection, connection_string)`
  - `adomd_connection` = existing ADOMD connection from `connection_manager.get_connection()`
  - `connection_string` = from `connection_manager.connection_string` (e.g., `Data Source=localhost:58738`)
- Main method: `execute_with_trace(query: str, clear_cache: bool = False) -> dict`

**Execution Flow**:
1. Get `SessionID` from ADOMD connection: `str(adomd_conn.SessionID)`
2. Get column/table ID→name mappings via DMVs (for xmSQL readability)
3. Open **separate** AMO `Server` connection for trace management
4. Create server trace with session filter, add events:
   - `QueryBegin` (ID=9), `QueryEnd` (ID=10) — total timing
   - `VertiPaqSEQueryEnd` (ID=83) — SE timing + xmSQL text
   - `VertiPaqSEQueryCacheMatch` (ID=85) — cache hits
   - `DirectQueryEnd` (ID=99) — for DirectQuery models
5. Add trace columns: EventClass, EventSubclass, Duration, CpuTime, TextData, StartTime, EndTime, SessionID, CurrentTime, ApplicationName, DatabaseName
6. Set session filter XML to only capture current session events
7. Subscribe `trace.OnEvent += self._on_trace_event` (thread-safe with `threading.Lock`)
8. `trace.Update()` then `trace.Start()`
9. Ping trace 5 times (500ms apart) to activate event subscription (DAX Studio pattern)
10. Optionally clear VertiPaq cache via XMLA `ClearCache` command
11. Execute DAX query via existing ADOMD connection
12. Wait for `QueryEnd` event (threading.Event with 30s timeout) + 2s buffer for stragglers
13. Stop & drop trace in `finally` block (guaranteed cleanup)
14. Compute SE/FE timings from collected events
15. Clean xmSQL text (replace column/table hex IDs with names)
16. Return result dict

**Key implementation details**:

**Trace setup** — uses AMO types already available via `dll_paths.load_amo_assemblies()`:
```python
from Microsoft.AnalysisServices import Server as AMOServer  # already used in query_executor.py
from Microsoft.AnalysisServices import (
    Trace, TraceEvent as AmoTraceEvent, TraceColumn,
    TraceEventClass, UpdateOptions, UpdateMode,
)
import System  # for XmlDocument (trace filter)
```

**Session filter XML** (same format as DAX Studio and DaxTraceRunner.cs):
```xml
<Or xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">
  <Equal><ColumnID>{SessionID_column_id}</ColumnID><Value>{session_id}</Value></Equal>
  <Equal><ColumnID>{ApplicationName_column_id}</ColumnID><Value>MCP_Trace</Value></Equal>
</Or>
```

**Event handler** (fires on .NET background thread via pythonnet):
```python
def _on_trace_event(self, sender, e):
    """CLR callback. Must not throw."""
    try:
        evt = TraceEvent(event_class=str(e.EventClass))
        # Access properties in try/except — not all populated for all events
        try: evt.duration = int(e.Duration)
        except: pass
        try: evt.cpu_time = int(e.CpuTime)
        except: pass
        try: evt.start_time = e.StartTime
        except: pass
        try: evt.end_time = e.EndTime
        except: pass
        evt.text_data = str(e.TextData or "")

        with self._events_lock:
            self._events.append(evt)

        if evt.event_class == "QueryEnd":
            self._query_end_event.set()
    except:
        pass  # CLR callback must never throw
```

**SE/FE computation**:
- **Total** = `QueryEnd.Duration` (or computed from start/end times)
- **SE (parallel)** = merged overlapping SE time intervals (handles parallel SE queries correctly)
- **FE** = Total - SE (can't be negative)
- **SE_CPU** = sum of all SE event `CpuTime` values
- **SE parallelism** = SE_CPU / SE_parallel_duration (>1 means multi-core)
- **SE queries** = count of `VertiPaqSEQueryEnd` events
- **SE cache hits** = count of `VertiPaqSEQueryCacheMatch` events

**Interval merging** (for accurate parallel SE duration):
```python
# Sort intervals by start time, merge overlapping
intervals = [(e.start_time, e.end_time) for e in se_events]
intervals.sort()
merged_ms = 0
current_end = None
for start, end in intervals:
    if current_end is None or start > current_end:
        merged_ms += (end - start).total_seconds() * 1000
        current_end = end
    elif end > current_end:
        merged_ms += (end - current_end).total_seconds() * 1000
        current_end = end
```

**Cache clearing via XMLA**:
```python
xmla = (
    '<Batch xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">'
    '<ClearCache><Object>'
    f'<DatabaseID>{database_id}</DatabaseID>'
    '</Object></ClearCache></Batch>'
)
cmd = AdomdCommand(xmla, adomd_conn)
cmd.ExecuteNonQuery()
```

**xmSQL cleaning** (column/table ID → name mapping via DMVs):
```sql
-- Column IDs
SELECT COLUMN_ID, ATTRIBUTE_NAME FROM $SYSTEM.DISCOVER_STORAGE_TABLE_COLUMNS WHERE COLUMN_TYPE = 'BASIC_DATA'
-- Table IDs
SELECT TABLE_ID, DIMENSION_NAME FROM $SYSTEM.DISCOVER_STORAGE_TABLES WHERE RIGHT(LEFT(TABLE_ID, 2), 1) <> '$'
```

---

### 2. `server/handlers/query_trace_handler.py` (~80 lines)

MCP handler. Follows exact pattern from `server/handlers/query_handler.py`.

**Tool name**: `04_Run_DAX_Trace`
**Category**: `query`
**Sort order**: 43 (after `04_Search_String` at 42)

**Input schema**:
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "DAX query (EVALUATE statement)"},
    "clear_cache": {"type": "boolean", "default": false, "description": "Clear VertiPaq cache before execution"}
  },
  "required": ["query"]
}
```

**Handler function** (`handle_run_dax_trace`):
1. Check `connection_state.is_connected()`
2. Get `adomd_conn` from `connection_state.connection_manager.get_connection()`
3. Get `conn_str` from `connection_state.connection_manager.connection_string`
4. Create `QueryTraceRunner(adomd_conn, conn_str)`
5. Call `runner.execute_with_trace(query, clear_cache)`
6. Format and return response

**Response format**:
```json
{
  "success": true,
  "performance": {
    "total_ms": 1234,
    "fe_ms": 450,
    "se_ms": 784,
    "se_cpu_ms": 1200,
    "se_parallelism": 1.5,
    "se_queries": 12,
    "se_cache_hits": 3,
    "fe_pct": 36.5,
    "se_pct": 63.5
  },
  "se_events": [
    {
      "line": 1,
      "duration_ms": 120,
      "cpu_ms": 180,
      "parallelism": 1.5,
      "query": "SET DC_KIND=\"AUTO\"; SELECT Sales[Amount], ..."
    }
  ],
  "query_rows": 50,
  "cache_cleared": false,
  "summary": "Total: 1234ms | FE: 450ms (36.5%) | SE: 784ms (63.5%) | SE queries: 12 | SE cache: 3"
}
```

---

## Files to Modify

### 3. `server/handlers/__init__.py` (+3 lines)

Add import at top:
```python
from server.handlers.query_trace_handler import register_query_trace_handler
```

Add registration call after `register_query_handlers(registry)` (line 68):
```python
register_query_trace_handler(registry)
```

### 4. `server/registry.py` (+2 changes)

Add to `CATEGORY_TOOLS[ToolCategory.QUERY]` list (line 49-53):
```python
ToolCategory.QUERY: [
    "04_Run_DAX",
    "04_Query_Operations",
    "04_Search_String",
    "04_Run_DAX_Trace",  # NEW
],
```

Update `CATEGORY_INFO[ToolCategory.QUERY]` tool_count from 3 to 4 (line 101).

---

## Key Technical Details

### .NET Types Already Available

- `Microsoft.AnalysisServices.Server` (AMO) — already used in `query_executor.py` as `AMOServer`
- `Microsoft.AnalysisServices.Trace`, `TraceEvent`, `TraceEventClass`, `TraceColumn` — in same assembly
- `Microsoft.AnalysisServices.AdomdClient.AdomdCommand` — already used everywhere
- DLLs loaded via `core/infrastructure/dll_paths.py` → `load_amo_assemblies()`

### Trace Event IDs (from Microsoft.AnalysisServices.TraceEventClass enum)

| Event | ID | Purpose |
|-------|----|---------|
| QueryBegin | 9 | Query start (DAX text) |
| QueryEnd | 10 | Query end (total Duration, CpuTime) |
| VertiPaqSEQueryBegin | 82 | SE query start |
| VertiPaqSEQueryEnd | 83 | SE query end (Duration, CpuTime, xmSQL in TextData) |
| VertiPaqSEQueryCacheMatch | 85 | SE cache hit |
| DirectQueryEnd | 99 | DirectQuery completion |
| ExecutionMetrics | 136 | High-level execution metrics |

### Trace Column IDs (from Microsoft.AnalysisServices.TraceColumn enum)

| Column | ID | Description |
|--------|----|-------------|
| EventClass | 0 | Event type |
| EventSubclass | 1 | Sub-type |
| Duration | 5 | Duration ms |
| CpuTime | 6 | CPU time ms |
| TextData | 42 | xmSQL / DAX text |
| SessionID | 39 | Session GUID |
| StartTime | 3 | Event start |
| EndTime | 4 | Event end |
| CurrentTime | 2 | Current time |
| ApplicationName | 37 | Client app name |
| DatabaseName | 28 | Database name |

### Connection Pattern

```python
# Get from connection_state (already connected)
conn_mgr = connection_state.connection_manager
adomd_conn = conn_mgr.get_connection()      # ADOMD connection for queries
conn_str = conn_mgr.connection_string         # "Data Source=localhost:{port}"

# Trace needs separate AMO connection
server = AMOServer()
server.Connect(conn_str)  # Same connection string works for AMO
```

### Risk: pythonnet Event Subscription

`trace.OnEvent += handler` is the standard pythonnet pattern for .NET events. Works in pythonnet 3.x. If it fails at runtime, fallback approach: skip real-time events, use a polling delay after query execution. Test immediately after writing the core module.

### Existing C# Reference (DO NOT USE, just for reference)

`core/infrastructure/dax_executor/DaxTraceRunner.cs` (1,600 lines) — comprehensive C# implementation derived from DAX Studio. Contains the exact trace setup, event handling, and SE/FE computation logic that this Python implementation ports. Key methods to reference:
- `CreateTrace()` — trace setup with events and filter
- `OnTraceEvent()` — event handler
- `CalculateNetParallelDuration()` — interval merging for parallel SE
- `CleanXmSQL()` — column/table ID replacement

---

## Verification Steps

1. Connect to PBI Desktop: `01_Connect_To_Instance`
2. Basic test: `04_Run_DAX_Trace` with `{"query": "EVALUATE ROW(\"x\", 1)"}` — should return near-zero timings
3. Real query + cache clear: `04_Run_DAX_Trace` with `{"query": "EVALUATE ...", "clear_cache": true}` — verify SE events and xmSQL appear
4. Cache test: Same query without clear_cache — verify SE cache hits increase
5. Cleanup: Verify no orphaned traces after each call

---

## Summary of Changes

| File | Action | Lines |
|------|--------|-------|
| `core/infrastructure/query_trace.py` | CREATE | ~200 |
| `server/handlers/query_trace_handler.py` | CREATE | ~80 |
| `server/handlers/__init__.py` | MODIFY | +3 |
| `server/registry.py` | MODIFY | +2 |
