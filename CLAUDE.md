# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP-PowerBi-Finvision is a Python-based Model Context Protocol (MCP) server for Power BI Desktop analysis. It connects to running Power BI Desktop instances via .NET interop (pythonnet/CLR) over stdio, providing 50+ tools across 9 categories for DAX debugging, TMDL editing, model operations, and offline PBIP analysis. Windows-only (requires .NET Framework 4.7.2+, Power BI Desktop).

## Commands

### Run the server
```bash
python src/run_server.py
```

### Install dependencies
```bash
pip install -r requirements.txt          # production
pip install -r python/requirements.txt   # alternative (no version caps)
pip install -e ".[dev]"                  # development (pytest, black, mypy, flake8)
```

### Lint and type check
```bash
black --check --line-length 100 core/ server/ src/
mypy core/                               # strict mode on core/
flake8 core/ server/ src/
```

### Tests
```bash
pytest                                   # run all tests with coverage
pytest tests/test_foo.py                 # single file
pytest tests/test_foo.py::TestClass::test_method  # single test
pytest -m "not slow"                     # skip slow/integration tests
```
Test config is in `python/pyproject.toml` under `[tool.pytest.ini_options]`. Coverage targets `core/` and `src/`.

### Package for distribution
```bash
build\package.bat                        # creates dist/*.mcpb
```

## Architecture

### Execution Flow

`src/run_server.py` bootstraps PYTHONPATH and loads `src/pbixray_server_enhanced.py`, which:
1. Creates global `ConnectionState` and `ConnectionManager` singletons
2. Initializes `HandlerRegistry` and calls `register_all_handlers()` (from `server/handlers/__init__.py`)
3. Creates `ToolDispatcher` for routing
4. Starts MCP stdio server via `mcp.server.stdio.stdio_server()`

Tool calls flow: MCP `call_tool()` -> input validation -> rate limiting -> `ToolDispatcher.dispatch_async()` (runs sync handlers in thread pool via `run_in_executor`) -> `HandlerRegistry.get_handler()` -> handler function -> middleware (token estimation, truncation, key compaction) -> JSON response.

### Layer Separation

- **`server/`** - MCP protocol layer: registry, dispatch, middleware, handlers, resources, caching
- **`core/`** - Domain logic with no MCP awareness:
  - `infrastructure/` - connection management, query execution, DLL loading, caching
  - `operations/` - CRUD managers (table, column, measure, relationship, calculation group, RLS)
  - `dax/` - DAX analysis, injection, context debugging
  - `tmdl/` - TMDL parsing, validation, editing, script generation
  - `pbip/` - Offline PBIP project analysis, report parsing, dependency engine
  - `analysis/` - BPA analyzer, model analysis
  - `comparison/` - Model comparison orchestration
  - `config/` - Configuration management (default_config.json + local overrides)
  - `utilities/` - json_utils (orjson-backed), mermaid_utils, diagram generation

### Handler Pattern

Every tool is a `ToolDefinition(name, description, handler, input_schema, category, sort_order)` registered with the global `HandlerRegistry`. Each handler file exports a `register_*_handler(registry)` function. Handlers are plain functions taking `args: Dict[str, Any]` and returning `Dict[str, Any]`. They access shared state through the global `connection_state` singleton.

Example handler registration:
```python
def register_foo_handler(registry):
    registry.register(ToolDefinition(
        name="02_Foo_Operations",
        description="...",
        handler=handle_foo,
        input_schema={...},
        category="model",
        sort_order=200
    ))
```

### Tool Categories and Deferred Loading

Tools are grouped by `ToolCategory` enum in `server/registry.py` (CORE, MODEL, BATCH, QUERY, DAX, ANALYSIS, PBIP, DOCS, DEBUG). A pre-computed `_TOOL_TO_CATEGORY` reverse lookup provides O(1) category resolution. Tool names follow the pattern `NN_Tool_Name` where NN indicates category order.

### Key Singletons

- **`connection_state`** (`core/infrastructure/connection_state.py`) - Global connection and manager state. Thread-safe with `threading.RLock`. Lazy-initializes 15+ managers (query executor, DAX injector, CRUD managers, BPA, etc.) on first connection.
- **`pbip_cache`** (`server/pbip_cache.py`) - Thread-safe LRU cache for parsed PBIP projects. Returns `PbipProject` frozen dataclass keyed by `(resolved_path, max_mtime)`. Shared between `pbip_operations_handler` and `hybrid_analysis_handler`.

### TMDL/PBIP Subsystem

**Single canonical parser**: `core/tmdl/unified_parser.py` (`UnifiedTmdlParser`) produces typed dataclasses from `core/tmdl/models.py` (`TmdlModel`, `TmdlTable`, `TmdlMeasure`, etc.). Old parsers in `core/tmdl/tmdl_parser.py` and `core/pbip/pbip_model_analyzer.py` are thin facades delegating to the unified parser.

**PBIP analysis pipeline**: `PbipProjectScanner` -> `TmdlModelAnalyzer` -> `PbipDependencyEngine` -> `PbipProject`. Multi-report merging intersects unused columns/measures across reports and prefixes page names for disambiguation.

### .NET Interop

DLL loading is centralized in `core/infrastructure/dll_paths.py` with `get_dll_paths()`, `load_amo_assemblies()`, `load_adomd_assembly()`. These load Microsoft.AnalysisServices DLLs from `lib/dotnet/` via pythonnet CLR. Used by 13+ files. Broad `except Exception` blocks in infrastructure code are intentional for CLR interop stability.

### Token Optimization

- `server/middleware.py` applies key compaction (`compact_keys`), token estimation, truncation, and summarization for large results
- `orjson` used throughout via `core/utilities/json_utils.py` (with stdlib json fallback)
- Response serialization uses `separators=(',', ':')` for minimal JSON

## Configuration

`config/default_config.json` provides defaults. Override with `config/local_config.json` (not committed). Key sections: `server`, `performance` (cache TTL, trace mode, query limits), `detection`, `query`, `features` (enable_bpa, etc.).

## Version

Version is defined in `src/__version__.py`. Must match `manifest.json` for packaging.

## Platform Notes

- Windows-only runtime (pythonnet, WMI, pywin32)
- Always use `encoding='utf-8'` in `open()` calls for Python source processing (e.g., `ast.parse`) to avoid Windows charmap errors
- Thread safety is critical: all shared state uses `threading.RLock`, double-checked locking for lazy initialization
- Dict-based consumers (`pbip_dependency_engine`, `pbip_enhanced_analyzer`, `bpa_analyzer`) use `.get()` extensively; gradual migration to typed `TmdlModel` via `TmdlModel.from_dict()`

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
