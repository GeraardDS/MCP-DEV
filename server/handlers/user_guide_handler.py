"""
User Guide Handler
Handles user guide display
"""
from typing import Dict, Any
import logging
import os
from server.registry import ToolDefinition

logger = logging.getLogger(__name__)

def handle_show_user_guide(args: Dict[str, Any]) -> Dict[str, Any]:
    """Show comprehensive user guide"""
    try:
        # Get the guide path
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir))
        guide_path = os.path.join(project_root, 'docs', 'PBIXRAY_Quickstart.md')

        if os.path.exists(guide_path):
            with open(guide_path, 'r', encoding='utf-8') as f:
                guide_content = f.read()

            return {
                'success': True,
                'guide': guide_content,
                'path': guide_path
            }
        else:
            # Return basic usage guide if file not found
            return {
                'success': True,
                'guide': _get_inline_guide(),
                'note': 'Using inline guide (file not found)'
            }

    except Exception as e:
        logger.error(f"Error loading user guide: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Error loading user guide: {str(e)}',
            'fallback_guide': _get_inline_guide()
        }

def _get_inline_guide() -> str:
    """Get inline user guide"""
    return """# MCP-PowerBi-Finvision Comprehensive User Guide v5.01

Welcome to MCP-PowerBi-Finvision! This guide covers all 50+ tools across 13 categories.

---

## 📋 QUICK START

### Step 1: Connect to Power BI
```
1. Open Power BI Desktop with your model
2. Use: 01 Detect PBI Instances
3. Use: 01 Connect To Instance (typically model_index=0)
```

### Step 2: Explore Your Model
```
- List tables: 02 Table Operations
- Describe a table: 02 Table Operations
- List measures: 02 Measure Operations
- Get measure details: 02 Measure Operations
```

---

## 🔧 CATEGORY 01: CONNECTION (2 tools)

### 01 Detect PBI Instances
**Purpose**: Detect running Power BI Desktop instances
**When to use**: Start of every session to find available models
**Parameters**: None
**Returns**: List of instances with ports and model names

### 01 Connect To Instance
**Purpose**: Connect to a specific Power BI Desktop instance
**When to use**: After detecting instances, to establish connection
**Parameters**:
  - model_index: Index from detection list (usually 0)
**Returns**: Connection status and model information

---

## 📊 CATEGORY 02: SCHEMA/METADATA (8 tools)

### 02_list_tables
**Purpose**: List all tables in the model
**When to use**: Initial exploration, understanding model structure
**Parameters**: None
**Returns**: Table names, row counts, types (fact/dimension)

### 02_describe_table
**Purpose**: Get comprehensive table information
**When to use**: Deep dive into specific table
**Parameters**:
  - table: Table name
**Returns**: Columns, measures, relationships, partitions, descriptions

### 02_list_columns
**Purpose**: List columns across tables
**When to use**: Finding columns by name or type
**Parameters**:
  - table (optional): Filter by table name
**Returns**: Column names, data types, tables

### 02_list_measures
**Purpose**: List all measures in the model
**When to use**: Understanding calculated metrics
**Parameters**:
  - table (optional): Filter by table name
**Returns**: Measure names, tables, display folders

### 02_get_measure_details
**Purpose**: Get detailed measure information
**When to use**: Analyzing specific measure logic
**Parameters**:
  - table: Table name
  - measure: Measure name
**Returns**: DAX formula, format string, dependencies, folder

### 02_list_calculated_columns
**Purpose**: List calculated columns
**When to use**: Finding calculated columns vs regular columns
**Parameters**: None
**Returns**: Column names, tables, DAX expressions

### 02_search_objects
**Purpose**: Search across tables, columns, and measures
**When to use**: Finding objects by name pattern
**Parameters**:
  - search_term: Text to search for
  - object_type (optional): Filter by type
**Returns**: Matching objects with details

### 02_search_string
**Purpose**: Search in measure names and expressions
**When to use**: Finding measures containing specific DAX patterns
**Parameters**:
  - search_string: Text to search for
  - search_in: 'name', 'expression', or 'both'
**Returns**: Matching measures with highlighted matches

---

## 🔍 CATEGORY 03: QUERY & DATA + DAX INTELLIGENCE (9 tools)

### 03 Preview Table Data
**Purpose**: Preview actual data from a table
**When to use**: Checking data content and quality
**Parameters**:
  - table: Table name
  - max_rows: Limit (default: 10)
**Returns**: Sample rows from table

### 03 Run DAX
**Purpose**: Execute any DAX query
**When to use**: Custom queries, testing calculations
**Parameters**:
  - query: DAX EVALUATE statement
  - top_n: Row limit (default: 100)
  - mode: 'auto', 'analyze', 'profile', or 'simple'
**Returns**: Query results with optional timing statistics

### 03 Standard DAX Analysis (UNIFIED TOOL)
**Purpose**: Complete DAX analysis: syntax validation + context analysis + debugging
**When to use**: Understanding complex DAX, debugging issues, getting optimization recommendations
**Parameters**:
  - expression: DAX expression or measure name
  - analysis_mode: 'all' (default - complete analysis), 'analyze', 'debug', or 'report'
  - skip_validation: Skip syntax check (default: false)
  - output_format: 'friendly' or 'steps' (debug mode)
  - include_optimization: Include suggestions (report mode)
  - include_profiling: Include performance (report mode)
**Returns**: Comprehensive DAX analysis with optimization recommendations
**Modes**:
  - all (DEFAULT): Complete analysis - analyze + debug + report + best practices
  - analyze: Context transition analysis with anti-patterns
  - debug: Step-by-step execution breakdown
  - report: Full analysis with optimization + profiling
**IMPORTANT WORKFLOW**:
  1. Tool provides analysis with detailed improvement recommendations
  2. The AI writes the optimized DAX code based on those recommendations
  3. The tool does NOT auto-generate optimized code - that's the AI's job
**Example**:
  Input: "Total Sales" (measure name) → Tool fetches expression → Analyzes → AI writes optimized version

### 03 Validate DAX Query
**Purpose**: Validate DAX syntax without execution
**When to use**: Quick syntax checks
**Parameters**:
  - query: DAX query to validate
**Returns**: Validation status and errors if any

### 03 Get Column Value Distribution
**Purpose**: Get top N values for a column
**When to use**: Understanding column content, checking for issues
**Parameters**:
  - table: Table name
  - column: Column name
  - top_n: Number of values (default: 10)
**Returns**: Values with counts and percentages

### 03 Get Column Summary
**Purpose**: Get statistical summary of column
**When to use**: Understanding numeric/date column ranges
**Parameters**:
  - table: Table name
  - column: Column name
**Returns**: Min, max, distinct count, null count

### 03 List Relationships
**Purpose**: List model relationships
**When to use**: Understanding model connectivity
**Parameters**:
  - active_only: Filter active relationships (default: false)
**Returns**: From/to tables/columns, cardinality, cross-filter direction

### 03 Get Data Sources
**Purpose**: List all data sources
**When to use**: Understanding data origins
**Parameters**: None
**Returns**: Connection strings, types, credentials info

### 03 Get M Expressions
**Purpose**: List Power Query M expressions
**When to use**: Reviewing data transformation logic
**Parameters**:
  - limit (optional): Maximum expressions to return
**Returns**: M code for each partition/table

---

## ⚙️ CATEGORY 04: MODEL OPERATIONS (8 tools)

### 04_upsert_measure
**Purpose**: Create or update a measure
**When to use**: Adding new calculations or fixing existing ones
**Parameters**:
  - table: Target table name
  - measure: Measure name
  - expression: DAX formula
  - format_string (optional): Format like "#,0" or "0.0%"
  - description (optional): Measure description
  - display_folder (optional): Folder path
**Returns**: Success status
**Note**: Automatically backs up before changes

### 04_delete_measure
**Purpose**: Delete a measure
**When to use**: Removing unused or incorrect measures
**Parameters**:
  - table: Table name
  - measure: Measure name
**Returns**: Success status
**Note**: Check dependencies first with analyze_measure_dependencies

### 04_bulk_create_measures
**Purpose**: Create multiple measures at once
**When to use**: Initializing measure sets, batch operations
**Parameters**:
  - measures: Array of {table, measure, expression, format_string?, description?, display_folder?}
**Returns**: Success count and any errors

### 04_bulk_delete_measures
**Purpose**: Delete multiple measures at once
**When to use**: Cleanup operations
**Parameters**:
  - measures: Array of {table, measure}
**Returns**: Success count and any errors

### 04_list_calculation_groups
**Purpose**: List calculation groups
**When to use**: Understanding time intelligence or other calculation modifiers
**Parameters**: None
**Returns**: Calculation group names, items, precedence

### 04_create_calculation_group
**Purpose**: Create a new calculation group
**When to use**: Implementing time intelligence or custom calculation patterns
**Parameters**:
  - name: Calculation group name
  - items: Array of {name, expression}
  - description (optional)
  - precedence (optional)
**Returns**: Success status

### 04_delete_calculation_group
**Purpose**: Delete a calculation group
**When to use**: Removing calculation groups
**Parameters**:
  - name: Calculation group name
**Returns**: Success status

### 04_list_roles
**Purpose**: List Row-Level Security (RLS) roles
**When to use**: Understanding security configuration
**Parameters**: None
**Returns**: Role names, descriptions, table permissions, DAX filters

---

## 📈 CATEGORY 05: ANALYSIS (1 unified tool)

### 05_comprehensive_analysis (UNIFIED ANALYSIS TOOL)
**Purpose**: Complete model analysis: Best Practices + Performance + Integrity
**When to use**: Model health checks, optimization, documentation
**Parameters**:
  - scope: 'all' (default), 'best_practices', 'performance', 'integrity'
  - depth: 'fast', 'balanced' (default), 'deep'
  - include_bpa: Include BPA rules (default: true)
  - include_performance: Include performance analysis (default: true)
  - include_integrity: Include validation (default: true)
  - max_seconds: Time limit for BPA (5-300)
**Returns**: Comprehensive analysis report with:
  - Best practices violations (120+ BPA rules)
  - Performance metrics (cardinality, data types)
  - Integrity issues (circular refs, duplicates, nulls)
  - Recommendations and priority levels
**Scope Options**:
  - all: Complete analysis (recommended for full health check)
  - best_practices: Focus on BPA and M practices
  - performance: Focus on cardinality and optimization
  - integrity: Focus on validation and errors
**Depth Options**:
  - fast: Quick scan (< 1 minute)
  - balanced: Standard analysis (recommended)
  - deep: Thorough analysis (may take several minutes)

---

## 🔗 CATEGORY 06: DEPENDENCIES (2 tools)

### 06 Analyze Measure Dependencies
**Purpose**: Analyze what a measure depends on
**When to use**: Understanding measure calculation chain
**Parameters**:
  - table: Table name
  - measure: Measure name
**Returns**: Dependency tree showing referenced measures, columns, tables
**Note**: Critical before modifying or deleting measures

### 06 Get Measure Impact
**Purpose**: Analyze what uses a measure
**When to use**: Impact analysis before changes
**Parameters**:
  - table: Table name
  - measure: Measure name
**Returns**: List of measures that reference this measure
**Note**: Use with analyze_measure_dependencies for complete picture

---

## 💾 CATEGORY 07: EXPORT (1 tool)

### 07 Get Live Model Schema
**Purpose**: Get live model schema (inline, without DAX expressions)
**When to use**: Quick model overview, structure analysis, lightweight documentation
**Parameters**:
  - include_hidden (optional): Include hidden objects (default: true)
**Returns**: Lightweight schema (~1-2k tokens) with:
  - Tables, columns, measures (names, data types, formats, folders)
  - Relationships (endpoints, cardinality, direction)
  - No DAX expressions (keeps token usage low)
**Note**: Returned inline, not saved to file

---

## 📄 CATEGORY 08: DOCUMENTATION (3 tools)

### 08 Generate Model Documentation
**Purpose**: Generate comprehensive Word documentation
**When to use**: Formal documentation, stakeholder reports
**Parameters**:
  - output_path (optional): Custom file path
**Returns**: Word document with tables, measures, relationships, best practices
**Contents**:
  - Model overview
  - Tables and columns
  - Measures with DAX
  - Relationships diagram
  - Best practices analysis

### 08 Update Model Documentation
**Purpose**: Update existing Word documentation
**When to use**: Incremental documentation updates
**Parameters**:
  - input_path: Existing Word document
  - output_path: Where to save updated version
**Returns**: Updated Word document

### 08 Export Model Explorer HTML
**Purpose**: Generate interactive HTML documentation
**When to use**: Shareable, searchable documentation
**Parameters**:
  - output_path (optional): Custom file path
**Returns**: Interactive HTML with search, filtering, collapsible sections
**Features**:
  - Search across all objects
  - Filter by type
  - Collapsible sections
  - Copy DAX to clipboard
  - No dependencies, self-contained

---

## 🔄 CATEGORY 09: COMPARISON (1 tool)

### 09 Compare Open Live Models
**Purpose**: Compare two live/open Power BI models - detects instances and compares OLD vs NEW
**When to use**: When you want to compare two Power BI models
**Parameters** (optional on first call):
  - old_port: Port number of OLD model
  - new_port: Port number of NEW model
**How it works**:
  1. First call: Detects all running Power BI instances (no parameters needed)
  2. Returns list of detected models with their ports
  3. Second call: Provide old_port and new_port to perform comparison
**Returns**: Detailed comparison report:
  - Added/removed/modified tables
  - Added/removed/modified measures
  - Added/removed/modified columns
  - Relationship changes
  - DAX formula differences
**Workflow**:
  1. Open both Power BI files in separate Desktop instances
  2. Run 09 Compare Open Live Models (without parameters) to detect models
  3. Identify which is OLD and which is NEW from the returned list
  4. Run 09 Compare Open Live Models again with old_port and new_port
**Use cases**:
  - Version comparison
  - Development vs production
  - Impact analysis of changes

---

## 📦 CATEGORY 10: PBIP ANALYSIS - HTML (1 tool)

### 10 PBIP Analysis HTML
**Purpose**: Analyze PBIP format without Power BI Desktop
**When to use**: CI/CD pipelines, Git repo analysis, no desktop access
**Parameters**:
  - pbip_path: Path to .pbip file or folder
  - output_path (optional): Output directory for report
**Returns**: HTML report with model analysis
**Features**:
  - Works offline (no Power BI connection)
  - Analyzes TMDL definition
  - Identifies tables, measures, relationships
  - Best practices from file analysis
  - Perfect for Git hooks and CI/CD
**Note**: PBIP format introduced in Power BI 2024

---

## 🔧 CATEGORY 11: TMDL OPERATIONS (1 unified tool)

### 11 TMDL Operations
**Purpose**: Unified handler for ALL TMDL automation tasks
**When to use**: TMDL export, find/replace, bulk rename, script generation
**Operations**:
  - **export**: Export complete model as TMDL to file
    - Optional: output_dir (output directory path)
    - Returns: Full TMDL export file with all DAX expressions
    - Example: {'operation': 'export', 'output_dir': 'C:/exports/tmdl'}

  - **find_replace**: Find and replace patterns in TMDL files
    - Required: tmdl_path, pattern, replacement
    - Optional: dry_run (default: true), regex (default: false)
    - Returns: List of matches and changes
    - Example: {'operation': 'find_replace', 'tmdl_path': 'C:/exports/tmdl', 'pattern': 'SUM', 'replacement': 'SUMX'}

  - **bulk_rename**: Rename objects with automatic reference updates
    - Required: tmdl_path, renames (array of {old_name, new_name})
    - Optional: dry_run (default: true), update_references (default: true)
    - Returns: Preview of rename operations
    - Example: {'operation': 'bulk_rename', 'tmdl_path': 'C:/exports/tmdl', 'renames': [{'old_name': 'Rev', 'new_name': 'Revenue'}]}

  - **generate_script**: Generate TMDL code for new objects
    - Required: definition (object properties dict)
    - Optional: object_type (table|measure|relationship|calc_group, default: 'table')
    - Returns: Valid TMDL code ready to use
    - Example: {'operation': 'generate_script', 'object_type': 'measure', 'definition': {'name': 'Total Sales', 'expression': 'SUM(Sales[Amount])'}}}

**Use cases**:
  - Export for version control or backup
  - Bulk DAX refactoring and renaming patterns
  - Rename tables/measures while maintaining references
  - Generate templates for new objects

**Safety**: Always run find_replace and bulk_rename with dry_run=true first!

---

## ❓ CATEGORY 12: HELP (1 tool)

### 12 Show User Guide
**Purpose**: Display this comprehensive user guide
**When to use**: Anytime you need tool reference
**Parameters**: None
**Returns**: This guide

---

## 🔀 CATEGORY 13: FULL MODEL (PBIP + SAMPLE) (2 tools)

### 13 PBIP Model - Sample Export
**Purpose**: Export combined TMDL + metadata + sample data
**When to use**: Complete offline analysis package
**Parameters**:
  - pbip_folder_path: Path to .SemanticModel folder or parent
  - output_dir (optional): Output location
  - connection_string/server/database (optional): Manual connection
  - include_sample_data: Include data samples (default: true)
  - sample_rows: Rows per table (default: 1000, max: 5000)
  - sample_compression: 'snappy' (default) or 'zstd'
  - include_row_counts: Include row counts (default: true)
  - track_column_usage: Track usage stats (default: true)
  - track_cardinality: Track cardinality (default: true)
  - tmdl_strategy: 'symlink' (default) or 'copy'
**Returns**: Folder with TMDL + metadata.json + sample_data (parquet)
**Features**:
  - Auto-detects running Power BI Desktop
  - Combines static TMDL with live metadata
  - Extracts sample data for testing
  - Optimized for AI analysis
**Use cases**:
  - AI-powered model analysis
  - Testing with real data
  - Comprehensive documentation

### 13 PBIP Model + Sample Analysis (FULLY AUTOMATED)
**Purpose**: Analyze exported hybrid model (reads all files internally)
**When to use**: After 13 PBIP Model - Sample Export
**Parameters**:
  - analysis_path: Path to analysis folder (tool reads all files internally)
  - operation: Type of analysis
    - 'read_metadata': Parse TMDL + JSON
    - 'find_objects': Search TMDL files
    - 'get_object_definition': Extract DAX from TMDL
    - 'analyze_dependencies': Parse dependency tree
    - 'analyze_performance': Scan measures for issues
    - 'get_sample_data': Read parquet data
    - 'get_unused_columns': Read JSON stats
    - 'get_report_dependencies': Read JSON usage
    - 'smart_analyze': Natural language query
  - intent: Natural language query (for smart_analyze)
  - object_filter: Filter criteria
  - format_type: 'json' (default) or 'toon' (compact)
  - batch_size/batch_number: Pagination
  - priority: Filter by priority level
  - detailed: Include detailed analysis
**Returns**: Analysis results based on operation
**Key Feature**: Fully automated - NO manual file reading needed!
**Intelligence**:
  - Fuzzy search (e.g., "base scenario" finds "PL-AMT-BASE Scenario")
  - Natural language queries with smart_analyze
  - Automatic pagination for large results
  - TOON format for 50% size reduction

---

## 🎯 COMMON WORKFLOWS

### Workflow 1: Model Health Check
```
1. 01 Detect PBI Instances
2. 01 Connect To Instance
3. 05 Live Model Full Analysis (scope='all', depth='balanced')
4. Review best practices violations
5. Address critical/high priority issues
```

### Workflow 2: Measure Development
```
1. 02 Measure Operations (study existing measures)
2. 03 Standard DAX Analysis (test DAX logic, mode='debug')
3. 02 Measure Operations (create new measure)
4. 03 Run DAX (test with real data)
5. 06 Analyze Measure Dependencies (verify dependencies)
```

### Workflow 3: Model Documentation
```
1. 02 Table Operations (get model overview)
2. 05 Live Model Full Analysis (get full analysis)
3. 08 Generate Model Documentation
4. 08 Export Model Explorer HTML (shareable version)
5. 11 TMDL Operations with operation='export' (full backup for version control)
```

### Workflow 4: Performance Optimization
```
1. 05 Live Model Full Analysis (scope='performance')
2. Review cardinality issues
3. 03 Get Column Value Distribution (check high-cardinality columns)
4. 03 List Relationships (verify relationship direction)
5. 03 Standard DAX Analysis (mode='report') (optimize measures)
```

### Workflow 5: Model Comparison
```
1. Open both Power BI files in separate Desktop instances
2. 09 Compare Open Live Models (no parameters) - detects models
3. Identify which is OLD and which is NEW from the list
4. 09 Compare Open Live Models (old_port, new_port) - performs comparison
5. Review changes and impacts
```

### Workflow 6: CI/CD Integration
```
1. 10 PBIP Analysis HTML (offline analysis)
2. Review best practices from PBIP
3. 13 PBIP Model - Sample Export (if live model available)
4. 13 PBIP Model + Sample Analysis (automated analysis)
5. Generate reports for pipeline
```

### Workflow 7: DAX Debugging & Optimization
```
1. 02 Measure Operations (get measure formula)
2. 06 Analyze Measure Dependencies (understand dependencies)
3. 03 Standard DAX Analysis (mode='all' or 'analyze') (get complete analysis)
4. AI writes optimized DAX based on recommendations from step 3
5. 03 Run DAX (test the optimized DAX with real data)
6. 02 Measure Operations (save optimized version)

IMPORTANT: The tool provides analysis and recommendations. The AI must write the optimized code.
```

---

## 💡 TIPS & BEST PRACTICES

### Connection Tips
- Always start with detect_pbi_instances
- Typically use model_index=0 for single file
- Keep Power BI Desktop open during analysis

### Analysis Tips
- Run comprehensive_analysis regularly (weekly recommended)
- Address CRITICAL and HIGH priority issues first
- Use depth='balanced' for most cases, 'deep' for problem areas

### DAX Development Tips
- Always use 03_standard_dax_analysis (mode='all') to get complete analysis with optimization recommendations
- The AI writes optimized code based on the tool's recommendations - the tool does NOT auto-generate code
- Test optimized DAX with 03_run_dax before committing
- Check dependencies with analyze_measure_dependencies before making changes
- Use mode='debug' for step-by-step context transition understanding

### Performance Tips
- Check cardinality with comprehensive_analysis
- Review column data types (integers > strings)
- Optimize bidirectional relationships
- Use calculated columns sparingly

### Documentation Tips
- Generate docs before major changes (baseline)
- Use HTML export for team sharing
- Export TMDL for version control (Git)
- Update docs after significant changes

### TMDL Automation Tips
- ALWAYS use dry_run=true first
- Test on a copy before bulk operations
- Use version control before find/replace
- Export TMDL before major refactoring

### Safety Tips
- Comprehensive_analysis backs up before changes
- Check measure_impact before deleting
- Use compare_pbi_models without parameters first to detect models
- Test DAX with validate_dax_query first

---

## 🚀 VERSION INFORMATION

**Current Version**: 5.01
**Tools**: 50+ across 13 categories
**Platform**: Windows 10/11 (64-bit)
**Requirements**:
  - Power BI Desktop installed
  - .NET Framework 4.7.2+
**Communication**: stdio (no exposed ports)

---

## 📞 SUPPORT & RESOURCES

For detailed documentation, visit:
- GitHub: https://github.com/bibiibjorn/MCP-PowerBi-Finvision
- Issues: Report bugs and feature requests on GitHub

---

**Note**: This MCP server runs locally and securely communicates via stdio. No data leaves your machine.
All operations are performed directly on your local Power BI Desktop instances.

**Last Updated**: January 2025
"""

def register_user_guide_handlers(registry):
    """Register user guide handler"""
    from server.tool_schemas import TOOL_SCHEMAS

    tools = [
        ToolDefinition(
            name="10_Show_User_Guide",
            description="Show comprehensive user guide",
            handler=handle_show_user_guide,
            input_schema=TOOL_SCHEMAS.get('show_user_guide', {}),
            category="core",
            sort_order=110  # 10 = Help
        ),
    ]

    for tool in tools:
        registry.register(tool)

    logger.info(f"Registered {len(tools)} user guide handlers")
