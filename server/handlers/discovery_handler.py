"""
Discovery Handler - Meta-tool for dynamic tool discovery

Token Optimization: This tool enables progressive disclosure of tool definitions.
Instead of loading all 44 tools at startup, users can discover and load tools on-demand.
"""
import logging
from typing import Any, Dict

from server.registry import ToolDefinition, ToolCategory, CATEGORY_TOOLS, CATEGORY_INFO, get_registry
from server.tool_documentation import get_tool_examples, get_tool_documentation

logger = logging.getLogger(__name__)


def handle_discover_tools(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Discover available tools and categories.

    This meta-tool provides:
    1. Overview of all tool categories (default)
    2. Details about tools in a specific category
    3. Full schema for a specific tool
    4. Examples for a specific tool

    Args:
        arguments: {
            category: str - Category to explore (core|model|batch|query|dax|analysis|pbip|docs|debug|all)
            tool_name: str - Specific tool to get schema for
            include_schema: bool - Include full input schema (default: False for category listing)
            include_examples: bool - Include usage examples (default: False)
        }

    Returns:
        Discovery information based on parameters
    """
    registry = get_registry()
    category = arguments.get('category', 'all')
    tool_name = arguments.get('tool_name')
    include_schema = arguments.get('include_schema', False)
    include_examples = arguments.get('include_examples', False)

    # If specific tool requested
    if tool_name:
        return _get_tool_info(tool_name, include_schema, include_examples)

    # If specific category requested
    if category and category != 'all':
        return _get_category_info(category, include_schema)

    # Default: return all categories overview
    return registry.get_discovery_info()


def _get_tool_info(tool_name: str, include_schema: bool, include_examples: bool) -> Dict[str, Any]:
    """Get info about a specific tool"""
    registry = get_registry()

    if not registry.has_tool(tool_name):
        return {
            'ok': False,
            'err': f"Tool '{tool_name}' not found",
            'hint': "Use 10_Discover_Tools to list available tools"
        }

    tool_def = registry.get_tool_def(tool_name)
    result = {
        'ok': True,
        'tool': tool_name,
        'desc': tool_def.description,
        'category': tool_def.category
    }

    if include_schema:
        result['schema'] = tool_def.input_schema

    if include_examples:
        examples = get_tool_examples(tool_name.lower().replace('_', ''))
        if not examples:
            # Try alternative naming patterns
            alt_names = [
                tool_name.lower(),
                tool_name.split('_', 1)[-1].lower() if '_' in tool_name else tool_name.lower(),
            ]
            for alt in alt_names:
                examples = get_tool_examples(alt)
                if examples:
                    break

        result['examples'] = examples if examples else []

    # Include documentation if available
    doc = get_tool_documentation(tool_name.lower().replace('_', ''))
    if doc.get('summary') != 'Documentation not available':
        result['doc'] = doc

    return result


def _get_category_info(category_str: str, include_schema: bool) -> Dict[str, Any]:
    """Get info about a specific category"""
    registry = get_registry()

    # Map string to ToolCategory enum
    try:
        category = ToolCategory(category_str.lower())
    except ValueError:
        return {
            'ok': False,
            'err': f"Unknown category: {category_str}",
            'valid_categories': [c.value for c in ToolCategory],
            'hint': "Use one of: core, model, batch, query, dax, analysis, pbip, docs, debug"
        }

    # Mark category as "loaded" for tracking
    registry.load_category(category)

    # Get tools in category
    tool_names = CATEGORY_TOOLS.get(category, [])
    info = CATEGORY_INFO.get(category, {})

    tools = []
    for name in tool_names:
        tool_info = {'name': name}

        if registry.has_tool(name):
            tool_def = registry.get_tool_def(name)
            tool_info['desc'] = tool_def.description

            if include_schema:
                tool_info['schema'] = tool_def.input_schema
        else:
            tool_info['desc'] = '(available but not loaded)'

        tools.append(tool_info)

    return {
        'ok': True,
        'category': category.value,
        'name': info.get('name', category.value),
        'description': info.get('description', ''),
        'tools': tools,
        'tool_count': len(tools)
    }


def register_discovery_handler(registry) -> None:
    """Register the discovery meta-tool"""
    registry.register(ToolDefinition(
        name="10_Discover_Tools",
        description="[10] Discover tools by category. Use to explore available capabilities without loading all schemas.",
        handler=handle_discover_tools,
        input_schema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["all", "core", "model", "batch", "query", "dax", "analysis", "pbip", "docs", "debug"],
                    "description": "Category to explore. 'all' shows overview.",
                    "default": "all"
                },
                "tool_name": {
                    "type": "string",
                    "description": "Get info for specific tool (e.g., '02_Table_Operations')"
                },
                "include_schema": {
                    "type": "boolean",
                    "description": "Include full input schema",
                    "default": False
                },
                "include_examples": {
                    "type": "boolean",
                    "description": "Include usage examples",
                    "default": False
                }
            }
        },
        category="core",
        sort_order=100
    ))
