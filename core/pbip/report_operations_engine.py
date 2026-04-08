"""
Report Operations Engine for PBIP Reports

Report-level operations: rename, rebind to a different semantic model,
backup/restore, and schema discovery for visual types and data roles.

No MCP awareness — pure domain logic operating on PBIP file structures.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utilities.pbip_utils import load_json_file, save_json_file

logger = logging.getLogger(__name__)


def rename_report(pbip_path: str, new_name: str) -> Dict[str, Any]:
    """Rename a report: rename .Report folder and update .platform displayName.

    Args:
        pbip_path: Path to the .pbip file or .Report folder
        new_name: New report name

    Returns:
        Dict with success status, old/new names, and updated paths
    """
    if not new_name or not new_name.strip():
        return {"success": False, "error": "New name is required"}

    path = Path(pbip_path)

    # Resolve to .Report folder
    if path.is_file() and path.suffix.lower() == ".pbip":
        report_folder = path.parent / f"{path.stem}.Report"
        pbip_file = path
    elif path.is_dir() and path.name.endswith(".Report"):
        report_folder = path
        pbip_file = path.parent / f"{path.name.replace('.Report', '.pbip')}"
    else:
        return {
            "success": False,
            "error": f"Expected .pbip file or .Report folder, got: {path}",
        }

    if not report_folder.exists():
        return {"success": False, "error": f"Report folder not found: {report_folder}"}

    old_name = report_folder.name.replace(".Report", "")
    new_report_folder = report_folder.parent / f"{new_name}.Report"

    if new_report_folder.exists():
        return {
            "success": False,
            "error": f"Target folder already exists: {new_report_folder}",
        }

    # Rename .Report folder
    report_folder.rename(new_report_folder)

    # Rename .pbip file if it exists
    new_pbip_file = None
    if pbip_file.exists():
        new_pbip_file = pbip_file.parent / f"{new_name}.pbip"
        pbip_file.rename(new_pbip_file)

    # Update .platform displayName inside the renamed folder
    platform_path = new_report_folder / ".platform"
    if platform_path.exists():
        platform_data = load_json_file(platform_path)
        if platform_data:
            metadata = platform_data.setdefault("metadata", {})
            metadata["displayName"] = new_name
            save_json_file(platform_path, platform_data)

    return {
        "success": True,
        "old_name": old_name,
        "new_name": new_name,
        "report_folder": str(new_report_folder),
        "pbip_file": str(new_pbip_file) if new_pbip_file else None,
    }


def rebind_report(
    definition_path: Path,
    model_path: str = None,
    model_id: str = None,
) -> Dict[str, Any]:
    """Rebind report to a different semantic model. Updates definition.pbir.

    The definition.pbir file controls which semantic model (dataset) the report
    connects to. This can be a local TMDL model path or a remote model ID.

    Args:
        definition_path: Path to the report's definition/ folder
        model_path: Relative path to the semantic model folder (for local binding)
        model_id: Remote semantic model ID (for service binding)

    Returns:
        Dict with success status and binding details
    """
    if not model_path and not model_id:
        return {
            "success": False,
            "error": "Either model_path or model_id must be provided",
        }

    pbir_path = definition_path / "definition.pbir"
    pbir_data = load_json_file(pbir_path)
    if not pbir_data:
        return {"success": False, "error": "Could not read definition.pbir"}

    old_ref = pbir_data.get("datasetReference", {})
    old_binding = {
        "path": old_ref.get("byPath", {}).get("path"),
        "id": old_ref.get("byConnection", {}).get("connectionString"),
    }

    if model_path:
        # Local model binding via byPath
        pbir_data["datasetReference"] = {
            "byPath": {
                "path": model_path,
            }
        }
    elif model_id:
        # Remote/service model binding via byConnection
        pbir_data["datasetReference"] = {
            "byConnection": {
                "connectionString": model_id,
                "pbiServiceModelId": None,
                "pbiModelVirtualServerName": "sobe_wowvirtualserver",
                "pbiModelDatabaseName": model_id,
                "name": "EntityDataSource",
                "connectionType": "pbiServiceXmlaStyleLive",
            }
        }

    if not save_json_file(pbir_path, pbir_data):
        return {"success": False, "error": "Failed to write definition.pbir"}

    return {
        "success": True,
        "old_binding": old_binding,
        "new_binding": {
            "path": model_path,
            "id": model_id,
        },
    }


def backup_report(
    report_path: Path,
    message: str = None,
) -> Dict[str, Any]:
    """Create a timestamped backup of the report folder.

    Creates a copy of the .Report folder with a timestamp suffix in the same
    parent directory. Optionally records a message in a backup.txt file.

    Args:
        report_path: Path to the .Report folder
        message: Optional description for the backup

    Returns:
        Dict with success status and backup path
    """
    report_path = Path(report_path)

    if not report_path.exists():
        return {"success": False, "error": f"Report folder not found: {report_path}"}

    if not report_path.is_dir():
        return {"success": False, "error": f"Expected a directory, got: {report_path}"}

    # Generate timestamped backup name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = report_path.name.replace(".Report", "")
    backup_name = f"{base_name}.Report.backup_{timestamp}"
    backup_path = report_path.parent / backup_name

    if backup_path.exists():
        return {"success": False, "error": f"Backup path already exists: {backup_path}"}

    # Copy the entire report folder
    shutil.copytree(str(report_path), str(backup_path))

    # Write optional backup message
    if message:
        backup_info_path = backup_path / "backup_info.txt"
        with open(backup_info_path, "w", encoding="utf-8") as f:
            f.write(f"Backup created: {datetime.now().isoformat()}\n")
            f.write(f"Source: {report_path}\n")
            f.write(f"Message: {message}\n")

    # Count contents for summary
    page_count = 0
    visual_count = 0
    definition_dir = backup_path / "definition"
    if definition_dir.exists():
        pages_dir = definition_dir / "pages"
        if pages_dir.exists():
            for page_folder in pages_dir.iterdir():
                if page_folder.is_dir():
                    page_count += 1
                    visuals_dir = page_folder / "visuals"
                    if visuals_dir.exists():
                        visual_count += sum(
                            1 for v in visuals_dir.iterdir() if v.is_dir()
                        )

    return {
        "success": True,
        "backup_path": str(backup_path),
        "source_path": str(report_path),
        "timestamp": timestamp,
        "message": message,
        "page_count": page_count,
        "visual_count": visual_count,
    }


def restore_report(
    report_path: Path,
    backup_path: str = None,
) -> Dict[str, Any]:
    """Restore report from backup.

    If backup_path is not provided, attempts to find the most recent backup
    in the same parent directory.

    Args:
        report_path: Path to the target .Report folder to restore to
        backup_path: Path to the backup folder (auto-detected if None)

    Returns:
        Dict with success status and restore details
    """
    report_path = Path(report_path)

    if backup_path:
        source = Path(backup_path)
    else:
        # Auto-detect most recent backup
        base_name = report_path.name.replace(".Report", "")
        parent = report_path.parent
        backups = sorted(
            parent.glob(f"{base_name}.Report.backup_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not backups:
            return {
                "success": False,
                "error": f"No backups found for {base_name} in {parent}",
            }
        source = backups[0]

    if not source.exists():
        return {"success": False, "error": f"Backup not found: {source}"}

    if not source.is_dir():
        return {"success": False, "error": f"Expected a directory, got: {source}"}

    # Safe restore: rename existing to temp, copy backup, then delete temp
    temp_path = None
    if report_path.exists():
        temp_path = report_path.with_name(report_path.name + ".restore_tmp")
        if temp_path.exists():
            shutil.rmtree(str(temp_path))
        report_path.rename(temp_path)

    try:
        shutil.copytree(str(source), str(report_path))
    except Exception:
        # Restore failed — roll back by renaming temp back
        if temp_path and temp_path.exists():
            if report_path.exists():
                shutil.rmtree(str(report_path))
            temp_path.rename(report_path)
        raise

    # Copy succeeded — remove temp
    if temp_path and temp_path.exists():
        shutil.rmtree(str(temp_path))

    # Remove backup metadata file from restored report
    backup_info = report_path / "backup_info.txt"
    if backup_info.exists():
        backup_info.unlink()

    return {
        "success": True,
        "restored_from": str(source),
        "restored_to": str(report_path),
    }


def discover_schema(
    definition_path: Path,
    visual_type: str = None,
) -> Dict[str, Any]:
    """Discover valid properties and data roles for visual types.

    Returns visual type -> {buckets, formatting_properties} mapping built
    from the known template registry and visual container objects.

    Args:
        definition_path: Path to the report's definition/ folder (used for context)
        visual_type: Optional filter to a specific visual type

    Returns:
        Dict with success status and schema information
    """
    # Lazy import to avoid circular dependency at module load time
    from core.pbip.authoring.visual_templates import (
        VISUAL_TYPE_BUCKETS,
        TEMPLATE_REGISTRY,
        get_template_catalog,
    )

    if visual_type:
        if visual_type not in TEMPLATE_REGISTRY:
            available = sorted(set(TEMPLATE_REGISTRY.keys()))
            return {
                "success": False,
                "error": (
                    f"Unknown visual type: '{visual_type}'. "
                    f"Available: {', '.join(available)}"
                ),
            }

        # Get details for a single visual type
        buckets = VISUAL_TYPE_BUCKETS.get(visual_type, {})

        # Extract formatting properties from the template
        template_fn = TEMPLATE_REGISTRY[visual_type]
        template = template_fn(None)
        formatting_props = _extract_formatting_properties(template)

        return {
            "success": True,
            "visual_type": visual_type,
            "buckets": buckets,
            "formatting_properties": formatting_props,
        }

    # Return catalog of all visual types
    catalog = get_template_catalog()
    return {
        "success": True,
        "visual_types": catalog,
        "total_types": len(catalog),
    }


def _extract_formatting_properties(template: Dict[str, Any]) -> Dict[str, List[str]]:
    """Extract available formatting property names from a visual template.

    Args:
        template: A visual.json template dict

    Returns:
        Dict mapping object categories to their property names
    """
    result: Dict[str, List[str]] = {}

    # Extract from visual.objects
    objects = template.get("visual", {}).get("objects", {})
    for obj_name, obj_list in objects.items():
        if isinstance(obj_list, list):
            props = []
            for entry in obj_list:
                if isinstance(entry, dict):
                    for key in entry.get("properties", {}).keys():
                        if key not in props:
                            props.append(key)
            if props:
                result[obj_name] = props

    # Extract from visual.visualContainerObjects
    vco = template.get("visual", {}).get("visualContainerObjects", {})
    for obj_name, obj_list in vco.items():
        key = f"container.{obj_name}"
        if isinstance(obj_list, list):
            props = []
            for entry in obj_list:
                if isinstance(entry, dict):
                    for k in entry.get("properties", {}).keys():
                        if k not in props:
                            props.append(k)
            if props:
                result[key] = props

    return result
