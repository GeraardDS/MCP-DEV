"""
Audit Log

JSONL stream of every autonomous-workflow action plus a markdown summary
emitted on session exit.

Format per line (JSONL):
    {
      "ts": 1712345678.91,
      "session_id": "autonomous-1712345600",
      "op": "close",
      "args": {...},
      "before": {"connected": true, "table_count": 12, "last_save": "..."},
      "after":  {"connected": false, "table_count": null, "last_save": null},
      "result": {"success": true, ...},
      "duration_ms": 1234
    }

Default location: %TEMP%/mcp-pbi-autonomous/<session_id>.jsonl
Override via mode_manager log_path or AuditLog(log_path=...).
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import json as _json

from core.utilities.json_utils import loads_json

logger = logging.getLogger(__name__)


def default_log_dir() -> str:
    """Return the default audit-log directory."""
    return os.path.join(tempfile.gettempdir(), "mcp-pbi-autonomous")


class AuditLog:
    """
    Append-only JSONL writer with a markdown summary emitter.

    Thread-safe: a single lock serializes append and summary calls so
    concurrent tool calls cannot corrupt the stream.
    """

    def __init__(
        self,
        session_id: str,
        log_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            session_id: Stable identifier for this session (used in filename).
            log_path: Override directory. Defaults to %TEMP%/mcp-pbi-autonomous/.
        """
        self.session_id = session_id
        log_dir = log_path or default_log_dir()
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            logger.warning(
                "Could not create audit log dir %s: %s — falling back to %TEMP%",
                log_dir,
                e,
            )
            log_dir = default_log_dir()
            os.makedirs(log_dir, exist_ok=True)

        self.log_dir = log_dir
        self.jsonl_path = os.path.join(log_dir, f"{session_id}.jsonl")
        self.summary_path = os.path.join(log_dir, f"{session_id}.summary.md")
        self._lock = threading.RLock()
        self._entry_count = 0

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def append(
        self,
        op: str,
        args: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Append a single audit entry. Errors logged but never raised."""
        entry: Dict[str, Any] = {
            "ts": time.time(),
            "session_id": self.session_id,
            "op": op,
        }
        if args is not None:
            entry["args"] = self._sanitize(args)
        if result is not None:
            entry["result"] = self._summarize_result(result)
        if before is not None:
            entry["before"] = before
        if after is not None:
            entry["after"] = after
        if duration_ms is not None:
            entry["duration_ms"] = round(duration_ms, 2)
        if notes:
            entry["notes"] = notes

        try:
            line = _json.dumps(entry, separators=(",", ":"), default=str)
            with self._lock:
                with open(self.jsonl_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self._entry_count += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Audit append failed (%s): %s", op, e)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def read_entries(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Read entries newest-first. Limit clamps the number returned."""
        try:
            with self._lock:
                if not os.path.exists(self.jsonl_path):
                    return []
                with open(self.jsonl_path, "r", encoding="utf-8") as fh:
                    lines = fh.readlines()
        except OSError as e:
            logger.warning("Audit read failed: %s", e)
            return []

        entries: List[Dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(loads_json(line))
            except Exception:  # noqa: BLE001
                continue
            if limit and len(entries) >= limit:
                break
        return entries

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def emit_summary(self, exit_reason: str = "manual") -> Optional[str]:
        """
        Render a markdown summary of the session. Returns the summary path
        on success, None on failure.
        """
        entries = self.read_entries()
        # Reverse back to chronological order for the summary
        entries = list(reversed(entries))

        first_ts = entries[0]["ts"] if entries else time.time()
        last_ts = entries[-1]["ts"] if entries else time.time()
        duration = last_ts - first_ts

        op_counts: Dict[str, int] = {}
        ok_counts: Dict[str, int] = {}
        fail_counts: Dict[str, int] = {}
        total_duration_ms = 0.0
        failures: List[Dict[str, Any]] = []

        for entry in entries:
            op = entry.get("op", "?")
            op_counts[op] = op_counts.get(op, 0) + 1
            result = entry.get("result", {})
            ok = bool(result.get("success", True)) if result else True
            if ok:
                ok_counts[op] = ok_counts.get(op, 0) + 1
            else:
                fail_counts[op] = fail_counts.get(op, 0) + 1
                failures.append(entry)
            total_duration_ms += float(entry.get("duration_ms") or 0.0)

        lines = []
        lines.append(f"# Autonomous Workflow Session — {self.session_id}")
        lines.append("")
        lines.append(f"- Started: {self._fmt_ts(first_ts)}")
        lines.append(f"- Ended:   {self._fmt_ts(last_ts)}")
        lines.append(f"- Wall duration: {duration:.1f}s")
        lines.append(f"- Exit reason: `{exit_reason}`")
        lines.append(f"- Total entries: {len(entries)}")
        lines.append(f"- Total tool time: {total_duration_ms / 1000:.2f}s")
        lines.append(f"- JSONL: `{self.jsonl_path}`")
        lines.append("")

        if op_counts:
            lines.append("## Operations")
            lines.append("")
            lines.append("| Operation | Total | OK | Fail |")
            lines.append("|---|---|---|---|")
            for op in sorted(op_counts.keys()):
                lines.append(
                    f"| `{op}` | {op_counts[op]} | "
                    f"{ok_counts.get(op, 0)} | {fail_counts.get(op, 0)} |"
                )
            lines.append("")

        if failures:
            lines.append("## Failures")
            lines.append("")
            for entry in failures[:25]:  # cap to keep summary readable
                op = entry.get("op", "?")
                ts = self._fmt_ts(entry.get("ts", 0))
                err = (entry.get("result") or {}).get("error", "(no error message)")
                lines.append(f"- `{op}` @ {ts} — {err}")
            if len(failures) > 25:
                lines.append(f"- ...and {len(failures) - 25} more (see JSONL)")
            lines.append("")

        text = "\n".join(lines) + "\n"
        try:
            with self._lock:
                with open(self.summary_path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            logger.info("Audit summary written: %s", self.summary_path)
            return self.summary_path
        except OSError as e:
            logger.warning("Audit summary write failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fmt_ts(ts: float) -> str:
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            return str(ts)

    @staticmethod
    def _sanitize(args: Dict[str, Any]) -> Dict[str, Any]:
        """Drop verbose fields and cap large strings."""
        out: Dict[str, Any] = {}
        for k, v in (args or {}).items():
            if isinstance(v, str) and len(v) > 500:
                out[k] = v[:500] + f"...[truncated {len(v) - 500} chars]"
            else:
                out[k] = v
        return out

    @staticmethod
    def _summarize_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only the small status/error fields for audit log readability."""
        if not isinstance(result, dict):
            return {"raw": str(result)[:200]}
        keep = {
            "success",
            "error",
            "error_type",
            "active",
            "session_id",
            "level",
            "status",
            "passed",
            "failed",
            "elapsed_seconds",
        }
        return {k: v for k, v in result.items() if k in keep}
