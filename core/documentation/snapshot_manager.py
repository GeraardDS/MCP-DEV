"""Snapshot management for Power BI model documentation."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from core.utilities.json_utils import load_json
from .utils import ensure_dir, now_iso, relationship_id, safe_filename, SNAPSHOT_SUFFIX


def snapshot_from_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Create a snapshot dictionary from a documentation context.

    Args:
        context: Documentation context dictionary

    Returns:
        Snapshot dictionary with tables, measures, relationships, and metadata
    """
    tables_map: Dict[str, Dict[str, Any]] = {}
    for tbl in context.get("tables", []):
        tables_map[tbl.get("name") or "Unknown"] = {
            "description": tbl.get("description"),
            "hidden": bool(tbl.get("hidden")),
            "columns": [col.get("name") for col in tbl.get("columns", [])],
            "measures": [meas.get("name") for meas in tbl.get("measures", [])],
        }
    measures_map: Dict[str, Dict[str, Any]] = {}
    for meas in context.get("measures", []):
        key = f"{meas.get('table')}::{meas.get('name')}"
        measures_map[key] = {
            "description": meas.get("description"),
            "expression": meas.get("expression"),
            "dependencies": meas.get("dependencies"),
            "hidden": bool(meas.get("hidden")),
        }
    rels = sorted(relationship_id(rel) for rel in context.get("relationships", []))
    return {
        "database_name": context.get("database_name"),
        "generated_at": context.get("generated_at"),
        "summary_counts": (context.get("summary", {}) or {}).get("counts", {}),
        "tables": tables_map,
        "measures": measures_map,
        "relationships": rels,
        "best_practices": context.get("best_practices", {}),
    }


