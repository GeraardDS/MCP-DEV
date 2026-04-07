"""Data collection for Power BI model documentation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.comparison import model_narrative
from core.dax.dax_reference_parser import parse_dax_references

from .utils import (
    build_reference_index,
    format_edge,
    now_iso,
    pick,
    to_bool,
)


def _summarize_best_practices(
    bpa_payload: Optional[Dict[str, Any]], light_payload: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Summarize best practice analysis results.

    Args:
        bpa_payload: Full BPA analyzer payload
        light_payload: Lightweight best practices payload

    Returns:
        dict: {
            "source": str,
            "total_issues": int,
            "by_severity": dict,
            "violations": list,
            "notes": list
        }
    """
    result: Dict[str, Any] = {
        "source": None,
        "total_issues": 0,
        "by_severity": {},
        "violations": [],
        "notes": [],
    }
    if bpa_payload and bpa_payload.get("violations"):
        result["source"] = "bpa"
        result["violations"] = bpa_payload["violations"]
        result["total_issues"] = len(bpa_payload["violations"])
        counts: Dict[str, int] = {}
        for item in bpa_payload["violations"]:
            severity = str(item.get("severity") or "Info").title()
            counts[severity] = counts.get(severity, 0) + 1
        result["by_severity"] = counts
        if bpa_payload.get("notes"):
            result["notes"].extend(bpa_payload["notes"])
    elif light_payload and light_payload.get("issues"):
        result["source"] = "lightweight"
        result["violations"] = light_payload.get("issues", [])
        result["total_issues"] = len(light_payload.get("issues", []))
        counts_light: Dict[str, int] = {}
        for item in light_payload.get("issues", []):
            severity = str(item.get("severity") or "info").title()
            counts_light[severity] = counts_light.get(severity, 0) + 1
        result["by_severity"] = counts_light
    return result


def _run_bpa_if_available(connection_state, exporter) -> Optional[Dict[str, Any]]:
    """Run Best Practice Analyzer if available.

    Args:
        connection_state: Power BI connection state object
        exporter: Model exporter object

    Returns:
        dict with violations and notes, or None if unavailable
    """
    try:
        bpa = getattr(connection_state, "bpa_analyzer", None)
        if not bpa:
            return None
        tmsl = exporter.export_tmsl(include_full_model=True)
        if not tmsl.get("success"):
            return None
        payload = tmsl.get("model")
        tmsl_json = tmsl.get("model") or tmsl.get("tmsl")
        if hasattr(bpa, "analyze_model_fast") and isinstance(tmsl_json, (str, bytes)):
            violations = bpa.analyze_model_fast(tmsl_json, {})
        elif hasattr(bpa, "analyze_model") and isinstance(tmsl_json, (str, bytes)):
            violations = bpa.analyze_model(tmsl_json)
        else:
            return None
        norm: List[Dict[str, Any]] = []
        for item in violations or []:
            try:
                data = {
                    "rule_id": getattr(item, "rule_id", getattr(item, "ruleId", "")),
                    "rule_name": getattr(
                        item, "rule_name", getattr(item, "ruleName", "")
                    ),
                    "category": getattr(item, "category", ""),
                    "severity": getattr(item, "severity", "Info"),
                    "object_type": getattr(item, "object_type", ""),
                    "object_name": getattr(item, "object_name", ""),
                    "table_name": getattr(item, "table_name", None),
                    "description": getattr(item, "description", ""),
                    "details": getattr(item, "details", None),
                    "fix_expression": getattr(item, "fix_expression", None),
                }
            except Exception:
                data = item if isinstance(item, dict) else {"raw": str(item)}
            norm.append(data)
        notes = []
        if hasattr(bpa, "get_run_notes"):
            try:
                notes = [str(n) for n in bpa.get_run_notes()]
            except Exception:
                notes = []
        return {
            "violations": norm,
            "notes": notes,
            "payload": payload,
        }
    except Exception:
        return None


