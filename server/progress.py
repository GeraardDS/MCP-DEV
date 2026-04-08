"""
Progress notification bridge for sync handlers running in thread pool.

Handlers are sync functions running via run_in_executor. Since Python 3.12+,
asyncio.loop.run_in_executor copies the current contextvars.Context to the
executor thread, so the MCP request_ctx ContextVar is available.

This module reads the progress token from the MCP request context and sends
progress notifications back through the async event loop.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_progress_token() -> Optional[tuple]:
    """
    Get the progress token and session from the MCP request context.

    Returns (progress_token, session) or None if not available.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx

        ctx = request_ctx.get(None)
        if ctx is None:
            return None

        meta = ctx.meta
        if meta is None or meta.progressToken is None:
            return None

        session = ctx.session
        if session is None:
            return None

        return (meta.progressToken, session)
    except (LookupError, AttributeError, ImportError):
        return None


def emit_progress(
    progress: float,
    total: Optional[float] = None,
    message: Optional[str] = None,
) -> None:
    """
    Emit a progress notification from a sync handler.

    Safe to call from any context -- silently no-ops if:
    - No MCP request context is available
    - No progress token was provided by the client
    - The notification fails for any reason

    Args:
        progress: Current progress value (should increase monotonically).
        total: Total expected progress value, if known.
        message: Human-readable progress message.
    """
    ctx_info = _get_progress_token()
    if ctx_info is None:
        return

    progress_token, session = ctx_info

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return

    async def _send():
        try:
            await session.send_progress_notification(
                progress_token=progress_token,
                progress=progress,
                total=total,
                message=message,
            )
        except Exception as e:
            logger.debug("Progress notification failed: %s", e)

    try:
        asyncio.run_coroutine_threadsafe(_send(), loop)
    except Exception as e:
        logger.debug("Could not schedule progress notification: %s", e)