def save_snapshot(
    context: Dict[str, Any], output_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Save a model snapshot to disk.

    Args:
        context: Documentation context dictionary
        output_dir: Optional output directory for the snapshot file

    Returns:
        dict: {"success": bool, "snapshot_path": str, "snapshot": dict}
    """
    snapshot = snapshot_from_context(context)
    out_dir = ensure_dir(output_dir)
    fname = safe_filename(context.get("database_name"), SNAPSHOT_SUFFIX)
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2)
    return {"success": True, "snapshot_path": path, "snapshot": snapshot}


def load_snapshot(
    path: Optional[str],
    output_dir: Optional[str] = None,
    database_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load a model snapshot from disk.

    Args:
        path: Optional path to snapshot file
        output_dir: Optional output directory to search for snapshot
        database_name: Optional database name to construct filename

    Returns:
        Snapshot dictionary if found, None otherwise
    """
    candidates: List[str] = []
    if path and os.path.exists(path):
        candidates.append(path)
    else:
        out_dir = ensure_dir(output_dir)
        if database_name:
            candidates.append(
                os.path.join(out_dir, safe_filename(database_name, SNAPSHOT_SUFFIX))
            )
        candidates.append(
            os.path.join(
                out_dir, safe_filename(database_name or "powerbi_model", SNAPSHOT_SUFFIX)
            )
        )
    for candidate in candidates:
        if os.path.exists(candidate):
            try:
                return load_json(candidate)
            except Exception:
                continue
    return None


def compute_diff(
    previous: Optional[Dict[str, Any]], current: Dict[str, Any]
) -> Dict[str, Any]:
    """Compute differences between two snapshots.

    Args:
        previous: Previous snapshot dictionary (or None for initial snapshot)
        current: Current snapshot dictionary

    Returns:
        dict: {
            "changes_detected": bool,
            "tables": {"added": [], "removed": [], "updated": []},
            "measures": {"added": [], "removed": [], "updated": []},
            "relationships": {"added": [], "removed": [], "updated": []},
            "best_practices": {"previous": int, "current": int}
        }
    """
    diff = {
        "changes_detected": False,
        "tables": {},
        "measures": {},
        "relationships": {},
        "best_practices": None,
    }
    if not previous:
        diff["changes_detected"] = True
        return diff

    # Tables
    prev_tables = previous.get("tables", {})
    curr_tables = current.get("tables", {})
    added_tables = sorted(set(curr_tables.keys()) - set(prev_tables.keys()))
    removed_tables = sorted(set(prev_tables.keys()) - set(curr_tables.keys()))
    updated_tables = []
    for tbl in set(curr_tables.keys()) & set(prev_tables.keys()):
        prev_entry = prev_tables.get(tbl, {})
        curr_entry = curr_tables.get(tbl, {})
        if (
            prev_entry.get("description") != curr_entry.get("description")
            or set(prev_entry.get("columns", [])) != set(curr_entry.get("columns", []))
            or set(prev_entry.get("measures", []))
            != set(curr_entry.get("measures", []))
        ):
            updated_tables.append(tbl)
    if added_tables or removed_tables or updated_tables:
        diff["changes_detected"] = True
        diff["tables"] = {
            "added": added_tables,
            "removed": removed_tables,
            "updated": updated_tables,
        }

    # Measures
    prev_measures = previous.get("measures", {})
    curr_measures = current.get("measures", {})
    added_measures = sorted(set(curr_measures.keys()) - set(prev_measures.keys()))
    removed_measures = sorted(set(prev_measures.keys()) - set(curr_measures.keys()))
    updated_measures = []
    for name in set(curr_measures.keys()) & set(prev_measures.keys()):
        prev_entry = prev_measures.get(name, {})
        curr_entry = curr_measures.get(name, {})
        if (
            prev_entry.get("expression") != curr_entry.get("expression")
            or prev_entry.get("description") != curr_entry.get("description")
            or prev_entry.get("dependencies") != curr_entry.get("dependencies")
        ):
            updated_measures.append(name)
    if added_measures or removed_measures or updated_measures:
        diff["changes_detected"] = True
        diff["measures"] = {
            "added": added_measures,
            "removed": removed_measures,
            "updated": updated_measures,
        }

    # Relationships
    prev_rels = set(previous.get("relationships", []))
    curr_rels = set(current.get("relationships", []))
    added_rels = sorted(curr_rels - prev_rels)
    removed_rels = sorted(prev_rels - curr_rels)
    if added_rels or removed_rels:
        diff["changes_detected"] = True
        diff["relationships"] = {
            "added": added_rels,
            "removed": removed_rels,
            "updated": [],
        }

    # Best practices delta
    prev_bp = previous.get("best_practices", {}) or {}
    curr_bp = current.get("best_practices", {}) or {}
    if prev_bp.get("total_issues") != curr_bp.get("total_issues"):
        diff["changes_detected"] = True
        diff["best_practices"] = {
            "previous": prev_bp.get("total_issues"),
            "current": curr_bp.get("total_issues"),
        }

    return diff


def compare_snapshots(
    snapshot1_path: str, snapshot2_path: str, output_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a side-by-side comparison report of two model snapshots.

    Args:
        snapshot1_path: Path to first snapshot file
        snapshot2_path: Path to second snapshot file
        output_dir: Optional output directory for comparison report

    Returns:
        dict: {
            "success": bool,
            "comparison_report": str (path to report),
            "diff": dict (detailed differences),
            "statistics": dict (summary stats)
        }
    """
    try:
        # Load snapshots
        snapshot1 = load_json(snapshot1_path)
        snapshot2 = load_json(snapshot2_path)

        # Compute diff
        diff = compute_diff(snapshot1, snapshot2)

        # Generate statistics
        stats = {
            "snapshot1": {
                "name": snapshot1.get("database_name", "Unknown"),
                "generated_at": snapshot1.get("generated_at", "Unknown"),
                "tables": len(snapshot1.get("tables", {})),
                "measures": len(snapshot1.get("measures", {})),
                "relationships": len(snapshot1.get("relationships", [])),
                "bp_issues": snapshot1.get("best_practices", {}).get("total_issues", 0),
            },
            "snapshot2": {
                "name": snapshot2.get("database_name", "Unknown"),
                "generated_at": snapshot2.get("generated_at", "Unknown"),
                "tables": len(snapshot2.get("tables", {})),
                "measures": len(snapshot2.get("measures", {})),
                "relationships": len(snapshot2.get("relationships", [])),
                "bp_issues": snapshot2.get("best_practices", {}).get("total_issues", 0),
            },
            "changes": {
                "tables_added": len(diff.get("tables", {}).get("added", [])),
                "tables_removed": len(diff.get("tables", {}).get("removed", [])),
                "tables_updated": len(diff.get("tables", {}).get("updated", [])),
                "measures_added": len(diff.get("measures", {}).get("added", [])),
                "measures_removed": len(diff.get("measures", {}).get("removed", [])),
                "measures_updated": len(diff.get("measures", {}).get("updated", [])),
                "relationships_added": len(
                    diff.get("relationships", {}).get("added", [])
                ),
                "relationships_removed": len(
                    diff.get("relationships", {}).get("removed", [])
                ),
            },
        }

        # Generate comparison report (text format)
        out_dir = ensure_dir(output_dir)
        report_name = f"comparison_report_{now_iso()}.txt"
        report_path = os.path.join(out_dir, report_name)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("Power BI Model Comparison Report\n")
            f.write("=" * 80 + "\n\n")

            f.write(
                f"Snapshot 1: {stats['snapshot1']['name']} ({stats['snapshot1']['generated_at']})\n"
            )
            f.write(
                f"  Tables: {stats['snapshot1']['tables']}, Measures: {stats['snapshot1']['measures']}, "
            )
            f.write(
                f"Relationships: {stats['snapshot1']['relationships']}, BPA Issues: {stats['snapshot1']['bp_issues']}\n\n"
            )

            f.write(
                f"Snapshot 2: {stats['snapshot2']['name']} ({stats['snapshot2']['generated_at']})\n"
            )
            f.write(
                f"  Tables: {stats['snapshot2']['tables']}, Measures: {stats['snapshot2']['measures']}, "
            )
            f.write(
                f"Relationships: {stats['snapshot2']['relationships']}, BPA Issues: {stats['snapshot2']['bp_issues']}\n\n"
            )

            f.write("=" * 80 + "\n")
            f.write("CHANGES SUMMARY\n")
            f.write("=" * 80 + "\n\n")

            # Tables
            if diff.get("tables"):
                f.write("TABLES:\n")
                if diff["tables"].get("added"):
                    f.write(f"  Added ({len(diff['tables']['added'])}):\n")
                    for item in diff["tables"]["added"]:
                        f.write(f"    + {item}\n")
                if diff["tables"].get("removed"):
                    f.write(f"  Removed ({len(diff['tables']['removed'])}):\n")
                    for item in diff["tables"]["removed"]:
                        f.write(f"    - {item}\n")
                if diff["tables"].get("updated"):
                    f.write(f"  Updated ({len(diff['tables']['updated'])}):\n")
                    for item in diff["tables"]["updated"]:
                        f.write(f"    ~ {item}\n")
                f.write("\n")

            # Measures
            if diff.get("measures"):
                f.write("MEASURES:\n")
                if diff["measures"].get("added"):
                    f.write(f"  Added ({len(diff['measures']['added'])}):\n")
                    for item in diff["measures"]["added"][
                        :50
                    ]:  # Limit to 50 for readability
                        f.write(f"    + {item}\n")
                    if len(diff["measures"]["added"]) > 50:
                        f.write(
                            f"    ... and {len(diff['measures']['added']) - 50} more\n"
                        )
                if diff["measures"].get("removed"):
                    f.write(f"  Removed ({len(diff['measures']['removed'])}):\n")
                    for item in diff["measures"]["removed"][:50]:
                        f.write(f"    - {item}\n")
                    if len(diff["measures"]["removed"]) > 50:
                        f.write(
                            f"    ... and {len(diff['measures']['removed']) - 50} more\n"
                        )
                if diff["measures"].get("updated"):
                    f.write(f"  Updated ({len(diff['measures']['updated'])}):\n")
                    for item in diff["measures"]["updated"][:50]:
                        f.write(f"    ~ {item}\n")
                    if len(diff["measures"]["updated"]) > 50:
                        f.write(
                            f"    ... and {len(diff['measures']['updated']) - 50} more\n"
                        )
                f.write("\n")

            # Relationships
            if diff.get("relationships"):
                f.write("RELATIONSHIPS:\n")
                if diff["relationships"].get("added"):
                    f.write(f"  Added ({len(diff['relationships']['added'])}):\n")
                    for item in diff["relationships"]["added"]:
                        f.write(f"    + {item}\n")
                if diff["relationships"].get("removed"):
                    f.write(f"  Removed ({len(diff['relationships']['removed'])}):\n")
                    for item in diff["relationships"]["removed"]:
                        f.write(f"    - {item}\n")
                f.write("\n")

            # Best Practices
            if diff.get("best_practices"):
                f.write("BEST PRACTICES:\n")
                prev = diff["best_practices"].get("previous", 0)
                curr = diff["best_practices"].get("current", 0)
                delta = curr - prev
                f.write(f"  Previous issues: {prev}\n")
                f.write(f"  Current issues: {curr}\n")
                f.write(f"  Delta: {'+' if delta > 0 else ''}{delta}\n\n")

            f.write("=" * 80 + "\n")
            f.write("END OF REPORT\n")
            f.write("=" * 80 + "\n")

        return {
            "success": True,
            "comparison_report": report_path,
            "diff": diff,
            "statistics": stats,
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}
