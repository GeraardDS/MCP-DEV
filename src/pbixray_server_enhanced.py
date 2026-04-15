#!/usr/bin/env python3
"""
MCP-PowerBi-Finvision Server v7.1.0 - Clean Modular Edition
Uses handler registry for all tool routing
"""

import asyncio
import json
import logging
import sys
import os
import time
from pathlib import Path
from typing import Any, List
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, Resource, Prompt, GetPromptResult

# Add parent directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from __version__ import __version__
from core.infrastructure.connection_manager import ConnectionManager
from core.validation.error_handler import ErrorHandler
from core.config.tool_timeouts import ToolTimeoutManager
from core.infrastructure.cache_manager import create_cache_manager
from core.validation.input_validator import InputValidator
from core.infrastructure.rate_limiter import RateLimiter
from core.infrastructure.limits_manager import init_limits_manager
from core.orchestration.agent_policy import AgentPolicy
from core.config.config_manager import config
from core.infrastructure.connection_state import connection_state

# Import handler registry system
from server.registry import get_registry
from server.dispatch import ToolDispatcher
from server.handlers import register_all_handlers
from server.resources import get_resource_manager
from server.prompts import get_prompts, get_prompt_messages


class _ToolError(Exception):
    """Raised to signal an error response to the MCP framework.

    The MCP SDK's call_tool decorator catches exceptions and wraps them in
    CallToolResult(isError=True). By raising this with the JSON error text,
    we get proper isError signaling without bypassing the framework.
    """
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp_powerbi_finvision")

# Configure file-based logging with buffering for performance.
# INFO level captures profiling run summaries and trace lifecycle;
# WARNING captures errors and retries; DEBUG is file-only on demand.
try:
    logs_dir = os.path.join(parent_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    LOG_PATH = os.path.join(logs_dir, "pbixray.log")

    # Add buffered file handler to root logger for better performance
    root_logger = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == LOG_PATH for h in root_logger.handlers):
        # Use MemoryHandler with buffering to reduce I/O overhead
        from logging.handlers import MemoryHandler
        _fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        _fh.setLevel(logging.INFO)
        _fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        # Flush on every INFO so profiling data appears immediately
        _mh = MemoryHandler(capacity=10, flushLevel=logging.INFO, target=_fh)
        root_logger.addHandler(_mh)
        logger.info("File logging enabled: %s", LOG_PATH)
except Exception as e:
    LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "pbixray.log")
    logger.warning("Could not set up file logging: %s", e)

# Track server start time
start_time = time.time()

# Initialize managers
connection_manager = ConnectionManager()
timeout_manager = ToolTimeoutManager(config.get('tool_timeouts', {}))
try:
    enhanced_cache = create_cache_manager(config.get_all())
except Exception:
    from core.infrastructure.cache_manager import EnhancedCacheManager
    enhanced_cache = EnhancedCacheManager()
rate_limiter = RateLimiter(config.get('rate_limiting', {}))
limits_manager = init_limits_manager(config.get_all())

connection_state.set_connection_manager(connection_manager)

# Initialize handler registry and dispatcher
registry = get_registry()
register_all_handlers(registry)
dispatcher = ToolDispatcher()

# Initialize MCP server
app = Server("MCP-PowerBi-Finvision")
agent_policy = AgentPolicy(
    config,
    timeout_manager=timeout_manager,
    cache_manager=enhanced_cache,
    rate_limiter=rate_limiter,
    limits_manager=limits_manager
)

# Set agent_policy in connection_state so handlers can access it
connection_state.agent_policy = agent_policy


@app.list_tools()
async def list_tools() -> List[Tool]:
    """List all available tools from registry"""
    return registry.get_all_tools_as_mcp()


