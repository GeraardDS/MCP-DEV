"""
PBIP Operations Handler
Unified handler for offline PBIP analysis operations with caching.

Provides granular, composable operations on PBIP projects:
- analyze: Full analysis with HTML report
- query_dependencies: Dependency graph queries
- query_measures: Measure search and filtering
- query_relationships: Relationship quality analysis
- query_unused: Unused object detection
- validate_model: TMDL validation and linting
- compare_models: Offline model comparison
- generate_documentation: Markdown documentation generation
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from server.registry import ToolDefinition
from server.pbip_cache import pbip_cache, normalize_pbip_path
from core.validation.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


_cache = pbip_cache
_normalize_pbip_path = normalize_pbip_path


# ═════════════════════════════════════════════════════════════════════
# Main dispatcher
# ═════════════════════════════════════════════════════════════════════

def handle_pbip_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unified PBIP operations."""
    operation = args.get("operation")

    if not operation:
        return {"success": False, "error": "operation parameter is required"}

    handlers = {
        "analyze": _handle_analyze,
        "query_dependencies": _handle_query_dependencies,
        "query_measures": _handle_query_measures,
        "query_relationships": _handle_query_relationships,
        "query_unused": _handle_query_unused,
        "validate_model": _handle_validate_model,
        "compare_models": _handle_compare_models,
        "generate_documentation": _handle_generate_documentation,
        "git_diff": _handle_git_diff,
    }

    handler = handlers.get(operation)
    if not handler:
        return {"success": False, "error": f"Unknown operation: {operation}"}

    return handler(args)


# ═════════════════════════════════════════════════════════════════════
# Operation handlers
# ═════════════════════════════════════════════════════════════════════

