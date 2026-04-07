"""
MCP Prompts — Named workflow templates for Power BI analysis.

Each prompt guides an LLM client through a multi-step tool sequence,
providing the exact tool names, parameters, and order to follow.
"""

from typing import List
from mcp.types import (
    Prompt,
    PromptArgument,
    PromptMessage,
    GetPromptResult,
    TextContent,
)


# ---------------------------------------------------------------------------
# Prompt definitions
# ---------------------------------------------------------------------------

PROMPTS: List[Prompt] = [
    Prompt(
        name="debug-visual",
        description=(
            "Debug a Power BI visual — trace SE/FE timing, analyze filters, "
            "identify bottlenecks"
        ),
        arguments=[
            PromptArgument(
                name="page_name",
                description="Report page containing the visual",
                required=True,
            ),
            PromptArgument(
                name="visual_name",
                description="Title or ID of the visual to debug (omit to debug all visuals on the page)",
                required=False,
            ),
            PromptArgument(
                name="enable_trace",
                description="Enable SE/FE profiling trace (default: true)",
                required=False,
            ),
        ],
    ),
    Prompt(
        name="analyze-model",
        description=(
            "Comprehensive model quality analysis — BPA rules, relationships, "
            "unused columns, dependencies"
        ),
        arguments=[
            PromptArgument(
                name="depth",
                description="Analysis depth: fast (BPA only), balanced (BPA + relationships + columns), or deep (full analysis with dependencies)",
                required=False,
            ),
        ],
    ),
    Prompt(
        name="create-measure",
        description=(
            "Create a DAX measure with validation — analyze expression, "
            "check best practices, then create"
        ),
        arguments=[
            PromptArgument(
                name="table_name",
                description="Target table for the measure",
                required=True,
            ),
            PromptArgument(
                name="measure_name",
                description="Name of the new measure",
                required=True,
            ),
            PromptArgument(
                name="expression",
                description="DAX expression for the measure",
                required=True,
            ),
            PromptArgument(
                name="format_string",
                description="Optional DAX format string (e.g. '#,0.00', '0.0%')",
                required=False,
            ),
        ],
    ),
    Prompt(
        name="document-report",
        description=(
            "Generate comprehensive report documentation — pages, visuals, "
            "measures, filters"
        ),
        arguments=[
            PromptArgument(
                name="pbip_path",
                description="Path to the PBIP project folder",
                required=True,
            ),
            PromptArgument(
                name="output_format",
                description="Output format: html or word (default: html)",
                required=False,
            ),
        ],
    ),
    Prompt(
        name="optimize-slow-measure",
        description=(
            "Full performance investigation for a slow measure — trace, "
            "analyze DAX patterns, suggest optimization"
        ),
        arguments=[
            PromptArgument(
                name="measure_name",
                description="Name of the slow measure to investigate",
                required=True,
            ),
            PromptArgument(
                name="page_name",
                description="Report page where the measure is used",
                required=True,
            ),
        ],
    ),
]

_PROMPT_MAP = {p.name: p for p in PROMPTS}


# ---------------------------------------------------------------------------
# Message builders (one per prompt)
# ---------------------------------------------------------------------------

def _messages_debug_visual(args: dict[str, str]) -> list[PromptMessage]:
    page_name = args.get("page_name", "<page_name>")
    visual_name = args.get("visual_name", "")
    enable_trace = args.get("enable_trace", "true").lower()

    visual_clause = f" visual '{visual_name}'" if visual_name else " all visuals"
    trace_flag = enable_trace != "false"

    system_text = (
        "You are a Power BI performance engineer. Follow the steps below to "
        "debug a visual, using the MCP tools provided by the powerbi-finvision "
        "server. Report findings in a structured format with timings, filter "
        "context, and actionable recommendations."
    )

    user_text = (
        f"Debug{visual_clause} on page '{page_name}'.\n\n"
        f"Steps:\n"
        f"1. Ensure you are connected via 01_Connect_To_Instance.\n"
        f"2. Set the PBIP path via 09_Debug_Config (operation='set_pbip_path') "
        f"if not already configured.\n"
        f"3. Run 09_Debug_Operations with operation='visual', "
        f"page_name='{page_name}'"
    )
    if visual_name:
        user_text += f", visual_title='{visual_name}'"
    user_text += f", trace={str(trace_flag).lower()}.\n"
    user_text += (
        f"4. Analyze the results: check SE vs FE time split, number of SE "
        f"queries, and total duration.\n"
        f"5. If SE time is dominant (>70% of total), run 09_Debug_Operations "
        f"with operation='optimize' to get DAX optimization suggestions.\n"
        f"6. Summarize: visual name, total ms, SE ms, FE ms, SE query count, "
        f"top bottleneck, and recommended fix."
    )

    return [
        PromptMessage(role="user", content=TextContent(type="text", text=system_text)),
        PromptMessage(role="user", content=TextContent(type="text", text=user_text)),
    ]