@app.list_resources()
async def list_resources() -> List[Resource]:
    """List all available MCP resources (exported model files)"""
    try:
        resource_manager = get_resource_manager()
        return resource_manager.list_resources()
    except Exception as e:
        logger.error(f"Error listing resources: {e}", exc_info=True)
        return []


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read an MCP resource (exported model file) by URI"""
    try:
        resource_manager = get_resource_manager()
        content = resource_manager.read_resource(uri)
        return content
    except Exception as e:
        logger.error(f"Error reading resource {uri}: {e}", exc_info=True)
        raise ValueError(f"Failed to read resource {uri}: {str(e)}")


@app.list_prompts()
async def list_prompts() -> List[Prompt]:
    """List all available prompt templates"""
    return get_prompts()


@app.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
    """Get a prompt template by name with substituted arguments"""
    return get_prompt_messages(name, arguments or {})


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent | ImageContent]:
    """Execute tool via dispatcher"""
    try:
        _t0 = time.time()

        # Strip _meta from arguments if present (some MCP clients send it inside arguments)
        if isinstance(arguments, dict):
            arguments.pop('_meta', None)

        # Fast path: Skip validation for read-only metadata tools (5-15% speedup)
        fast_path_tools = {
            'list_tables', 'list_columns', 'list_measures', 'list_relationships',
            'detect_powerbi_desktop', '03_List_Relationships', '01_Connection',
            '10_Show_User_Guide'
        }

        needs_validation = name not in fast_path_tools

        # Input validation (only for tools that need it)
        if needs_validation:
            if 'table' in arguments:
                is_valid, error = InputValidator.validate_table_name(arguments['table'])
                if not is_valid:
                    raise _ToolError(json.dumps({
                        'success': False,
                        'error': error,
                        'error_type': 'invalid_input'
                    }, separators=(',', ':')))

            if 'query' in arguments:
                is_valid, error = InputValidator.validate_dax_query(arguments['query'])
                if not is_valid:
                    raise _ToolError(json.dumps({
                        'success': False,
                        'error': error,
                        'error_type': 'invalid_input'
                    }, separators=(',', ':')))

        # Rate limiting (only check if enabled and tool has limit)
        if rate_limiter and rate_limiter.enabled and not rate_limiter.allow_request(name):
            raise _ToolError(json.dumps({
                'success': False,
                'error': 'Rate limit exceeded',
                'error_type': 'rate_limit',
                'retry_after': rate_limiter.get_retry_after(name)
            }, separators=(',', ':')))

        # Dispatch to handler (async to avoid blocking the event loop)
        result = await dispatcher.dispatch_async(name, arguments)

        # Record telemetry
        _dur = round((time.time() - _t0) * 1000, 2)
        logger.debug("Tool %s completed in %sms", name, _dur)

        # Token tracking, limits awareness, and compaction for all responses
        if isinstance(result, dict):
            from server.middleware import (
                estimate_tokens, truncate_if_needed,
                summarize_large_result, compact_keys
            )
            estimated_tokens = estimate_tokens(result)
            is_likely_small = estimated_tokens < 1000

            # Only add limits info and do expensive checks for non-small responses
            if not is_likely_small:
                result = agent_policy.wrap_response_with_limits_info(result, name)

                # Check for token overflow (only for high-token tools)
                if result.get('_limits_info', {}).get('token_usage', {}).get('level') == 'over':
                    high_token_tools = {
                        'full_analysis', 'export_tmdl', 'analyze_model_bpa',
                        '05_Live_Model_Full_Analysis', '11_TMDL_Operations'
                    }
                    if name in high_token_tools:
                        token_info = result['_limits_info']['token_usage']
                        raise _ToolError(json.dumps({
                            'ok': False,
                            'err': (
                                f"Response blocked: {token_info['estimated_tokens']:,} tokens "
                                f"exceeds {token_info['max_tokens']:,} limit ({token_info['percentage']}%)"
                            ),
                            'err_type': 'token_limit_exceeded',
                            'fix': "Use summary_only=true, pagination (limit/offset), or export to file"
                        }, separators=(',', ':')))

                # Add optimization suggestions (only for large results)
                suggestion = agent_policy.suggest_optimizations(name, result)
                if suggestion:
                    if '_limits_info' not in result:
                        result['_limits_info'] = {}
                    result['_limits_info']['suggestion'] = suggestion

                # Summarize very large results (>50K tokens) before hard truncation
                result = summarize_large_result(result)

                # Apply global truncation as final safety net
                max_tokens = limits_manager.token.max_result_tokens
                result = truncate_if_needed(result, max_tokens)

        # Special handling for get_recent_logs
        if name == "get_recent_logs" and isinstance(result, dict) and 'logs' in result:
            return [TextContent(
                type="text",
                text=result['logs'],
                _meta={"anthropic/maxResultSizeChars": 500000},
            )]

        # Handle responses with diagram content - generate professional HTML
        if isinstance(result, dict) and '_image_content' in result:
            result.pop('_image_content')  # Remove image content, we'll use Mermaid HTML instead

            # Get the mermaid code from diagram_metadata or regenerate
            mermaid_code = result.get('_mermaid_code', '')
            measure_info = result.get('measure', {})
            diagram_meta = result.get('diagram_metadata', {})

            # Get formatted text analysis
            if 'formatted_output' in result:
                text_output = result['formatted_output']
            else:
                text_output = json.dumps(result, separators=(',', ':'))

            # Generate and open HTML if we have mermaid code
            if mermaid_code:
                try:
                    from core.utilities.diagram_html_generator import generate_dependency_html
                    html_path = generate_dependency_html(
                        mermaid_code=mermaid_code,
                        measure_table=measure_info.get('table', ''),
                        measure_name=measure_info.get('name', ''),
                        metadata=diagram_meta,
                        auto_open=True,
                        referenced_measures=result.get('referenced_measures', []),
                        referenced_columns=result.get('referenced_columns', []),
                        used_by_measures=result.get('used_by_measures', [])
                    )
                    if html_path:
                        text_output += f"\n\n{'═' * 80}\n"
                        text_output += f"  DEPENDENCY DIAGRAM\n"
                        text_output += f"{'═' * 80}\n"
                        text_output += f"  Interactive diagram opened in browser: {html_path}\n"
                        text_output += f"{'═' * 80}"
                except Exception as e:
                    logger.warning(f"Failed to generate HTML diagram: {e}")

            return [TextContent(
                type="text",
                text=text_output,
                _meta={"anthropic/maxResultSizeChars": 500000},
            )]

        # Detect error responses from handlers (success=False or ok=False)
        _is_error = False
        if isinstance(result, dict):
            _is_error = result.get('success') is False or result.get('ok') is False

        # Apply key compaction before final serialization (15-25% token savings)
        if isinstance(result, dict):
            from server.middleware import compact_keys
            result = compact_keys(result)

        # Final serialization
        final_text = json.dumps(result, separators=(',', ':'))

        # Spill large outputs to file only when they exceed Claude Code's max inline cap.
        # Since v2.1.91, Claude Code honors `_meta["anthropic/maxResultSizeChars"]` (up to 500K)
        # on TextContent responses, so we can keep most outputs inline and avoid the
        # extra Read round-trip. Only spill when output would genuinely exceed 500K.
        SPILL_THRESHOLD = 450000  # chars — under the 500K _meta cap, leaves headroom for overhead
        if len(final_text) > SPILL_THRESHOLD:
            try:
                from datetime import datetime
                spill_dir = os.path.join(parent_dir, 'output')
                os.makedirs(spill_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                safe_name = name.replace(' ', '_')[:30]
                spill_path = os.path.join(spill_dir, f'{safe_name}_{timestamp}.json')
                with open(spill_path, 'w', encoding='utf-8') as f:
                    f.write(final_text)

                # Build compact inline summary from the result
                summary_parts = {
                    'ok': result.get('ok', result.get('success', True)),
                    '_full_output': spill_path,
                    '_full_output_size': f'{len(final_text) / 1024:.1f}KB',
                    '_note': 'Full output saved to file. Use Read tool to access if needed.',
                }

                # Preserve key scalar fields from the result
                for key in ['ms', 'execution_time_ms', 'total', 'total_count',
                            'total_ms', 'fe_ms', 'se_ms', 'fe_pct', 'se_pct',
                            'se_queries', 'query', 'message', 'measure',
                            'table', 'page_name', 'visual_id']:
                    if key in result and not isinstance(result[key], (dict, list)):
                        summary_parts[key] = result[key]

                # Include top-level summary/analysis strings (truncated)
                for key in ['summary', 'analysis', 'formatted_output', 'optimization_summary']:
                    if key in result and isinstance(result[key], str):
                        val = result[key]
                        if len(val) > 5000:
                            summary_parts[key] = val[:5000] + '... [truncated, see full output file]'
                        else:
                            summary_parts[key] = val

                # Include short lists (< 10 items)
                for key, val in result.items():
                    if isinstance(val, list) and 0 < len(val) <= 10 and key not in summary_parts:
                        summary_parts[key] = val

                final_text = json.dumps(summary_parts, separators=(',', ':'))
            except Exception as e:
                logger.warning(f"Failed to spill large output to file: {e}")
                # Fall through with original final_text

        # Signal errors via _ToolError so the MCP framework sets isError=True
        if _is_error:
            raise _ToolError(final_text)

        # Annotate with _meta so Claude Code (v2.1.91+) persists up to 500K chars inline
        # instead of truncating to its default ~50K. Avoids the Read round-trip for large
        # INFO.* dumps, TMDL exports, schema/model documentation, and measure audits.
        return [TextContent(
            type="text",
            text=final_text,
            _meta={"anthropic/maxResultSizeChars": 500000},
        )]

    except _ToolError:
        raise  # Let _ToolError propagate to the MCP framework for isError=True
    except Exception as e:
        logger.error(f"Error in {name}: {e}", exc_info=True)
        raise _ToolError(json.dumps(
            ErrorHandler.handle_unexpected_error(name, e), separators=(',', ':')
        ))


async def main():
    """Main entry point"""
    logger.info("=" * 80)
    logger.info(f"MCP-PowerBi-Finvision Server v{__version__} - Clean Modular Edition")
    logger.info("=" * 80)
    logger.info(f"Registered {len(registry._handlers)} tools")

    # Build initialization instructions
    def _initial_instructions() -> str:
        try:
            guides_dir = os.path.join(parent_dir, 'docs')
            lines = [
                f"MCP-PowerBi-Finvision v{__version__} — Power BI Desktop MCP server.",
                "",
                "What you can do:",
                "- Connect to your open Power BI Desktop instance",
                "- Inspect tables/columns/measures and preview data",
                "- Search objects and view data sources and M expressions",
                "- Run Best Practice Analyzer (BPA) and relationship analysis",
                "- Export compact schema, TMDL, and documentation",
                "",
                "Quick start:",
                "1) Run tool: detect_powerbi_desktop",
                "2) Then: connect_to_powerbi (usually model_index=0)",
                "3) Try: list_tables | describe_table | preview_table_data",
                "",
                f"Full guide: {guides_dir}/PBIXRAY_Quickstart.pdf"
            ]
            return "\n".join(lines)
        except Exception:
            return (
                f"MCP-PowerBi-Finvision v{__version__}. "
                "Start by running 'detect_powerbi_desktop' and then 'connect_to_powerbi'."
            )

    init_opts = app.create_initialization_options()
    try:
        setattr(init_opts, "instructions", _initial_instructions())
    except Exception:
        pass

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, init_opts)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.critical(f"Server crashed: {e}", exc_info=True)
        # Flush all log handlers to ensure error is written
        for handler in logging.getLogger().handlers:
            handler.flush()
        raise
