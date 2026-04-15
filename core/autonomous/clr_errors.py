"""
CLR Error Extraction

Unwraps `System.AggregateException` / nested `InnerException` chains coming
from TOM `RequestRefresh` / `SaveChanges` failures so handlers can surface a
structured, actionable error instead of the opaque top-level message.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def extract_clr_exception_chain(exc: BaseException, max_depth: int = 8) -> List[Dict[str, Any]]:
    """
    Walk pythonnet's exception chain and return one dict per level.

    Each level captures:
        - type:    .NET type name if available else Python class name
        - message: scalar message string
        - source:  .Source if available (library that raised)
        - hresult: .HResult if available (signed int)
    """
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    depth = 0

    while current is not None and depth < max_depth:
        ident = id(current)
        if ident in seen:
            break
        seen.add(ident)

        detail: Dict[str, Any] = {}
        clr_type = getattr(current, "GetType", None)
        try:
            if callable(clr_type):
                t = clr_type()
                detail["type"] = getattr(t, "FullName", None) or str(t)
            else:
                detail["type"] = type(current).__name__
        except Exception:  # noqa: BLE001
            detail["type"] = type(current).__name__

        try:
            message = getattr(current, "Message", None) or str(current)
            detail["message"] = str(message).strip()
        except Exception:  # noqa: BLE001
            detail["message"] = str(current)

        for field in ("Source", "HResult", "StackTrace"):
            try:
                v = getattr(current, field, None)
                if v not in (None, ""):
                    if field == "StackTrace":
                        # Keep stack trace short — first line only
                        detail[field.lower()] = str(v).splitlines()[0][:400]
                    else:
                        detail[field.lower()] = v
            except Exception:  # noqa: BLE001
                pass

        out.append(detail)

        inner = getattr(current, "InnerException", None)
        if inner is None:
            inner = getattr(current, "__cause__", None) or getattr(
                current,
                "__context__",
                None,
            )
        current = inner
        depth += 1

    return out


def format_refresh_error(
    exc: BaseException,
    table: Optional[str] = None,
    partition: Optional[str] = None,
    last_query: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a structured error dict for refresh failures."""
    chain = extract_clr_exception_chain(exc)
    top = chain[0] if chain else {"message": str(exc), "type": type(exc).__name__}
    root = chain[-1] if chain else top

    out: Dict[str, Any] = {
        "success": False,
        "error": top.get("message") or str(exc),
        "error_type": "refresh_error",
        "clr_chain": chain,
        "clr_root_cause": root.get("message"),
        "clr_root_type": root.get("type"),
    }
    if table:
        out["table"] = table
    if partition:
        out["partition"] = partition
    if last_query:
        snippet = last_query.strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + f"...[truncated {len(last_query) - 800} chars]"
        out["last_query"] = snippet
    return out