def collect_model_documentation(
    connection_state,
    *,
    include_hidden: bool = True,
    dependency_depth: int = 1,
    lightweight_best_practices: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect comprehensive documentation for a Power BI model.

    Args:
        connection_state: Power BI Desktop connection state object
        include_hidden: Whether to include hidden objects
        dependency_depth: Depth for dependency analysis (unused, reserved for future)
        lightweight_best_practices: Optional lightweight best practices payload

    Returns:
        dict: {
            "success": bool,
            "database_name": str,
            "generated_at": str,
            "summary": dict,
            "tables": list,
            "measures": list,
            "relationships": list,
            "dependency_edges": list,
            "best_practices": dict,
            "notes": list,
            "narrative": dict
        }
    """
    if not connection_state or not connection_state.is_connected():
        return {"success": False, "error": "Power BI Desktop is not connected"}

    qe = getattr(connection_state, "query_executor", None)
    exporter = getattr(connection_state, "model_exporter", None)
    if not qe:
        return {"success": False, "error": "query_executor manager unavailable"}

    notes: List[str] = []
    summary: Dict[str, Any] = {}
    if exporter:
        try:
            summary = exporter.get_model_summary(qe)
        except Exception as exc:
            notes.append(f"Model summary unavailable: {exc}")
            summary = {"success": False}
    else:
        notes.append("Model exporter unavailable; summary limited")
        summary = {"success": False}

    db_name = None
    try:
        db_name = qe._get_database_name()
    except Exception:
        db_name = None
    if not db_name:
        db_name = summary.get("database_name") or "PowerBI_Model"

    # Fetch metadata once
    tables_res = qe.execute_info_query("TABLES", top_n=5000)
    columns_res = qe.execute_info_query("COLUMNS", top_n=5000)
    measures_res = qe.execute_info_query("MEASURES", top_n=5000)
    relationships_res = qe.execute_info_query("RELATIONSHIPS", top_n=5000)

    tables_rows = tables_res.get("rows", []) if tables_res.get("success") else []
    columns_rows = columns_res.get("rows", []) if columns_res.get("success") else []
    measures_rows = measures_res.get("rows", []) if measures_res.get("success") else []
    relationships_rows = (
        relationships_res.get("rows", []) if relationships_res.get("success") else []
    )

    if not include_hidden:
        tables_rows = [r for r in tables_rows if not to_bool(pick(r, "IsHidden"))]
        columns_rows = [r for r in columns_rows if not to_bool(pick(r, "IsHidden"))]
        measures_rows = [r for r in measures_rows if not to_bool(pick(r, "IsHidden"))]

    # Organize columns and measures by table
    columns_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for col in columns_rows:
        table = str(
            pick(
                col,
                "Table",
                "TableName",
                "TABLE_NAME",
                "FromTable",
                "TABLE",
                "[Table]",
                default="",
            )
        )
        columns_by_table.setdefault(table, []).append(col)

    measures_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for meas in measures_rows:
        table = str(
            pick(
                meas,
                "Table",
                "TableName",
                "TABLE_NAME",
                "FromTable",
                "TABLE",
                "[Table]",
                default="",
            )
        )
        measures_by_table.setdefault(table, []).append(meas)

    reference_index = build_reference_index(measures_rows, columns_rows)

    tables: List[Dict[str, Any]] = []
    for table in tables_rows:
        t_name = str(
            pick(
                table,
                "Name",
                "Table",
                "TableName",
                "TABLE_NAME",
                "Caption",
                "[Name]",
                "[Table]",
                default="Unknown",
            )
        )
        table_entry = {
            "name": t_name,
            "description": pick(
                table,
                "Description",
                "TableDescription",
                "DESCRIPTION",
                "Caption",
                default="",
            ),
            "hidden": to_bool(pick(table, "IsHidden", "Hidden", "[IsHidden]")),
            "row_count": pick(table, "RowCount", "RowCount64", "ROW_COUNT", default=None),
            "columns": [],
            "measures": [],
        }

        def _column_sort_key(row: Dict[str, Any]) -> str:
            return str(
                pick(
                    row,
                    "Name",
                    "Column",
                    "ColumnName",
                    "COLUMN_NAME",
                    "Caption",
                    "[Name]",
                    default="",
                )
            )

        for col in sorted(columns_by_table.get(t_name, []), key=_column_sort_key):
            col_name = str(
                pick(
                    col,
                    "Name",
                    "Column",
                    "ColumnName",
                    "COLUMN_NAME",
                    "Caption",
                    "[Name]",
                    "[Column]",
                    "ExplicitName",
                    default="",
                )
            ).strip()

            # Additional fallback: try to extract from composite keys
            if not col_name:
                # Try to get from fully qualified names like "TableName[ColumnName]"
                for key in ["FullyQualifiedName", "QualifiedName"]:
                    fq_name = pick(col, key, default="")
                    if fq_name and "[" in fq_name and "]" in fq_name:
                        col_name = fq_name.split("[")[-1].replace("]", "").strip()
                        if col_name:
                            break

            if not col_name:
                col_name = "Unnamed Column"

            table_entry["columns"].append(
                {
                    "name": col_name,
                    "data_type": str(
                        pick(
                            col,
                            "DataType",
                            "DATA_TYPE",
                            "Type",
                            "ColumnType",
                            "ExplicitDataType",
                            default="Unknown",
                        )
                    ),
                    "description": pick(
                        col, "Description", "ColumnDescription", "DESCRIPTION", default=""
                    ),
                    "hidden": to_bool(pick(col, "IsHidden", "Hidden", "[IsHidden]")),
                    "summarize_by": pick(col, "SummarizeBy", "SUMMARIZE_BY", default=None),
                    "type": str(
                        pick(col, "Type", "ColumnType", "COLUMN_TYPE", default="")
                    ),
                }
            )

        def _measure_sort_key(row: Dict[str, Any]) -> str:
            return str(
                pick(
                    row,
                    "Name",
                    "Measure",
                    "MeasureName",
                    "MEASURE_NAME",
                    "Caption",
                    "[Name]",
                    default="",
                )
            )

        for meas in sorted(measures_by_table.get(t_name, []), key=_measure_sort_key):
            expr = pick(meas, "Expression", "Formula", default="") or ""
            refs = (
                parse_dax_references(expr, reference_index)
                if expr
                else {"tables": [], "columns": [], "measures": []}
            )
            deps_cols = [f"{tbl}[{col}]" for tbl, col in refs.get("columns", [])]
            deps_meas = [
                f"{tbl}.{name}" if tbl else name for tbl, name in refs.get("measures", [])
            ]
            meas_name = str(
                pick(
                    meas,
                    "Name",
                    "Measure",
                    "MeasureName",
                    "MEASURE_NAME",
                    "Caption",
                    "[Name]",
                    default="",
                )
            )
            if not meas_name:
                meas_name = "Unnamed Measure"

            table_entry["measures"].append(
                {
                    "name": meas_name,
                    "description": pick(
                        meas,
                        "Description",
                        "MeasureDescription",
                        "DESCRIPTION",
                        "Caption",
                        default="",
                    ),
                    "expression": expr,
                    "format_string": pick(
                        meas, "FormatString", "FORMAT_STRING", "Format", default=""
                    ),
                    "display_folder": pick(meas, "DisplayFolder", "Folder", default=""),
                    "hidden": to_bool(pick(meas, "IsHidden", "Hidden", "[IsHidden]")),
                    "dependencies": {
                        "columns": deps_cols,
                        "measures": deps_meas,
                        "tables": refs.get("tables", []),
                    },
                }
            )

        tables.append(table_entry)

    # Flatten measure list for summary sections
    all_measures: List[Dict[str, Any]] = []
    dependency_edges: List[Dict[str, Any]] = []
    for table in tables:
        for meas in table["measures"]:
            source = f"{table['name']}.{meas['name']}"
            dependency_edges.append(
                format_edge(source, meas["dependencies"]["measures"], "measure")
            )
            dependency_edges.append(
                format_edge(source, meas["dependencies"]["columns"], "column")
            )
            all_measures.append(
                {
                    "table": table["name"],
                    "name": meas["name"],
                    "description": meas["description"],
                    "expression": meas["expression"],
                    "dependencies": meas["dependencies"],
                    "hidden": meas["hidden"],
                }
            )

    relationships: List[Dict[str, Any]] = []
    for rel in relationships_rows:
        relationships.append(
            {
                "from_table": str(pick(rel, "FromTable", default="")),
                "from_column": str(pick(rel, "FromColumn", default="")),
                "to_table": str(pick(rel, "ToTable", default="")),
                "to_column": str(pick(rel, "ToColumn", default="")),
                "is_active": to_bool(pick(rel, "IsActive", default=False)),
                "cardinality": str(
                    pick(rel, "Cardinality", default=pick(rel, "RelationshipType", default=""))
                ),
                "direction": str(pick(rel, "CrossFilterDirection", default="")),
            }
        )

    try:
        narrative = model_narrative.generate_narrative(
            summary, {"relationships": {"count": len(relationships)}}
        )
    except Exception:
        narrative = {"success": False}

    bpa_payload = _run_bpa_if_available(connection_state, exporter) if exporter else None
    best_practices = _summarize_best_practices(bpa_payload, lightweight_best_practices)

    context = {
        "success": True,
        "generated_at": now_iso(),
        "database_name": db_name,
        "summary": summary,
        "tables": tables,
        "measures": all_measures,
        "relationships": relationships,
        "dependency_edges": dependency_edges,
        "best_practices": best_practices,
        "notes": notes,
        "narrative": narrative,
    }
    return context
