"""
Query Trace Runner for SE/FE timing analysis.

Uses native .NET DaxExecutor.exe for accurate trace timings.
The exe connects to SSAS natively, runs the AMO server trace,
and returns JSON on stdout — no pythonnet overhead.
"""

import json
import subprocess
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Subprocess timeout: 5 min query + 1 min margin for trace setup/teardown
_SUBPROCESS_TIMEOUT_S = 360


class NativeTraceRunner:
    """Executes trace via native .NET DaxExecutor.exe for accurate timings.

    Bypasses pythonnet entirely — the C# exe connects to SSAS natively,
    runs the trace, and returns JSON on stdout.
    """

    def __init__(self, connection_string: str):
        self._connection_string = connection_string
        self._exe_path = self._find_exe()

    @staticmethod
    def is_available() -> bool:
        """Check if the native trace runner exe exists."""
        from core.infrastructure.dll_paths import get_trace_runner_path
        return get_trace_runner_path() is not None

    def _find_exe(self) -> str:
        from core.infrastructure.dll_paths import get_trace_runner_path
        path = get_trace_runner_path()
        if path is None:
            raise FileNotFoundError(
                "DaxExecutor.exe not found. "
                "Run: cd core/infrastructure/dax_executor && dotnet build -c Release"
            )
        return path

    def execute_with_trace(self, query: str, clear_cache: bool = True) -> dict:
        """Execute DAX with native trace. Returns dict with timing metrics."""
        # .NET 8 resolves 'localhost' to IPv6 ::1, but PBI Desktop SSAS only
        # listens on IPv4 127.0.0.1. Normalise before passing to the exe.
        conn_str = self._connection_string.replace("localhost:", "127.0.0.1:")
        request = json.dumps({
            "connection_string": conn_str,
            "query": query,
            "clear_cache": clear_cache,
        })

        try:
            result = subprocess.run(
                [self._exe_path, "--local"],
                input=request,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            logger.error("Native trace runner timed out")
            return {"_error": "Native trace runner timed out"}
        except FileNotFoundError:
            logger.error("DaxExecutor.exe not found at %s", self._exe_path)
            return {"_error": "DaxExecutor.exe not found"}

        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                logger.debug("TraceRunner: %s", line)

        try:
            response = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse trace runner output: %s", e)
            logger.error("stdout (first 500): %s", result.stdout[:500])
            return {"_error": f"Failed to parse native trace output: {e}"}

        # Check for error in C# response
        perf = response.get("Performance", {})
        if perf.get("Error"):
            return {"_error": perf.get("ErrorMessage", "Unknown trace error")}

        return self._map_response(response)

    @staticmethod
    def _map_response(response: dict) -> dict:
        """Map C# output format to Python handler format."""
        perf = response.get("Performance", {})
        events = response.get("EventDetails", [])

        total_ms = perf.get("Total", 0)
        fe_ms = perf.get("FE", 0)
        se_ms = perf.get("SE", 0)

        # Map SE event details (filter to SE events only, skip FE segments)
        se_details = []
        se_line = 1
        for evt in events:
            if evt.get("Class") != "SE":
                continue
            se_details.append({
                "line": se_line,
                "duration_ms": evt.get("Duration", 0),
                "cpu_ms": evt.get("CPU", 0),
                "parallelism": evt.get("Par", 0),
                "rows": evt.get("Rows", 0),
                "kb": evt.get("KB", 0),
                "query": evt.get("Query", ""),
            })
            se_line += 1

        return {
            "total_ms": int(total_ms),
            "fe_ms": int(fe_ms),
            "se_ms": int(se_ms),
            "se_cpu_ms": int(perf.get("SE_CPU", 0)),
            "se_parallelism": round(perf.get("SE_Par", 0), 1),
            "se_queries": perf.get("SE_Queries", 0),
            "se_cache_hits": perf.get("SE_Cache", 0),
            "fe_pct": round(fe_ms / total_ms * 100, 1) if total_ms > 0 else 0,
            "se_pct": round(se_ms / total_ms * 100, 1) if total_ms > 0 else 0,
            "se_events": se_details,
            "cache_cleared": response.get("CacheCleared", False),
        }