def _messages_analyze_model(args: dict[str, str]) -> list[PromptMessage]:
    depth = args.get("depth", "balanced").lower()
    if depth not in ("fast", "balanced", "deep"):
        depth = "balanced"

    system_text = (
        "You are a Power BI model quality analyst. Follow the steps below to "
        "perform a comprehensive model analysis. Present findings grouped by "
        "severity (critical / warning / info) with clear remediation steps."
    )

    steps = [
        "1. Ensure you are connected via 01_Connect_To_Instance.",
    ]

    if depth == "fast":
        steps.append(
            "2. Run 06_Analysis_Operations with operation='bpa' to execute "
            "Best Practice Analyzer rules."
        )
        steps.append(
            "3. Summarize BPA violations grouped by severity."
        )
    elif depth == "balanced":
        steps.extend([
            "2. Run 06_Analysis_Operations with operation='bpa' to execute "
            "Best Practice Analyzer rules.",
            "3. Run 06_Analysis_Operations with operation='relationships' to "
            "review relationship topology.",
            "4. Run 05_Column_Usage_Mapping to identify unused columns.",
            "5. Summarize: BPA violations (by severity), relationship issues, "
            "and unused columns that can be removed.",
        ])
    else:  # deep
        steps.extend([
            "2. Run 06_Analysis_Operations with operation='bpa' to execute "
            "Best Practice Analyzer rules.",
            "3. Run 06_Analysis_Operations with operation='relationships' to "
            "review relationship topology.",
            "4. Run 05_Column_Usage_Mapping to identify unused columns.",
            "5. Run 06_Analysis_Operations with operation='full' for complete "
            "model analysis including VertiPaq statistics.",
            "6. Run 07_PBIP_Dependency_Analysis to map measure dependencies.",
            "7. Summarize: BPA violations (by severity), relationship issues, "
            "unused columns, dependency hotspots, and VertiPaq compression "
            "recommendations.",
        ])

    user_text = (
        f"Perform a {depth}-depth model quality analysis.\n\n"
        f"Steps:\n" + "\n".join(steps)
    )

    return [
        PromptMessage(role="user", content=TextContent(type="text", text=system_text)),
        PromptMessage(role="user", content=TextContent(type="text", text=user_text)),
    ]


def _messages_create_measure(args: dict[str, str]) -> list[PromptMessage]:
    table_name = args.get("table_name", "<table_name>")
    measure_name = args.get("measure_name", "<measure_name>")
    expression = args.get("expression", "<expression>")
    format_string = args.get("format_string", "")

    system_text = (
        "You are a DAX expert creating a validated measure. Analyze the "
        "expression for correctness, check for anti-patterns, then create "
        "the measure. Report any issues found during validation."
    )

    format_clause = ""
    if format_string:
        format_clause = f", format_string='{format_string}'"

    user_text = (
        f"Create measure '{measure_name}' in table '{table_name}' with "
        f"expression:\n```dax\n{expression}\n```\n\n"
        f"Steps:\n"
        f"1. Ensure you are connected via 01_Connect_To_Instance.\n"
        f"2. Run 05_DAX_Intelligence with operation='analyze', "
        f"expression=\"{expression}\" to check for anti-patterns, circular "
        f"references, and performance issues.\n"
        f"3. Review the analysis results. If critical issues are found, "
        f"suggest a corrected expression and confirm with the user before "
        f"proceeding.\n"
        f"4. Run 02_Measure_Operations with operation='create', "
        f"table='{table_name}', name='{measure_name}', "
        f"expression=\"{expression}\"{format_clause}.\n"
        f"5. Verify the measure was created by running 02_Measure_Operations "
        f"with operation='get', table='{table_name}', name='{measure_name}'.\n"
        f"6. Report: measure created, any warnings from validation, and the "
        f"final expression used."
    )

    return [
        PromptMessage(role="user", content=TextContent(type="text", text=system_text)),
        PromptMessage(role="user", content=TextContent(type="text", text=user_text)),
    ]


