"""
Aggregation Analysis Handler

MCP tool handler for aggregation analysis of Power BI PBIP models.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def handle_aggregation_analysis(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle aggregation analysis requests.

    Args:
        args: Tool arguments including:
            - pbip_path: Path to PBIP project
            - output_format: summary, detailed, html, json
            - output_path: Optional output path for reports
            - page_filter: Optional page name filter
            - include_visual_details: Whether to include visual details

    Returns:
        Analysis result dictionary
    """
    from core.aggregation import (
        AggregationAnalyzer,
        AggregationReportBuilder,
    )

    pbip_path = args.get("pbip_path", "")
    output_format = args.get("output_format", "summary")
    output_path = args.get("output_path")
    page_filter = args.get("page_filter")
    include_visual_details = args.get("include_visual_details", True)

    # Validate path
    if not pbip_path:
        return {
            "success": False,
            "error": "pbip_path is required",
        }

    path = Path(pbip_path)
    if not path.exists():
        return {
            "success": False,
            "error": f"Path does not exist: {pbip_path}",
        }

    try:
        # Create analyzer and run analysis
        logger.info(f"Starting aggregation analysis for {pbip_path}")
        analyzer = AggregationAnalyzer(str(path))
        result = analyzer.analyze(include_report=True)

        # Build report
        report_builder = AggregationReportBuilder(result)

        # Filter pages if requested
        if page_filter and result.report_summary:
            filtered_pages = [
                p for p in result.report_summary.pages
                if page_filter.lower() in p.page_name.lower()
            ]
            result.report_summary.pages = filtered_pages

        # Generate HTML report only when requested or alongside json format
        saved_path = None
        if output_format in ("html", "json"):
            export_dir = Path(pbip_path).parent / "exports" / "aggregation_analysis"
            export_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_name = result.model_name.replace(" ", "_")
            html_output_path = output_path if output_path and output_format == "html" else str(export_dir / f"{model_name}_Aggregation_{timestamp}.html")
            saved_path = report_builder.save_html_report(html_output_path)

        # Generate output based on format
        if output_format == "html":
            return {
                "success": True,
                "format": "html",
                "output_path": saved_path,
                "message": f"HTML report saved to {saved_path}",
                "summary": _build_brief_summary(result),
            }

        elif output_format == "json":
            json_data = report_builder.build_json_export()

            if output_path:
                json_output_path = output_path
                report_builder.save_json_export(json_output_path)
                return {
                    "success": True,
                    "format": "json",
                    "output_path": json_output_path,
                    "html_report_path": saved_path,
                    "message": f"JSON export saved to {json_output_path}. HTML report also saved to {saved_path}",
                    "data": json_data if include_visual_details else _strip_visual_details(json_data),
                }
            else:
                return {
                    "success": True,
                    "format": "json",
                    "html_report_path": saved_path,
                    "message": f"HTML report saved to {saved_path}",
                    "data": json_data if include_visual_details else _strip_visual_details(json_data),
                }

        elif output_format == "detailed":
            detailed_text = report_builder.build_detailed_text()
            return {
                "success": True,
                "format": "detailed",
                "report": detailed_text,
            }

        else:  # summary (default)
            summary_text = report_builder.build_summary_text()
            return {
                "success": True,
                "format": "summary",
                "report": summary_text,
            }

    except Exception as e:
        logger.exception(f"Error during aggregation analysis: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def _build_brief_summary(result) -> Dict[str, Any]:
    """Build a brief summary for HTML/JSON responses."""
    summary = {
        "model_name": result.model_name,
        "aggregation_tables": len(result.aggregation_tables),
        "agg_aware_measures": len(result.agg_aware_measures),
        "agg_level_measures": len(result.agg_level_measures),
    }

    if result.report_summary:
        rs = result.report_summary
        summary["report"] = {
            "pages": rs.total_pages,
            "visuals_analyzed": rs.visuals_analyzed,
            "optimization_score": rs.optimization_score,
            "level_breakdown": rs.agg_level_breakdown,
        }

    return summary


def _strip_visual_details(json_data: Dict) -> Dict:
    """Strip detailed visual information from JSON output."""
    if "report_summary" in json_data and "pages" in json_data["report_summary"]:
        for page in json_data["report_summary"]["pages"]:
            page["visuals"] = [
                {
                    "visual_id": v["visual_id"],
                    "visual_type": v["visual_type"],
                    "agg_level": v["agg_level"],
                    "agg_table": v["agg_table"],
                }
                for v in page.get("visuals", [])
            ]
    return json_data


def register_aggregation_handler(registry) -> None:
    """Register aggregation analysis handler with the tool registry."""
    from server.registry import ToolDefinition

    tool = ToolDefinition(
        name="07_Analyze_Aggregation",
        description="Analyze aggregation table usage, optimization opportunities, and row savings.",
        handler=handle_aggregation_analysis,
        input_schema=get_aggregation_schema(),
        category="pbip",
        sort_order=74,  # 07 = PBIP Analysis
        annotations={"readOnlyHint": True},
    )
    registry.register(tool)


def get_aggregation_schema() -> Dict[str, Any]:
    """Get the JSON schema for the analyze_aggregation tool."""
    return {
        "type": "object",
        "properties": {
            "pbip_path": {
                "type": "string",
                "description": "Path to PBIP project or .SemanticModel folder"
            },
            "output_format": {
                "type": "string",
                "enum": ["summary", "detailed", "html", "json"],
                "default": "summary"
            },
            "output_path": {
                "type": "string",
                "description": "Output path for reports"
            },
            "page_filter": {
                "type": "string",
                "description": "Filter pages by name"
            },
            "include_visual_details": {
                "type": "boolean",
                "default": True
            }
        },
        "required": ["pbip_path"]
    }


# Tool schema for inclusion in tool_schemas.py
AGGREGATION_TOOL_SCHEMA = get_aggregation_schema()
