"""
Handler Registry System
Manages registration and lookup of tool handlers with dynamic loading support.

Token Optimization: Supports deferred tool loading to reduce initial token usage.
Core tools are always loaded; other categories load on-demand.
"""
from typing import Dict, Callable, Any, List, Set, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Tool categories for dynamic loading"""
    CORE = "core"              # Always loaded (connection, help)
    MODEL = "model"            # Table, column, measure, relationship, calc group, role ops
    BATCH = "batch"            # Batch operations & transactions
    QUERY = "query"            # DAX, search, data sources
    DAX = "dax"                # DAX intelligence, dependencies
    ANALYSIS = "analysis"      # Simple/full analysis, comparison
    PBIP = "pbip"              # PBIP analysis, report info, slicers, visuals
    DOCS = "docs"              # Documentation generation
    DEBUG = "debug"            # Debug tools
    AUTHORING = "authoring"    # PBIP report authoring & prototyping


# Define which tools belong to each category (for deferred loading)
CATEGORY_TOOLS = {
    ToolCategory.CORE: [
        "01_Connection",
        "10_Show_User_Guide",
    ],
    ToolCategory.MODEL: [
        "02_Model_Operations",
        "02_TMDL_Operations",
    ],
    ToolCategory.BATCH: [
        "03_Batch_Operations",
    ],
    ToolCategory.QUERY: [
        "04_Run_DAX",
        "04_Query_Operations",
    ],
    ToolCategory.DAX: [
        "05_DAX_Intelligence",
        "05_Column_Usage_Mapping",
    ],
    ToolCategory.ANALYSIS: [
        "06_Analysis_Operations",
    ],
    ToolCategory.PBIP: [
        "07_PBIP_Operations",
        "07_Report_Operations",
        "07_Page_Operations",
        "07_Visual_Operations",
        "07_Bookmark_Operations",
        "07_Theme_Operations",
        "SVG_Visual_Operations",
    ],
    ToolCategory.DOCS: [
        "08_Documentation_Word",
    ],
    ToolCategory.DEBUG: [
        "09_Debug_Operations",
        "09_Validate",
        "09_Profile",
        "09_Document",
    ],
    ToolCategory.AUTHORING: [
        "11_PBIP_Authoring",
    ],
}


# Pre-computed reverse lookup: tool_name -> ToolCategory (O(1) instead of O(n*m))
_TOOL_TO_CATEGORY = {
    tool_name: category
    for category, tools in CATEGORY_TOOLS.items()
    for tool_name in tools
}

# Category descriptions for discovery
# tool_count is computed dynamically by get_discovery_info() from CATEGORY_TOOLS
CATEGORY_INFO = {
    ToolCategory.CORE: {"name": "Connection & Help", "description": "Connect to Power BI, get help"},
    ToolCategory.MODEL: {"name": "Model Operations", "description": "Table/column/measure/relationship CRUD"},
    ToolCategory.BATCH: {"name": "Batch & Transactions", "description": "Batch operations with ACID transactions"},
    ToolCategory.QUERY: {"name": "Query & Search", "description": "DAX queries, search objects, roles"},
    ToolCategory.DAX: {"name": "DAX Intelligence", "description": "DAX analysis, dependencies, optimization"},
    ToolCategory.ANALYSIS: {"name": "Analysis", "description": "Model analysis, BPA, comparison"},
    ToolCategory.PBIP: {"name": "PBIP & Report", "description": "Report/page/visual/filter/bookmark/theme operations, SVG visuals"},
    ToolCategory.DOCS: {"name": "Documentation", "description": "Generate/update Word docs"},
    ToolCategory.DEBUG: {"name": "Debug", "description": "Visual debugging, profiling, validation"},
    ToolCategory.AUTHORING: {"name": "Report Authoring", "description": "Create, clone PBIP report pages and visuals"},
}


@dataclass
class ToolDefinition:
    """Definition of a tool with its handler"""
    name: str
    description: str
    handler: Callable
    input_schema: Dict[str, Any]
    category: str = "general"
    sort_order: int = 999  # Default to end if not specified
    annotations: Optional[Dict[str, Any]] = field(default=None)  # MCP ToolAnnotations hints (readOnlyHint, destructiveHint, etc.)
    output_schema: Optional[Dict[str, Any]] = field(default=None)  # JSON Schema for structured output validation


class HandlerRegistry:
    """
    Central registry for all tool handlers with dynamic loading support.

    Token Optimization:
    - Core tools always returned in list_tools()
    - Other categories loaded on-demand when tool is called
    - get_tools_for_discovery() returns minimal info for all categories
    """

    def __init__(self):
        self._handlers: Dict[str, ToolDefinition] = {}
        self._categories: Dict[str, List[str]] = {}
        self._tool_to_category: Dict[str, ToolCategory] = {}  # Reverse lookup: tool_name -> ToolCategory
        self._loaded_categories: Set[ToolCategory] = {ToolCategory.CORE}
        self._deferred_mode: bool = False  # MCP requires all tools registered upfront - deferred mode breaks tool calls
        self._total_tools: Optional[int] = None  # Cached total tools count

    def register(self, tool_def: ToolDefinition) -> None:
        """Register a tool handler"""
        # Validate required fields
        if not getattr(tool_def, 'name', None):
            logger.warning("Tool registration skipped: missing 'name' field")
            return
        if not getattr(tool_def, 'handler', None):
            logger.warning(f"Tool registration skipped for '{tool_def.name}': missing 'handler' field")
            return
        if not getattr(tool_def, 'input_schema', None):
            logger.warning(f"Tool registration skipped for '{tool_def.name}': missing 'input_schema' field")
            return

        self._handlers[tool_def.name] = tool_def

        # Track by category
        if tool_def.category not in self._categories:
            self._categories[tool_def.category] = []
        self._categories[tool_def.category].append(tool_def.name)

        # Reverse lookup index: tool_name -> ToolCategory
        if tool_def.name in _TOOL_TO_CATEGORY:
            self._tool_to_category[tool_def.name] = _TOOL_TO_CATEGORY[tool_def.name]

        # Invalidate cached total_tools count
        self._total_tools = None

        logger.debug(f"Registered tool: {tool_def.name} (category: {tool_def.category})")

    def get_handler(self, tool_name: str) -> Callable:
        """Get handler function for a tool"""
        if tool_name not in self._handlers:
            raise KeyError(f"Unknown tool: {tool_name}")
        return self._handlers[tool_name].handler

    def get_tool_def(self, tool_name: str) -> ToolDefinition:
        """Get full tool definition"""
        if tool_name not in self._handlers:
            raise KeyError(f"Unknown tool: {tool_name}")
        return self._handlers[tool_name]

    def get_all_tools(self) -> List[ToolDefinition]:
        """Get all registered tools"""
        return list(self._handlers.values())

    def enable_deferred_mode(self, enabled: bool = True) -> None:
        """
        Enable/disable deferred tool loading mode.
        When enabled, list_tools() only returns core tools.
        """
        self._deferred_mode = enabled
        logger.info(f"Deferred tool loading mode: {'enabled' if enabled else 'disabled'}")

    def load_category(self, category: ToolCategory) -> None:
        """Mark a category as loaded (for tracking)"""
        self._loaded_categories.add(category)

    def is_category_loaded(self, category: ToolCategory) -> bool:
        """Check if a category is loaded"""
        return category in self._loaded_categories

    def get_all_tools_as_mcp(self, include_deferred: bool = None):
        """
        Get tools as MCP Tool objects.

        Args:
            include_deferred: If None, uses self._deferred_mode setting.
                             If True, returns all tools.
                             If False, returns only core tools.
        """
        from mcp.types import Tool, ToolAnnotations

        use_deferred = self._deferred_mode if include_deferred is None else not include_deferred

        tools = []
        sorted_defs = sorted(self._handlers.values(), key=lambda x: (x.sort_order, x.name))

        for tool_def in sorted_defs:
            # In deferred mode, only include core tools
            if use_deferred:
                is_core = tool_def.name in CATEGORY_TOOLS.get(ToolCategory.CORE, [])
                if not is_core:
                    continue

            # Build MCP Tool kwargs
            tool_kwargs = {
                "name": tool_def.name,
                "description": tool_def.description,
                "inputSchema": tool_def.input_schema,
            }

            # Pass through annotations if defined
            if tool_def.annotations:
                tool_kwargs["annotations"] = ToolAnnotations(**tool_def.annotations)

            # Pass through output schema if defined
            if tool_def.output_schema:
                tool_kwargs["outputSchema"] = tool_def.output_schema

            tools.append(Tool(**tool_kwargs))
        return tools

    def get_tools_by_category(self, category: str) -> List[ToolDefinition]:
        """Get tools in a specific category"""
        tool_names = self._categories.get(category, [])
        return [self._handlers[name] for name in tool_names if name in self._handlers]

    def get_tools_by_tool_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """Get tools by ToolCategory enum"""
        tool_names = CATEGORY_TOOLS.get(category, [])
        return [self._handlers[name] for name in tool_names if name in self._handlers]

    def list_categories(self) -> List[str]:
        """List all categories"""
        return list(self._categories.keys())

    def has_tool(self, tool_name: str) -> bool:
        """Check if tool is registered"""
        return tool_name in self._handlers

    def get_category_for_tool(self, tool_name: str) -> Optional[ToolCategory]:
        """Get the ToolCategory for a tool name (O(1) lookup via reverse index)"""
        return self._tool_to_category.get(tool_name)

    def get_discovery_info(self) -> Dict[str, Any]:
        """
        Get minimal discovery info for all tools.
        """
        categories = []
        for cat in ToolCategory:
            info = CATEGORY_INFO.get(cat, {})
            tool_names = CATEGORY_TOOLS.get(cat, [])
            categories.append({
                "id": cat.value,
                "name": info.get("name", cat.value),
                "desc": info.get("description", ""),
                "tools": len(tool_names),
                "loaded": cat in self._loaded_categories
            })

        if self._total_tools is None:
            self._total_tools = sum(len(tools) for tools in CATEGORY_TOOLS.values())

        return {
            "total_tools": self._total_tools,
            "categories": categories,
            "deferred_mode": self._deferred_mode,
        }

    def get_category_tools_info(self, category: ToolCategory) -> Dict[str, Any]:
        """
        Get tools info for a specific category (without full schemas).
        """
        tool_names = CATEGORY_TOOLS.get(category, [])
        tools = []

        for name in tool_names:
            if name in self._handlers:
                tool_def = self._handlers[name]
                tools.append({
                    "name": name,
                    "desc": tool_def.description[:100] if len(tool_def.description) > 100 else tool_def.description
                })
            else:
                tools.append({"name": name, "desc": "(not loaded)"})

        info = CATEGORY_INFO.get(category, {})
        return {
            "category": category.value,
            "name": info.get("name", category.value),
            "description": info.get("description", ""),
            "tools": tools,
            "loaded": category in self._loaded_categories
        }


# Global registry instance
_registry = HandlerRegistry()


def get_registry() -> HandlerRegistry:
    """Get the global handler registry"""
    return _registry