def _messages_document_report(args: dict[str, str]) -> list[PromptMessage]:
    pbip_path = args.get("pbip_path", "<pbip_path>")
    output_format = args.get("output_format", "html").lower()
    if output_format not in ("html", "word"):
        output_format = "html"

    system_text = (
        "You are a Power BI documentation specialist. Generate comprehensive "
        "report documentation covering pages, visuals, measures, and filter "
        "context. Organize the output clearly with sections for each page."
    )

    steps = [
        f"1. Run 09_Debug_Config with operation='set_pbip_path', "
        f"pbip_path='{pbip_path}' to configure the PBIP project path.",
        f"2. Run 09_Document with operation='generate', format='{output_format}' "
        f"to produce the report documentation.",
        f"3. Run 07_PBIP_Dependency_Analysis with pbip_path='{pbip_path}' to "
        f"map measure-to-visual dependencies.",
    ]

    if output_format == "word":
        steps.append(
            "4. Run 08_Documentation_Word to generate the Word document."
        )
        steps.append(
            "5. Report: path to generated Word document, page count, and "
            "summary of report structure."
        )
    else:
        steps.append(
            "4. Report: path to generated HTML documentation, page count, "
            "and summary of report structure."
        )

    user_text = (
        f"Generate {output_format.upper()} documentation for the PBIP project "
        f"at '{pbip_path}'.\n\n"
        f"Steps:\n" + "\n".join(steps)
    )

    return [
        PromptMessage(role="user", content=TextContent(type="text", text=system_text)),
        PromptMessage(role="user", content=TextContent(type="text", text=user_text)),
    ]


def _messages_optimize_slow_measure(args: dict[str, str]) -> list[PromptMessage]:
    measure_name = args.get("measure_name", "<measure_name>")
    page_name = args.get("page_name", "<page_name>")

    system_text = (
        "You are a Power BI performance engineer. Investigate a slow measure "
        "using DAX analysis and visual profiling. Provide concrete optimization "
        "recommendations with before/after DAX when applicable."
    )

    user_text = (
        f"Investigate slow measure '{measure_name}' on page '{page_name}'.\n\n"
        f"Steps:\n"
        f"1. Ensure you are connected via 01_Connect_To_Instance.\n"
        f"2. Run 05_DAX_Intelligence with operation='analyze', "
        f"measure='{measure_name}' to inspect the DAX expression for "
        f"anti-patterns (nested CALCULATE, row-by-row iteration, excessive "
        f"FILTER usage, etc.).\n"
        f"3. Run 09_Debug_Config with operation='set_pbip_path' if not "
        f"already set.\n"
        f"4. Run 09_Debug_Operations with operation='visual', "
        f"page_name='{page_name}', trace=true to capture SE/FE timing for "
        f"visuals on the page.\n"
        f"5. Identify which visual(s) use '{measure_name}' and note their "
        f"SE time, FE time, and SE query count.\n"
        f"6. Run 09_Debug_Operations with operation='optimize' to get "
        f"server-side optimization suggestions.\n"
        f"7. Summarize findings:\n"
        f"   - Current DAX pattern issues\n"
        f"   - SE vs FE time breakdown\n"
        f"   - Recommended DAX rewrites (show before/after)\n"
        f"   - Expected performance improvement"
    )

    return [
        PromptMessage(role="user", content=TextContent(type="text", text=system_text)),
        PromptMessage(role="user", content=TextContent(type="text", text=user_text)),
    ]


# Dispatch map: prompt name -> message builder
_MESSAGE_BUILDERS = {
    "debug-visual": _messages_debug_visual,
    "analyze-model": _messages_analyze_model,
    "create-measure": _messages_create_measure,
    "document-report": _messages_document_report,
    "optimize-slow-measure": _messages_optimize_slow_measure,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_prompts() -> list[Prompt]:
    """Return all registered prompts for list_prompts."""
    return PROMPTS


def get_prompt_messages(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
    """Build and return prompt messages for get_prompt.

    Raises ValueError if the prompt name is not found.
    """
    builder = _MESSAGE_BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"Unknown prompt: {name}")

    messages = builder(arguments or {})
    description = _PROMPT_MAP[name].description

    return GetPromptResult(description=description, messages=messages)