def _handle_analyze(args: Dict[str, Any]) -> Dict[str, Any]:
    """Full analysis with HTML report (uses cache for parsed model data)."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    try:
        from core.pbip.pbip_enhanced_analyzer import EnhancedPbipAnalyzer
        from core.pbip.pbip_html_generator import PbipHtmlGenerator

        path = _normalize_pbip_path(pbip_path)
        data = _cache.get_or_parse(path)

        model_data = data.model_data
        report_data = data.report_data
        dependencies = data.dependencies

        # Run enhanced analysis (BPA, lineage, quality metrics)
        analyzer = EnhancedPbipAnalyzer(
            model_data=model_data,
            dependencies=dependencies,
            report_data=report_data
        )
        result = analyzer.run_full_analysis()

        # Determine output path
        server_root = Path(__file__).parent.parent.parent
        default_exports_path = server_root / "exports"
        default_exports_path.mkdir(exist_ok=True)

        output_path = args.get("output_path", str(default_exports_path))
        if not os.path.isabs(output_path):
            output_path = str(server_root / output_path)

        repo_name = os.path.basename(path) or "PBIP_Repository"

        # Generate HTML report
        html_generator = PbipHtmlGenerator()
        html_file_path = html_generator.generate_full_report(
            model_data=model_data,
            report_data=report_data,
            dependencies=dependencies,
            output_path=output_path,
            repository_name=repo_name,
            enhanced_results=result
        )

        return {
            "success": True,
            "html_report": html_file_path,
            "message": f"HTML report generated: {html_file_path}",
        }

    except Exception as e:
        logger.error(f"Error in analyze operation: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_query_dependencies(args: Dict[str, Any]) -> Dict[str, Any]:
    """Query dependency graph for a specific object."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    object_name = args.get("object_name")
    direction = args.get("direction", "both")  # "forward", "reverse", "both"

    try:
        path = _normalize_pbip_path(pbip_path)
        data = _cache.get_or_parse(path)
        deps = data.dependencies

        result: Dict[str, Any] = {"success": True}

        if object_name:
            # Query for a specific object
            fwd = deps.get("measure_to_measure", {}).get(object_name, [])
            rev = deps.get("measure_to_measure_reverse", {}).get(object_name, [])
            col_deps = deps.get("measure_to_column", {}).get(object_name, [])

            if direction in ("forward", "both"):
                result["depends_on_measures"] = fwd
                result["depends_on_columns"] = col_deps
            if direction in ("reverse", "both"):
                result["referenced_by"] = rev
        else:
            # Return summary statistics
            m2m = deps.get("measure_to_measure", {})
            m2c = deps.get("measure_to_column", {})
            unused = deps.get("unused_columns", [])
            unused_measures = deps.get("unused_measures", [])

            result["summary"] = {
                "measures_with_dependencies": len(m2m),
                "measures_with_column_refs": len(m2c),
                "unused_columns": len(unused) if isinstance(unused, list) else 0,
                "unused_measures": len(unused_measures) if isinstance(unused_measures, list) else 0,
            }
            # Include the full maps for detailed inspection
            result["measure_to_measure"] = m2m
            result["measure_to_column"] = m2c

        return result

    except Exception as e:
        logger.error(f"Error querying dependencies: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_query_measures(args: Dict[str, Any]) -> Dict[str, Any]:
    """List/search measures with filtering."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    table_filter = args.get("table")
    folder_filter = args.get("display_folder")
    name_pattern = args.get("pattern")
    expr_search = args.get("expression_search")

    try:
        path = _normalize_pbip_path(pbip_path)
        data = _cache.get_or_parse(path)
        model = data.model_data

        measures = []
        for table in model.get("tables", []):
            table_name = table.get("name", "")

            if table_filter and table_filter.lower() != table_name.lower():
                continue

            for m in table.get("measures", []):
                m_name = m.get("name", "")
                m_folder = m.get("display_folder", "")
                m_expr = m.get("expression", "")

                if folder_filter and not m_folder.lower().startswith(folder_filter.lower()):
                    continue

                if name_pattern:
                    try:
                        if not re.search(name_pattern, m_name, re.IGNORECASE):
                            continue
                    except re.error:
                        if name_pattern.lower() not in m_name.lower():
                            continue

                if expr_search:
                    try:
                        if not re.search(expr_search, m_expr, re.IGNORECASE):
                            continue
                    except re.error:
                        if expr_search.lower() not in m_expr.lower():
                            continue

                measures.append({
                    "table": table_name,
                    "name": m_name,
                    "expression": m.get("expression", ""),
                    "display_folder": m_folder,
                    "format_string": m.get("format_string", ""),
                    "is_hidden": m.get("is_hidden", False),
                    "description": m.get("description", ""),
                })

        return {
            "success": True,
            "total": len(measures),
            "measures": measures,
        }

    except Exception as e:
        logger.error(f"Error querying measures: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_query_relationships(args: Dict[str, Any]) -> Dict[str, Any]:
    """List relationships with quality analysis."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    try:
        path = _normalize_pbip_path(pbip_path)
        data = _cache.get_or_parse(path)
        model = data.model_data

        relationships = model.get("relationships", [])

        # Compute quality indicators
        issues = []
        bidirectional = []
        inactive = []
        many_to_many = []

        for rel in relationships:
            # Check for many-to-many
            from_card = (rel.get("from_cardinality") or "").lower()
            to_card = (rel.get("to_cardinality") or "").lower()
            if from_card == "many" and to_card == "many":
                many_to_many.append(rel)
                issues.append(f"Many-to-many: {rel.get('from_table', '?')} <-> {rel.get('to_table', '?')}")

            # Check for bidirectional
            cross_filter = (rel.get("cross_filtering_behavior") or "").lower()
            if cross_filter in ("bothDirections", "bothdirections", "both"):
                bidirectional.append(rel)
                issues.append(f"Bidirectional: {rel.get('from_table', '?')} <-> {rel.get('to_table', '?')}")

            # Check for inactive
            if not rel.get("is_active", True):
                inactive.append(rel)

        return {
            "success": True,
            "total": len(relationships),
            "relationships": relationships,
            "quality": {
                "many_to_many_count": len(many_to_many),
                "bidirectional_count": len(bidirectional),
                "inactive_count": len(inactive),
                "issues": issues,
            },
        }

    except Exception as e:
        logger.error(f"Error querying relationships: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_query_unused(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find unused measures and columns."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    try:
        path = _normalize_pbip_path(pbip_path)
        data = _cache.get_or_parse(path)
        deps = data.dependencies

        unused_cols = deps.get("unused_columns", [])
        unused_measures = deps.get("unused_measures", [])

        return {
            "success": True,
            "unused_columns": unused_cols if isinstance(unused_cols, list) else [],
            "unused_columns_count": len(unused_cols) if isinstance(unused_cols, list) else 0,
            "unused_measures": unused_measures if isinstance(unused_measures, list) else [],
            "unused_measures_count": len(unused_measures) if isinstance(unused_measures, list) else 0,
        }

    except Exception as e:
        logger.error(f"Error querying unused objects: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_validate_model(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run TMDL validation on a PBIP folder."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    try:
        from core.tmdl.validator import TmdlValidator

        path = _normalize_pbip_path(pbip_path)

        # Find the definition folder
        p = Path(path)
        definition_path = None
        for sm in p.rglob("*.SemanticModel"):
            candidate = sm / "definition"
            if candidate.is_dir():
                definition_path = str(candidate)
                break

        if not definition_path:
            # Try direct definition path
            if (p / "definition").is_dir():
                definition_path = str(p / "definition")
            else:
                return {"success": False, "error": "Could not find definition/ folder in PBIP project"}

        validator = TmdlValidator()
        result = validator.validate_syntax(definition_path)

        return {
            "success": True,
            "validation_result": {
                "is_valid": result.is_valid,
                "errors": [{"file": e.file, "line": e.line, "message": e.message, "severity": e.severity.value} for e in result.errors],
                "warnings": [{"file": w.file, "line": w.line, "message": w.message, "severity": w.severity.value} for w in result.warnings] if hasattr(result, 'warnings') else [],
                "error_count": len(result.errors),
            },
        }

    except ImportError:
        return {"success": False, "error": "TmdlValidator not available"}
    except Exception as e:
        logger.error(f"Error validating model: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_compare_models(args: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two PBIP projects offline."""
    source_path = args.get("source_path")
    target_path = args.get("target_path")

    if not source_path or not target_path:
        return {"success": False, "error": "Both source_path and target_path are required"}

    try:
        from core.tmdl.tmdl_semantic_diff import TmdlSemanticDiff

        src = _normalize_pbip_path(source_path)
        tgt = _normalize_pbip_path(target_path)

        # Parse both models
        src_data = _cache.get_or_parse(src)
        tgt_data = _cache.get_or_parse(tgt)

        differ = TmdlSemanticDiff(
            src_data.model_data,
            tgt_data.model_data
        )
        diff_result = differ.compare()

        return {
            "success": True,
            "comparison": diff_result,
        }

    except ImportError:
        return {"success": False, "error": "TmdlSemanticDiff not available"}
    except Exception as e:
        logger.error(f"Error comparing models: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_generate_documentation(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate markdown documentation from PBIP metadata."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    output_path = args.get("output_path")

    try:
        path = _normalize_pbip_path(pbip_path)
        data = _cache.get_or_parse(path)
        model = data.model_data
        deps = data.dependencies

        md = _generate_markdown(model, deps)

        # Save to file if output_path specified
        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8")
            return {"success": True, "file": str(out), "message": f"Documentation saved to {out}"}

        return {"success": True, "documentation": md}

    except Exception as e:
        logger.error(f"Error generating documentation: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_git_diff(args: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze git changes to PBIP project with semantic understanding."""
    pbip_path = args.get("pbip_path")
    if not pbip_path:
        return {"success": False, "error": "pbip_path is required"}

    from_ref = args.get("from_ref")
    to_ref = args.get("to_ref")
    base_branch = args.get("base_branch")

    try:
        from core.pbip.pbip_git_analyzer import PbipGitAnalyzer

        path = _normalize_pbip_path(pbip_path)
        analyzer = PbipGitAnalyzer(path)

        if base_branch:
            # PR summary mode
            result = analyzer.summarize_pr_changes(base_branch)
        elif from_ref:
            # Commit diff mode
            result = analyzer.analyze_commit_diff(
                from_ref=from_ref,
                to_ref=to_ref or "HEAD",
            )
        else:
            # Working changes mode (default)
            result = analyzer.analyze_working_changes()

        return {"success": True, **result}

    except ValueError as ve:
        return {"success": False, "error": str(ve)}
    except Exception as e:
        logger.error(f"Error in git diff analysis: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════
# Markdown documentation generator
# ═════════════════════════════════════════════════════════════════════

def _generate_markdown(model: Dict[str, Any], deps: Dict[str, Any]) -> str:
    """Generate comprehensive markdown documentation."""
    lines: List[str] = []

    # Header
    db_name = ""
    db = model.get("database")
    if isinstance(db, dict):
        db_name = db.get("name", "")
    lines.append(f"# {db_name or 'Power BI Model'} Documentation\n")

    # Overview
    tables = model.get("tables", [])
    rels = model.get("relationships", [])
    total_cols = sum(len(t.get("columns", [])) for t in tables)
    total_measures = sum(len(t.get("measures", [])) for t in tables)

    lines.append("## Overview\n")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Tables | {len(tables)} |")
    lines.append(f"| Columns | {total_cols} |")
    lines.append(f"| Measures | {total_measures} |")
    lines.append(f"| Relationships | {len(rels)} |")
    lines.append("")

    # Tables
    lines.append("## Tables\n")
    for table in sorted(tables, key=lambda t: t.get("name", "")):
        name = table.get("name", "")
        desc = table.get("description", "")
        hidden = " *(hidden)*" if table.get("is_hidden") else ""
        cols = table.get("columns", [])
        measures = table.get("measures", [])

        lines.append(f"### {name}{hidden}\n")
        if desc:
            lines.append(f"{desc}\n")

        # Columns
        if cols:
            lines.append("#### Columns\n")
            lines.append("| Name | Type | Key | Hidden |")
            lines.append("|------|------|-----|--------|")
            for c in cols:
                key = "Yes" if c.get("is_key") else ""
                hidden_c = "Yes" if c.get("is_hidden") else ""
                dtype = c.get("data_type", "")
                lines.append(f"| {c.get('name', '')} | {dtype} | {key} | {hidden_c} |")
            lines.append("")

        # Measures
        if measures:
            lines.append("#### Measures\n")
            for m in measures:
                m_name = m.get("name", "")
                expr = m.get("expression", "")
                folder = m.get("display_folder", "")
                desc_m = m.get("description", "")
                fmt = m.get("format_string", "")

                lines.append(f"**{m_name}**")
                if folder:
                    lines.append(f"  - Folder: `{folder}`")
                if desc_m:
                    lines.append(f"  - {desc_m}")
                if fmt:
                    lines.append(f"  - Format: `{fmt}`")
                if expr:
                    lines.append(f"  ```dax\n  {expr}\n  ```")
                lines.append("")

    # Relationships (Mermaid diagram)
    if rels:
        lines.append("## Relationships\n")
        lines.append("```mermaid")
        lines.append("erDiagram")
        for r in rels:
            from_t = r.get("from_table", r.get("fromTable", "?"))
            to_t = r.get("to_table", r.get("toTable", "?"))
            from_c = r.get("from_column_name", r.get("fromColumn", ""))
            to_c = r.get("to_column_name", r.get("toColumn", ""))
            card = r.get("from_cardinality", "many")
            to_card = r.get("to_cardinality", "one")

            # Mermaid cardinality notation
            left = "||" if card and "one" in str(card).lower() else "}o"
            right = "||" if to_card and "one" in str(to_card).lower() else "o{"
            active = "--" if r.get("is_active", True) else ".."

            # Sanitize names for Mermaid (no spaces)
            safe_from = from_t.replace(" ", "_") if from_t else "Unknown"
            safe_to = to_t.replace(" ", "_") if to_t else "Unknown"

            lines.append(f'    {safe_from} {left}{active}{right} {safe_to} : "{from_c} -> {to_c}"')
        lines.append("```\n")

        # Relationship table
        lines.append("| From | To | Cardinality | Active | Cross-Filter |")
        lines.append("|------|-----|-------------|--------|-------------|")
        for r in rels:
            from_t = r.get("from_table", r.get("fromTable", "?"))
            from_c = r.get("from_column_name", r.get("fromColumn", ""))
            to_t = r.get("to_table", r.get("toTable", "?"))
            to_c = r.get("to_column_name", r.get("toColumn", ""))
            active = "Yes" if r.get("is_active", True) else "No"
            cross = r.get("cross_filtering_behavior", "")
            lines.append(f"| {from_t}.{from_c} | {to_t}.{to_c} | {r.get('from_cardinality', '?')}-to-{r.get('to_cardinality', '?')} | {active} | {cross} |")
        lines.append("")

    # Unused objects
    unused_cols = deps.get("unused_columns", [])
    unused_measures = deps.get("unused_measures", [])
    if unused_cols or unused_measures:
        lines.append("## Unused Objects\n")
        if unused_cols:
            lines.append(f"### Unused Columns ({len(unused_cols)})\n")
            for c in unused_cols[:50]:  # Limit to 50
                lines.append(f"- {c}")
            if len(unused_cols) > 50:
                lines.append(f"- ... and {len(unused_cols) - 50} more")
            lines.append("")
        if unused_measures:
            lines.append(f"### Unused Measures ({len(unused_measures)})\n")
            for m in unused_measures[:50]:
                lines.append(f"- {m}")
            if len(unused_measures) > 50:
                lines.append(f"- ... and {len(unused_measures) - 50} more")
            lines.append("")

    # Expressions
    expressions = model.get("expressions", [])
    if expressions and not (len(expressions) == 1 and "content" in expressions[0]):
        lines.append("## Shared Expressions (M Parameters)\n")
        for expr in expressions:
            if isinstance(expr, dict) and "name" in expr:
                lines.append(f"**{expr['name']}**")
                if expr.get("expression"):
                    lines.append(f"```m\n{expr['expression']}\n```")
                lines.append("")

    # Roles
    roles = model.get("roles", [])
    if roles:
        lines.append("## Security Roles\n")
        for role in roles:
            r_name = role.get("name", "")
            lines.append(f"### {r_name}\n")
            perms = role.get("table_permissions", [])
            if perms:
                for tp in perms:
                    lines.append(f"- **{tp.get('table', '')}**: `{tp.get('filter_expression', 'N/A')}`")
            lines.append("")

    lines.append("---\n*Generated by MCP-PowerBi-Finvision*\n")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# Registration
# ═════════════════════════════════════════════════════════════════════

def register_pbip_operations_handler(registry):
    """Register PBIP operations handler."""

    tool = ToolDefinition(
        name="07_PBIP_Operations",
        description="Offline PBIP analysis (no live connection needed): analyze, query_dependencies, query_measures, query_relationships, query_unused, validate_model, compare_models, generate_documentation, git_diff.",
        handler=handle_pbip_operations,
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "analyze", "query_dependencies", "query_measures",
                        "query_relationships", "query_unused", "validate_model",
                        "compare_models", "generate_documentation", "git_diff",
                    ],
                },
                "pbip_path": {
                    "type": "string",
                    "description": "Path to .pbip file, project directory, or .SemanticModel folder",
                },
                "object_name": {
                    "type": "string",
                    "description": "Object name (query_dependencies, e.g. '[Total Sales]')",
                },
                "direction": {
                    "type": "string",
                    "enum": ["forward", "reverse", "both"],
                },
                "table": {
                    "type": "string",
                    "description": "Table filter (query_measures)",
                },
                "display_folder": {
                    "type": "string",
                    "description": "Display folder filter (query_measures)",
                },
                "pattern": {
                    "type": "string",
                    "description": "Name pattern regex (query_measures)",
                },
                "expression_search": {
                    "type": "string",
                    "description": "DAX expression regex search (query_measures)",
                },
                "source_path": {
                    "type": "string",
                    "description": "Source PBIP path (compare_models)",
                },
                "target_path": {
                    "type": "string",
                    "description": "Target PBIP path (compare_models)",
                },
                "output_path": {
                    "type": "string",
                    "description": "Output path (analyze, generate_documentation)",
                },
            },
            "required": ["operation"],
        },
        category="pbip",
        sort_order=70,  # Primary PBIP analysis tool
    )

    registry.register(tool)
    logger.info("Registered pbip_operations handler")
